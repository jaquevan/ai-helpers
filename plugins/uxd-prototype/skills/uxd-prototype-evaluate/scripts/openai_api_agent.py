#!/usr/bin/env python3
"""Small direct-API agent loop for the evaluation pipeline.

It deliberately exposes one narrow tool: run a shell command in the project
workspace. The evaluation skill already defines the workflow; the model only
needs a way to inspect files, run validators/Playwright, and write artifacts.
No additional SDK is required.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from model_pricing import PRICING, estimated_cost
from usage_journal import UsageJournal, append_trace_event


MAX_AGENT_TURNS = 12
MAX_TOOL_OUTPUT_CHARS = 8000
FORBIDDEN_COMMAND_PATTERNS = (
    (r"\bgit\s+push\b", "git push is disabled for evaluator phases"),
    (r"(?:^|[;&|()\s])security(?:\s|$)", "Keychain access is disabled"),
    (r"\b(?:keychain|printenv)\b", "credential discovery is disabled"),
    (r"(?:^|[;&|()\s])env(?:\s|$)", "environment inspection is disabled"),
    (r"\$(?:\{)?HOME(?:\})?|(?:^|\s)~(?:/|\s|$)", "home-directory access is disabled"),
    (r"(?:^|/)\.claude(?:/|$)|(?:^|/)\.cursor/plugins/cache(?:/|$)", "global plugin caches are disabled"),
    (r"\.atlassian-credentials|\.env(?:\.|\s|$)", "credential files are disabled"),
    (r"\b(?:OPENAI_API_KEY|LANGFUSE_PUBLIC_KEY|LANGFUSE_SECRET_KEY|ATLASSIAN_API_TOKEN)\b", "secret variables are unavailable"),
    (r"(?:api\.)?atlassian\.com|atlassian\.net", "Jira network access is disabled; use staged MCP context"),
    (r"(?:^|[/\s])\.\.(?:[/\s]|$)", "parent-directory traversal is disabled"),
)


class OpenAIResponseError(RuntimeError):
    """An explicit HTTP error response; usage from earlier rounds remains known."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"OpenAI Responses API error {status_code}: {detail}")


def redact_api_error(detail: str) -> str:
    """Remove API credentials from provider error text before logging."""
    return re.sub(r"sk-[A-Za-z0-9*_\-]{8,}", "[REDACTED_KEY]", detail)


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


def validate_shell_command(
    command: str,
    allowed_roots: tuple[str, ...],
    environment: dict[str, str] | None = None,
) -> None:
    """Reject credential discovery and paths outside the benchmark scope."""
    for pattern, reason in FORBIDDEN_COMMAND_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise ValueError(reason)

    roots = tuple(Path(root).resolve() for root in allowed_roots)
    expanded = command
    for name, value in (environment or {}).items():
        expanded = expanded.replace(f"${{{name}}}", value).replace(f"${name}", value)
    without_urls = re.sub(r"https?://[^\s'\"]+", "", expanded)
    for raw_path in re.findall(r"(?<![A-Za-z0-9_:])(/[^\s'\";|&<>]+)", without_urls):
        candidate = raw_path.rstrip(",:)]}")
        if not _is_within(Path(candidate), roots):
            raise ValueError(f"path is outside allowed roots: {candidate}")


def tool_environment(
    *, project_dir: str, skill_dir: str, jira_context_file: str, jira_issue_key: str,
    consistency_check_dir: str | None = None,
    prototype_export_dir: str | None = None,
) -> dict[str, str]:
    """Return a minimal environment that never exposes host credentials."""
    safe_names = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "CI")
    environment = {
        name: os.environ[name]
        for name in safe_names
        if os.environ.get(name)
    }
    environment.update({
        "UXD_PROJECT_ROOT": str(Path(project_dir).resolve()),
        "AI_HELPERS_SKILL_DIR": str(Path(skill_dir).resolve()),
        "CLAUDE_SKILL_DIR": str(Path(skill_dir).resolve()),
        "CLAUDE_PLUGIN_ROOT": str(Path(skill_dir).resolve().parents[1]),
        "UXD_CONSISTENCY_CHECK_DIR": str(
            Path(consistency_check_dir).resolve()
            if consistency_check_dir
            else Path(skill_dir).resolve().parent / "uxd-consistency-check"
        ),
        "UXD_PROTOTYPE_EXPORT_DIR": str(
            Path(prototype_export_dir).resolve()
            if prototype_export_dir
            else Path(skill_dir).resolve().parent / "uxd-prototype-export"
        ),
        "JIRA_CONTEXT_FILE": str(Path(jira_context_file).resolve()),
        "JIRA_ISSUE_KEY": jira_issue_key,
    })
    return environment


