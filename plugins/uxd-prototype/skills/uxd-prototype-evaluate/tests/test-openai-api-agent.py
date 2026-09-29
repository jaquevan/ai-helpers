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
    secret = "sk-" + "svcacctest" + "1234567890"
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
        consistency = root / "uxd-workshop" / "skills" / "uxd-consistency-check"
        consistency.mkdir(parents=True)
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
        scope_diagnostic = openai_api_agent._tool_failure_diagnostic(
            "Scope denied: path is outside allowed roots: /private/user/sensitive/file.txt", 3
        )
        assert scope_diagnostic == {
            "turn": 3,
            "category": "scope_denied",
            "reason": "path_outside_allowed_roots",
        }

        scope_requests = []
        outside_path = root / "outside.txt"

        def scope_call_response(payload):
            scope_requests.append(payload)
            if len(scope_requests) == 1:
                return {
                    "id": "response-scope-call",
                    "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
                    "output": [{
                        "type": "function_call",
                        "call_id": "call-scope-denied",
                        "arguments": json.dumps({
                            "command": f"cat {outside_path}",
                            "timeout_seconds": 1,
                        }),
                    }],
                }
            call_output = next(
                item for item in payload["input"]
                if item.get("type") == "function_call_output"
            )
            assert call_output["call_id"] == "call-scope-denied"
            assert call_output["output"].startswith("Scope denied:")
            return {
                "id": "response-after-scope-denial",
                "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "I will correct the path."}],
                }],
            }

        with patch.object(openai_api_agent, "_request", side_effect=scope_call_response):
            scope_recovered = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=None,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert scope_recovered["status"] == "completed"
        assert scope_recovered["tool_failures"] == 1
        assert scope_recovered["tool_failure_diagnostics"][0]["reason"] == "path_outside_allowed_roots"
        assert len(scope_requests) == 2

        partial_requests = []

        def response_then_http_error(payload):
            partial_requests.append(payload)
            if len(partial_requests) == 1:
                return {
                    "id": "response-before-http-error",
                    "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
                    "output": [{
                        "type": "function_call",
                        "call_id": "call-before-http-error",
                        "arguments": json.dumps({"command": "pwd", "timeout_seconds": 1}),
                    }],
                }
            assert any(
                item.get("type") == "function_call_output"
                and item.get("call_id") == "call-before-http-error"
                for item in payload["input"]
            )
            raise openai_api_agent.OpenAIResponseError(400, "simulated invalid follow-up")

        with patch.object(openai_api_agent, "_request", side_effect=response_then_http_error):
            partial = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=None,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert partial["status"] == "failed"
        assert partial["provider_error_category"] == "provider_request"
        assert partial["token_usage"]["input_tokens"] == 20
        assert partial["token_usage"]["output_tokens"] == 5
        assert "provider_request" in partial["error_categories"]

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
                consistency_check_dir=str(consistency),
            )
        assert environment["JIRA_ISSUE_KEY"] == "RHOAIUX-3239"
        assert environment["CLAUDE_SKILL_DIR"] == str(skill.resolve())
        assert environment["UXD_PROTOTYPE_EXPORT_DIR"] == str(
            (skill.resolve().parent / "uxd-prototype-export")
        )
        assert environment["UXD_CONSISTENCY_CHECK_DIR"] == str(consistency.resolve())
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
        assert capped["cost_usd"] == 0.000284
        assert MAX_AGENT_TURNS == 12

        bounded_requests = []

        def over_input_response(payload):
            bounded_requests.append(payload)
            return {
                **capped_response,
                "id": "response-input-bound",
                "usage": {
                    "input_tokens": 101,
                    "output_tokens": 10,
                    "total_tokens": 111,
                },
            }

        with patch.object(openai_api_agent, "_request", side_effect=over_input_response):
            input_bounded = run_agent(
                "test",
                model="gpt-5.6-terra",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=2,
                max_output_tokens=256,
                max_input_tokens=100,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert input_bounded["exit_code"] == 2
        assert input_bounded["input_token_bound_exceeded"] is True
        assert input_bounded["tool_calls"] == 0
        assert len(bounded_requests) == 1
        assert bounded_requests[0]["max_output_tokens"] == 256

        # Creator phases can remove the fixed turn ceiling while remaining
        # bounded by cumulative output tokens and cost.
        unlimited_workspace = root / "unlimited-workspace"
        unlimited_workspace.mkdir()
        artifact = unlimited_workspace / "done.json"
        unlimited_requests = []

        def artifact_response(payload):
            call_number = len(unlimited_requests) + 1
            unlimited_requests.append(payload)
            return {
                "id": f"response-unlimited-{call_number}",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
                "output": [{
                    "type": "function_call",
                    "call_id": f"call-unlimited-{call_number}",
                    "arguments": json.dumps({
                        "command": f"touch {artifact}",
                        "timeout_seconds": 1,
                    }),
                }],
            }

        with patch.object(openai_api_agent, "_request", side_effect=artifact_response):
            unlimited = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(unlimited_workspace),
                system_prompt="test",
                max_turns=None,
                max_output_tokens=20,
                max_input_tokens=1000,
                max_total_output_tokens=100,
                max_total_cost_usd=1.0,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
                after_turn=lambda turn: ("required artifact complete", True)
                if turn == 5 and artifact.is_file() else None,
                turn_feedback=lambda turn: f"artifact feedback round {turn}" if turn < 5 else None,
            )
        assert unlimited["status"] == "completed"
        assert unlimited["turns_used"] == 5
        assert unlimited["turn_limit_reached"] is False
        assert unlimited["tool_calls"] == 5
        assert len(unlimited_requests) == 5
        assert all(item["max_output_tokens"] == 20 for item in unlimited_requests)
        assert any(
            item.get("role") == "user" and item.get("content") == "artifact feedback round 1"
            for item in unlimited_requests[1]["input"]
        )
        assert unlimited["artifact_gate_completed"] == "required artifact complete"
        assert "artifact_completion_gate" in unlimited["recovery_actions"]

        feedback_artifact = unlimited_workspace / "feedback-complete.json"
        feedback_requests = []

        def feedback_response(payload):
            response_number = len(feedback_requests) + 1
            feedback_requests.append(payload)
            output = [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}]
            if response_number == 2:
                output = [{
                    "type": "function_call",
                    "call_id": "call-feedback-create",
                    "arguments": json.dumps({
                        "command": f"touch {feedback_artifact}",
                        "timeout_seconds": 1,
                    }),
                }]
            return {
                "id": f"response-feedback-{response_number}",
                "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                "output": output,
            }

        with patch.object(openai_api_agent, "_request", side_effect=feedback_response):
            feedback_run = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(unlimited_workspace),
                system_prompt="test",
                max_turns=None,
                max_output_tokens=20,
                max_total_output_tokens=100,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
                after_turn=lambda turn: ("required artifact complete", True)
                if turn == 2 and feedback_artifact.is_file() else None,
                turn_feedback=lambda turn: "The required files are still invalid; correct them."
                if turn == 1 else None,
            )
        assert feedback_run["status"] == "completed"
        assert feedback_run["turns_used"] == 2
        assert feedback_requests[1]["input"] == [{
            "role": "user",
            "content": "The required files are still invalid; correct them.",
        }]

        # Per-turn output remains bounded by the remaining cumulative budget.
        output_bound_requests = []

        def output_bound_response(payload):
            output_bound_requests.append(payload)
            response_number = len(output_bound_requests)
            return {
                "id": f"response-output-bound-{response_number}",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 10 if response_number == 1 else 6,
                    "total_tokens": 20 if response_number == 1 else 16,
                },
                "output": [{
                    "type": "function_call",
                    "call_id": f"call-output-bound-{response_number}",
                    "arguments": json.dumps({
                        "command": f"touch {unlimited_workspace / f'bound-{response_number}'}",
                        "timeout_seconds": 1,
                    }),
                }],
            }

        with patch.object(openai_api_agent, "_request", side_effect=output_bound_response):
            output_bounded = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(unlimited_workspace),
                system_prompt="test",
                max_turns=None,
                max_output_tokens=10,
                max_total_output_tokens=15,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert output_bounded["exit_code"] == 2
        assert output_bounded["output_token_bound_exceeded"] is True
        assert "output_token_bound" in output_bounded["error_categories"]
        assert output_bounded["tool_calls"] == 1
        assert [item["max_output_tokens"] for item in output_bound_requests] == [10, 5]
        assert not (unlimited_workspace / "bound-2").exists()

        # A cost ceiling stops additional requests after the usage reaches the
        # configured reservation, even though tool rounds are unlimited.
        cost_bound_requests = []

        def cost_bound_response(payload):
            cost_bound_requests.append(payload)
            return {
                "id": f"response-cost-bound-{len(cost_bound_requests)}",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
                "output": [{
                    "type": "function_call",
                    "call_id": "call-cost-bound",
                    "arguments": json.dumps({
                        "command": f"touch {unlimited_workspace / 'cost-bound'}",
                        "timeout_seconds": 1,
                    }),
                }],
            }

        with patch.object(openai_api_agent, "_request", side_effect=cost_bound_response):
            cost_bounded = run_agent(
                "test",
                model="gpt-6-sol",
                project_dir=str(unlimited_workspace),
                system_prompt="test",
                max_turns=None,
                max_output_tokens=200,
                max_total_cost_usd=0.0001,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
            )
        assert cost_bounded["exit_code"] == 2
        assert cost_bounded["cost_bound_exceeded"] is True
        assert "cost_bound" in cost_bounded["error_categories"]
        assert cost_bounded["tool_calls"] == 0
        assert len(cost_bound_requests) == 1
        assert not (unlimited_workspace / "cost-bound").exists()

        gate_response = {
            **capped_response,
            "id": "response-2",
        }
        with patch.object(openai_api_agent, "_request", return_value=gate_response):
            artifact_stopped = run_agent(
                "test",
                model="gpt-5.6-terra",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=2,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
                after_turn=lambda turn: "fix-log must be valid by turn 2" if turn == 1 else None,
            )
        assert artifact_stopped["exit_code"] == 2
        assert artifact_stopped["turn_limit_reached"] is False
        assert artifact_stopped["artifact_gate_failure"] == "fix-log must be valid by turn 2"
        assert artifact_stopped["turns_used"] == 1

        with patch.object(openai_api_agent, "_request", return_value=gate_response):
            artifact_completed = run_agent(
                "test",
                model="gpt-5.6-terra",
                project_dir=str(workspace),
                system_prompt="test",
                max_turns=2,
                skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="RHOAIUX-3239",
                benchmark_dir=str(benchmark),
                after_turn=lambda turn: ("valid no-op", True) if turn == 1 else None,
            )
        assert artifact_completed["exit_code"] == 0
        assert artifact_completed["status"] == "completed"
        assert artifact_completed["turn_limit_reached"] is False
        assert artifact_completed["artifact_gate_completed"] == "valid no-op"
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
