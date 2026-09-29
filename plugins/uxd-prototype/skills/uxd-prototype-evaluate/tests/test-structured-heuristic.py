#!/usr/bin/env python3
"""Focused contract test for the unattended sibling heuristic phase."""

from __future__ import annotations

import json
import copy
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from openai_structured_heuristic import build_heuristic_request, run_structured_heuristic, validate_heuristic_output  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cff00000040101005fe5c4b90000000049454e44ae426082")


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = Path(temp_dir)
        (artifacts / "screenshots").mkdir()
        (artifacts / "screenshots" / "baseline.png").write_bytes(PNG)
        (artifacts / "consistency-report.json").write_text("{}")
        (artifacts / "prototype-evidence.json").write_text(json.dumps({
            "screenshots": ["screenshots/baseline.png"],
            "page": {"body_text": "Playground View code"},
        }))
        (artifacts / "journey-log.json").write_text(json.dumps({
            "journeys": [{"title": "Export Playground code", "steps": []}],
        }))
        packet = {
            "key": "TEST-1",
            "prototype_url": "http://127.0.0.1:8080/playground",
            "artifacts_dir": str(artifacts),
        }
        output = {
            "evaluators": [
                {"id": "A", "candidate_ids": ["A1"]},
                {"id": "B", "candidate_ids": ["B1"]},
                {"id": "C", "candidate_ids": []},
            ],
            "findings": [{
                "id": "V-01", "candidate_ids": ["A1", "B1"],
                "title": "Export status is unclear", "screenshot": "screenshots/baseline.png",
                "location": "View code action", "heuristic_id": "nielsen-1",
                "observation": "The rendered state does not show export progress.",
                "evidence": "No progress or completion status is visible near View code.",
                "suggested_severity": "major", "agreement": "majority",
                "identified_by": ["A", "B"], "borderline": False,
                "user_testing_signal": "Can users tell when export is complete?",
            }],
            "coverage_limitations": ["Only the supplied desktop state was evaluated."],
        }
        response = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        result = run_structured_heuristic(
            packet, model="gpt-6-sol", request_fn=lambda _request: response
        )
        assert result["status"] == "completed"
        document = json.loads((artifacts / "heuristic-evaluation.json").read_text())
        assert document["source"] == "uxd-research-heuristic-eval"
        assert document["status"] == "unreviewed-draft"
        assert document["defaults_assumed"] is True
        markdown = (artifacts / "heuristic-evaluation.md").read_text()
        rendered_html = (artifacts / "heuristic-evaluation.html").read_text()
        for text in (markdown, rendered_html):
            assert "Unreviewed Draft" in text and "Nielsen's 10" in text
            assert "Suggested severity" in text
            assert all(lens in text for lens in ("Visual inspection", "Task flow", "Edge cases"))
            assert "Accessibility / WCAG conformance was not evaluated" in text
            assert "Recommendation:" not in text and "WCAG compliant" not in text
        assert "data:image/png;base64" in rendered_html
        request = build_heuristic_request(packet, model="gpt-6-sol")
        assert request["text"]["format"]["type"] == "json_schema"
        assert request["max_output_tokens"] == 16000
        assert "recommendations" not in request["text"]["format"]["schema"]["properties"]
        schema_text = json.dumps(request["text"]["format"]["schema"])
        assert "uniqueItems" not in schema_text
        id_schema = request["text"]["format"]["schema"]["properties"]["findings"]["items"]["properties"]["id"]
        assert id_schema == {"type": "string", "enum": [f"V-{i:02d}" for i in range(1, 11)]}
        assert request["model"] == "gpt-6-sol"
        runaway = copy.deepcopy(output)
        runaway["findings"][0]["id"] = "F-1-" + "invalid" * 100
        try:
            validate_heuristic_output(runaway, packet)
        except ValueError as error:
            assert "must be one of" in str(error)
        else:
            raise AssertionError("runaway finding ID was accepted")
        too_many = copy.deepcopy(output)
        too_many["findings"] = [copy.deepcopy(output["findings"][0]) for _ in range(11)]
        try:
            validate_heuristic_output(too_many, packet)
        except ValueError as error:
            assert "too many items" in str(error)
        else:
            raise AssertionError("oversized findings list was accepted")
        duplicate = copy.deepcopy(output)
        duplicate["findings"][0]["identified_by"] = ["A", "A"]
        try:
            validate_heuristic_output(duplicate, packet)
        except ValueError as error:
            assert "duplicate evaluators" in str(error)
        else:
            raise AssertionError("duplicate evaluator agreement was accepted")
        incomplete = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "usage": {"input_tokens": 5281, "output_tokens": 8000, "total_tokens": 13281}}
        failed = run_structured_heuristic(packet, model="gpt-6-sol", request_fn=lambda _request: incomplete)
        assert failed["exit_code"] == 2 and failed["turns_used"] == 1
        assert failed["token_usage"]["total_tokens"] == 13281
        assert failed["cost_usd"] > 0
        assert failed["turn_limit_reached"] is True
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
