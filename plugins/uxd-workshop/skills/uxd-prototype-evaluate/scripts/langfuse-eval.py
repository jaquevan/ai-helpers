#!/usr/bin/env python3
"""Lean artifact scorer with optional Langfuse quality scores.

This replaces the active MLflow scorer path without deleting the old script.
Scoring is local and deterministic; Langfuse receives one metadata-only trace.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
import langfuse_trace  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Score eval artifacts and log to Langfuse")
    parser.add_argument("artifacts_dir")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--prototype-key", default=None)
    parser.add_argument("--scorers", nargs="+", default=["pipeline-output", "report-rendering", "script-tests"])
    return parser.parse_args()


def run_scorer(script: Path, artifacts_dir: str) -> dict:
    command = ["node", str(script), artifacts_dir]
    if script.name == "validate-artifact-schemas.js":
        command.append("--json")
    result = subprocess.run(command, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"results": [{"scorer": script.stem, "pass": False, "detail": result.stderr[-500:]}]}


def run_script_tests() -> dict:
    result = subprocess.run(
        ["bash", str(SKILL_DIR / "tests" / "run-script-tests.sh")],
        cwd=str(SKILL_DIR), capture_output=True, text=True,
    )
    checks = []
    current = "script-tests"
    for line in result.stdout.splitlines():
        if line.startswith("Test "):
            current = line[5:].rstrip(": ")
        elif line.strip() in {"PASS", "FAIL"}:
            checks.append({"scorer": current, "pass": line.strip() == "PASS", "detail": line.strip()})
    return {"results": checks}


def main() -> int:
    args = parse_args()
    artifacts_dir = os.path.abspath(args.artifacts_dir)
    key = args.prototype_key or Path(artifacts_dir).resolve().parent.name
    scorers = ["pipeline-output", "report-rendering", "script-tests"] if "all" in args.scorers else args.scorers
    scripts = {
        "pipeline-output": SKILL_DIR / "scripts" / "validate-artifact-schemas.js",
        "report-rendering": SKILL_DIR / "scripts" / "validate-report-rendering.js",
    }
    checks = []
    for scorer in scorers:
        output = run_script_tests() if scorer == "script-tests" else run_scorer(scripts[scorer], artifacts_dir)
        checks.extend(output.get("results", []))

    passed = sum(1 for check in checks if check.get("pass"))
    failed = len(checks) - passed
    eval_run_id = langfuse_trace.make_eval_run_id(key)
    quality = {
        "pass_count": passed,
        "fail_count": failed,
        "pass_rate": passed / max(len(checks), 1),
        "all_pass": 1 if failed == 0 else 0,
    }
    payload = {
        "prototype_key": key,
        "eval_run_id": eval_run_id,
        "experiment": "artifact-eval",
        "invocation": "cli",
        "provider": args.provider or "none",
        "model": args.model,
        "run_result": {"cost_usd": 0, "token_usage": {}},
        "phases": [{"phase": "artifact-scoring", "model": None, "llm_cost_usd": 0}],
        "quality": quality,
    }
    summary = langfuse_trace.log_pipeline_run(payload)
    result = {"eval_run_id": eval_run_id, **quality, "checks": checks, **summary}
    print(json.dumps(result, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
