#!/usr/bin/env python3
"""Offline response usage, API state, and failure recovery regressions."""

from __future__ import annotations

from io import BytesIO
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import urllib.error
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import openai_api_agent  # noqa: E402
import langfuse_trace  # noqa: E402
from usage_journal import UsageJournal  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        journal_path = root / "usage.jsonl"
        journal = UsageJournal(
            journal_path, run_id="fixture-run", attempt_id="attempt-1",
            phase="eval-journey", model="gpt-6-sol",
        )
        first_request = journal.begin("req-known")
        response = {
            "id": "resp-known", "status": "completed",
            "usage": {
                "input_tokens": 100, "output_tokens": 25,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 5},
            },
        }
        journal.response(first_request, response)
        # Reopening and replaying an already recorded response is idempotent.
        reopened = UsageJournal(
            journal_path, run_id="fixture-run", attempt_id="attempt-1",
            phase="eval-journey", model="gpt-6-sol",
        )
        reopened.response(first_request, response)
        unknown_request = reopened.begin("req-unknown")
        reopened.failed(unknown_request, category="provider_transport", usage_unknown=True)
        summary = UsageJournal(journal_path, model="gpt-6-sol").summary()
        assert summary["token_usage"]["input_tokens"] == 100
        assert summary["token_usage"]["output_tokens"] == 25
        assert summary["responses_recorded"] == 1
        assert summary["usage_known"] is False
        assert summary["unknown_request_ids"] == ["req-unknown"]
        assert journal_path.stat().st_mode & 0o777 == 0o600

        # Long-context rates apply per response. Two short responses can exceed
        # 272K cumulatively without changing their individual rate tier.
        tiered_path = root / "tiered-usage.jsonl"
        tiered = UsageJournal(tiered_path, model="gpt-6-sol")
        for request_id in ("short-1", "short-2"):
            current = tiered.begin(request_id)
            tiered.response(current, {
                "id": f"response-{request_id}",
                "usage": {"input_tokens": 150_000, "output_tokens": 0},
            })
        tiered_summary = UsageJournal(tiered_path, model="gpt-6-sol").summary()
        assert tiered_summary["token_usage"]["input_tokens"] == 300_000
        assert tiered_summary["known_usage_cost_usd"] == 0.6
        assert tiered_summary["cost_usd"] == 0.6

        long_path = root / "long-usage.jsonl"
        long_journal = UsageJournal(long_path, model="gpt-6-sol")
        long_request = long_journal.begin("one-long-response")
        long_journal.response(long_request, {
            "id": "long-response",
            "usage": {"input_tokens": 272_001, "output_tokens": 100},
        })
        long_summary = UsageJournal(long_path, model="gpt-6-sol").summary()
        assert long_summary["known_usage_cost_usd"] == 1.089504

        # The reservation uses long-context rates for a bound that can cross
        # the threshold; final settlement uses the exact per-response journal sum.
        cost_authority = langfuse_trace.OpenAICostAuthority(
            cap_usd=5, phase_bounds={"tiered": (300_000, 0)},
        )
        reservation = cost_authority.reserve("tiered", "gpt-6-sol")
        assert reservation["reserved_usd"] == 1.2
        settlement = cost_authority.settle(reservation, {
            **tiered_summary["token_usage"],
            "known_usage_cost_usd": tiered_summary["known_usage_cost_usd"],
            "cost_known": tiered_summary["cost_known"],
        })
        assert settlement["settled_usd"] == 0.6

        missing_usage_path = root / "missing-usage.jsonl"
        missing_journal = UsageJournal(missing_usage_path, model="gpt-6-sol")
        missing_request = missing_journal.begin("req-missing")
        missing_journal.response(missing_request, {"id": "resp-no-usage", "status": "completed"})
        missing_summary = UsageJournal(missing_usage_path).summary()
        assert missing_summary["usage_known"] is False
        assert missing_summary["unknown_request_ids"] == ["req-missing"]

        # Reproduce the provider's rejection for the contradictory state mode
        # without network access. Existing adapters either keep response state
        # or replay inputs with store:false; they must never combine both.
        contradictory = {
            "model": "gpt-6-sol", "previous_response_id": "resp-previous",
            "input": [], "store": False,
        }

        def fake_provider_rejects(request, timeout):
            sent = json.loads(request.data)
            assert sent == contradictory
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {},
                BytesIO(b"previous_response_id cannot be used when store is false"),
            )

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fixture-123456789"}),
            patch.object(urllib.request, "urlopen", side_effect=fake_provider_rejects),
        ):
            try:
                openai_api_agent._request(contradictory)
            except openai_api_agent.OpenAIResponseError as error:
                assert error.status_code == 400
                assert "store is false" in str(error)
            else:
                raise AssertionError("contradictory Responses API state must be rejected")

        workspace, skill, benchmark = (root / name for name in ("workspace", "skill", "benchmark"))
        for directory in (workspace, skill, benchmark):
            directory.mkdir()
        requests = []

        def replay(payload):
            requests.append(payload)
            if len(requests) == 1:
                return {
                    "id": "resp-agent-1",
                    "usage": {"input_tokens": 40, "output_tokens": 8},
                    "output": [{
                        "type": "function_call", "call_id": "call-1",
                        "name": "save", "arguments": "{}",
                    }],
                }
            return {
                "id": "resp-agent-2",
                "usage": {"input_tokens": 55, "output_tokens": 10},
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "done"}],
                }],
            }

        direct_journal = root / "direct-usage.jsonl"
        direct_trace = root / "direct-trace.jsonl"
        with patch.object(openai_api_agent, "_request", side_effect=replay):
            direct = openai_api_agent.run_agent(
                "staged task", model="gpt-6-sol", project_dir=str(workspace),
                system_prompt="restricted", max_turns=3,
                skill_dir=str(skill), jira_context_file=str(benchmark / "jira.json"),
                jira_issue_key="DEMO-1", benchmark_dir=str(benchmark),
                usage_journal_path=str(direct_journal), trace_path=str(direct_trace),
                run_id="fixture-run", phase="create-plan",
                tool_definitions=[{"type": "function", "name": "save", "parameters": {}}],
                tool_handler=lambda _name, _args: "saved",
            )
        assert direct["status"] == "completed"
        assert direct["token_usage"]["input_tokens"] == 95
        assert direct["token_usage"]["output_tokens"] == 18
        assert requests[0]["store"] is True
        assert requests[1]["store"] is True
        assert requests[1]["previous_response_id"] == "resp-agent-1"
        assert requests[1]["input"] == [{
            "type": "function_call_output", "call_id": "call-1", "output": "saved",
        }]
        exchanges = [json.loads(line) for line in direct_trace.read_text().splitlines()]
        assert [event["event"] for event in exchanges] == [
            "request", "response", "tool_exchange", "request", "response",
        ]
        assert exchanges[0]["payload"]["store"] is True
        assert exchanges[1]["response"]["id"] == "resp-agent-1"

        # A second-request transport failure leaves the first response usage
        # known, records the in-flight request as unknown, and never reports
        # the partial cost as the total.
        partial_path = root / "partial-usage.jsonl"
        calls = 0

        def response_then_disconnect(payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "id": "resp-before-crash",
                    "usage": {"input_tokens": 13, "output_tokens": 4},
                    "output": [{"type": "function_call", "call_id": "c", "name": "save", "arguments": "{}"}],
                }
            raise OSError("mock transport dropped after first response")

        with patch.object(openai_api_agent, "_request", side_effect=response_then_disconnect):
            failed = openai_api_agent.run_agent(
                "staged task", model="gpt-6-sol", project_dir=str(workspace),
                system_prompt="restricted", max_turns=3, skill_dir=str(skill),
                jira_context_file=str(benchmark / "jira.json"), jira_issue_key="DEMO-1",
                benchmark_dir=str(benchmark), usage_journal_path=str(partial_path),
                tool_definitions=[{"type": "function", "name": "save", "parameters": {}}],
                tool_handler=lambda _name, _args: "saved",
            )
        recovered = UsageJournal(partial_path, model="gpt-6-sol").summary()
        assert failed["usage_known"] is False
        assert failed["cost_usd"] is None
        assert failed["token_usage"]["input_tokens"] == 13
        assert failed["unknown_request_ids"] == recovered["unknown_request_ids"]
        assert recovered["usage_unknown"] is True

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
