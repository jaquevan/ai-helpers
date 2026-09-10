#!/usr/bin/env python3
"""Deterministic source-evaluator integration test."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


EVALUATOR_DIR = Path(__file__).resolve().parents[1]
WORKSHOP_DIR = EVALUATOR_DIR.parents[1]
FIXTURE = (
    WORKSHOP_DIR
    / "skills"
    / "uxd-consistency-check"
    / "tests"
    / "fixtures"
    / "ground-truth"
)
sys.path.insert(0, str(EVALUATOR_DIR / "scripts"))

from run_evaluator import run_deterministic_source  # noqa: E402


def main() -> int:
    repo_root = EVALUATOR_DIR.parents[3]
    repo_tmp = repo_root / "tmp"
    repo_tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo_tmp) as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        benchmark = root / "benchmark"
        shutil.copytree(FIXTURE, workspace)
        benchmark.mkdir()
        context = benchmark / "jira-context.json"
        context.write_text(json.dumps({
            "schema_version": 1,
            "source": "atlassian-mcp",
            "ticket": {
                "key": "RHOAIUX-3239",
                "summary": "Tool calling visibility",
                "description": "Acceptance Criteria\n- Show tool calls",
            },
        }))

        result = run_deterministic_source(
            key="RHOAIUX-3239",
            workspace=workspace,
            jira_context_file=context,
            benchmark_dir=benchmark,
            all_files=True,
        )
        assert result["status"] == "completed", result
        assert result["model_invoked"] is False
        assert result["validator"]["all_pass"] is True
        assert result["finding_count"] > 0
        assert result["summary"]["warnings"] > 0
        assert Path(result["consistency_report"]).is_file()
        saved = json.loads((benchmark / "deterministic-source-result.json").read_text())
        assert saved["model_invoked"] is False

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
