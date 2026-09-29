#!/usr/bin/env python3
"""Deterministic tests for bounded, phase-specific OpenAI orchestration."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "langfuse-trace-pipeline.py"
SPEC = importlib.util.spec_from_file_location("bounded_phase_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
from usage_journal import UsageJournal  # noqa: E402


def main() -> int:
    assert pipeline.trace_content_policy(type("Args", (), {
        "personal_run": False, "benchmark_name": "quality-study",
        "comparison_id": None, "condition": None,
        "trace_content": None, "trace_sanitized_artifacts": False,
    })()) == "full"
    assert pipeline.trace_content_policy(type("Args", (), {
        "personal_run": True, "benchmark_name": "designer-phase-costs",
        "comparison_id": None, "condition": None,
        "trace_content": None, "trace_sanitized_artifacts": False,
    })()) == "metadata"
    try:
        pipeline.trace_content_policy(type("Args", (), {
            "personal_run": False, "benchmark_name": "quality-study",
            "comparison_id": None, "condition": None,
            "trace_content": "metadata", "trace_sanitized_artifacts": False,
        })())
    except ValueError as error:
        assert "require trace_content=full" in str(error)
    else:
        raise AssertionError("controlled benchmark may not silently choose metadata-only capture")

    full_phase_names = [spec["name"] for spec in pipeline.selected_openai_phases()]
    light_phase_names = [
        spec["name"] for spec in pipeline.selected_openai_phases(no_fix=True)
    ]
    assert "eval-fix" in full_phase_names
    assert "eval-fix" not in light_phase_names
    assert light_phase_names == [name for name in full_phase_names if name != "eval-fix"]

    flag_args = type("Args", (), {
        "iterate_flags": "--fresh --no-fix --no-report --no-iterate --max-iterations=1",
        "no_fix": False, "no_report": False, "no_iterate": False,
        "cold_run": False, "max_iterations": 3,
    })()
    pipeline.normalize_execution_flags(flag_args)
    assert flag_args.no_fix is True
    assert flag_args.no_report is True
    assert flag_args.no_iterate is True
    assert flag_args.cold_run is True
    assert flag_args.max_iterations == 1
    assert pipeline.should_render_report(no_report=True, exit_code=0) is False
    assert pipeline.should_render_report(no_report=False, exit_code=0) is True
    assert pipeline.should_render_report(no_report=False, exit_code=2) is False
    light_estimate = pipeline.apply_fix_mode_to_estimate({
        "estimate": {
            "phases": [
                {"phase": "eval-journey", "openai_cost_usd": 0.2},
                {"phase": "eval-fix", "openai_cost_usd": 0.8},
                {"phase": "eval-usability", "openai_cost_usd": 0.3},
            ],
        },
    }, no_fix=True)
    assert [phase["phase"] for phase in light_estimate["estimate"]["phases"]] == [
        "eval-journey", "eval-usability",
    ]
    assert light_estimate["estimate"]["single_run_openai_cost_usd"] == 0.5

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        benchmark = root / "benchmark"
        workspace.mkdir()
        benchmark.mkdir()
        context = benchmark / "jira-context.json"
        context.write_text("{}")
        artifacts = workspace / ".artifacts" / "RHOAIUX-3239" / "eval"
        artifacts.mkdir(parents=True)
        (artifacts / "consistency-report.json").write_text("{}")
        (artifacts / "extract-state.json").write_text(json.dumps({
            "ac_list": [{"criterion_id": "AC-1"}],
            "persona_selection": {
                "method": "automatic",
                "selected": ["ml-engineer+junior"],
                "target_audience_text": "AI engineers",
                "target_audience_source": "RHOAIUX-3239",
                "reasoning": "test",
                "considered_but_rejected": [],
            },
            "journey_definitions": [],
            "tasks_to_be_done": [],
        }))
        csv_fixture = (
            "# ACCEPTANCE CRITERIA\n"
            "criterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action\n"
            "AC-1,jira,T1,Visible behavior,,,,,,\n"
        )
        (artifacts / "evaluation-report.csv").write_text(csv_fixture)
        (artifacts / "refinement-suggestions.json").write_text("[]")
        (artifacts / "screenshots").mkdir()
        (artifacts / "screenshots" / "journey-baseline.png").write_bytes(b"png")
        (artifacts / "prototype-evidence.json").write_text(json.dumps({
            "screenshots": ["screenshots/journey-baseline.png"],
            "page": {"body_text": "test"},
        }))
        plan = pipeline.write_phase_plan(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
            artifact_mode="legacy-csv",
        )
        assert len(plan) == 5
        assert all(packet["artifact_mode"] == "legacy-csv" for packet in plan)
        assert [packet["turn_limit"] for packet in plan] == [1, 12, 1, 1, 10]
        assert sum(packet["turn_limit"] for packet in plan) <= pipeline.PIPELINE_MAX_TURNS == 30
        assert plan[0]["required_inputs"] == [
            {
                "name": "evaluation-report.csv",
                "path": str((artifacts / "evaluation-report.csv").resolve()),
            },
            {
                "name": "extract-state.json",
                "path": str((artifacts / "extract-state.json").resolve()),
            },
            {
                "name": "prototype-evidence.json",
                "path": str((artifacts / "prototype-evidence.json").resolve()),
            },
        ]
        journey_prompt = pipeline.build_phase_prompt(pipeline.OPENAI_PHASES[0], plan[0])
        assert "EVALUATION INPUT" in journey_prompt
        assert "Structured journey evaluation" not in journey_prompt
        assert "Kueue" not in journey_prompt
        fix = plan[1]
        assert fix["phase"] == "eval-fix"
        assert fix["turn_limit"] == 12
        assert fix["max_file_edits"] == 8
        assert fix["expected_outputs"] == [str((artifacts / "fix-log.json").resolve())]
        (artifacts / "journey-log.json").write_text("{}")
        heuristic_prompt = pipeline.build_phase_prompt(pipeline.OPENAI_PHASES[3], plan[3])
        assert "Nielsen's 10" in heuristic_prompt
        assert "review\": \"none" in heuristic_prompt
        usability_prompt = pipeline.build_phase_prompt(pipeline.OPENAI_PHASES[4], plan[4])
        assert "ml-engineer+junior" in usability_prompt
        assert "browser_click" in usability_prompt
        assert "filesystem" in usability_prompt
        assert str(root) not in usability_prompt

        canonical = Path(__file__).resolve().parent / "fixtures" / "canonical" / "v1" / "valid"
        for name in ("brief.json", "evaluation.json", "evidence.json", "actions.json", "state.json"):
            shutil.copy2(canonical / name, artifacts / name)
        canonical_crop = artifacts / "evidence" / "crops" / "evidence-1.png"
        canonical_crop.parent.mkdir(parents=True)
        canonical_crop.write_bytes(b"png")

        observed_limits = {}

        def fake_structured(packet, *, max_turns, **_kwargs):
            observed_limits["eval-journey"] = max_turns
            (Path(packet["artifacts_dir"]) / "journey-log.json").write_text("{}")
            return {
                "exit_code": 0,
                "status": "completed",
                "duration_s": 0.1,
                "output_text": "completed eval-journey",
                "turns_used": 1,
                "token_usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "cached_input_tokens": 4,
                    "reasoning_tokens": 1,
                },
                "cost_usd": 0.001,
            }

        def fake_visual(packet, *, max_turns, **_kwargs):
            observed_limits["eval-consistency-visual"] = max_turns
            (Path(packet["artifacts_dir"]) / "consistency-report.json").write_text("{}")
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-consistency-visual", "turns_used": 1,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        def fake_fix(packet, *, max_turns, **_kwargs):
            observed_limits["eval-fix"] = max_turns
            (Path(packet["artifacts_dir"]) / "fix-log.json").write_text("[]")
            used = min(6, max_turns)
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-fix", "turns_used": used,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        def fake_live(packet, *, max_turns, **_kwargs):
            observed_limits["eval-usability"] = max_turns
            for name in ("persona-results.json", "journey-log.json"):
                (Path(packet["artifacts_dir"]) / name).write_text("{}")
            used = min(9, max_turns)
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-usability", "turns_used": used,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        def fake_heuristic(packet, *, max_turns, **_kwargs):
            observed_limits["eval-heuristic"] = max_turns
            directory = Path(packet["artifacts_dir"])
            (directory / "heuristic-evaluation.json").write_text(json.dumps({"source": "uxd-research-heuristic-eval", "status": "unreviewed-draft", "defaults_assumed": True}))
            (directory / "heuristic-evaluation.md").write_text("# Unreviewed Draft")
            (directory / "heuristic-evaluation.html").write_text("<h1>Unreviewed Draft</h1>")
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-heuristic", "turns_used": 1,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        (artifacts / "refinement-suggestions.json").unlink()
        try:
            pipeline.run_openai_phases(
                key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
                jira_context_file=str(context), benchmark_dir=str(benchmark / "missing-input"),
                platform="api", model_override=None, reasoning_effort="low", max_turns=pipeline.PIPELINE_MAX_TURNS,
                trace_dir=benchmark / "missing-input-trace",
                structured_journey_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
                structured_visual_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
                structured_heuristic_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
                live_usability_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
                bounded_fix_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
            )
        except ValueError as error:
            assert "eval-fix missing required inputs" in str(error)
        else:
            raise AssertionError("all-phase input preflight should reject a missing eval-fix input")
        (artifacts / "refinement-suggestions.json").write_text("[]")

        result = pipeline.run_openai_phases(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
            platform="api",
            model_override=None,
            reasoning_effort="low",
            max_turns=pipeline.PIPELINE_MAX_TURNS,
            trace_dir=benchmark / "trace",
            structured_journey_runner=fake_structured,
            structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live,
            bounded_fix_runner=fake_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
        )
        assert result["status"] == "completed"
        assert result["turns_used"] == 18
        assert observed_limits == {
            "eval-journey": 1,
            "eval-fix": 12,
            "eval-consistency-visual": 1,
            "eval-heuristic": 1,
            "eval-usability": 10,
        }
        assert result["token_usage"]["input_tokens"] == 50
        assert result["token_usage"]["output_tokens"] == 10
        assert result["cost_usd"] == round(sum(
            pipeline.langfuse_trace.estimated_cost(
                phase["model"], phase["input_tokens"], phase["output_tokens"],
                phase["cache_read_tokens"], phase["cache_write_tokens"]
            ) for phase in result["phases"]
        ), 8)
        assert {phase["model"] for phase in result["phases"]} == {"gpt-6-sol"}
        cost_report = pipeline.write_evaluation_cost(artifacts, result, "fixture-run")
        assert cost_report["invoice_reconciled"] is False
        assert cost_report["total_estimated_usd"] == result["cost_usd"]
        assert cost_report["billing_source"] == "provider_usage_price_card_estimate"
        assert json.loads((artifacts / "evaluation-cost.json").read_text())["total_estimated_usd"] == result["cost_usd"]
        assert [item["phase"] for item in result["phases"]] == [
            spec["name"] for spec in pipeline.OPENAI_PHASES
        ]
        packets = sorted((benchmark / "phase-packets").glob("*.json"))
        assert len(packets) == 5

        local_fix = pipeline.run_openai_phases(
            key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
            jira_context_file=str(context), benchmark_dir=str(benchmark / "local-fix-noop"),
            platform="api", model_override=None, reasoning_effort="high",
            max_turns=pipeline.PIPELINE_MAX_TURNS, trace_dir=benchmark / "local-fix-noop-trace",
            structured_journey_runner=fake_structured, structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic, live_usability_runner=fake_live,
            bounded_fix_runner=lambda packet, **kwargs: pipeline.run_bounded_fix(
                packet, agent_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("paid fix was called")), **kwargs
            ),
            output_validator=lambda _packet: (True, "test validator passed"),
        )
        assert local_fix["status"] == "completed"
        assert local_fix["phases"][1]["provider"] == "local"
        assert local_fix["phases"][1]["model"] is None
        assert local_fix["phases"][1]["llm_cost_usd"] == 0
        assert len(json.loads((artifacts / "fix-log.json").read_text())) == 1

        incomplete_heuristic = pipeline.run_openai_phases(
            key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
            jira_context_file=str(context), benchmark_dir=str(benchmark / "incomplete-heuristic"),
            platform="api", model_override=None, reasoning_effort="high",
            max_turns=pipeline.PIPELINE_MAX_TURNS, trace_dir=benchmark / "incomplete-heuristic-trace",
            structured_journey_runner=fake_structured, structured_visual_runner=fake_visual,
            structured_heuristic_runner=lambda _packet, **_kwargs: {
                "exit_code": 2, "status": "failed", "output_text": "OpenAI heuristic response incomplete (max_output_tokens)",
                "turns_used": 1, "token_usage": {"input_tokens": 5281, "output_tokens": 8000, "total_tokens": 13281},
                "cost_usd": 0.090562,
            },
            live_usability_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("usability called after failure")),
            bounded_fix_runner=fake_fix, output_validator=lambda _packet: (True, "stale outputs present"),
        )
        assert incomplete_heuristic["status"] == "failed"
        assert incomplete_heuristic["phases"][-1]["phase"] == "eval-heuristic"
        assert incomplete_heuristic["phases"][-1]["llm_cost_usd"] == 0.090562
        assert "max_output_tokens" in incomplete_heuristic["phases"][-1]["validation"]
        assert incomplete_heuristic["budget"]["completed_openai_usd"] == incomplete_heuristic["cost_usd"]

        def limit_reached_fix(packet, *, max_turns, **_kwargs):
            (Path(packet["artifacts_dir"]) / "fix-log.json").write_text("[]")
            return {
                "exit_code": 2, "status": "failed", "duration_s": 0.1,
                "output_text": "turn limit reached", "turns_used": max_turns,
                "turn_limit_reached": True,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 0, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        limit_reached = pipeline.run_openai_phases(
            key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
            jira_context_file=str(context), benchmark_dir=str(benchmark / "limit-reached"),
            platform="api", model_override=None, reasoning_effort="low",
            max_turns=pipeline.PIPELINE_MAX_TURNS, trace_dir=benchmark / "limit-reached-trace",
            structured_journey_runner=fake_structured, structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live, bounded_fix_runner=limit_reached_fix,
            output_validator=lambda _packet: (True, "valid artifact exists"),
        )
        assert limit_reached["status"] == "failed"
        assert [phase["phase"] for phase in limit_reached["phases"]] == [
            "eval-journey", "eval-fix",
        ]
        assert limit_reached["phases"][-1]["status"] == "failed"

        (artifacts / "evaluation-report.csv").write_text(csv_fixture)
        capped = pipeline.run_openai_phases(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark / "capped"),
            platform="api",
            model_override="gpt-5.6-luna",
            reasoning_effort="low",
            max_turns=2,
            trace_dir=benchmark / "capped-trace",
            structured_journey_runner=fake_structured,
            structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live,
            bounded_fix_runner=fake_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
        )
        assert capped["status"] == "failed"
        assert capped["turns_used"] == 2
        assert capped["turn_limit_reached"] is True
        assert "before eval-consistency-visual" in capped["output_text"]

        budget_blocked = pipeline.run_openai_phases(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark / "budget-blocked"),
            platform="api",
            model_override=None,
            reasoning_effort="low",
            max_turns=pipeline.PIPELINE_MAX_TURNS,
            trace_dir=benchmark / "budget-blocked-trace",
            structured_journey_runner=fake_structured,
            structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live,
            bounded_fix_runner=fake_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
            cost_authority=pipeline.langfuse_trace.OpenAICostAuthority(cap_usd=0.03),
        )
        assert budget_blocked["status"] == "blocked"
        assert len(budget_blocked["phases"]) == 1
        assert budget_blocked["phases"][-1]["phase"] == "eval-journey"
        assert budget_blocked["phases"][-1]["llm_cost_usd"] == 0
        assert budget_blocked["phases"][-1]["error_category"] == "budget_cap"
        assert budget_blocked["budget"]["completed_openai_usd"] <= 0.000044

        ledger = benchmark / "program-openai-ledger.json"
        process_one = pipeline.langfuse_trace.OpenAICostAuthority(
            cap_usd=0.03, ledger_path=ledger
        )
        reservation = process_one.reserve("eval-journey", "gpt-5.6-luna")
        assert reservation is not None
        process_one.settle(reservation, {"input_tokens": 10, "output_tokens": 2})
        assert json.loads(ledger.read_text())["completed_openai_usd"] == 0.0000044
        correction_ledger = benchmark / "correction-ledger.json"
        correction_authority = pipeline.langfuse_trace.OpenAICostAuthority(cap_usd=25, ledger_path=correction_ledger)
        incomplete_reservation = correction_authority.reserve("eval-heuristic", "gpt-6-sol")
        correction_authority.settle(incomplete_reservation, {})
        correction = correction_authority.reconcile_settlement(incomplete_reservation["id"], {"input_tokens": 5281, "output_tokens": 8000})
        assert correction == 0.090562
        assert json.loads(correction_ledger.read_text())["completed_openai_usd"] == 0.090562
        try:
            correction_authority.reconcile_settlement(incomplete_reservation["id"], {"input_tokens": 5281, "output_tokens": 8000})
        except ValueError:
            pass
        else:
            raise AssertionError("Repeated reconciliation doubled the charge")

        process_two = pipeline.langfuse_trace.OpenAICostAuthority(
            cap_usd=0.03, ledger_path=ledger
        )
        assert process_two.completed_usd == 0.0000044
        cross_invocation = pipeline.run_openai_phases(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark / "two-invocation"),
            platform="api",
            model_override=None,
            reasoning_effort="low",
            max_turns=pipeline.PIPELINE_MAX_TURNS,
            trace_dir=benchmark / "two-invocation-trace",
            structured_journey_runner=fake_structured,
            structured_visual_runner=fake_visual,
            structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live,
            bounded_fix_runner=fake_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
            cost_authority=process_two,
        )
        assert cross_invocation["status"] == "blocked"
        assert cross_invocation["phases"][-1]["phase"] == "eval-journey"
        assert cross_invocation["phases"][-1]["llm_cost_usd"] == 0
        assert cross_invocation["cost_usd"] <= 0.03
        persisted = json.loads(ledger.read_text())
        assert [event["event"] for event in persisted["events"]] == ["reserve", "settle"]

        def expensive_result(phase: str, turns: int = 1):
            input_tokens = {
                "eval-journey": 40_000_000,
                "eval-fix": 2_000_000,
                "eval-consistency-visual": 40_000_000,
                "eval-heuristic": 4_000_000,
                "eval-usability": 4_000_000,
            }[phase]
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": f"completed {phase}", "turns_used": turns,
                "token_usage": {"input_tokens": input_tokens, "output_tokens": 0, "total_tokens": input_tokens, "cached_input_tokens": 0, "reasoning_tokens": 0},
                "cost_usd": 0,
            }

        def expensive_journey(_packet, **_kwargs):
            return expensive_result("eval-journey")

        def expensive_fix(packet, **_kwargs):
            (Path(packet["artifacts_dir"]) / "fix-log.json").write_text("[]")
            return expensive_result("eval-fix")

        def expensive_visual(_packet, **_kwargs):
            return expensive_result("eval-consistency-visual")

        def expensive_live(_packet, **_kwargs):
            return expensive_result("eval-usability")

        def expensive_heuristic(_packet, **_kwargs):
            return expensive_result("eval-heuristic")

        fourth_blocked = pipeline.run_openai_phases(
            key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
            jira_context_file=str(context), benchmark_dir=str(benchmark / "fourth-blocked"),
            platform="api", model_override=None, reasoning_effort="low", max_turns=pipeline.PIPELINE_MAX_TURNS,
            trace_dir=benchmark / "fourth-blocked-trace", structured_journey_runner=expensive_journey,
            structured_visual_runner=expensive_visual, live_usability_runner=expensive_live,
            structured_heuristic_runner=expensive_heuristic,
            bounded_fix_runner=expensive_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
            cost_authority=pipeline.langfuse_trace.OpenAICostAuthority(
                cap_usd=25.0,
                phase_bounds={
                    "eval-journey": (40_000_000, 0),
                    "eval-fix": (2_000_000, 0),
                    "eval-consistency-visual": (40_000_000, 0),
                    "eval-heuristic": (4_000_000, 0),
                    "eval-usability": (4_000_000, 0),
                },
            ),
        )
        assert fourth_blocked["status"] == "blocked"
        assert [phase["phase"] for phase in fourth_blocked["phases"]] == ["eval-journey"]
        assert fourth_blocked["phases"][-1]["error_category"] == "budget_cap"
        assert fourth_blocked["budget"]["cap_usd"] == 25.0

        # A crashed child can leave a durable first response and an unresolved
        # second request. The parent settles known usage and keeps the unknown
        # portion reserved instead of recording a zero-cost phase.
        crash_benchmark = benchmark / "child-crash"
        crash_trace = benchmark / "child-crash-trace"

        def child_crash_after_response(packet, *, usage_journal_path, run_id, attempt_id, model, **_kwargs):
            journal = UsageJournal(
                usage_journal_path, run_id=run_id, attempt_id=attempt_id,
                phase="eval-journey", model=model,
            )
            request_id = journal.begin("child-response-1")
            journal.response(request_id, {
                "id": "child-response-known", "status": "completed",
                "usage": {"input_tokens": 700, "output_tokens": 90},
            })
            journal.begin("child-request-lost")
            raise TimeoutError("mock child process timeout after first response")

        child_crash_authority = pipeline.langfuse_trace.OpenAICostAuthority(
            ledger_path=crash_benchmark / "openai-budget-ledger.json",
        )
        child_crash = pipeline.run_openai_phases(
            key="RHOAIUX-3239", url="http://localhost:9000", workspace=str(workspace),
            jira_context_file=str(context), benchmark_dir=str(crash_benchmark),
            platform="api", model_override=None, reasoning_effort="low",
            max_turns=pipeline.PIPELINE_MAX_TURNS, trace_dir=crash_trace,
            structured_journey_runner=child_crash_after_response,
            structured_visual_runner=fake_visual, structured_heuristic_runner=fake_heuristic,
            live_usability_runner=fake_live, bounded_fix_runner=fake_fix,
            output_validator=lambda _packet: (True, "test validator passed"),
            cost_authority=child_crash_authority, run_id="child-crash-run",
        )
        assert child_crash["status"] == "failed"
        assert child_crash["cost_usd"] is None
        assert child_crash["known_usage_cost_usd"] > 0
        assert child_crash["phases"][0]["usage_unknown"] is True
        assert child_crash["phases"][0]["input_tokens"] == 700
        assert child_crash["budget"]["active_reserved_openai_usd"] > 0
        blocked_after_unknown = pipeline.langfuse_trace.OpenAICostAuthority(
            ledger_path=crash_benchmark / "openai-budget-ledger.json",
        )
        assert blocked_after_unknown.reserve("eval-journey", "gpt-6-sol") is None

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
