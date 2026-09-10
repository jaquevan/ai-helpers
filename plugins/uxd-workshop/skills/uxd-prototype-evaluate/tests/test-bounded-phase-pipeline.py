#!/usr/bin/env python3
"""Deterministic tests for bounded, phase-specific OpenAI orchestration."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "langfuse-trace-pipeline.py"
SPEC = importlib.util.spec_from_file_location("bounded_phase_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def main() -> int:
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
            platform="api",
            model_override=None,
        )
        assert len(plan) == 3
        assert sum(packet["turn_limit"] for packet in plan) == 12
        assert plan[0]["required_inputs"] == [
            {
                "name": "extract-state.json",
                "path": str((artifacts / "extract-state.json").resolve()),
            },
            {
                "name": "evaluation-report.csv",
                "path": str((artifacts / "evaluation-report.csv").resolve()),
            },
            {
                "name": "prototype-evidence.json",
                "path": str((artifacts / "prototype-evidence.json").resolve()),
            },
        ]
        journey_prompt = pipeline.build_phase_prompt(pipeline.OPENAI_PHASES[0], plan[0])
        assert "Structured journey evaluation" in journey_prompt
        assert "Kueue" not in journey_prompt
        usability_prompt = pipeline.build_phase_prompt(pipeline.OPENAI_PHASES[2], plan[2])
        assert "ml-engineer+junior" in usability_prompt
        assert "browser_click" in usability_prompt
        assert "filesystem" in usability_prompt
        assert str(root) not in usability_prompt

        def fake_structured(packet, **_kwargs):
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

        def fake_visual(packet, **_kwargs):
            (Path(packet["artifacts_dir"]) / "consistency-report.json").write_text("{}")
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-consistency-visual", "turns_used": 1,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        def fake_live(packet, *, max_turns, **_kwargs):
            for name in ("persona-results.json", "journey-log.json"):
                (Path(packet["artifacts_dir"]) / name).write_text("{}")
            used = min(2, max_turns)
            return {
                "exit_code": 0, "status": "completed", "duration_s": 0.1,
                "output_text": "completed eval-usability", "turns_used": used,
                "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_input_tokens": 4, "reasoning_tokens": 1},
                "cost_usd": 0.001,
            }

        result = pipeline.run_openai_phases(
            key="RHOAIUX-3239",
            url="http://localhost:9000",
            workspace=str(workspace),
            jira_context_file=str(context),
            benchmark_dir=str(benchmark),
            platform="api",
            model_override=None,
            reasoning_effort="low",
            max_turns=12,
            trace_dir=benchmark / "trace",
            structured_journey_runner=fake_structured,
            structured_visual_runner=fake_visual,
            live_usability_runner=fake_live,
            output_validator=lambda _packet: (True, "test validator passed"),
        )
        assert result["status"] == "completed"
        assert result["turns_used"] == 4
        assert result["token_usage"]["input_tokens"] == 30
        assert result["token_usage"]["output_tokens"] == 6
        assert result["cost_usd"] == 0.003
        assert [item["phase"] for item in result["phases"]] == [
            spec["name"] for spec in pipeline.OPENAI_PHASES
        ]
        packets = sorted((benchmark / "phase-packets").glob("*.json"))
        assert len(packets) == 3

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
            live_usability_runner=fake_live,
            output_validator=lambda _packet: (True, "test validator passed"),
        )
        assert capped["status"] == "failed"
        assert capped["turns_used"] == 2
        assert capped["turn_limit_reached"] is True
        assert "before eval-usability" in capped["output_text"]

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
