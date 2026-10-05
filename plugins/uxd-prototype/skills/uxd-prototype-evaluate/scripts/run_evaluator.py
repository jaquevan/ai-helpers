#!/usr/bin/env python3
"""Run and validate bundled source consistency without a model or network."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from jira_context import load_jira_context


SCRIPT_DIR = Path(__file__).resolve().parent
ANALYZER = SCRIPT_DIR.parent.parent / "uxd-consistency-check" / "scripts" / "analyze.py"
VALIDATOR = SCRIPT_DIR / "validate-consistency.js"


def _git_output(workspace: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def resolve_base_ref(workspace: Path, explicit: str | None = None) -> str | None:
    if explicit:
        if _git_output(workspace, "rev-parse", "--verify", explicit):
            return explicit
        raise ValueError(f"Git base ref does not exist: {explicit}")
    remote_head = _git_output(
        workspace, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
    )
    for candidate in (remote_head, "origin/main", "main", "HEAD"):
        if candidate and _git_output(workspace, "rev-parse", "--verify", candidate):
            return candidate
    return None


def run_deterministic_source(
    *,
    key: str,
    workspace: str | Path,
    jira_context_file: str | Path,
    artifacts_dir: str | Path | None = None,
    base_ref: str | None = None,
    all_files: bool = False,
    provided_guidelines: list[str] | None = None,
    trust_guideline_commands: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace_path}")
    if not ANALYZER.is_file() or not VALIDATOR.is_file():
        raise ValueError("Local evaluator or consistency-check installation is incomplete")
    load_jira_context(jira_context_file, key)
    artifacts_dir = (
        Path(artifacts_dir).resolve()
        if artifacts_dir else workspace_path / ".artifacts" / key / "eval"
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifacts_dir / "consistency-report.json"
    resolved_base = None if all_files else resolve_base_ref(workspace_path, base_ref)
    command = [
        sys.executable, str(ANALYZER), "--src", str(workspace_path),
        "--json-file", str(report_path),
    ]
    if resolved_base:
        command.extend(["--changed", "--base-ref", resolved_base])
    for source in provided_guidelines or []:
        command.extend(["--guidelines", source])
    if trust_guideline_commands:
        command.append("--trust-guideline-commands")
    checker = subprocess.run(
        command, cwd=workspace_path, capture_output=True, text=True, check=False
    )
    if checker.returncode not in (0, 1) or not report_path.is_file():
        return {
            "status": "failed", "model_invoked": False,
            "error": "Consistency checker did not produce a report",
            "checker_exit_code": checker.returncode, "checker_stderr": checker.stderr[-1000:],
        }
    validation = subprocess.run(
        ["node", str(VALIDATOR), str(artifacts_dir), "--json"],
        cwd=workspace_path, capture_output=True, text=True, check=False,
    )
    try:
        validation_data = json.loads(validation.stdout)
    except json.JSONDecodeError:
        validation_data = {
            "all_pass": False, "error": "Validator did not return JSON",
            "stderr": validation.stderr[-1000:],
        }
    report = json.loads(report_path.read_text())
    return {
        "status": "completed" if validation.returncode == 0 and validation_data.get("all_pass") else "failed",
        "phase": "eval-consistency-source", "model_invoked": False,
        "consistency_report": str(report_path), "base_ref": resolved_base,
        "changed_only": bool(resolved_base), "checker_exit_code": checker.returncode,
        "validator_exit_code": validation.returncode, "validator": validation_data,
        "summary": report.get("summary") or {},
        "finding_count": len((report.get("source_mode") or {}).get("violations") or []),
        "duration_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--jira-context", required=True)
    parser.add_argument("--artifacts-dir", help="Consumer eval directory when source is a separate checkout")
    parser.add_argument("--base-ref")
    parser.add_argument("--all-files", action="store_true")
    parser.add_argument("--guidelines", action="append", default=[])
    parser.add_argument("--trust-guideline-commands", action="store_true")
    args = parser.parse_args()
    try:
        result = run_deterministic_source(
            key=args.key, workspace=args.workspace, jira_context_file=args.jira_context,
            artifacts_dir=args.artifacts_dir, base_ref=args.base_ref, all_files=args.all_files,
            provided_guidelines=args.guidelines, trust_guideline_commands=args.trust_guideline_commands,
        )
    except (OSError, ValueError) as error:
        result = {"status": "failed", "model_invoked": False, "error": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
