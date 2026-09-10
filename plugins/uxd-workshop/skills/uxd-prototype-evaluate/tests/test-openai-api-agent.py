#!/usr/bin/env python3
"""Privacy regression test for provider error handling."""

from __future__ import annotations

import sys
import tempfile
import json
from unittest.mock import patch
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import openai_api_agent  # noqa: E402
from openai_api_agent import (  # noqa: E402
    MAX_AGENT_TURNS,
    redact_api_error,
    run_agent,
    tool_environment,
    validate_shell_command,
)


def main() -> int:
    secret = "sk-svcacctest1234567890"
    redacted = redact_api_error(f"Incorrect API key: {secret}")
    assert secret not in redacted
    assert "[REDACTED_KEY]" in redacted

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        skill = root / "skill"
        benchmark = root / "benchmark"
        for path in (workspace, skill, benchmark):
            path.mkdir()
        allowed = tuple(str(path) for path in (workspace, skill, benchmark))

        validate_shell_command(
            f"python3 {skill}/scripts/check.py --workspace {workspace}",
            allowed,
        )
        denied = (
            "security find-generic-password -g -s atlassian",
            "find $HOME/.claude/plugins/cache -type f",
            f"cat {root}/outside.txt",
            "cat ../outside.txt",
            "printenv OPENAI_API_KEY",
        )
        for command in denied:
            try:
                validate_shell_command(command, allowed)
            except ValueError:
                pass
            else:
                raise AssertionError(f"command should have been denied: {command}")

        with patch.dict(
            "os.environ",
            {
                "PATH": "/usr/bin:/bin",
                "OPENAI_API_KEY": secret,
                "LANGFUSE_SECRET_KEY": "secret",
                "ATLASSIAN_API_TOKEN": "secret",
            },
            clear=True,
        ):
            environment = tool_environment(
                project_dir=str(workspace),
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
            )
        assert environment["JIRA_ISSUE_KEY"] == "RHOAIUX-3239"
        assert environment["CLAUDE_SKILL_DIR"] == str(skill.resolve())
        assert environment["UXD_PROTOTYPE_EXPORT_DIR"] == str(
            (skill.resolve().parent / "uxd-prototype-export")
        )
        assert "OPENAI_API_KEY" not in environment
        assert "LANGFUSE_SECRET_KEY" not in environment
        assert "ATLASSIAN_API_TOKEN" not in environment
        validate_shell_command(
            "python3 ${CLAUDE_SKILL_DIR}/scripts/check.py",
            allowed,
            environment,
        )
        try:
            validate_shell_command(
                "cat ${CLAUDE_PLUGIN_ROOT}/skills/other/SKILL.md",
                allowed,
                environment,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("local environment variables must not escape allowed roots")

        capped_response = {
            "id": "response-1",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens_details": {"reasoning_tokens": 2},
            },
            "output": [{
                "type": "function_call",
                "call_id": "call-1",
                "arguments": json.dumps({"command": "pwd", "timeout_seconds": 1}),
            }],
        }
        with patch.object(openai_api_agent, "_request", return_value=capped_response):
            capped = run_agent(
                "test",
                model="gpt-5.6-terra",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=1,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert capped["exit_code"] == 2
        assert capped["turn_limit_reached"] is True
        assert capped["turns_used"] == 1
        assert capped["token_usage"]["total_tokens"] == 110
        assert capped["cost_usd"] == 0.00032
        assert MAX_AGENT_TURNS == 12
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
