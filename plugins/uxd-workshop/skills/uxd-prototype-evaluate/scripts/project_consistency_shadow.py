#!/usr/bin/env python3
"""Project a legacy source-consistency report into canonical shadow artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONSISTENCY_DIR = SKILL_DIR.parent / "uxd-consistency-check"
VALIDATOR = SCRIPT_DIR / "validate-canonical-artifacts.js"
ADAPTER = SCRIPT_DIR / "materialize-legacy-eval-artifacts.js"
SCHEMA_VERSION = "1.0.0"
PROJECTOR_VERSION = "1"
SOURCE_SUFFIXES = {".css", ".htm", ".html", ".js", ".jsx", ".scss", ".ts", ".tsx"}
IGNORED_PARTS = {".artifacts", ".git", "dist", "node_modules"}
CANONICAL_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:[\\/])(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._+@=-]+(?:/[A-Za-z0-9._+@=-]+)*$"
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _utc_timestamp(value: str | None = None) -> str:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bounded(value: Any, maximum: int, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    return text[:maximum]


def _source_path(value: Any) -> str:
    path = str(value or "").removeprefix("./")
    return path if CANONICAL_PATH.fullmatch(path) else "unknown-source"


def _git_lines(workspace: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []


def collect_source_inputs(workspace: Path, base_ref: str | None) -> list[Path]:
    """Return the exact deterministic source set used for shadow identity/metrics."""
    if base_ref:
        relative_paths = set(_git_lines(workspace, "diff", "--name-only", base_ref, "--"))
        relative_paths.update(_git_lines(workspace, "ls-files", "--others", "--exclude-standard"))
        candidates = [workspace / relative for relative in sorted(relative_paths)]
    else:
        candidates = sorted(workspace.rglob("*"))
    return [
        candidate
        for candidate in candidates
        if candidate.is_file()
        and candidate.suffix.lower() in SOURCE_SUFFIXES
        and not any(part in IGNORED_PARTS for part in candidate.relative_to(workspace).parts)
    ]


def build_input_identity(
    *, workspace: Path, jira_context: dict[str, Any], base_ref: str | None
) -> dict[str, Any]:
    source_files = collect_source_inputs(workspace, base_ref)
    build_hasher = hashlib.sha256()
    input_bytes = 0
    relative_files = []
    for source_file in source_files:
        relative = source_file.relative_to(workspace).as_posix()
        content = source_file.read_bytes()
        relative_files.append(relative)
        input_bytes += len(content)
        build_hasher.update(relative.encode())
        build_hasher.update(b"\0")
        build_hasher.update(content)
        build_hasher.update(b"\0")

    evaluator_hasher = hashlib.sha256()
    evaluator_hasher.update(SCHEMA_VERSION.encode())
    evaluator_hasher.update(PROJECTOR_VERSION.encode())
    version_file = CONSISTENCY_DIR / "VERSION"
    version = version_file.read_text().strip()
    evaluator_hasher.update(version.encode())
    for guideline in sorted((CONSISTENCY_DIR / "guidelines").rglob("*.md")):
        evaluator_hasher.update(guideline.relative_to(CONSISTENCY_DIR).as_posix().encode())
        evaluator_hasher.update(guideline.read_bytes())

    return {
        "source_files": relative_files,
        "input_files": len(source_files),
        "input_bytes": input_bytes,
        "intent_key": _sha256_json(jira_context),
        "build_key": "sha256:" + build_hasher.hexdigest(),
        "evaluator_key": "sha256:" + evaluator_hasher.hexdigest(),
        "evaluator_version": version,
    }


def _canonical_finding(finding: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "guideline_id": finding.get("guideline_id"),
        "file": finding.get("file"),
        "line": finding.get("line"),
        "property": finding.get("property"),
        "value": finding.get("value"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return {
        "id": f"finding-{digest}",
        "origin": "source",
        "guideline_id": _bounded(finding.get("guideline_id"), 160, "unknown-guideline"),
        "guideline_title": _bounded(finding.get("guideline_title"), 280, "PatternFly guideline"),
        "category": _bounded(finding.get("category"), 80, "foundations"),
        "severity": finding.get("severity", "warning"),
        "verdict": finding.get("verdict", "FLAGGED"),
        "confidence": finding.get("confidence", "low"),
        "property": _bounded(finding.get("property"), 280, "source"),
        "value": _bounded(finding.get("value"), 1000, "source match"),
        "check_method": finding.get("check_method", "automated_candidate"),
        "file": _source_path(finding.get("file")),
        "line": finding.get("line"),
        "evidence_ids": [],
        "description": _bounded(finding.get("description"), 280, "PatternFly source finding"),
        "recommendation": _bounded(finding.get("suggestion"), 500, "Use the matching PatternFly component or token."),
        "pf_doc_url": "https://www.patternfly.org/",
        "review_candidate": bool(finding.get("review_candidate")),
    }


def build_canonical_documents(
    *,
    key: str,
    workspace: Path,
    jira_context: dict[str, Any],
    legacy_report: dict[str, Any],
    base_ref: str | None,
    duration_ms: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    identity = build_input_identity(
        workspace=workspace, jira_context=jira_context, base_ref=base_ref
    )
    compound_payload = {
        "intent_key": identity["intent_key"],
        "build_key": identity["build_key"],
        "evaluator_key": identity["evaluator_key"],
    }
    compound_key = _sha256(
        json.dumps(compound_payload, separators=(",", ":")).encode()
    )
    run_digest = hashlib.sha256(
        f"{identity['intent_key']}|{identity['build_key']}|{identity['evaluator_key']}".encode()
    ).hexdigest()[:16]
    run_id = f"eval-{key}-{run_digest}"
    ended_at = _utc_timestamp(legacy_report.get("checked_at"))
    ended_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    started_at = (ended_dt - timedelta(milliseconds=max(0, duration_ms))).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    producer = {"name": "uxd-consistency-check-shadow", "version": identity["evaluator_version"]}
    envelope = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "prototype_key": key,
        "created_at": ended_at,
        "producer": producer,
    }
    findings = [
        _canonical_finding(finding)
        for finding in (legacy_report.get("source_mode") or {}).get("violations") or []
    ]
    consistency_counts = {
        "error": sum(finding["severity"] == "error" for finding in findings),
        "warning": sum(finding["severity"] == "warning" for finding in findings),
        "info": sum(finding["severity"] == "info" for finding in findings),
        "total": len(findings),
    }
    consistency_status = (
        "failed" if consistency_counts["error"] else "flagged" if findings else "passed"
    )

    brief = {
        **envelope,
        "artifact_type": "brief",
        "intent": {
            "stage": "consistency-source",
            "title": _bounded(jira_context["ticket"].get("summary"), 500, key),
            "acceptance_criteria": [],
            "tasks": [],
            "personas": [],
            "scope": {
                "prototype_url": workspace.as_uri(),
                "source_mode": "workspace",
                "source_ref": identity["build_key"],
                "changed_files": identity["source_files"],
            },
        },
    }
    evaluation = {
        **envelope,
        "artifact_type": "evaluation",
        "status": "failed" if consistency_counts["error"] else "needs-attention" if findings else "passed",
        "ac_results": [],
        "journeys": [],
        "usability": {"status": "not-run", "score": 0, "max_score": 0, "dimensions": []},
        "consistency": {
            "status": consistency_status,
            "guidelines_version": _bounded(legacy_report.get("guidelines_version"), 160, identity["evaluator_version"]),
            "guidelines_checked": int((legacy_report.get("summary") or {}).get("total_guidelines_checked", 0)),
            "screenshots_checked": 0,
            "source_checked": True,
            "visual_checked": False,
            "findings": findings,
        },
        "summary": {
            "ac_counts": {"pass": 0, "fail": 0, "flagged": 0, "not_run": 0, "total": 0},
            "consistency_counts": consistency_counts,
            "journey_counts": {"pass": 0, "fail": 0, "flagged": 0, "not_run": 0, "total": 0},
        },
    }
    evidence = {**envelope, "artifact_type": "evidence", "captures": [], "items": []}
    actions = {**envelope, "artifact_type": "actions", "actions": []}
    evaluation_bytes = len(_json_bytes(evaluation))
    state = {
        **envelope,
        "artifact_type": "state",
        "lifecycle": {
            "status": "completed",
            "current_phase": "consistency",
            "iteration": 0,
            "max_iterations": 1,
            "exit_reason": "pending",
            "iterations": [],
        },
        "identity": {**compound_payload, "compound_key": compound_key},
        "cache": {
            "decision": "bypass",
            "entry_key": compound_key,
            "invalidated_by": ["none"],
            "restored_artifacts": [],
        },
        "phases": [
            {
                "name": "consistency-source",
                "status": "completed",
                "model_invoked": False,
                "provider": "none",
                "model": "",
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": max(0, duration_ms),
                "input_files": identity["input_files"],
                "input_bytes": identity["input_bytes"],
                "output_bytes": evaluation_bytes,
                "token_usage": {"input": 0, "cached_input": 0, "output": 0, "reasoning_tokens": 0},
                "llm_cost_usd": 0,
            }
        ],
    }
    documents = {
        "brief.json": brief,
        "evaluation.json": evaluation,
        "evidence.json": evidence,
        "actions.json": actions,
        "state.json": state,
    }
    return documents, {**identity, "compound_key": compound_key, "run_id": run_id}


def _normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "guideline_id",
        "severity",
        "verdict",
        "confidence",
        "review_candidate",
        "file",
        "line",
        "property",
        "value",
    )
    findings = [
        {
            field: _source_path(finding.get(field)) if field == "file" else finding.get(field)
            for field in fields
        }
        for finding in (report.get("source_mode") or {}).get("violations") or []
    ]
    findings.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return {"findings": findings, "summary": report.get("summary") or {}}


def _validate_directory(directory: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["node", str(VALIDATOR), str(directory), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"Canonical validator did not return JSON: {error}") from error
    if result.returncode != 0 or not payload.get("valid"):
        raise ValueError(f"Canonical shadow validation failed: {payload.get('errors')}")
    return payload


def _compare_through_adapter(directory: Path, legacy_report: dict[str, Any]) -> bool:
    with tempfile.TemporaryDirectory(prefix="uxd-consistency-parity-") as temp_dir:
        output_dir = Path(temp_dir) / "compatibility"
        result = subprocess.run(
            [
                "node",
                str(ADAPTER),
                "--canonical-dir",
                str(directory),
                "--output-dir",
                str(output_dir),
                "--targets",
                "consistency",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(f"Compatibility adapter failed: {result.stdout or result.stderr}")
        projected = json.loads((output_dir / "consistency-report.json").read_text())
        return _normalize_report(legacy_report) == _normalize_report(projected)


def _atomic_install(stage_dir: Path, target_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = None
    if target_dir.exists():
        backup_dir = target_dir.parent / f".{target_dir.name}.backup-{os.getpid()}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        target_dir.rename(backup_dir)
    try:
        stage_dir.rename(target_dir)
    except Exception:
        if backup_dir and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        raise
    if backup_dir:
        shutil.rmtree(backup_dir)


def write_consistency_shadow(
    *,
    key: str,
    workspace: str | Path,
    jira_context: dict[str, Any],
    legacy_report: dict[str, Any],
    shadow_root: str | Path,
    base_ref: str | None,
    duration_ms: int,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    shadow_root_path = Path(shadow_root).resolve()
    documents, identity = build_canonical_documents(
        key=key,
        workspace=workspace_path,
        jira_context=jira_context,
        legacy_report=legacy_report,
        base_ref=base_ref,
        duration_ms=duration_ms,
    )
    target_dir = shadow_root_path / identity["run_id"]
    shadow_root_path.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=".consistency-shadow-stage-", dir=shadow_root_path))
    try:
        for filename, document in documents.items():
            (stage_dir / filename).write_bytes(_json_bytes(document))
        validation = _validate_directory(stage_dir)
        parity = _compare_through_adapter(stage_dir, legacy_report)
        if not parity:
            raise ValueError("Canonical shadow failed normalized legacy parity")
        file_bytes = sum((stage_dir / filename).stat().st_size for filename in documents)
        _atomic_install(stage_dir, target_dir)
    except Exception:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        raise
    return {
        "status": "completed",
        "directory": str(target_dir),
        "run_id": identity["run_id"],
        "compound_key": identity["compound_key"],
        "input_files": identity["input_files"],
        "input_bytes": identity["input_bytes"],
        "artifact_bytes": file_bytes,
        "finding_count": len(documents["evaluation.json"]["consistency"]["findings"]),
        "schema_valid": validation["valid"],
        "adapter_parity": parity,
        "model_invoked": False,
        "llm_cost_usd": 0,
    }


__all__ = [
    "build_canonical_documents",
    "build_input_identity",
    "collect_source_inputs",
    "write_consistency_shadow",
]