def _request(payload: dict) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for the direct API runner")

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    endpoint = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if os.environ.get("OPENAI_ORG_ID"):
        headers["OpenAI-Organization"] = os.environ["OPENAI_ORG_ID"]
    if os.environ.get("OPENAI_PROJECT_ID"):
        headers["OpenAI-Project"] = os.environ["OPENAI_PROJECT_ID"]

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = redact_api_error(error.read().decode(errors="replace")[:2000])
        raise OpenAIResponseError(error.code, detail) from error


def request_with_capture(
    payload: dict[str, Any],
    *,
    request_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    usage_journal_path: str | None = None,
    trace_path: str | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    phase: str | None = None,
    model: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Call Responses API with a fsynced usage record and replayable exchange."""
    if payload.get("previous_response_id") and payload.get("store") is False:
        raise ValueError(
            "Responses API state conflict: previous_response_id requires stored response state"
        )
    journal = (
        UsageJournal(
            usage_journal_path, run_id=run_id, attempt_id=attempt_id,
            phase=phase, model=model or payload.get("model"),
        )
        if usage_journal_path else None
    )
    request_id = journal.begin() if journal else uuid.uuid4().hex
    request_event = {
        "event": "request",
        "request_id": request_id,
        "phase": phase,
        "model": model or payload.get("model"),
        "payload": payload,
    }
    append_trace_event(trace_path, request_event)
    if on_event:
        try:
            on_event(request_event)
        except Exception:
            pass
    try:
        response = (request_fn or _request)(payload)
    except OpenAIResponseError as error:
        rejected = 400 <= error.status_code < 500
        if journal:
            journal.failed(
                request_id, category="provider_request_rejected" if rejected else "provider_server_error",
                usage_unknown=not rejected,
            )
        append_trace_event(trace_path, {
            "event": "request_failed", "request_id": request_id,
            "status_code": error.status_code,
            "error_category": "provider_request_rejected" if rejected else "provider_server_error",
            "usage_unknown": not rejected,
        })
        raise
    except BaseException as error:
        if journal:
            journal.failed(request_id, category="provider_transport", usage_unknown=True)
        append_trace_event(trace_path, {
            "event": "request_failed", "request_id": request_id,
            "error_category": "provider_transport", "usage_unknown": True,
        })
        raise
    usage_event = journal.response(request_id, response) if journal else None
    response_event = {
        "event": "response",
        "request_id": request_id,
        "phase": phase,
        "model": model or payload.get("model"),
        "response": response,
        "usage": usage_event,
    }
    append_trace_event(trace_path, response_event)
    if on_event:
        try:
            on_event(response_event)
        except Exception:
            pass
    return response


def _tool_definition() -> dict:
    return {
        "type": "function",
        "name": "run_shell",
        "description": (
            "Run a shell command in the evaluation workspace. Use this to read "
            "files, run the documented evaluation steps, run tests, and write "
            "artifacts. Keep commands scoped to the current workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    }


def _run_shell(
    arguments: str,
    cwd: str,
    *,
    allowed_roots: tuple[str, ...],
    environment: dict[str, str],
) -> str:
    try:
        parsed = json.loads(arguments)
        command = parsed["command"]
        timeout = min(max(int(parsed.get("timeout_seconds", 120)), 1), 600)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return f"Invalid run_shell arguments: {error}"

    try:
        validate_shell_command(command, allowed_roots, environment)
    except ValueError as error:
        return f"Scope denied: {error}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=environment,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > MAX_TOOL_OUTPUT_CHARS:
            output = output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[tool output truncated]"
        return f"exit_code={result.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except OSError as error:
        return f"Command failed to start: {error}"


def _tool_failure_diagnostic(output: str, turn: int) -> dict[str, Any]:
    """Return a privacy-safe reason code; never persist commands or shell output."""
    diagnostic: dict[str, Any] = {"turn": turn}
    if output.startswith("Scope denied:"):
        reason = output.partition(":")[2].strip().lower()
        if "path is outside allowed roots" in reason:
            code = "path_outside_allowed_roots"
        elif "credential files" in reason:
            code = "credential_file_access_blocked"
        elif "parent-directory traversal" in reason:
            code = "parent_directory_traversal_blocked"
        elif "home-directory access" in reason:
            code = "home_directory_access_blocked"
        elif "keychain access" in reason:
            code = "keychain_access_blocked"
        elif "environment inspection" in reason:
            code = "environment_inspection_blocked"
        elif "jira network access" in reason:
            code = "jira_network_access_blocked"
        else:
            code = "command_policy_blocked"
        diagnostic.update({"category": "scope_denied", "reason": code})
    elif output.startswith("Command timed out"):
        diagnostic.update({"category": "timeout", "reason": "tool_timeout"})
    elif output.startswith("Command failed to start"):
        diagnostic.update({"category": "tool_start", "reason": "tool_process_start_failed"})
    elif output.startswith("Tool validation failed:"):
        diagnostic.update({"category": "tool_validation", "reason": "host_tool_rejected"})
    else:
        match = re.match(r"exit_code=(\d+)", output)
        if match and int(match.group(1)) != 0:
            diagnostic.update({
                "category": "tool_nonzero_exit",
                "reason": "nonzero_exit_code",
                "exit_code": int(match.group(1)),
            })
    return diagnostic


def _usage(response: dict) -> dict:
    usage = response.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        "cached_input_tokens": int(
            (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
        ),
        "cache_write_tokens": int(
            (usage.get("input_tokens_details") or {}).get("cache_write_tokens", 0) or 0
        ),
        "reasoning_tokens": int(
            (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        ),
    }


def _cost(model: str, usage: dict) -> float | None:
    if model not in PRICING:
        return None
    return estimated_cost(model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                          int(usage.get("cached_input_tokens", 0)), int(usage.get("cache_write_tokens", 0)))


def run_agent(
    prompt: str,
    *,
    model: str,
    project_dir: str,
    system_prompt: str,
    reasoning_effort: str = "low",
    max_turns: int | None = MAX_AGENT_TURNS,
    max_output_tokens: int | None = None,
    max_input_tokens: int | None = None,
    max_total_output_tokens: int | None = None,
    max_total_cost_usd: float | None = None,
    trace_path: str | None = None,
    usage_journal_path: str | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    phase: str | None = None,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
    skill_dir: str,
    jira_context_file: str,
    jira_issue_key: str,
    benchmark_dir: str,
    after_turn: Callable[[int], str | tuple[str, bool] | None] | None = None,
    turn_feedback: Callable[[int], str | None] | None = None,
    additional_allowed_roots: tuple[str, ...] = (),
    consistency_check_dir: str | None = None,
    prototype_export_dir: str | None = None,
    tool_definitions: list[dict[str, Any]] | None = None,
    tool_handler: Callable[[str, str], str] | None = None,
    max_tool_calls: int = 64,
    max_run_seconds: int = 5400,
    max_total_tool_output_chars: int = 64000,
) -> dict:
    """Run the tool loop and return normalized usage/cost metadata.

    ``after_turn`` may enforce a runner-specific artifact deadline after the
    model has received that turn's tool output. A string stops as a failure;
    ``(message, True)`` stops successfully (for example, a valid no-op).
    """
    if max_turns is not None and not 1 <= max_turns <= MAX_AGENT_TURNS:
        raise ValueError(f"max_turns must be None or between 1 and {MAX_AGENT_TURNS}")
    if max_output_tokens is not None and max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    if max_input_tokens is not None and max_input_tokens < 1:
        raise ValueError("max_input_tokens must be positive")
    if max_total_output_tokens is not None and max_total_output_tokens < 1:
        raise ValueError("max_total_output_tokens must be positive")
    if max_total_cost_usd is not None and max_total_cost_usd <= 0:
        raise ValueError("max_total_cost_usd must be positive")
    if max_tool_calls < 1 or max_run_seconds < 1 or max_total_tool_output_chars < 1:
        raise ValueError("tool, wall-time, and output limits must be positive")

    resolved_skill = Path(skill_dir).resolve()
    allowed_roots = tuple(str(Path(path).resolve()) for path in (
        project_dir,
        resolved_skill,
        resolved_skill.parent / "uxd-consistency-check",
        resolved_skill.parent / "uxd-prototype-export",
        resolved_skill.parents[1] / "knowledge",
        benchmark_dir,
        *additional_allowed_roots,
    ))
    environment = tool_environment(
        project_dir=project_dir,
        skill_dir=skill_dir,
        jira_context_file=jira_context_file,
        jira_issue_key=jira_issue_key,
        consistency_check_dir=consistency_check_dir,
        prototype_export_dir=prototype_export_dir,
    )
    initial_input = [
        {"role": "developer", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    request = {
        "model": model,
        "input": initial_input,
        "tools": tool_definitions or [_tool_definition()],
        "reasoning": {"effort": reasoning_effort},
        "text": {"verbosity": "low"},
        "store": True,
    }
    if max_output_tokens is not None:
        request["max_output_tokens"] = max_output_tokens
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    final_text = ""
    response_id = None
    turns_used = 0
    hit_turn_limit = False
    artifact_gate_failure = None
    artifact_gate_completed = None
    provider_error = None
    provider_error_category = None
    provider_http_status = None
    input_token_bound_reached = False
    output_token_bound_reached = False
    cost_bound_reached = False
    input_token_bound_exceeded = False
    output_token_bound_exceeded = False
    cost_bound_exceeded = False
    tool_calls_used = 0
    tool_output_chars_used = 0
    tool_limit_reached = False
    wall_time_limit_reached = False
    tool_failures = 0
    tool_error_categories: set[str] = set()
    tool_failure_diagnostics: list[dict[str, Any]] = []
    tool_failure_diagnostics_truncated = False
    started = time.monotonic()
    trace_file = Path(trace_path) if trace_path else None
    if trace_file:
        trace_file.parent.mkdir(parents=True, exist_ok=True)

    usage_journal = (
        UsageJournal(
            usage_journal_path, run_id=run_id, attempt_id=attempt_id,
            phase=phase, model=model,
        )
        if usage_journal_path else None
    )
    usage_unknown = False
    unknown_request_ids: list[str] = []
    known_usage_cost_usd = 0.0
    cost_known = True

    while max_turns is None or turns_used < max_turns:
        if time.monotonic() - started >= max_run_seconds:
            wall_time_limit_reached = True
            artifact_gate_failure = f"phase wall-time bound reached ({max_run_seconds}s)"
            final_text = artifact_gate_failure
            break
        if tool_calls_used >= max_tool_calls:
            tool_limit_reached = True
            artifact_gate_failure = f"phase tool-call bound reached ({max_tool_calls})"
            final_text = artifact_gate_failure
            break
        current_cost = known_usage_cost_usd if cost_known else None
        if max_input_tokens is not None and total_usage["input_tokens"] >= max_input_tokens:
            input_token_bound_reached = True
            artifact_gate_failure = (
                f"input token bound reached ({total_usage['input_tokens']} >= {max_input_tokens}); "
                "stopped before another model request"
            )
            final_text = artifact_gate_failure
            break
        if max_total_output_tokens is not None and total_usage["output_tokens"] >= max_total_output_tokens:
            output_token_bound_reached = True
            artifact_gate_failure = (
                f"total output token bound reached ({total_usage['output_tokens']} >= "
                f"{max_total_output_tokens}); stopped before another model request"
            )
            final_text = artifact_gate_failure
            break
        if (
            max_total_cost_usd is not None
            and current_cost is not None
            and current_cost >= max_total_cost_usd
        ):
            cost_bound_reached = True
            artifact_gate_failure = (
                f"phase cost bound reached ({current_cost:.8f} >= {max_total_cost_usd:.8f}); "
                "stopped before another model request"
            )
            final_text = artifact_gate_failure
            break

        turns_used += 1
        if response_id:
            request = {
                "model": model,
                "previous_response_id": response_id,
                "input": tool_outputs,
                "tools": tool_definitions or [_tool_definition()],
                "reasoning": {"effort": reasoning_effort},
                "text": {"verbosity": "low"},
                "store": True,
            }
        remaining_output = (
            max_total_output_tokens - total_usage["output_tokens"]
            if max_total_output_tokens is not None
            else None
        )
        request_output_limit = max_output_tokens
        if remaining_output is not None:
            request_output_limit = min(request_output_limit, remaining_output) if request_output_limit else remaining_output
        if request_output_limit is not None:
            request["max_output_tokens"] = request_output_limit
        try:
            response = request_with_capture(
                request,
                usage_journal_path=usage_journal_path,
                trace_path=trace_path,
                run_id=run_id,
                attempt_id=attempt_id,
                phase=phase,
                model=model,
                on_event=event_callback,
            )
        except OpenAIResponseError as error:
            provider_http_status = error.status_code
            provider_error = f"OpenAI Responses API request rejected (HTTP {error.status_code})"
            provider_error_category = "provider_request"
            artifact_gate_failure = provider_error
            final_text = provider_error
            break
        except Exception as error:
            provider_error = "OpenAI Responses API transport failed"
            provider_error_category = "provider_transport"
            artifact_gate_failure = provider_error
            final_text = provider_error
            usage_unknown = True
            if usage_journal:
                summary = UsageJournal(
                    usage_journal_path, run_id=run_id, attempt_id=attempt_id,
                    phase=phase, model=model,
                ).summary()
                unknown_request_ids = summary["unknown_request_ids"]
                total_usage.update(summary["token_usage"])
                known_usage_cost_usd = summary["known_usage_cost_usd"]
                cost_known = summary["cost_known"]
            break

        response_id = response.get("id")
        usage = _usage(response)
        if not isinstance(response.get("usage"), dict) or not all(
            isinstance(response["usage"].get(field), int)
            for field in ("input_tokens", "output_tokens")
        ):
            usage_unknown = True
            provider_error_category = "provider_usage_unknown"
            artifact_gate_failure = "OpenAI response did not include reconcilable usage"
            final_text = artifact_gate_failure
            break
        response_cost = _cost(model, usage)
        if response_cost is None:
            cost_known = False
        else:
            known_usage_cost_usd += response_cost
        if usage_journal:
            usage_summary = UsageJournal(
                usage_journal_path, run_id=run_id, attempt_id=attempt_id,
                phase=phase, model=model,
            ).summary()
            known_usage_cost_usd = usage_summary["known_usage_cost_usd"]
            cost_known = usage_summary["cost_known"]
        for key, value in usage.items():
            total_usage[key] += value

        if max_input_tokens is not None and total_usage["input_tokens"] > max_input_tokens:
            input_token_bound_exceeded = True
            artifact_gate_failure = (
                f"input token bound exceeded ({total_usage['input_tokens']} > {max_input_tokens}); "
                "stopped before executing tool calls or requesting another model turn"
            )
            final_text = artifact_gate_failure
            break
        if time.monotonic() - started >= max_run_seconds:
            wall_time_limit_reached = True
            artifact_gate_failure = f"phase wall-time bound reached ({max_run_seconds}s)"
            final_text = artifact_gate_failure
            break
        if (
            max_total_output_tokens is not None
            and total_usage["output_tokens"] > max_total_output_tokens
        ):
            output_token_bound_exceeded = True
            artifact_gate_failure = (
                f"total output token bound exceeded ({total_usage['output_tokens']} > "
                f"{max_total_output_tokens}); stopped before executing tool calls"
            )
            final_text = artifact_gate_failure
            break
        current_cost = known_usage_cost_usd if cost_known else None
        if (
            max_total_cost_usd is not None
            and current_cost is not None
            and current_cost > max_total_cost_usd
        ):
            cost_bound_exceeded = True
            artifact_gate_failure = (
                f"phase cost bound exceeded ({current_cost:.8f} > {max_total_cost_usd:.8f}); "
                "stopped before executing tool calls"
            )
            final_text = artifact_gate_failure
            break

        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        messages = [item for item in response.get("output", []) if item.get("type") == "message"]
        for message in messages:
            for content in message.get("content", []):
                if content.get("type") == "output_text":
                    final_text += content.get("text", "")

        tool_outputs = []
        for call in calls:
            tool_calls_used += 1
            if tool_calls_used > max_tool_calls or tool_limit_reached:
                tool_limit_reached = True
                output = f"Phase tool-call bound reached ({max_tool_calls}); no further tools executed."
            elif tool_handler:
                try:
                    output = tool_handler(str(call.get("name") or ""), call.get("arguments", "{}"))
                except Exception as error:
                    output = f"Tool failed: {type(error).__name__}"
            else:
                output = _run_shell(
                    call.get("arguments", "{}"),
                    project_dir,
                    allowed_roots=allowed_roots,
                    environment=environment,
                )
            remaining_output = max_total_tool_output_chars - tool_output_chars_used
            if len(output) > remaining_output:
                output = output[:max(remaining_output, 0)] + "\n...[phase tool-output bound reached]"
                tool_limit_reached = True
            tool_output_chars_used += len(output)
            diagnostic = _tool_failure_diagnostic(output, turns_used)
            if diagnostic.get("category"):
                if len(tool_failure_diagnostics) < 20:
                    tool_failure_diagnostics.append(diagnostic)
                else:
                    tool_failure_diagnostics_truncated = True
            if output.startswith("Scope denied:"):
                tool_failures += 1
                tool_error_categories.add("scope_denied")
            elif output.startswith("Command timed out"):
                tool_failures += 1
                tool_error_categories.add("timeout")
            elif output.startswith("Command failed to start"):
                tool_failures += 1
                tool_error_categories.add("tool_start")
            elif output.startswith("Tool failed:"):
                tool_failures += 1
                tool_error_categories.add("tool_handler")
            elif output.startswith("Tool validation failed:"):
                tool_failures += 1
                tool_error_categories.add("tool_validation")
            else:
                match = re.match(r"exit_code=(\d+)", output)
                if match and int(match.group(1)) != 0:
                    tool_failures += 1
                    tool_error_categories.add("tool_nonzero_exit")
            # Every function call must receive a matching output, including
            # scope-denied, timed-out, and process-start failures. Otherwise
            # the next Responses API request is rejected as an unresolved call.
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": call.get("call_id"),
                "output": output,
            })
            tool_event = {
                "event": "tool_exchange", "phase": phase, "model": model,
                "turn": turns_used, "call": call, "output": output,
            }
            append_trace_event(trace_path, tool_event)
            if event_callback:
                try:
                    event_callback(tool_event)
                except Exception:
                    pass
            if tool_limit_reached and tool_calls_used >= max_tool_calls:
                # Send an explicit result for every call in this response, then
                # stop without issuing a continuation request.
                continue
        if tool_limit_reached:
            artifact_gate_failure = artifact_gate_failure or "phase tool-call or tool-output bound reached"
            final_text = artifact_gate_failure
            break
        if after_turn:
            gate_result = after_turn(turns_used)
            if gate_result:
                if isinstance(gate_result, tuple):
                    gate_message, gate_succeeded = gate_result
                else:
                    gate_message, gate_succeeded = gate_result, False
                if gate_succeeded:
                    artifact_gate_completed = gate_message
                else:
                    artifact_gate_failure = gate_message
                final_text = (final_text.rstrip() + "\n" + gate_message).strip()
                break
        if turn_feedback:
            feedback = turn_feedback(turns_used)
            if feedback:
                tool_outputs.append({"role": "user", "content": feedback})
                if not calls:
                    continue
        if not calls:
            break
    else:
        hit_turn_limit = True
        final_text = (
            final_text.rstrip()
            + f"\nOpenAI agent reached max_turns={max_turns} before completion."
        ).lstrip()

    cost = known_usage_cost_usd if cost_known else None
    if usage_journal:
        summary = UsageJournal(
            usage_journal_path, run_id=run_id, attempt_id=attempt_id,
            phase=phase, model=model,
        ).summary()
        usage_unknown = usage_unknown or summary["usage_unknown"]
        unknown_request_ids = summary["unknown_request_ids"]
        # The journal is the crash-recovery authority; it can include a response
        # whose usage was persisted just before a later exception.
        total_usage.update(summary["token_usage"])
        known_usage_cost_usd = summary["known_usage_cost_usd"]
        cost_known = summary["cost_known"]
        cost = summary["cost_usd"]
    error_categories = set(tool_error_categories)
    recovery_actions = []
    if provider_error_category:
        error_categories.add(provider_error_category)
        recovery_actions.append("provider_request_failed")
    if tool_failures and not hit_turn_limit:
        recovery_actions.append("continued_after_tool_failure")
    if hit_turn_limit:
        error_categories.add("turn_limit")
        recovery_actions.append("turn_limit_stop")
    if tool_limit_reached:
        error_categories.add("tool_limit")
        recovery_actions.append("tool_limit_stop")
    if wall_time_limit_reached:
        error_categories.add("wall_time_limit")
        recovery_actions.append("wall_time_limit_stop")
    if usage_unknown:
        error_categories.add("usage_unknown")
        recovery_actions.append("retain_reservation_for_reconciliation")
    if input_token_bound_exceeded or input_token_bound_reached:
        error_categories.add("input_token_bound")
        recovery_actions.append("input_token_bound_stop")
    if output_token_bound_exceeded or output_token_bound_reached:
        error_categories.add("output_token_bound")
        recovery_actions.append("output_token_bound_stop")
    if cost_bound_exceeded or cost_bound_reached:
        error_categories.add("cost_bound")
        recovery_actions.append("cost_bound_stop")
    if artifact_gate_completed:
        recovery_actions.append("artifact_completion_gate")
    return {
        "provider": "openai",
        "model": model,
        "agent": "responses-api",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": 2 if hit_turn_limit or artifact_gate_failure or tool_limit_reached or wall_time_limit_reached else 0,
        "status": "failed" if hit_turn_limit or artifact_gate_failure or tool_limit_reached or wall_time_limit_reached else "completed",
        "output_text": final_text,
        "token_usage": total_usage,
        "cost_usd": cost if not usage_unknown else None,
        "known_usage_cost_usd": round(known_usage_cost_usd, 8),
        "usage_known": not usage_unknown,
        "usage_unknown": usage_unknown,
        "unknown_request_ids": unknown_request_ids,
        "billing_source": "provider_estimate" if cost is not None and not usage_unknown else "partial_provider_usage_unknown" if usage_unknown else "unavailable",
        "turns_used": turns_used,
        "turn_limit_reached": hit_turn_limit,
        "artifact_gate_failure": artifact_gate_failure,
        "artifact_gate_completed": artifact_gate_completed,
        "provider_error": provider_error,
        "provider_error_category": provider_error_category,
        "provider_http_status": provider_http_status,
        "input_token_bound_exceeded": input_token_bound_exceeded,
        "input_token_bound_reached": input_token_bound_reached,
        "output_token_bound_exceeded": output_token_bound_exceeded,
        "output_token_bound_reached": output_token_bound_reached,
        "cost_bound_exceeded": cost_bound_exceeded,
        "cost_bound_reached": cost_bound_reached,
        "tool_calls": tool_calls_used,
        "tool_limit_reached": tool_limit_reached,
        "wall_time_limit_reached": wall_time_limit_reached,
        "tool_failures": tool_failures,
        "tool_failure_diagnostics": tool_failure_diagnostics,
        "tool_failure_diagnostics_truncated": tool_failure_diagnostics_truncated,
        "error_categories": sorted(error_categories),
        "recovery_actions": sorted(set(recovery_actions)),
    }
