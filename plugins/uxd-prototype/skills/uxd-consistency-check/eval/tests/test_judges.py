"""Calibrate eval judges with real analyzer output and broken-report controls."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SKILL_DIR = Path(__file__).resolve().parents[2]
EVAL_DIR = SKILL_DIR / "eval"


class EvalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = yaml.safe_load((EVAL_DIR / "eval.yaml").read_text())
        cls.judges = {}
        for judge in config["judges"]:
            namespace = {}
            source = "def check(outputs, arguments):\n" + "\n".join(
                "    " + line for line in judge["check"].splitlines()
            )
            exec(compile(source, str(EVAL_DIR / "eval.yaml"), "exec"), namespace)
            cls.judges[judge["name"]] = namespace["check"]

    def source_outputs(self, name):
        case_dir = EVAL_DIR / "cases" / name
        expected = yaml.safe_load((case_dir / "annotations.yaml").read_text())
        prototype = case_dir / "prototype"
        before = {path: path.read_bytes() for path in prototype.rglob("*") if path.is_file()}
        with tempfile.TemporaryDirectory(prefix="consistency-eval-") as tmp:
            report_path = Path(tmp) / "consistency-report.json"
            result = subprocess.run(
                [sys.executable, str(SKILL_DIR / "scripts" / "analyze.py"),
                 "--src", str(prototype), "--guideline", expected["guideline"],
                 "--json-file", str(report_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, expected["expected_exit"], result.stdout + result.stderr)
            report = report_path.read_text()
        after = {path: path.read_bytes() for path in prototype.rglob("*") if path.is_file()}
        self.assertEqual(before, after, "Source audit must not edit the prototype")
        return {"annotations": expected, "files": {"artifacts/consistency-report.json": report}}

    def check_source(self, outputs):
        return self.judges["grounded_source_report"](outputs, {})

    def test_all_source_cases_match_grounded_expectations(self):
        for name in ("custom-css", "clean-patternfly", "pagination-candidate", "native-control"):
            with self.subTest(case=name):
                passed, reason = self.check_source(self.source_outputs(name))
                self.assertTrue(passed, reason)

    def test_missing_report_does_not_pass_clean_case(self):
        outputs = self.source_outputs("clean-patternfly")
        outputs["files"] = {}
        self.assertFalse(self.check_source(outputs)[0])

    def test_incorrect_evidence_classification_and_visual_claims_fail(self):
        outputs = self.source_outputs("pagination-candidate")
        report = json.loads(outputs["files"]["artifacts/consistency-report.json"])
        for field, value in (("line", 999), ("verdict", "VIOLATION"),
                             ("severity", "error"), ("review_candidate", False)):
            with self.subTest(field=field):
                altered = copy.deepcopy(report)
                altered["source_mode"]["violations"][0][field] = value
                candidate = copy.deepcopy(outputs)
                candidate["files"]["artifacts/consistency-report.json"] = json.dumps(altered)
                self.assertFalse(self.check_source(candidate)[0])
        report["visual_mode"]["ran"] = True
        outputs["files"]["artifacts/consistency-report.json"] = json.dumps(report)
        self.assertFalse(self.check_source(outputs)[0])

    def test_visual_judge_rejects_unsubstantiated_pass(self):
        check = self.judges["visual_evidence_limits"]
        grounded = (
            "Without screenshots or a live URL, visual and DOM evidence are unavailable. "
            "Provide screenshots and a URL for DOM measurements. "
            "Visual review supplements the separate deterministic source result."
        )
        self.assertTrue(check({"conversation": grounded}, {})[0])
        self.assertFalse(check({"conversation": "Project Felt visual checks passed."}, {})[0])
        self.assertFalse(check({"conversation": grounded + " Verified pill controls."}, {})[0])


if __name__ == "__main__":
    unittest.main()
