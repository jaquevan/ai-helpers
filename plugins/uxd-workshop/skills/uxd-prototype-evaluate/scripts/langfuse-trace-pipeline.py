#!/usr/bin/env python3
"""Run the evaluation pipeline with direct OpenAI API + Langfuse telemetry.

MLflow scripts remain in the repository for reference, but this is the active
pipeline path. Set EVAL_PROVIDER=anthropic to use the existing Claude CLI path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]
sys.path.insert(0, str(SCRIPT_DIR))

import langfuse_trace  # noqa: E402
from model_defaults import detect_platform, model_for, provider_for  # noqa: E402
from openai_api_agent import run_agent  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Run eval pipeline with Langfuse telemetry")
    parser.add_argument("--key", required=True, help="Jira key, for example PROJ-298")
    parser.add_argument("--url", required=True, help="Running prototype URL")
    parser.add_argument("--model", default=None, help="Model override for the whole run")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--platform", choices=["api", "codex", "cursor", "anthropic"], default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--iterate-flags", default="")
    parser.add_argument("--experiment-label", default="eval-iterate")
    parser.add_argument("--reasoning-effort", default="low", choices=["none", "low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-turns", type=int, default=40)
    return parser.parse_args()


def resolve_workspace(key: str, override: str | None) -> str:
    if override:
        return override
    state = PROJECT_ROOT / ".artifacts" / key / "eval" / "eval-state.yaml"
    if state.is_file():
        for line in state.read_text().splitlines():
            if line.startswith("workspace:") and line.split(":", 1)[1].strip():
                return line.split(":", 1)[1].strip()
    legacy = PROJECT_ROOT / ".artifacts" / key / "workspace"
    return str(legacy if legacy.is_dir() else PROJECT_ROOT / "workspace" / "rhoai-https")


def build_prompt(key: str, url: str, workspace: str, flags: str) -> str:
    extra = f"\nAdditional flags: {flags}" if flags else ""
    return (
        f"Run the uxd-prototype-evaluate workflow for Jira key {key}.\n"
        f"Prototype URL: {url}\nWorkspace: {workspace}\n"
        "Read the skill and orchestration instructions in the repository before acting. "
        "Execute the full two-phase pipeline, write all artifacts under "
        f".artifacts/{key}/eval/, and finish with a concise summary of results."
        f"{extra}"
    )


def normalize_prototype_url(url: str) -> str:
    """Accept a URL copied from chat when Markdown link syntax is included."""
    match = re.fullmatch(r"\[(https?://[^\]]+)\]\(https?://[^)]+\)", url.strip())
    return match.group(1) if match else url.strip()


def run_anthropic(prompt: str, model: str, project_dir: str, trace_path: Path) -> dict:
    """Compatibility path for designers who still use Anthropic models."""
    command = ["claude", "--print", "--model", model, "--output-format", "stream-json", "--verbose"]
    started = time.monotonic()
    proc = subprocess.run(command, input=prompt, cwd=project_dir, capture_output=True, text=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(proc.stdout)
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    cost = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            cost = event.get("total_cost_usd")
            usage.update({
                "input_tokens": event.get("usage", {}).get("input_tokens", 0),
                "output_tokens": event.get("usage", {}).get("output_tokens", 0),
            })
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return {
        "provider": "anthropic",
        "model": model,
        "agent": "claude-cli",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": proc.returncode,
        "token_usage": usage,
        "cost_usd": cost,
        "billing_source": "provider_reported" if cost is not None else "unavailable",
    }


def main() -> int:
    args = parse_args()
    platform = args.platform or detect_platform()
    provider = args.provider or os.environ.get("EVAL_PROVIDER") or provider_for(platform)
    model = args.model or os.environ.get("EVAL_MODEL") or model_for("eval-journey", platform)
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. Export a replacement key in this shell "
            "before running the OpenAI pipeline.",
            file=sys.stderr,
        )
        return 2
    url = normalize_prototype_url(args.url)
    workspace = resolve_workspace(args.key, args.workspace)
    prompt = build_prompt(args.key, args.url, workspace, args.iterate_flags)
    trace_dir = PROJECT_ROOT / "tmp" / "trace-runs" / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    trace_path = trace_dir / "responses.jsonl"

    if provider == "openai":
        result = run_agent(
            prompt,
            model=model,
            project_dir=str(PROJECT_ROOT),
            system_prompt=(
                "You are the direct-API execution agent for a local UX evaluation repository. "
                "Use the run_shell tool for all repository inspection and commands. Follow the "
                "repository's AGENTS.md and the evaluation skill instructions. Do not merely "
                "describe commands: execute them and verify artifacts."
            ),
            reasoning_effort=args.reasoning_effort,
            max_turns=args.max_turns,
            trace_path=str(trace_path),
        )
    else:
        result = run_anthropic(prompt, model, str(PROJECT_ROOT), trace_path)

    eval_run_id = langfuse_trace.make_eval_run_id(args.key)
    usage = result.get("token_usage", {})
    phases = [{
        "phase": "eval-iterate",
        "model": model,
        "provider": provider,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "llm_cost_usd": result.get("cost_usd") or 0,
    }]
    payload = {
        "prototype_key": args.key,
        "eval_run_id": eval_run_id,
        "experiment": args.experiment_label,
        "invocation": platform,
        "provider": provider,
        "model": model,
        "billing_source": result.get("billing_source"),
        "iterate_flags": args.iterate_flags,
        "prompt": prompt,
        "run_result": result,
        "phases": phases,
    }
    summary = langfuse_trace.log_pipeline_run(payload)
    print(json.dumps({**result, "eval_run_id": eval_run_id, **summary}, indent=2))
    return 0 if result.get("exit_code") == 0 else result.get("exit_code", 1)


if __name__ == "__main__":
    sys.exit(main())
