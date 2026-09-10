#!/usr/bin/env python3
"""Deterministic tests for MCP-first local benchmark preflight."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "langfuse-trace-pipeline.py"
SPEC = importlib.util.spec_from_file_location("langfuse_trace_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def main() -> int:
    repo_tmp = pipeline.PROJECT_ROOT / "tmp"
    repo_tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo_tmp) as temp_dir:
        benchmark = Path(temp_dir).resolve()
        workspace = benchmark / "workspace"
        workspace.mkdir()
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

        resolved = pipeline.resolve_local_inputs(
            key="RHOAIUX-3239",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
        )
        assert resolved["workspace"] == str(workspace)
        assert resolved["jira_context_file"] == str(context)

        prompt = pipeline.build_prompt(
            "RHOAIUX-3239",
            "http://localhost:9000",
            str(workspace),
            "--no-fix",
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
            consistency_report=str(
                workspace
                / ".artifacts"
                / "RHOAIUX-3239"
                / "eval"
                / "consistency-report.json"
            ),
        )
        assert str(pipeline.SKILL_DIR) in prompt
        assert str(context) in prompt
        assert "Validated source consistency report" in prompt
        assert ".claude" in prompt and "Do not discover" in prompt
        assert "credential" in prompt

        invalid_context = benchmark / "invalid.json"
        invalid_context.write_text(json.dumps({
            "source": "manual",
            "ticket": {
                "key": "RHOAIUX-3239",
                "summary": "Invalid",
                "description": "Invalid",
            },
        }))
        try:
            pipeline.resolve_local_inputs(
                key="RHOAIUX-3239",
                workspace=str(workspace),
                jira_context_file=str(invalid_context),
                benchmark_dir=str(benchmark),
            )
        except ValueError as error:
            assert "atlassian-mcp" in str(error)
        else:
            raise AssertionError("non-MCP Jira context should fail")

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
