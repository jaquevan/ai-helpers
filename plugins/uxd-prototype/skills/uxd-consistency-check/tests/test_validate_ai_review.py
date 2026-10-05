#!/usr/bin/env python3
"""Contract tests for supplemental model-assisted consistency findings."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_ai_review.py"
SPEC = importlib.util.spec_from_file_location("validate_ai_review", SCRIPT)
assert SPEC and SPEC.loader
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


class ValidateAiReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "panel.html").write_text(
            '<button style="color: red">Run</button>\n', encoding="utf-8"
        )
        self.source_finding = {
            "guideline_id": "no-custom-css",
            "file": "src/panel.html",
            "line_start": 1,
            "line_end": 1,
            "evidence": '<button style="color: red">Run</button>',
            "rationale": "The button adds authored inline CSS.",
            "suggestion": "Use PatternFly classes or tokens instead.",
            "confidence": "high",
        }

    def tearDown(self):
        self.temp.cleanup()

    def source_payload(self, finding=None):
        return {
            "status": "completed",
            "mode": "source",
            "model": "openai/gpt-6-luna",
            "non_deterministic": True,
            "findings": [finding if finding is not None else self.source_finding],
        }

    def test_source_finding_is_grounded_and_normalized(self):
        result = review.validate_review(
            self.source_payload(), mode="source", model="openai/gpt-6-luna",
            source_root=self.root, screenshots=[],
        )
        finding = result["findings"][0]
        self.assertEqual(finding["severity"], "error")
        self.assertEqual(finding["verdict"], "VIOLATION")
        self.assertEqual(finding["check_method"], "model_review")
        self.assertEqual(result["summary"]["finding_count"], 1)

    def test_source_review_rejects_unverifiable_evidence(self):
        item = {**self.source_finding, "evidence": "different source"}
        with self.assertRaisesRegex(ValueError, "evidence does not match"):
            review.validate_review(
                self.source_payload(item), mode="source", model="openai/gpt-6-luna",
                source_root=self.root, screenshots=[],
            )

    def test_source_review_rejects_path_traversal(self):
        item = {**self.source_finding, "file": "../outside.html"}
        with self.assertRaisesRegex(ValueError, "escapes source root"):
            review.validate_review(
                self.source_payload(item), mode="source", model="openai/gpt-6-luna",
                source_root=self.root, screenshots=[],
            )

    def test_review_rejects_unknown_guidelines_and_wrong_model(self):
        item = {**self.source_finding, "guideline_id": "made-up-guideline"}
        with self.assertRaisesRegex(ValueError, "unknown guideline_id"):
            review.validate_review(
                self.source_payload(item), mode="source", model="openai/gpt-6-luna",
                source_root=self.root, screenshots=[],
            )
        with self.assertRaisesRegex(ValueError, "must match requested model"):
            review.validate_review(
                self.source_payload(), mode="source", model="openai/gpt-6-sol",
                source_root=self.root, screenshots=[],
            )

    def test_visual_review_requires_supplied_screenshot(self):
        screenshot = self.root / "screenshots" / "view.png"
        screenshot.parent.mkdir()
        screenshot.write_bytes(b"test image")
        payload = {
            "status": "completed",
            "mode": "visual",
            "model": "openai/gpt-6-luna",
            "non_deterministic": True,
            "findings": [{
                "guideline_id": "icon-style-consistency",
                "screenshot": str(screenshot),
                "rationale": "The same action uses different icon styles.",
                "suggestion": "Use one icon style consistently.",
                "confidence": "medium",
            }],
        }
        result = review.validate_review(
            payload, mode="visual", model="openai/gpt-6-luna", source_root=self.root,
            screenshots=[str(screenshot)],
        )
        self.assertEqual(result["findings"][0]["severity"], "warning")
        self.assertEqual(result["findings"][0]["verdict"], "FLAGGED")
        other_screenshot = self.root / "screenshots" / "other.png"
        other_screenshot.write_bytes(b"another image")
        with self.assertRaisesRegex(ValueError, "unreviewed screenshot"):
            review.validate_review(
                payload, mode="visual", model="openai/gpt-6-luna", source_root=self.root,
                screenshots=[str(other_screenshot)],
            )


if __name__ == "__main__":
    unittest.main()
