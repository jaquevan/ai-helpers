#!/usr/bin/env python3
"""Deterministic source-evaluator integration test."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

EVALUATOR_DIR = Path(__file__).resolve().parents[1]
FIXTURE = EVALUATOR_DIR.parent / "uxd-consistency-check" / "tests" / "fixtures" / "ground-truth"
sys.path.insert(0, str(EVALUATOR_DIR / "scripts"))

from run_evaluator import run_deterministic_source


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        workspace = root / "workspace"
        shutil.copytree(FIXTURE, workspace)
        context = root / "jira-context.json"
        context.write_text(json.dumps({
            "schema_version": 1, "source": "atlassian-mcp",
            "ticket": {"key": "PROJ-123", "summary": "Prototype check", "description": "Show tool calls"},
        }))
        result = run_deterministic_source(
            key="PROJ-123", workspace=workspace, jira_context_file=context,
            artifacts_dir=root / "consumer-eval", all_files=True,
        )
        assert result["status"] == "completed", result
        assert result["model_invoked"] is False
        assert result["validator"]["all_pass"] is True
        assert result["finding_count"] > 0
        assert Path(result["consistency_report"]).is_file()
        assert Path(result["consistency_report"]).parent == root / "consumer-eval"
        assert not (workspace / ".artifacts").exists()
        assert not (root / "consumer-eval" / "shadow").exists()
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
