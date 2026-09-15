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

import run_evaluator as evaluator  # noqa: E402


CANONICAL_FILES = {
    "actions.json",
    "brief.json",
    "evaluation.json",
    "evidence.json",
    "state.json",
}


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

        result = evaluator.run_deterministic_source(
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
        assert result["summary"]["violations"] > 0
        assert Path(result["consistency_report"]).is_file()
        shadow = result["shadow"]
        assert shadow["status"] == "completed", shadow
        assert shadow["schema_valid"] is True
        assert shadow["adapter_parity"] is True
        assert shadow["model_invoked"] is False
        assert shadow["llm_cost_usd"] == 0
        assert shadow["input_files"] > 0

        shadow_dir = Path(shadow["directory"])
        assert {path.name for path in shadow_dir.iterdir()} == CANONICAL_FILES
        evaluation = json.loads((shadow_dir / "evaluation.json").read_text())
        assert evaluation["consistency"]["source_checked"] is True
        assert evaluation["consistency"]["visual_checked"] is False
        assert evaluation["consistency"]["findings"][0]["severity"] == "error"
        state = json.loads((shadow_dir / "state.json").read_text())
        phase = state["phases"][0]
        assert phase["name"] == "consistency-source"
        assert phase["model_invoked"] is False
        assert phase["provider"] == "none"
        assert phase["input_files"] == shadow["input_files"]
        assert phase["llm_cost_usd"] == 0
        assert all(value == 0 for value in phase["token_usage"].values())

        protected = [
            Path(result["consistency_report"]),
            workspace / ".artifacts" / "RHOAIUX-3239" / "eval" / "evaluation-report.csv",
            workspace / ".artifacts" / "RHOAIUX-3239" / "eval" / "journey-log.json",
        ]
        for path in protected[1:]:
            path.write_text("legacy-boundary\n")
        before = {path: path.read_bytes() for path in protected}
        evaluator.write_consistency_shadow(
            key="RHOAIUX-3239",
            workspace=workspace,
            jira_context=json.loads(context.read_text()),
            legacy_report=json.loads(protected[0].read_text()),
            shadow_root=workspace / ".artifacts" / "RHOAIUX-3239" / "eval" / "shadow" / "consistency-source",
            base_ref=None,
            duration_ms=0,
        )
        assert before == {path: path.read_bytes() for path in protected}

        original_projector = evaluator.write_consistency_shadow
        try:
            evaluator.write_consistency_shadow = lambda **_: (_ for _ in ()).throw(ValueError("shadow test failure"))
            degraded = evaluator.run_deterministic_source(
                key="RHOAIUX-3239",
                workspace=workspace,
                jira_context_file=context,
                benchmark_dir=benchmark,
                all_files=True,
            )
        finally:
            evaluator.write_consistency_shadow = original_projector
        assert degraded["status"] == "completed", degraded
        assert degraded["shadow"]["status"] == "failed"
        assert degraded["model_invoked"] is False
        saved = json.loads((benchmark / "deterministic-source-result.json").read_text())
        assert saved["model_invoked"] is False

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
