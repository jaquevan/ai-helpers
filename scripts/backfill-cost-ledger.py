#!/usr/bin/env python3
"""Backfill cost-ledger rows from existing eval artifacts (no Claude run)."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
EVAL_SCRIPTS = ROOT / "plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts"

KEYS = [
    ("RHAISTRAT-1492", "golden-a-opus-nofix", "--fresh --no-fix --max-iterations=1"),
    ("RHAISTRAT-1527", "golden-a-opus-nofix", "--fresh --no-fix --max-iterations=1"),
    ("RHAISTRAT-133", "golden-a-opus-nofix", "--fresh --no-fix --max-iterations=1"),
]


def read_quality(artifacts_dir: Path) -> dict:
    quality = {"ac_pass": 0, "ac_fail": 0, "ac_flagged": 0, "usability": None}
    csv_path = artifacts_dir / "evaluation-report.csv"
    if csv_path.is_file():
        for line in csv_path.read_text().splitlines()[1:]:
            if ",PASS," in line:
                quality["ac_pass"] += 1
            elif ",FAIL," in line:
                quality["ac_fail"] += 1
            elif ",FLAGGED," in line:
                quality["ac_flagged"] += 1
    summary_path = artifacts_dir / "evaluation-summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text())
            u = summary.get("usability") or {}
            if isinstance(u.get("total_score"), (int, float)):
                quality["usability"] = u["total_score"]
        except json.JSONDecodeError:
            pass
    return quality


def main() -> int:
    sys.path.insert(0, str(EVAL_SCRIPTS))
    import langfuse_trace  # noqa: E402

    for key, experiment, flags in KEYS:
        artifacts_dir = ROOT / ".artifacts" / key / "eval"
        if not artifacts_dir.is_dir():
            print(f"SKIP {key}: no artifacts at {artifacts_dir}", file=sys.stderr)
            continue

        render_metrics = artifacts_dir / "render-metrics.json"
        if not render_metrics.is_file():
            report = artifacts_dir / "evaluation-report.html"
            if report.is_file():
                subprocess.run(
                    ["node", str(EVAL_SCRIPTS / "render-report.js"), str(artifacts_dir)],
                    cwd=str(ROOT), check=False,
                )

        phases = []
        if render_metrics.is_file():
            m = json.loads(render_metrics.read_text())
            phases.append({
                "phase": "render-report.js",
                "model": None,
                "llm_cost_usd": 0,
                "duration_ms": m.get("duration_ms", 0),
                "output_bytes": m.get("output_bytes", 0),
            })

        eval_run_id = langfuse_trace.make_eval_run_id(key, seed=experiment)
        dims = langfuse_trace.parse_iterate_flags(flags)
        payload = {
            "eval_run_id": eval_run_id,
            "prototype_key": key,
            "experiment": experiment,
            "hypothesis": "Backfill from existing artifacts (pre-instrumentation run)",
            "iterate_flags": flags,
            "run_mode": dims["run_mode"],
            "fix_mode": dims["fix_mode"],
            "invocation": "cursor",
            "model": "claude-opus-4-6",
            "model_tier": "premium",
            "phases": phases,
            "totals": {
                "llm_cost_usd": 0,
                "observability_cost_usd": 0,
                "total_tokens": 0,
            },
            "quality": read_quality(artifacts_dir),
            "notes": "Backfilled — llm_cost_usd=0; re-run with make langfuse-pipeline for traced cost",
        }

        proc = subprocess.run(
            ["node", str(EVAL_SCRIPTS / "log-cost-ledger.js"),
             f"--artifacts-dir={artifacts_dir}"],
            input=json.dumps(payload),
            capture_output=True, text=True, cwd=str(ROOT),
        )
        print(proc.stdout.strip() or proc.stderr.strip())

    return 0


if __name__ == "__main__":
    sys.exit(main())
