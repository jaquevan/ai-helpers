#!/usr/bin/env python3
"""Small direct-API model comparison runner.

Each model is run against one skill prompt, then usage/cost/quality metadata is
sent to Langfuse. It intentionally does not depend on MLflow or agent-eval.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]
sys.path.insert(0, str(SCRIPT_DIR))
import langfuse_trace  # noqa: E402
from openai_api_agent import run_agent  # noqa: E402


PHASE_DOCS = {
    "eval-extract": "eval-extract.md",
    "eval-classify": "eval-classify.md",
    "eval-journey": "eval-journey.md",
    "eval-consistency": "eval-consistency.md",
    "eval-usability": "eval-usability.md",
    "eval-report": "eval-report.md",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare OpenAI models with Langfuse")
    parser.add_argument("--key", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:9204")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--skills", nargs="+", default=["eval-extract", "eval-classify", "eval-consistency", "eval-report"])
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = args.workspace or str(PROJECT_ROOT / "workspace" / "rhoai-https")
    results = []
    for skill in args.skills:
        if skill not in PHASE_DOCS:
            raise SystemExit(f"Unknown skill: {skill}")
        prompt = (
            f"Read {SKILL_DIR / 'references' / 'phases' / PHASE_DOCS[skill]} and execute only that phase.\n"
            f"Key: {args.key}\nURL: {args.url}\nWorkspace: {workspace}\n"
            f"Write artifacts under .artifacts/{args.key}/eval/."
        )
        for model in args.models:
            print(f"{skill} {model}", file=sys.stderr)
            if args.dry_run:
                print(prompt)
                continue
            trace_path = PROJECT_ROOT / "tmp" / "trace-runs" / f"compare-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{skill}-{model}.jsonl"
            result = run_agent(
                prompt,
                model=model,
                project_dir=str(PROJECT_ROOT),
                system_prompt=(
                    "You are a direct-API evaluation agent. Use run_shell to execute the requested "
                    "phase and verify its artifacts. Follow repository instructions."
                ),
                reasoning_effort="low" if "luna" in model else "medium",
                trace_path=str(trace_path),
            )
            usage = result.get("token_usage", {})
            eval_run_id = langfuse_trace.make_eval_run_id(args.key)
            summary = langfuse_trace.log_pipeline_run({
                "prototype_key": args.key,
                "eval_run_id": eval_run_id,
                "experiment": f"compare-{skill}-{model}",
                "invocation": "api",
                "provider": "openai",
                "model": model,
                "billing_source": result.get("billing_source"),
                "run_result": result,
                "phases": [{
                    "phase": skill,
                    "model": model,
                    "provider": "openai",
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "llm_cost_usd": result.get("cost_usd") or 0,
                }],
            })
            results.append({"skill": skill, "model": model, **result, **summary})

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
