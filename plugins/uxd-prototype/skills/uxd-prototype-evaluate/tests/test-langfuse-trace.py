#!/usr/bin/env python3
"""Deterministic tests for per-subskill Langfuse phase construction."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import langfuse_trace  # noqa: E402


class FakeObservation:
    def __init__(self, observation_id="0123456789abcdef"):
        self.id = observation_id
        self.updates = []
        self.child_observations = []
        self.ended = False
        self.otel_attributes = {}
        self._otel_span = types.SimpleNamespace(set_attribute=lambda key, value: self.otel_attributes.update({key: value}))

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        self.ended = True
        return self

    def start_observation(self, **kwargs):
        child = FakeObservation(f"child-{len(self.child_observations) + 1}")
        child.start_kwargs = kwargs
        self.child_observations.append(child)
        return child

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.ended = True
        return False


class FakeClient:
    def __init__(self):
        self.events = []
        self.current_observations = []
        self.flushed = False
        self.shutdown_called = False
        self.root = None
        self.counter = 0

    def _observation_id(self):
        self.counter += 1
        return f"{self.counter:016x}"

    def start_as_current_observation(self, **kwargs):
        self.root = FakeObservation(self._observation_id())
        self.root.start_kwargs = kwargs
        self.current_observations.append(self.root)
        return self.root

    def start_observation(self, **kwargs):
        observation = FakeObservation(self._observation_id())
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
        assert costed_by_name["eval-consistency-visual"]["llm_cost_usd"] is None
        assert costed_by_name["eval-consistency-visual"]["screenshots_analyzed"] == 3

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = Path(tmp)
        from datetime import datetime, timezone
        run_started = datetime.now(timezone.utc)
        (artifacts / "state.json").write_text(json.dumps({"created_at": run_started.isoformat()}))
        (artifacts / "evaluation-report.html").write_text("stale report")
        (artifacts / "render-metrics.json").write_text(json.dumps({"duration_ms": 10, "output_bytes": 12}))
        (artifacts / "journey-log.json").write_text("{}")
        (artifacts / "persona-results.json").write_text("[]")
        (artifacts / "consistency-report.json").write_text(json.dumps({"summary": {"total_guidelines_checked": 24}}))
        old = run_started.timestamp() - 3600
        for name in ("evaluation-report.html", "render-metrics.json", "journey-log.json", "persona-results.json", "consistency-report.json"):
            os.utime(artifacts / name, (old, old))
        stale_phases = langfuse_trace.build_pipeline_phases(artifacts, {"cost_usd": 0, "token_usage": {}})
        stale_names = {phase["phase"] for phase in stale_phases}
        assert "eval-report" not in stale_names
        assert "playwright-run" not in stale_names
        assert "render-report.js" not in stale_names
        assert "validate-artifact-schemas" not in stale_names
        assert "uxd-consistency-check" not in stale_names

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

    benchmark_values = langfuse_trace._trace_values({
        "prototype_key": "PROJ-123",
        "eval_run_id": "eval-PROJ-123-benchmark",
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "benchmark": {
            "benchmark_name": "prototype-evaluator-architecture",
            "comparison_id": "rhaistrat-432-json-parity",
            "condition": "optimized",
            "build_key": "sha256:" + "a" * 64,
            "evaluator_key": "sha256:" + "b" * 64,
            "provider_model": "openai/gpt-5.6-luna",
            "cache_decision": "miss",
            "screenshot_mode": "targeted-crops",
            "artifact_mode": "canonical-json",
            "csv_used": False,
        },
    })
    assert benchmark_values["metadata"]["condition"] == "optimized"
    assert benchmark_values["metadata"]["comparison_id"] == "rhaistrat-432-json-parity"
    assert "benchmark_name=prototype-evaluator-architecture" in benchmark_values["tags"]
    assert "csv_used=False" in benchmark_values["tags"]
    creator_values = langfuse_trace._trace_values({
        "component": "creator",
        "pipeline": "prototype-creator",
        "prototype_key": "CREATE-123",
        "eval_run_id": "create-CREATE-123-run",
        "jira_url": "https://redhat.atlassian.net/browse/CREATE-123",
        "source_revision": "0123456789abcdef",
        "provider": "openai",
        "model": "gpt-6-sol",
        "benchmark": {
            "benchmark_name": "creator-paid-phases",
            "comparison_id": "creator-CREATE-123-rev-a",
        },
    })
    assert creator_values["metadata"]["component"] == "creator"
    assert creator_values["metadata"]["pipeline"] == "prototype-creator"
    assert creator_values["metadata"]["jira_url"] == "https://redhat.atlassian.net/browse/CREATE-123"
    assert creator_values["metadata"]["source_revision"] == "0123456789abcdef"
    assert creator_values["metadata"]["fix_mode"] == "not_applicable"
    assert creator_values["trace_id"] == langfuse_trace.langfuse_trace_id("create-CREATE-123-run")
    assert "comparison_id=creator-CREATE-123-rev-a" in creator_values["tags"]
    assert langfuse_trace.PHASE_DISPLAY_ORDER["create-plan"] == (20, "creator-paid")
    assert {"create-plan", "create-generate", "create-refine"}.issubset(
        langfuse_trace.PHASE_NAMES
    )
    assert langfuse_trace.error_category("OpenAI Responses API error 429") == "provider_transport"
    assert langfuse_trace.error_category("missing required input: journey-log.json") == "missing_input"
    assert langfuse_trace.error_category("OpenAI agent reached max_turns=12") == "turn_budget"
    assert langfuse_trace.error_category("schema validation failed") == "validation"

    fake_client = FakeClient()
    initial_payload = {
        "prototype_key": "RHOAIUX-3239",
        "eval_run_id": "eval-RHOAIUX-3239-live-test",
        "invocation": "api",
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "prompt": "Evaluate local prototype",
    }
    with patch.dict(os.environ, {
        "LANGFUSE_TRACE_ID": "a" * 32,
        "LANGFUSE_PARENT_SPAN_ID": "b" * 16,
    }, clear=False):
        assert langfuse_trace.injected_trace_context() == {
            "trace_id": "a" * 32,
            "parent_span_id": "b" * 16,
        }
        bridge_client = FakeClient()
        with (
            patch.object(langfuse_trace, "_get_client", return_value=bridge_client),
            patch.dict(sys.modules, {"langfuse": types.SimpleNamespace(propagate_attributes=lambda **_kwargs: nullcontext())}),
        ):
            with langfuse_trace.LivePipelineTrace(initial_payload) as bridge:
                bridge_root = bridge_client.current_observations[0]
                assert bridge_root.start_kwargs["trace_context"] == {
                    "trace_id": "a" * 32,
                    "parent_span_id": "b" * 16,
                }
                assert bridge_root.start_kwargs["name"].startswith("evaluation-pipeline/")
                assert bridge_root.otel_attributes["langfuse.internal.is_app_root"] is False
                bridge_phase = bridge.start_phase(
                    name="eval-journey", model="gpt-5.6-luna", input_text="raw opted-in prompt"
                )
                assert bridge_phase.start_kwargs["input"] == "raw opted-in prompt"
                bridge.finish_phase(
                    bridge_phase,
                    phase={"phase": "eval-journey", "status": "completed", "llm_cost_usd": 0},
                    output_text="raw opted-in response",
                    trace_events=[
                        {"event": "request", "request_id": "bridge-request", "payload": {"input": "raw opted-in prompt"}},
                        {"event": "response", "request_id": "bridge-request", "response": {"id": "fixture-response"}},
                    ],
                )
                assert bridge_phase.updates[-1]["output"]["model_output"] == "raw opted-in response"
                assert bridge_phase.child_observations[0].updates[-1]["output"]["id"] == "fixture-response"
                bridge.finish({**initial_payload, "run_result": {"exit_code": 0, "cost_usd": 0}, "phases": []})
        duplicate = langfuse_trace.log_pipeline_run({"eval_run_id": "eval-bridge", "run_result": {"cost_usd": 1}})
        assert duplicate["bridge_attached"] is True
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
            "expected_outputs_present": True,
            "tool_calls": 7,
            "tool_failures": 1,
            "tool_failure_diagnostics": [{
                "turn": 1,
                "category": "scope_denied",
                "reason": "path_outside_allowed_roots",
            }],
            "error_categories": ["tool_nonzero_exit"],
            "recovery_actions": ["continued_after_tool_failure"],
            "artifact_gate_completed": "required outputs are valid",
            "provider_error_category": "provider_request",
            "provider_http_status": 400,
        },
        output_text="Classification completed",
    )
    assert phase_observation.ended
    assert phase_observation.start_kwargs["name"] == "eval-classify"
    assert phase_observation.start_kwargs["input"] is None
    assert phase_observation.start_kwargs["metadata"]["input_complete"] is True
    assert phase_observation.start_kwargs["metadata"]["phase_order"] == 3
    assert phase_observation.start_kwargs["metadata"]["phase_group"] == "deterministic"
    assert phase_observation.updates[-1]["metadata"]["duration_ms"] == 1250
    assert phase_observation.updates[-1]["usage_details"] == {
        "input": 20,
        "output": 20,
        "cache_read_input_tokens": 80,
        "cache_write_input_tokens": 0,
    }
    assert phase_observation.updates[-1]["metadata"]["model_invoked"] is False
    assert phase_observation.updates[-1]["metadata"]["billing_source"] == "local_no_model_cost"
    assert phase_observation.updates[-1]["metadata"]["tool_calls"] == 7
    assert phase_observation.updates[-1]["metadata"]["tool_failures"] == 1
    assert phase_observation.updates[-1]["metadata"]["tool_failure_diagnostics"][0]["reason"] == "path_outside_allowed_roots"
    assert phase_observation.updates[-1]["metadata"]["provider_error_category"] == "provider_request"
    assert phase_observation.updates[-1]["metadata"]["provider_http_status"] == 400
    assert phase_observation.updates[-1]["metadata"]["error_categories"] == ["tool_nonzero_exit"]
    assert phase_observation.updates[-1]["metadata"]["artifact_gate_completed"] == "required outputs are valid"
    assert phase_observation.updates[-1]["output"] is None
    assert phase_observation.updates[-1]["metadata"]["output_complete"] is False
    assert phase_observation.updates[-1]["metadata"]["privacy_mode"] == "metadata_only"
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
    assert generation.updates[-1]["output"] is None
    assert "usage_details" not in generation.updates[-1]
    assert "cost_details" not in generation.updates[-1]
    assert live.root.updates[-1]["metadata"]["status"] == "completed"
    assert fake_client.flushed
    assert fake_client.shutdown_called

    grouped_client = FakeClient()
    grouped_langfuse = types.SimpleNamespace(
        propagate_attributes=lambda **_kwargs: nullcontext(),
    )
    grouped_payload = {
        **initial_payload,
        "benchmark": {
            "benchmark_name": "designer-phase-costs",
            "comparison_id": "rhaistrat-432-json-parity",
            "condition": "optimized-cold",
            "artifact_mode": "canonical-json-v1",
            "csv_used": False,
        },
    }
    with (
        patch.object(langfuse_trace, "_get_client", return_value=grouped_client),
        patch.dict(sys.modules, {"langfuse": grouped_langfuse}),
    ):
        with langfuse_trace.LivePipelineTrace(grouped_payload) as grouped:
            assert [
                item.start_kwargs["name"] for item in grouped_client.current_observations
            ] == [
                "evaluation/RHOAIUX-3239/rhaistrat-432-json-parity",
                "evaluation-phases",
            ]
            grouped.finish({
                **grouped_payload,
                "run_result": {
                    "exit_code": 0,
                    "status": "completed",
                    "duration_s": 0,
                    "cost_usd": 0,
                    "token_usage": {},
                },
                "phases": [],
            })
    assert all(item.ended for item in grouped_client.current_observations)

    metadata_client = FakeClient()
    safe_output = {
        "status": "completed",
        "violation_groups": 2,
        "model_invoked": False,
    }
    fake_langfuse = types.SimpleNamespace(
        propagate_attributes=lambda **_kwargs: nullcontext(),
    )
    with (
        patch.object(langfuse_trace, "_get_client", return_value=metadata_client),
        patch.dict(sys.modules, {"langfuse": fake_langfuse}),
    ):
        metadata_result = langfuse_trace.log_metadata_trace(
            root_name="consistency-check/PROJ-123",
            run_id="consistency-PROJ-123-test",
            metadata={"component": "consistency", "privacy_mode": "metadata_only"},
            events=[{"phase": "consistency-source", "output": safe_output}],
            output=safe_output,
        )
    assert metadata_result["logged"] is True
    assert metadata_client.root.updates[-1]["output"] == safe_output
    assert metadata_client.events[-1]["output"] == safe_output
    assert "output" not in metadata_client.events[-1]["metadata"]

    nested_metadata_client = FakeClient()
    with (
        patch.object(langfuse_trace, "_get_client", return_value=nested_metadata_client),
        patch.dict(sys.modules, {"langfuse": fake_langfuse}),
        patch.dict(os.environ, {
            "LANGFUSE_TRACE_ID": "c" * 32,
            "LANGFUSE_PARENT_SPAN_ID": "d" * 16,
        }, clear=False),
    ):
        nested_result = langfuse_trace.log_metadata_trace(
            root_name="consistency-source-ai",
            run_id="consistency-PROJ-123-source-ai",
            metadata={"component": "consistency", "privacy_mode": "metadata_only", "model_invoked": True},
            events=[{"phase": "consistency-source-ai", "model_invoked": True, "output": safe_output}],
            output=safe_output,
        )
    assert nested_result["trace_id"] == "c" * 32
    assert nested_metadata_client.root.start_kwargs["trace_context"] == {
        "trace_id": "c" * 32,
        "parent_span_id": "d" * 16,
    }
    assert nested_metadata_client.events[-1]["metadata"]["model_invoked"] is True

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = Path(tmp)
        (artifacts / "evaluation.json").write_text(json.dumps({
            "artifact_type": "evaluation",
            "status": "completed",
            "rationale": "email jane@example.test must be redacted",
            "image": {"base64": "not-for-export"},
            "screenshot_path": "screenshots/a.png",
            "summary": {"pass": 1},
        }))
        sanitized = langfuse_trace.sanitized_evaluation_artifact(artifacts)
        assert sanitized is not None
        exported = json.dumps(sanitized)
        assert "jane@example.test" not in exported
        assert "screenshot_path" not in exported
        assert "base64" not in exported

        (artifacts / "persona-results.json").write_text(json.dumps([{
            "persona": "data-scientist+junior",
            "outcome": "blocked",
            "reasoning": "email jane@example.test must be redacted",
            "screenshots": ["screenshots/persona.png"],
            "trace": [{"action": "Deploy model", "image": {"base64": "blocked"}}],
        }]))
        persona_output = langfuse_trace.sanitized_phase_artifact("eval-usability", artifacts)
        assert persona_output is not None
        assert isinstance(persona_output["content"], list)
        assert persona_output["content"][0]["outcome"] == "blocked"
        persona_export = json.dumps(persona_output)
        assert "jane@example.test" not in persona_export
        assert "screenshots" not in persona_export
        assert "base64" not in persona_export

        (artifacts / "consistency-report.json").write_text(json.dumps({
            "summary": {"total_guidelines_checked": 2, "violations": 1, "warnings": 0, "passes": 1},
            "visual_mode": {
                "screenshots_checked": 1,
                "findings": [{
                    "guideline_id": "button-label", "guideline_title": "Button labels",
                    "category": "content", "severity": "warning", "verdict": "FLAGGED",
                    "description": "Visible control needs a clearer label.",
                    "suggestion": "Use an action-specific label.",
                    "screenshot": "screenshots/private.png", "url": "https://private.test",
                    "dom": "<button>private</button>", "path": "/private/source.tsx",
                }],
            },
        }))
        visual_output = langfuse_trace.sanitized_phase_artifact("eval-consistency-visual", artifacts)
        assert visual_output is not None
        envelope = visual_output["content"]
        assert envelope["artifact_type"] == "uxd-consistency-visual-judge-envelope"
        assert envelope["summary"]["visual_finding_count"] == 1
        assert envelope["findings"][0]["guideline"]["id"] == "button-label"
        assert envelope["findings"][0]["remediation"] == "Use an action-specific label."
        visual_export = json.dumps(visual_output)
        assert "screenshots/private.png" not in visual_export
        assert "private.test" not in visual_export
        assert "source.tsx" not in visual_export

        (artifacts / "consistency-report.json").write_text(json.dumps({
            "summary": {"total_guidelines_checked": 2, "violations": 0, "warnings": 0, "passes": 2},
            "visual_mode": {"screenshots_checked": 1, "findings": []},
        }))
        zero_visual_output = langfuse_trace.sanitized_phase_artifact("eval-consistency-visual", artifacts)
        assert zero_visual_output is not None
        assert zero_visual_output["content"]["verdict"] == "PASS"
        assert zero_visual_output["content"]["findings"] == []
        assert zero_visual_output["content"]["summary"]["visual_finding_count"] == 0

        (artifacts / "evidence.json").write_text(json.dumps({
            "items": [{"id": "crop-1", "image": {"width": 312, "height": 128}}],
        }))
        image_estimate = langfuse_trace.calibration_image_token_expectations(artifacts)
        assert image_estimate["model_invoked"] is False
        assert image_estimate["crops"][0]["high_detail_tokens"] == 1445
        assert image_estimate["auto_detail_expected_tokens"] == 1445
        assert image_estimate["measurement_status"] == "not_measured"

    opted_payload = {
        **initial_payload,
        "privacy_mode": "sanitized_artifact_output",
        "sanitized_artifact_output": sanitized,
        "run_result": {"exit_code": 0, "cost_usd": 0, "token_usage": {}},
        "phases": [],
    }
    with patch.object(langfuse_trace, "_get_client", return_value=fake_client):
        opted = langfuse_trace.LivePipelineTrace(opted_payload)
    opted.root = FakeObservation()
    opted.generation = FakeObservation()
    opted.finish(opted_payload)
    assert opted.root.updates[-1]["output"] == sanitized

    # Full trace mode keeps ordinary benchmark content and complete artifacts,
    # while redacting credential values in nested request/response content.
    with tempfile.TemporaryDirectory() as tmp:
        root_dir = Path(tmp)
        artifacts_dir = root_dir / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "criteria.md").write_text(
            "Approval must explain why a request is blocked.\n"
            "Authorization: Basic dXNlcjpwYXNz\n"
            "Cookie: session=browser-cookie-secret; Path=/\n"
            "api_key=sk-proj-fixture-secret-123456789\n"
            "langfuse_public_key=pk-lf-fixture-public-123456789\n"
            "https://example.test/?access_token=query-secret-98765\n"
            "environment credential: fixture-env-secret-value-45678\n"
        )
        (artifacts_dir / "screen.png").write_bytes(b"\x89PNG\r\nfixture-binary")
        (artifacts_dir / "auth-state.json").write_text('{"accessToken":"credential-file-secret"}')
        source_tree = artifacts_dir / "code"
        source_tree.mkdir()
        (source_tree / "unrelated.tsx").write_text("must not be captured in run summary")
        with patch.dict(os.environ, {"EVAL_ACCESS_TOKEN": "fixture-env-secret-value-45678"}):
            bundle = langfuse_trace.full_artifact_bundle(artifacts_dir)
        encoded_bundle = json.dumps(bundle)
        assert "Approval must explain why a request is blocked" in encoded_bundle
        assert "screen.png" in encoded_bundle
        assert "base64" in encoded_bundle
        for secret in (
            "dXNlcjpwYXNz", "browser-cookie-secret", "sk-proj-fixture-secret-123456789",
            "pk-lf-fixture-public-123456789",
            "query-secret-98765", "fixture-env-secret-value-45678", "credential-file-secret",
        ):
            assert secret not in encoded_bundle
        assert "[REDACTED]" in encoded_bundle
        assert langfuse_trace.redact_content({
            "public_key": "pk-lf-fixture-public-123456789",
        }) == {"public_key": "[REDACTED]"}
        assert json.loads(encoded_bundle)[0]["content"]["encoding"] == "omitted"
        selected_bundle = langfuse_trace.full_artifact_bundle(
            artifacts_dir, include_paths=["criteria.md"]
        )
        assert [entry["path"] for entry in selected_bundle] == ["criteria.md"]
        try:
            langfuse_trace.full_artifact_bundle(artifacts_dir, include_paths=["../outside.txt"])
        except ValueError:
            pass
        else:
            raise AssertionError("full artifact capture must reject paths outside its artifact root")

        trace_context_path = root_dir / "langfuse-trace-context.json"
        full_payload = {
            **initial_payload,
            "component": "creator",
            "pipeline": "prototype-creator",
            "eval_run_id": "shared-fixture-run",
            "privacy_mode": "full_raw",
            "trace_content": "full",
            "trace_context_path": str(trace_context_path),
            "artifacts_dir": str(artifacts_dir),
        }
        full_client = FakeClient()
        with (
            patch.object(langfuse_trace, "_get_client", return_value=full_client),
            patch.dict(sys.modules, {"langfuse": fake_langfuse}),
        ):
            with langfuse_trace.LivePipelineTrace(full_payload) as full_trace:
                full_phase = full_trace.start_phase(
                    name="create-plan", model="gpt-6-sol",
                    input_text="Acceptance criteria: approve the request and show a clear status.",
                )
                full_trace.finish_phase(
                    full_phase,
                    phase={
                        "phase": "create-plan", "model": "gpt-6-sol", "status": "failed",
                        "input_tokens": 80, "output_tokens": 9, "cache_read_tokens": 10,
                        "known_usage_cost_usd": 0.0004, "llm_cost_usd": None,
                        "usage_known": False, "usage_unknown": True,
                        "unknown_request_ids": ["req-unresolved"],
                    },
                    output_text="Known partial result; awaiting usage reconciliation.",
                    trace_events=[
                        {
                            "event": "request", "request_id": "req-full-1", "model": "gpt-6-sol",
                            "payload": {"input": "Acceptance criteria", "tools": [{"name": "creator_write_output"}]},
                        },
                        {
                            "event": "response", "request_id": "req-full-1",
                            "response": {
                                "output_text": "Known partial result",
                                "output": [
                                    {"type": "reasoning", "summary": [{
                                        "type": "summary_text", "text": "private reasoning fixture",
                                    }]},
                                    {"type": "message", "content": [{
                                        "type": "output_text", "text": "Known partial result",
                                    }]},
                                ],
                            },
                            "usage": {"input_tokens": 80, "output_tokens": 9, "cached_input_tokens": 10},
                            "usage_known": False,
                        },
                        {
                            "event": "tool_exchange", "call": {"call_id": "call-full-1", "name": "creator_write_output"},
                            "output": {"status": "written", "text": "Approval wording stays clear."},
                            "credentials": "sk-proj-fixture-secret-123456789",
                        },
                        # Simulate journal recovery replaying an exchange that
                        # the live stream had already attached to this phase.
                        {
                            "event": "request", "request_id": "req-full-1", "model": "gpt-6-sol",
                            "payload": {"input": "Acceptance criteria", "tools": [{"name": "creator_write_output"}]},
                        },
                        {
                            "event": "response", "request_id": "req-full-1",
                            "response": {
                                "output_text": "Known partial result",
                                "output": [{"type": "message", "content": [{
                                    "type": "output_text", "text": "Known partial result",
                                }]}],
                            },
                            "usage": {"input_tokens": 80, "output_tokens": 9, "cached_input_tokens": 10},
                            "usage_known": False,
                        },
                        {
                            "event": "tool_exchange", "call": {"call_id": "call-full-1", "name": "creator_write_output"},
                            "output": {"status": "written", "text": "Approval wording stays clear."},
                            "credentials": "sk-proj-fixture-secret-123456789",
                        },
                    ],
                    artifacts_dir=artifacts_dir,
                    artifact_paths=["criteria.md"],
                )
                phase_output = full_phase.updates[-1]["output"]
                assert full_phase.start_kwargs["as_type"] == "span"
                assert "model" not in full_phase.start_kwargs
                assert "usage_details" not in full_phase.updates[-1]
                assert "cost_details" not in full_phase.updates[-1]
                assert full_phase.updates[-1]["metadata"]["estimated_cost_usd"] == 0.0004
                assert full_phase.updates[-1]["metadata"]["child_observation_counts"] == {
                    "requests": 1, "tools": 1, "artifacts": 1,
                }
                assert phase_output["model_output"].startswith("Known partial result")
                assert phase_output["detail_location"] == "nested_request_tool_artifact_observations"
                assert "sk-proj-fixture-secret-123456789" not in json.dumps(phase_output)
                assert full_phase.start_kwargs["input"].startswith("Acceptance criteria")
                child_types = [child.start_kwargs["as_type"] for child in full_phase.child_observations]
                assert child_types.count("generation") == 1
                assert child_types.count("tool") == 1
                assert child_types.count("span") >= 1  # artifact child per file
                request_child = next(
                    child for child in full_phase.child_observations
                    if child.start_kwargs["as_type"] == "generation"
                )
                assert request_child.start_kwargs["input"]["input"] == "Acceptance criteria"
                assert request_child.updates[0]["output"]["output_text"] == "Known partial result"
                assert "private reasoning fixture" not in json.dumps(request_child.updates[0]["output"])
                assert request_child.updates[0]["output"]["output"][0]["type"] == "message"
                assert request_child.updates[0]["usage_details"]["cache_read_input_tokens"] == 10
                tool_child = next(
                    child for child in full_phase.child_observations
                    if child.start_kwargs["as_type"] == "tool"
                )
                assert tool_child.start_kwargs["input"]["name"] == "creator_write_output"
                assert tool_child.updates[0]["output"]["text"] == "Approval wording stays clear."
                artifact_child = next(
                    child for child in full_phase.child_observations
                    if child.start_kwargs.get("metadata", {}).get("path") == "criteria.md"
                )
                assert artifact_child.updates[0]["output"]["text"].startswith("Approval must explain")
                nested_payloads = json.dumps([
                    child.start_kwargs for child in full_phase.child_observations
                ] + [child.updates for child in full_phase.child_observations])
                assert "sk-proj-fixture-secret-123456789" not in nested_payloads
                full_trace.finish({
                    **full_payload,
                    "run_result": {
                        "status": "failed", "exit_code": 2, "cost_usd": None,
                        "known_usage_cost_usd": 0.0004, "usage_known": False,
                        "usage_unknown": True, "token_usage": {"input_tokens": 80, "output_tokens": 9},
                    },
                    "phases": [],
                }, artifact_paths=["criteria.md"])
                assert full_trace.finished is True
                assert [item["path"] for item in full_trace.payload["full_trace_content"]["artifacts"]] == [
                    "criteria.md"
                ]
                assert "unrelated.tsx" not in json.dumps(full_trace.payload["full_trace_content"])
                first_root_id = full_trace.root.id
                first_trace_id = full_trace.values["trace_id"]
        context = json.loads(trace_context_path.read_text())
        assert context["trace_id"] == first_trace_id
        assert context["parent_span_id"] == first_root_id
        assert trace_context_path.stat().st_mode & 0o777 == 0o600
        root_update = full_client.current_observations[0].updates[-1]
        assert root_update["metadata"]["llm_cost_usd"] is None
        assert root_update["metadata"]["known_usage_cost_usd"] == 0.0004
        assert root_update["metadata"]["usage_unknown"] is True
        assert "cost_usd=unknown" in root_update["status_message"]

        next_client = FakeClient()
        with (
            patch.object(langfuse_trace, "_get_client", return_value=next_client),
            patch.dict(sys.modules, {"langfuse": fake_langfuse}),
        ):
            with langfuse_trace.LivePipelineTrace(full_payload) as next_trace:
                assert next_trace.bridge_context == {
                    "trace_id": first_trace_id,
                    "parent_span_id": first_root_id,
                }
                assert next_client.current_observations[0].start_kwargs["trace_context"] == next_trace.bridge_context
                next_trace.finish({
                    **full_payload, "run_result": {"status": "completed", "cost_usd": 0}, "phases": [],
                })

        with patch.object(langfuse_trace, "_get_client", return_value=None):
            try:
                with langfuse_trace.LivePipelineTrace(full_payload):
                    pass
            except RuntimeError as error:
                assert "refusing a silent metadata-only downgrade" in str(error)
            else:
                raise AssertionError("full-content runs must stop if Langfuse is unavailable")

    orchestration = SCRIPT_DIR.parent / "references" / "orchestration.md"
    assert "langfuse_trace.py phase" not in orchestration.read_text()

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
