#!/usr/bin/env python3
"""Exercise packaged classification and report rendering outside the repo cwd."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
REPORT_FIXTURE = SKILL_DIR / "tests" / "fixtures" / "minimal" / "report"


def run_node(script: str, artifacts: Path, cwd: Path) -> dict:
    completed = subprocess.run(
        ["node", str(SCRIPTS_DIR / script), str(artifacts), "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def read_acceptance_rows(report_path: Path) -> list[dict[str, str]]:
    lines = report_path.read_text().splitlines()
    header_index = lines.index(
        "criterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action"
    )
    reader = csv.DictReader(lines[header_index:])
    return list(reader)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_temp:
        temp = Path(raw_temp)
        foreign_cwd = temp / "unrelated-working-directory"
        foreign_cwd.mkdir()

        classify_artifacts = temp / "classification" / "eval"
        classify_artifacts.mkdir(parents=True)
        extract = {
            "key": "PORTABLE-1",
            "title": "Portable classifier test",
            "ac_list": [
                {"criterion_id": "AC-1", "source": "jira", "text": "A button opens the details panel"},
                {
                    "criterion_id": "AC-2", "source": "jira",
                    "text": "Align with the external PatternFly specification",
                    "references": ["https://www.patternfly.org/components/button"],
                },
                {"criterion_id": "AC-3", "source": "jira", "text": "API returns 429 after rate limit"},
                {"criterion_id": "AC-4", "source": "jira", "text": "The workflow is intuitive"},
                {"criterion_id": "AC-5", "source": "jira", "text": "Figma file delivered with annotations and specifications"},
                {"criterion_id": "AC-6", "source": "jira", "text": "API validation shows an error message"},
            ],
        }
        (classify_artifacts / "extract-state.json").write_text(json.dumps(extract))
        classification = run_node("run-classification.js", classify_artifacts, foreign_cwd)
        assert classification["model_invoked"] is False
        assert classification["tier_counts"] == {"T1": 2, "T2": 1, "T3": 1, "T4": 2}
        rows = read_acceptance_rows(classify_artifacts / "evaluation-report.csv")
        assert [row["tier"] for row in rows] == ["T1", "T2", "T3", "T4", "T4", "T1"]
        assert rows[2]["verdict"] == "PASS"
        assert rows[3]["human_action"]
        validator = subprocess.run(
            ["node", str(SCRIPTS_DIR / "validate-classify.js"), str(classify_artifacts), "--json"],
            cwd=foreign_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        assert validator.returncode == 0, validator.stdout + validator.stderr

        report_artifacts = temp / "report" / "eval"
        shutil.copytree(REPORT_FIXTURE, report_artifacts)
        for generated in ("evaluation-report.html", "render-metrics.json"):
            (report_artifacts / generated).unlink(missing_ok=True)
        report = run_node("run-report.js", report_artifacts, foreign_cwd)
        assert report["model_invoked"] is False
        assert report["validation_fail_count"] == 0
        assert (report_artifacts / "evaluation-report.html").is_file()
        assert (report_artifacts / "evaluation-summary.json").is_file()
        assert (report_artifacts / "render-metrics.json").is_file()

        for script_name in (
            "run-classification.js", "run-report.js", "classify-ac-tier.js",
            "validate-classify.js", "validate-report-rendering.js",
        ):
            source = (SCRIPTS_DIR / script_name).read_text()
            assert "/Users/" not in source
            assert "Desktop/ai-helpers" not in source

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
