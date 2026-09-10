import subprocess
import sys
import tempfile
import unittest
import json
import importlib.util
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
ANALYZER = SKILL_DIR / "scripts" / "analyze.py"
FIXTURES = Path(__file__).parent / "fixtures"

ANALYZE_SPEC = importlib.util.spec_from_file_location("consistency_analyze", ANALYZER)
ANALYZE_MODULE = importlib.util.module_from_spec(ANALYZE_SPEC)
ANALYZE_SPEC.loader.exec_module(ANALYZE_MODULE)


class AnalyzeCliTests(unittest.TestCase):
    def test_grep_context_with_jsx_colon_preserves_file_and_line(self):
        matches = [
            "src/components/Example.tsx-70-<Flex alignItems={{ default: 'alignItemsCenter' }} />"
        ]

        parsed = ANALYZE_MODULE.parse_matches_to_by_file(matches)

        self.assertEqual(list(parsed), ["src/components/Example.tsx"])
        self.assertEqual(parsed["src/components/Example.tsx"][0]["line"], "70")
        self.assertIn("default: 'alignItemsCenter'", parsed["src/components/Example.tsx"][0]["content"])

    def run_checker(self, fixture_name, guideline):
        fixture = FIXTURES / fixture_name
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-") as report_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(fixture),
                    "--guideline",
                    guideline,
                    "--report-dir",
                    report_dir,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            reports = list(Path(report_dir).glob("*.md"))
            markdown = reports[0].read_text() if reports else ""
            return result, markdown

    def test_clean_patternfly_fixture_passes(self):
        result, markdown = self.run_checker("clean", "icon-style-consistency")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("All checks passed", markdown)

    def test_filled_icon_fixture_is_reported(self):
        result, markdown = self.run_checker("violating", "icon-style-consistency")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Example.tsx", markdown)
        self.assertIn("FolderIcon", markdown)

    def test_clean_html_ground_truth_passes(self):
        result, markdown = self.run_checker("ground-truth-clean", "no-custom-css")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("All checks passed", markdown)

    def test_html_ground_truth_reports_all_expected_custom_css(self):
        result, markdown = self.run_checker("ground-truth", "no-custom-css")
        expected = json.loads((FIXTURES / "ground-truth" / "expected-findings.json").read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            f"Violations:** {len(expected['no-custom-css']['expected_findings'])} across 1 guidelines",
            markdown,
        )
        for finding in expected["no-custom-css"]["expected_findings"]:
            self.assertIn(finding["file"].split("/")[-1], markdown)

    def test_json_output_matches_evaluator_contract(self):
        fixture = FIXTURES / "ground-truth"
        expected = json.loads((fixture / "expected-findings.json").read_text())
        result = subprocess.run(
            [
                sys.executable,
                str(ANALYZER),
                "--src",
                str(fixture),
                "--guideline",
                "no-custom-css",
                "--json-output",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"], {
            "total_guidelines_checked": 1,
            "violations": 0,
            "warnings": 1,
            "passes": 0,
        })
        actual_locations = sorted(
            (finding["file"], finding["line"])
            for finding in report["source_mode"]["violations"]
        )
        expected_locations = sorted(
            (finding["file"], finding["line"])
            for finding in expected["no-custom-css"]["expected_findings"]
        )
        self.assertEqual(actual_locations, expected_locations)
        self.assertTrue(all(finding["verdict"] == "FLAGGED" for finding in report["source_mode"]["violations"]))
        self.assertTrue(all(finding["confidence"] == "high" for finding in report["source_mode"]["violations"]))
        self.assertTrue(all(not finding["review_candidate"] for finding in report["source_mode"]["violations"]))

    def test_candidate_search_is_flagged_and_never_fails(self):
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-candidate-") as tmp:
            workspace = Path(tmp)
            source = workspace / "src" / "Example.tsx"
            source.parent.mkdir(parents=True)
            source.write_text("export const Example = () => <Pagination itemCount={30} />;\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(workspace),
                    "--guideline",
                    "table-pagination",
                    "--json-output",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["violations"], 0)
            self.assertEqual(report["summary"]["warnings"], 1)
            finding = report["source_mode"]["violations"][0]
            self.assertEqual(finding["severity"], "warning")
            self.assertEqual(finding["verdict"], "FLAGGED")
            self.assertEqual(finding["confidence"], "low")
            self.assertTrue(finding["review_candidate"])
            self.assertEqual(finding["check_method"], "automated_candidate")

    def test_changed_mode_excludes_unchanged_lines_in_touched_file(self):
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-git-") as tmp:
            workspace = Path(tmp)
            source = workspace / "src" / "Example.tsx"
            source.parent.mkdir(parents=True)
            source.write_text(
                "export const Existing = () => <div style={{ color: 'red' }} />;\n"
                "export const Stable = () => <div className=\"pf-v6-u-m-md\" />;\n"
            )
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(["git", "add", "src/Example.tsx"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=workspace, check=True)

            source.write_text(
                source.read_text()
                + "export const Added = () => <div style={{ color: 'blue' }} />;\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(workspace),
                    "--guideline",
                    "no-custom-css",
                    "--changed",
                    "--base-ref",
                    "HEAD",
                    "--json-output",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            findings = json.loads(result.stdout)["source_mode"]["violations"]
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["line"], 3)

    def test_json_file_writes_evaluator_contract(self):
        fixture = FIXTURES / "ground-truth-clean"
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-json-") as tmp:
            output = Path(tmp) / "nested" / "consistency-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(fixture),
                    "--guideline",
                    "no-custom-css",
                    "--json-file",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            report = json.loads(output.read_text())
            self.assertEqual(report["source"], "uxd-consistency-check")
            self.assertTrue(report["source_mode"]["ran"])

    def test_standalone_html_root_without_src_directory_is_checked(self):
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-standalone-") as tmp:
            prototype = Path(tmp) / "prototype"
            prototype.mkdir()
            (prototype / "index.html").write_text(
                '<link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@6/patternfly.min.css">\n'
                '<div style="color: red">Custom</div>\n'
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(prototype),
                    "--guideline",
                    "no-custom-css",
                    "--json-output",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            findings = json.loads(result.stdout)["source_mode"]["violations"]
            self.assertEqual(len(findings), 1)
            self.assertEqual(Path(findings[0]["file"]).name, "index.html")

    def test_changed_mode_includes_untracked_prototype_files(self):
        with tempfile.TemporaryDirectory(prefix="uxd-consistency-untracked-") as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=workspace, check=True)
            (workspace / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=workspace, check=True)
            (workspace / "src" / "New.tsx").write_text(
                "export const New = () => <div style={{ color: 'red' }} />;\n"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZER),
                    "--src",
                    str(workspace),
                    "--guideline",
                    "no-custom-css",
                    "--changed",
                    "--base-ref",
                    "HEAD",
                    "--json-output",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            findings = json.loads(result.stdout)["source_mode"]["violations"]
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0]["file"].endswith("New.tsx"))


if __name__ == "__main__":
    unittest.main()
