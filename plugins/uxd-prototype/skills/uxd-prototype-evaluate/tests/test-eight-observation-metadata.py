#!/usr/bin/env python3
"""Zero-spend fixture for the shared eight-observation metadata contract."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import langfuse_trace  # noqa: E402


class FakeObservation:
    def __init__(self, start_kwargs):
        self.start_kwargs = start_kwargs
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        return self


class FakeClient:
    def __init__(self):
        self.observations = []

    def start_observation(self, **kwargs):
        observation = FakeObservation(kwargs)
        self.observations.append(observation)
        return observation


def main() -> int:
    client = FakeClient()
    payload = {
        "prototype_key": "RHAISTRAT-1745",
        "eval_run_id": "eval-RHAISTRAT-1745-eight-observations",
        "invocation": "api",
        "provider": "openai",
        "model": "phase-routed",
        "privacy_mode": "sanitized_artifact_output",
        "benchmark": {"benchmark_name": "designer-phase-costs"},
    }
    with patch.object(langfuse_trace, "_get_client", return_value=client):
        trace = langfuse_trace.LivePipelineTrace(payload)
    trace.root = object()

    deterministic = (
        "eval-extract", "eval-classify", "eval-consistency-source", "eval-report",
    )
    paid = (
        "eval-journey", "eval-fix", "eval-consistency-visual", "eval-heuristic", "eval-usability",
    )
    for phase_name in (*deterministic, *paid):
        is_paid = phase_name in paid
        observation = trace.start_phase(
            name=phase_name,
            model="gpt-6-sol" if is_paid else None,
            provider="openai" if is_paid else "local",
            input_text=f"fixture:{phase_name}",
        )
        trace.finish_phase(
            observation,
            phase={
                "phase": phase_name,
                "model": "gpt-6-sol" if is_paid else None,
                "model_invoked": is_paid,
                "provider": "openai" if is_paid else "local",
                "status": "completed",
                "input_tokens": 1 if is_paid else 0,
                "output_tokens": 1 if is_paid else 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "llm_cost_usd": 0,
                "validation": "fixture passed",
            },
            output_text="fixture completed",
        )

    assert len(client.observations) == 9
    for observation in client.observations:
        start_metadata = observation.start_kwargs["metadata"]
        finish_metadata = observation.updates[-1]["metadata"]
        assert start_metadata["benchmark_name"] == "designer-phase-costs"
        assert start_metadata["privacy_mode"] == "sanitized_artifact_output"
        assert observation.start_kwargs.get("model") == ("gpt-6-sol" if start_metadata["phase"] in paid else None)
        assert finish_metadata["benchmark_name"] == "designer-phase-costs"
        assert finish_metadata["privacy_mode"] == "sanitized_artifact_output"
        assert finish_metadata["model"] == ("gpt-6-sol" if finish_metadata["phase"] in paid else None)
        assert finish_metadata["model_invoked"] is (finish_metadata["phase"] in paid)
        assert "estimated_cost_usd" in finish_metadata

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
