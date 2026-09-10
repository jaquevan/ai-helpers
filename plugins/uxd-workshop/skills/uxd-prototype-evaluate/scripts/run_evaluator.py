#!/usr/bin/env python3
"""Deterministic evaluator entrypoint for model-free source consistency."""

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
SKILL_DIR = SCRIPT_DIR.parent
CONSISTENCY_DIR = SKILL_DIR.parent / "uxd-consistency-check"
ANALYZER = CONSISTENCY_DIR / "scripts" / "analyze.py"
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
    candidates = [remote_head, "origin/main", "main", "HEAD"]
    for candidate in candidates:
        if candidate and _git_output(workspace, "rev-parse", "--verify", candidate):
            return candidate
    return None


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def run_deterministic_source(
    *,
    key: str,
    workspace: str | Path,
    jira_context_file: str | Path,
    benchmark_dir: str | Path,
    base_ref: str | None = None,
    all_files: bool = False,
) -> dict[str, Any]:
    """Run the bundled checker and schema validator without an LLM or network."""
    started = time.monotonic()
    workspace_path = Path(workspace).resolve()
    benchmark_path = Path(benchmark_dir).resolve()
    context_path = Path(jira_context_file).resolve()
    if not workspace_path.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace_path}")
    if not ANALYZER.is_file() or not VALIDATOR.is_file():
        raise ValueError("Local evaluator or consistency-check installation is incomplete")
    load_jira_context(context_path, key)
    benchmark_path.mkdir(parents=True, exist_ok=True)

    artifacts_dir = workspace_path / ".artifacts" / key / "eval"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifacts_dir / "consistency-report.json"

    resolved_base = None if all_files else resolve_base_ref(workspace_path, base_ref)
    command = [
        sys.executable,
        str(ANALYZER),
        "--src",
        str(workspace_path),
        "--json-file",
        str(report_path),
    ]
    if resolved_base:
        command.extend(["--changed", "--base-ref", resolved_base])

    checker = _run(command, cwd=workspace_path)
    if checker.returncode not in (0, 1) or not report_path.is_file():
        result = {
            "status": "failed",
            "phase": "eval-consistency-source",
            "model_invoked": False,
            "error": "Consistency checker did not produce a report",
            "checker_exit_code": checker.returncode,
            "checker_stderr": checker.stderr[-1000:],
            "duration_s": round(time.monotonic() - started, 3),
        }
        (benchmark_path / "deterministic-source-result.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        return result

    validation = _run(
        ["node", str(VALIDATOR), str(artifacts_dir), "--json"],
        cwd=workspace_path,
    )
    try:
        validation_data = json.loads(validation.stdout)
    except json.JSONDecodeError:
        validation_data = {
            "all_pass": False,
            "error": "Validator did not return JSON",
            "stderr": validation.stderr[-1000:],
        }

    report = json.loads(report_path.read_text())
    status = "completed" if validation.returncode == 0 and validation_data.get("all_pass") else "failed"
    result = {
        "status": status,
        "phase": "eval-consistency-source",
        "model_invoked": False,
        "source": "uxd-consistency-check",
        "workspace": str(workspace_path),
        "jira_context_file": str(context_path),
        "consistency_report": str(report_path),
        "base_ref": resolved_base,
        "changed_only": bool(resolved_base),
        "checker_exit_code": checker.returncode,
        "validator_exit_code": validation.returncode,
        "validator": validation_data,
        "summary": report.get("summary") or {},
        "finding_count": len((report.get("source_mode") or {}).get("violations") or []),
        "duration_s": round(time.monotonic() - started, 3),
    }
    (benchmark_path / "deterministic-source-result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--jira-context", required=True)
    parser.add_argument("--benchmark-dir", required=True)
    parser.add_argument("--base-ref")
    parser.add_argument("--all-files", action="store_true")
    args = parser.parse_args()
    try:
        result = run_deterministic_source(
            key=args.key,
            workspace=args.workspace,
            jira_context_file=args.jira_context,
            benchmark_dir=args.benchmark_dir,
            base_ref=args.base_ref,
            all_files=args.all_files,
        )
    except ValueError as error:
        result = {"status": "failed", "error": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
