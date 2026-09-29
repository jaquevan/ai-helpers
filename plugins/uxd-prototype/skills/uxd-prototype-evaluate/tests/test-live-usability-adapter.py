#!/usr/bin/env python3
"""Ensure failed browser workers return paid usage to pipeline telemetry."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("live_usability_adapter", SCRIPT_DIR / "openai_live_usability.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
from usage_journal import UsageJournal  # noqa: E402


def main() -> int:
    payload = {
        "provider": "openai", "model": "gpt-5.6-terra", "status": "failed",
        "exit_code": 2, "output_text": "provider unavailable", "turns_used": 2,
        "token_usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10, "cached_input_tokens": 0, "reasoning_tokens": 0},
    }
    original = adapter.subprocess.run
    adapter.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout=json.dumps(payload), stderr="")
    try:
        result = adapter.run_live_usability({"artifacts_dir": ".", "prototype_url": "http://localhost"}, model="gpt-5.6-terra")
    finally:
        adapter.subprocess.run = original
    assert result["status"] == "failed"
    assert result["turns_used"] == 2
    assert result["token_usage"]["total_tokens"] == 10
    assert result["cost_usd"] is not None

    # Model a Node worker that persists one response, begins another request,
    # then exceeds the Python timeout. The journal remains the recovery channel.
    with tempfile.TemporaryDirectory() as temp_dir:
        journal_path = Path(temp_dir) / "node-usage.jsonl"

        def timeout_after_response(*_args, **_kwargs):
            journal = UsageJournal(
                journal_path, run_id="node-python-fixture", attempt_id="usability-1",
                phase="eval-usability", model="gpt-5.6-terra",
            )
            request_id = journal.begin("node-response-known")
            journal.response(request_id, {
                "id": "node-response-known-id", "status": "completed",
                "usage": {"input_tokens": 19, "output_tokens": 7},
            })
            journal.begin("node-response-lost")
            raise adapter.subprocess.TimeoutExpired(["node", "fixture"], 1200)

        adapter.subprocess.run = timeout_after_response
        try:
            try:
                adapter.run_live_usability(
                    {"artifacts_dir": ".", "prototype_url": "http://localhost"},
                    model="gpt-5.6-terra", usage_journal_path=str(journal_path),
                    run_id="node-python-fixture", attempt_id="usability-1",
                )
            except TimeoutError:
                pass
            else:
                raise AssertionError("child timeout must reach the parent as a failure")
        finally:
            adapter.subprocess.run = original
        partial = UsageJournal(journal_path, model="gpt-5.6-terra").summary()
        assert partial["token_usage"]["input_tokens"] == 19
        assert partial["token_usage"]["output_tokens"] == 7
        assert partial["usage_known"] is False
        assert partial["unknown_request_ids"] == ["node-response-lost"]
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
