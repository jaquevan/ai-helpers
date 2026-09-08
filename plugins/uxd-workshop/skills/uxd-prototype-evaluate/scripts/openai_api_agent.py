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
        detail = error.read().decode(errors="replace")[:2000]
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


def _run_shell(arguments: str, cwd: str) -> str:
    try:
        parsed = json.loads(arguments)
        command = parsed["command"]
        timeout = min(max(int(parsed.get("timeout_seconds", 120)), 1), 600)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return f"Invalid run_shell arguments: {error}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > 24000:
            output = output[:24000] + "\n...[tool output truncated]"
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
    max_turns: int = 40,
    trace_path: str | None = None,
) -> dict:
    """Run the tool loop and return normalized usage/cost metadata."""
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
    started = time.monotonic()
    trace_file = Path(trace_path) if trace_path else None
    if trace_file:
        trace_file.parent.mkdir(parents=True, exist_ok=True)

    for _turn in range(max_turns):
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
            output = _run_shell(call.get("arguments", "{}"), project_dir)
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": call.get("call_id"),
                "output": output,
            })
    else:
        raise RuntimeError(f"OpenAI agent exceeded max_turns={max_turns}")

    cost = _cost(model, total_usage)
    return {
        "provider": "openai",
        "model": model,
        "agent": "responses-api",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": 0,
        "output_text": final_text,
        "token_usage": total_usage,
        "cost_usd": cost,
        "billing_source": "provider_estimate" if cost is not None else "unavailable",
    }
