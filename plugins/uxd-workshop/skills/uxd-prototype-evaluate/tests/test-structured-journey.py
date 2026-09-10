#!/usr/bin/env python3
"""Deterministic contract tests for the structured journey runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "openai_structured_journey.py"
SPEC = importlib.util.spec_from_file_location("openai_structured_journey_test", MODULE_PATH)
assert SPEC and SPEC.loader
journey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journey)

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cff00000040101005fe5c4b90000000049454e44ae426082"
)


def fixture(root: Path) -> dict:
    artifacts = root / "workspace" / ".artifacts" / "TEST-1" / "eval"
    screenshot = artifacts / "screenshots" / "journey-baseline.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(PNG_1X1)
    persona_selection = {
        "method": "automatic",
        "selected": ["ml-engineer+junior"],
        "target_audience_text": "AI engineers",
        "target_audience_source": "TEST-1",
        "reasoning": "Matched AI engineer",
        "considered_but_rejected": [],
    }
    (artifacts / "extract-state.json").write_text(json.dumps({
        "persona_selection": persona_selection,
        "journey_definitions": [{
            "id": "journey-1",
            "title": "Inspect tool calls",
            "persona": "ml-engineer",
            "source": "Jira acceptance criteria",
            "ac_ids": ["AC-1", "AC-2"],
            "expected_path": [],
        }],
        "tasks_to_be_done": [{"task": "Inspect tool calls", "covers_acs": ["AC-1"]}],
    }))
    (artifacts / "prototype-evidence.json").write_text(json.dumps({
        "schema_version": 1,
        "capture_method": "deterministic-baseline",
        "prototype_url": "http://localhost:9000/",
        "screenshots": ["screenshots/journey-baseline.png"],
        "page": {
            "title": "Tool calls",
            "body_text": "Tool calls Arguments Result",
            "headings": [{"level": 1, "text": "Playground"}],
            "controls": [{"tag": "button", "role": "", "name": "Run"}],
        },
    }))
    (artifacts / "evaluation-report.csv").write_text(
        "# ACCEPTANCE CRITERIA\n"
        "criterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action\n"
        "AC-1,jira,T1,Tool calls are visible,,,,,,\n"
        "AC-2,jira,T4,Engineering reviewed the design,,,,,,Confirm engineering review\n"
    )
    return {
        "phase": "eval-journey",
        "prototype_url": "http://localhost:9000/",
        "workspace": str(root / "workspace"),
        "artifacts_dir": str(artifacts),
    }


def output_payload() -> dict:
    return {
        "depth": "quick",
        "prototype_url": "http://localhost:9000/",
        "evaluated_at": "2026-09-10T20:00:00+00:00",
        "persona_selection": {
            "method": "automatic",
            "selected": ["ml-engineer+junior"],
            "target_audience_text": "AI engineers",
            "target_audience_source": "TEST-1",
            "reasoning": "Matched AI engineer",
            "considered_but_rejected": [],
        },
        "journeys": [{
            "id": "journey-1",
            "title": "Inspect tool calls",
            "persona": "ml-engineer+junior",
            "source": "Jira acceptance criteria",
            "steps_expected": 1,
            "steps_completed": 1,
            "verdict": "PASS",
            "verdict_detail": "Tool-call details are visible in the supplied evidence.",
            "ac_ids": ["AC-1"],
            "steps": [{
                "step": 1,
                "action": "Inspect the playground",
                "result": "success",
                "screenshot": "screenshots/journey-baseline.png",
                "narration": "Tool calls, arguments, and result labels are visible.",
            }],
        }],
        "exploration": [],
        "criterion_results": [{
            "criterion_id": "AC-1",
            "verdict": "PASS",
            "rationale": "The supplied visual evidence shows tool-call details.",
            "evidence": "screenshots/journey-baseline.png",
            "fix_action": "",
            "fix_file": "",
            "human_action": "",
        }],
    }


def assert_provider_schema_subset(schema: dict) -> None:
    assert "uniqueItems" not in schema
    if schema.get("type") == "object":
        for child in schema.get("properties", {}).values():
            assert_provider_schema_subset(child)
    elif schema.get("type") == "array":
        assert_provider_schema_subset(schema["items"])


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        packet = fixture(root)
        request = journey.build_journey_request(
            packet, model="gpt-5.6-terra", reasoning_effort="low"
        )
        output_format = request["text"]["format"]
        assert output_format["type"] == "json_schema"
        assert output_format["strict"] is True
        assert output_format["schema"]["additionalProperties"] is False
        assert_provider_schema_subset(output_format["schema"])
        assert "response_format" not in request
        assert request["store"] is False
        assert "tools" not in request
        user_content = request["input"][1]["content"]
        assert [part["type"] for part in user_content] == ["input_text", "input_image"]
        assert user_content[1]["image_url"].startswith("data:image/png;base64,")
        assert "/Users/" not in user_content[0]["text"]
        assert "Kueue" not in user_content[0]["text"]

        expected = output_payload()
        response = {
            "id": "resp_test",
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(expected)}],
            }],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens_details": {"reasoning_tokens": 5},
            },
        }
        result = journey.run_structured_journey(
            packet,
            model="gpt-5.6-terra",
            trace_path=str(root / "trace" / "journey.jsonl"),
            request_fn=lambda _request: response,
        )
        assert result["status"] == "completed"
        assert result["turns_used"] == 1
        assert result["token_usage"]["cached_input_tokens"] == 20
        artifacts = Path(packet["artifacts_dir"])
        assert json.loads((artifacts / "journey-log.json").read_text()) == expected
        csv_text = (artifacts / "evaluation-report.csv").read_text()
        assert "AC-1,jira,T1,Tool calls are visible,PASS" in csv_text
        assert "AC-2,jira,T4,Engineering reviewed the design,FLAGGED" in csv_text

        invalid = output_payload()
        invalid["unexpected"] = True
        try:
            journey.validate_journey_output(invalid, packet)
        except ValueError as error:
            assert "unexpected fields" in str(error)
        else:
            raise AssertionError("Local schema validation accepted an extra field")

        t4_extra = output_payload()
        t4_extra["criterion_results"].append({
            "criterion_id": "AC-2",
            "verdict": "FLAGGED",
            "rationale": "Requires review outside the prototype.",
            "evidence": "",
            "fix_action": "",
            "fix_file": "",
            "human_action": "Confirm engineering review",
        })
        journey.validate_journey_output(t4_extra, packet)

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
