#!/usr/bin/env python3
"""Small direct-API agent loop for the evaluation pipeline.

It deliberately exposes one narrow tool: run a shell command in the project
workspace. The evaluation skill already defines the workflow; the model only
needs a way to inspect files, run validators/Playwright, and write artifacts.
No MLflow or additional SDK is required.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


PRICING = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (4.00, 20.00),
}

MAX_AGENT_TURNS = 12
MAX_TOOL_OUTPUT_CHARS = 8000
FORBIDDEN_COMMAND_PATTERNS = (
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
    *, project_dir: str, skill_dir: str, jira_context_file: str, jira_issue_key: str
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
            Path(skill_dir).resolve().parent / "uxd-consistency-check"
        ),
        "UXD_PROTOTYPE_EXPORT_DIR": str(
            Path(skill_dir).resolve().parent / "uxd-prototype-export"
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
        raise RuntimeError(f"OpenAI Responses API error {error.code}: {detail}") from error


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
        "reasoning_tokens": int(
            (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        ),
    }


def _cost(model: str, usage: dict) -> float | None:
    rates = PRICING.get(model)
    if not rates:
        return None
    input_rate, output_rate = rates
    return round(
        usage["input_tokens"] * input_rate / 1_000_000
        + usage["output_tokens"] * output_rate / 1_000_000,
        8,
    )


def run_agent(
    prompt: str,
    *,
    model: str,
    project_dir: str,
    system_prompt: str,
    reasoning_effort: str = "low",
    max_turns: int = MAX_AGENT_TURNS,
    trace_path: str | None = None,
    skill_dir: str,
    jira_context_file: str,
    jira_issue_key: str,
    benchmark_dir: str,
) -> dict:
    """Run the tool loop and return normalized usage/cost metadata."""
    if not 1 <= max_turns <= MAX_AGENT_TURNS:
        raise ValueError(f"max_turns must be between 1 and {MAX_AGENT_TURNS}")

    resolved_skill = Path(skill_dir).resolve()
    allowed_roots = tuple(str(Path(path).resolve()) for path in (
        project_dir,
        resolved_skill,
        resolved_skill.parent / "uxd-consistency-check",
        resolved_skill.parent / "uxd-prototype-export",
        resolved_skill.parents[1] / "knowledge",
        benchmark_dir,
    ))
    environment = tool_environment(
        project_dir=project_dir,
        skill_dir=skill_dir,
        jira_context_file=jira_context_file,
        jira_issue_key=jira_issue_key,
    )
    request = {
        "model": model,
        "input": [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "tools": [_tool_definition()],
        "reasoning": {"effort": reasoning_effort},
        "text": {"verbosity": "low"},
    }
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    final_text = ""
    response_id = None
    turns_used = 0
    hit_turn_limit = False
    started = time.monotonic()
    trace_file = Path(trace_path) if trace_path else None
    if trace_file:
        trace_file.parent.mkdir(parents=True, exist_ok=True)

    for _turn in range(max_turns):
        turns_used = _turn + 1
        if response_id:
            request = {
                "model": model,
                "previous_response_id": response_id,
                "input": tool_outputs,
                "tools": [_tool_definition()],
                "reasoning": {"effort": reasoning_effort},
                "text": {"verbosity": "low"},
            }
        response = _request(request)
        if trace_file:
            with trace_file.open("a") as stream:
                stream.write(json.dumps(response) + "\n")

        response_id = response.get("id")
        usage = _usage(response)
        for key, value in usage.items():
            total_usage[key] += value

        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        messages = [item for item in response.get("output", []) if item.get("type") == "message"]
        for message in messages:
            for content in message.get("content", []):
                if content.get("type") == "output_text":
                    final_text += content.get("text", "")

        if not calls:
            break

        tool_outputs = []
        for call in calls:
            output = _run_shell(
                call.get("arguments", "{}"),
                project_dir,
                allowed_roots=allowed_roots,
                environment=environment,
            )
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": call.get("call_id"),
                "output": output,
            })
    else:
        hit_turn_limit = True
        final_text = (
            final_text.rstrip()
            + f"\nOpenAI agent reached max_turns={max_turns} before completion."
        ).lstrip()

    cost = _cost(model, total_usage)
    return {
        "provider": "openai",
        "model": model,
        "agent": "responses-api",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": 2 if hit_turn_limit else 0,
        "status": "failed" if hit_turn_limit else "completed",
        "output_text": final_text,
        "token_usage": total_usage,
        "cost_usd": cost,
        "billing_source": "provider_estimate" if cost is not None else "unavailable",
        "turns_used": turns_used,
        "turn_limit_reached": hit_turn_limit,
    }
