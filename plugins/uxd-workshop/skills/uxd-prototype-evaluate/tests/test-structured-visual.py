#!/usr/bin/env python3
"""Deterministic contract test for image-only visual consistency."""

import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import openai_structured_visual as visual  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cff00000040101005fe5c4b90000000049454e44ae426082")


def main():
    with tempfile.TemporaryDirectory() as temp:
        artifacts = Path(temp) / ".artifacts" / "TEST-1" / "eval"
        shot = artifacts / "screenshots" / "baseline.png"
        shot.parent.mkdir(parents=True); shot.write_bytes(PNG)
        (artifacts / "prototype-evidence.json").write_text(json.dumps({"screenshots": ["screenshots/baseline.png"], "page": {"body_text": "Create project"}}))
        (artifacts / "journey-log.json").write_text(json.dumps({"journeys": []}))
        (artifacts / "consistency-report.json").write_text(json.dumps({
            "source": "uxd-consistency-check", "guidelines_version": "test", "degraded": False,
            "checked_at": "2026-09-10T00:00:00Z", "source_mode": {"ran": True, "violations": []},
            "visual_mode": {"ran": False, "screenshots_checked": 0, "findings": []},
            "summary": {"total_guidelines_checked": 1, "violations": 0, "warnings": 0, "passes": 1},
        }))
        packet = {"phase": "eval-consistency-visual", "prototype_url": "http://localhost:9000", "artifacts_dir": str(artifacts), "workspace": temp}
        request = visual.build_visual_request(packet, model="gpt-5.6-terra")
        assert request["text"]["format"]["type"] == "json_schema"
        assert request["text"]["format"]["strict"] is True
        assert "tools" not in request
        assert request["input"][1]["content"][-1]["type"] == "input_image"
        prompt = request["input"][1]["content"][0]["text"]
        assert "reference_specs" in prompt and "No Custom CSS" in prompt
        assert "/Users/" not in prompt
        finding = {"screenshot": "screenshots/baseline.png", "guideline_id": "cta-button-icons", "guideline_title": "CTA Button Icons", "category": "components", "severity": "warning", "verdict": "FLAGGED", "description": "The primary Create action may include an icon.", "suggestion": "Confirm the action is text-only.", "seen_on": ["screenshots/baseline.png"]}
        response = {"id": "resp_visual", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"findings": [finding]})}]}], "usage": {"input_tokens": 90, "output_tokens": 20, "total_tokens": 110}}
        result = visual.run_structured_visual(packet, model="gpt-5.6-terra", request_fn=lambda _: response)
        assert result["turns_used"] == 1
        report = json.loads((artifacts / "consistency-report.json").read_text())
        assert report["visual_mode"]["ran"] is True
        assert report["visual_mode"]["input_metrics"]["guidelines_analyzed"] >= 1
        invalid = {"findings": [{**finding, "severity": "error"}]}
        try: visual.validate_visual_output(invalid, packet)
        except ValueError as error: assert "FLAGGED" in str(error)
        else: raise AssertionError("Invalid FLAGGED severity accepted")
    print("PASS")


if __name__ == "__main__": main()
