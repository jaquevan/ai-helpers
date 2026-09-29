#!/usr/bin/env python3
"""Deterministic tests for Jira MCP extraction."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "extract_jira_context.py"


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        artifacts = workspace / ".artifacts" / "TEST-1" / "eval"
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=workspace, check=True)
        source = workspace / "src" / "Example.tsx"
        source.parent.mkdir()
        source.write_text("export const Example = () => null;\n")
        subprocess.run(["git", "add", "."], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=workspace, check=True)
        source.write_text("export const Example = () => <div />;\n")
        artifacts.mkdir(parents=True)
        (artifacts / "stale-output.json").write_text("{}")

        context = root / "jira-context.json"
        context.write_text(json.dumps({
            "schema_version": 1,
            "source": "atlassian-mcp",
            "ticket": {
                "key": "TEST-1",
                "summary": "Tool visibility epic",
                "description": "## Problem Statement\nAI engineers need to inspect tool calls.",
                "issue_type": "Epic",
                "parent": None,
                "issue_links": [],
            },
            "related_issues": [{
                "key": "TEST-2",
                "summary": "Show tool calls",
                "issue_type": "Story",
                "description": (
                    "## Problem Statement\nAI engineers cannot easily inspect tool calls.\n\n"
                    "## Objective\nShow tool calls in the playground.\n\n"
                    "## Acceptance Criteria\n- Show tool name and arguments\n- Show results"
                ),
            }],
        }))
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--key", "TEST-1",
                "--jira-context", str(context),
                "--workspace", str(workspace),
                "--artifacts-dir", str(artifacts),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        summary = json.loads(result.stdout)
        extract = json.loads((artifacts / "extract-state.json").read_text())
        delta = json.loads((artifacts / "mr-delta.json").read_text())
        assert summary["model_invoked"] is False
        assert summary["source_ticket"] == "TEST-2"
        assert [item["text"] for item in extract["ac_list"]] == [
            "Show tool name and arguments",
            "Show results",
        ]
        assert extract["persona_selection"]["selected"] == [
            "ml-engineer+junior",
            "ml-engineer+senior",
        ]
        assert extract["journey_definitions"][0]["ac_ids"] == ["AC-1", "AC-2"]
        assert extract["tasks_to_be_done"][0]["covers_acs"] == ["AC-1", "AC-2"]
        assert "src/Example.tsx" in delta["modified_files"]
        assert not any(path.startswith(".artifacts/") for path in delta["changed_files"])

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
