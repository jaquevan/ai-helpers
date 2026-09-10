#!/usr/bin/env python3
"""Deterministic tests for per-subskill Langfuse phase construction."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import langfuse_trace  # noqa: E402


class FakeObservation:
    def __init__(self):
        self.updates = []
        self.ended = False

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        self.ended = True
        return self


class FakeClient:
    def __init__(self):
        self.events = []
        self.flushed = False
        self.shutdown_called = False

    def start_observation(self, **kwargs):
        observation = FakeObservation()
        observation.start_kwargs = kwargs
        return observation

    def create_event(self, **kwargs):
        self.events.append(kwargs)

    def create_score(self, **_kwargs):
        return None

    def flush(self):
        self.flushed = True

    def shutdown(self):
        self.shutdown_called = True

    def get_trace_url(self, *, trace_id):
        return f"http://langfuse.test/trace/{trace_id}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artifacts = Path(tmp)
        (artifacts / "eval-state.yaml").write_text(
            "eval_run_id: eval-RHOAIUX-3239-test\n"
            "consistency_source_start: 2026-09-10T10:00:00Z\n"
            "consistency_source_end: 2026-09-10T10:00:02Z\n"
            "bridge_start: 2026-09-10T10:00:02Z\n"
            "bridge_end: 2026-09-10T10:00:05Z\n"
        )
        (artifacts / "consistency-report.json").write_text(json.dumps({
            "guidelines_version": "test-version",
            "source_mode": {
                "ran": True,
                "violations": [
                    {"file": "src/a.tsx"},
                    {"file": "src/a.tsx"},
                    {"file": "src/b.tsx"},
                ],
            },
            "summary": {
                "total_guidelines_checked": 23,
                "violations": 2,
                "warnings": 2,
                "passes": 21,
            },
            "visual_mode": {
                "ran": True,
                "screenshots_checked": 3,
                "findings": [],
                "input_metrics": {
                    "screenshots_considered": 8,
                    "screenshots_analyzed": 3,
                    "guidelines_analyzed": 4,
                    "input_bytes": 12000,
                },
            },
        }))

        phases = langfuse_trace.build_pipeline_phases(
            artifacts,
            {"cost_usd": 0, "token_usage": {}},
        )
        by_name = {phase["phase"]: phase for phase in phases}

        assert "eval-consistency-source" in by_name
        assert "uxd-consistency-check" in by_name
        checker = by_name["uxd-consistency-check"]
        assert checker["guideline_count"] == 23
        assert checker["match_count"] == 3
        assert checker["affected_files"] == 2
        assert checker["llm_cost_usd"] == 0
        assert "uxd-consistency-check" in langfuse_trace.PHASE_NAMES

        costed = langfuse_trace.build_pipeline_phases(
            artifacts,
            {
                "cost_usd": 1.0,
                "model": "gpt-5.6-terra",
                "token_usage": {"input_tokens": 1000, "output_tokens": 100},
            },
        )
        costed_by_name = {phase["phase"]: phase for phase in costed}
        assert costed_by_name["eval-consistency-source"].get("llm_cost_usd", 0) == 0
        assert costed_by_name["uxd-consistency-check"].get("llm_cost_usd", 0) == 0
        assert costed_by_name["eval-consistency-visual"]["llm_cost_usd"] > 0
        assert costed_by_name["eval-consistency-visual"]["screenshots_analyzed"] == 3

    with patch.dict(os.environ, {"AI_HELPERS_PLATFORM": "codex"}, clear=True):
        assert langfuse_trace.detect_invocation() == "codex"
    with patch.dict(os.environ, {"CODEX_THREAD_ID": "test-thread"}, clear=True):
        assert langfuse_trace.detect_invocation() == "codex"
    with patch.dict(os.environ, {}, clear=True):
        assert langfuse_trace.detect_invocation() == "cli"
        assert langfuse_trace.detect_invocation("cursor") == "cursor"

    assert langfuse_trace.pipeline_run_status({"exit_code": 0}) == "completed"
    assert langfuse_trace.pipeline_run_status({
        "exit_code": 0,
        "output_text": "Workflow blocked at preflight",
    }) == "blocked"
    assert langfuse_trace.pipeline_run_status({"exit_code": 2}) == "failed"

    fake_client = FakeClient()
    initial_payload = {
        "prototype_key": "RHOAIUX-3239",
        "eval_run_id": "eval-RHOAIUX-3239-live-test",
        "invocation": "api",
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "prompt": "Evaluate local prototype",
    }
    with patch.object(langfuse_trace, "_get_client", return_value=fake_client):
        live = langfuse_trace.LivePipelineTrace(initial_payload)
    live.root = FakeObservation()
    live.generation = FakeObservation()
    phase_observation = live.start_phase(
        name="eval-classify",
        model="gpt-5.6-luna",
        input_text="Classify one phase",
    )
    live.finish_phase(
        phase_observation,
        phase={
            "phase": "eval-classify",
            "provider": "openai",
            "status": "completed",
            "duration_ms": 1250,
            "turns_used": 2,
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_tokens": 80,
            "llm_cost_usd": 0.001,
            "validation": "passed",
        },
        output_text="Classification completed",
    )
    assert phase_observation.ended
    assert phase_observation.start_kwargs["name"] == "eval-classify"
    assert phase_observation.start_kwargs["input"] == "Classify one phase"
    assert phase_observation.start_kwargs["metadata"]["input_complete"] is True
    assert phase_observation.updates[-1]["metadata"]["duration_ms"] == 1250
    assert phase_observation.updates[-1]["usage_details"] == {
        "input": 20,
        "output": 20,
        "cache_read_input_tokens": 80,
    }
    assert phase_observation.updates[-1]["metadata"]["output_complete"] is True
    assert "eval-classify" in live.live_phase_names
    result_payload = {
        **initial_payload,
        "run_result": {
            "exit_code": 0,
            "status": "completed",
            "duration_s": 4.25,
            "output_text": "Evaluation completed",
            "cost_usd": 0.01,
            "token_usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cached_input_tokens": 80,
            },
        },
        "phases": [{
            "phase": "uxd-prototype-evaluate",
            "model": "gpt-5.6-terra",
        }],
    }
    generation = live.generation
    live.finish(result_payload)
    live.__exit__(None, None, None)
    assert generation.ended
    assert generation.updates[-1]["metadata"]["duration_ms"] == 4250
    assert generation.updates[-1]["output"] == "Evaluation completed"
    assert "usage_details" not in generation.updates[-1]
    assert "cost_details" not in generation.updates[-1]
    assert live.root.updates[-1]["metadata"]["status"] == "completed"
    assert fake_client.flushed
    assert fake_client.shutdown_called

    orchestration = SCRIPT_DIR.parent / "references" / "orchestration.md"
    assert "langfuse_trace.py phase" not in orchestration.read_text()

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
