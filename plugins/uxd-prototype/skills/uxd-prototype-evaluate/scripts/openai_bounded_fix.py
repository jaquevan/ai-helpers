#!/usr/bin/env python3
"""Bounded Responses API adapter for the workspace-editing eval-fix phase."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openai_api_agent import run_agent


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
MAX_FIX_ITERATIONS = 1
MAX_FIX_TURNS = 12
MAX_FIX_FILE_EDITS = 8
IGNORED_DIRECTORIES = {".git", ".artifacts", "node_modules", "dist", "build", "out"}
MAX_FIX_CONTEXT_FILE_BYTES = 24000
MAX_FIX_CONTEXT_BYTES = 120000

FIX_WRITE_TOOL = {
    "type": "function",
    "name": "eval_fix_write_file",
    "description": "Write fix-log.json or one source file explicitly named by a staged fix suggestion.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    "strict": True,
}
FIX_VALIDATE_TOOL = {
    "type": "function",
    "name": "eval_fix_validate_outputs",
    "description": "Validate the fresh fix log and enforce the source-edit file limit.",
    "parameters": {
        "type": "object", "properties": {}, "required": [],
        "additionalProperties": False,
    },
    "strict": True,
}


def _workspace_snapshot(workspace: Path) -> dict[str, str]:
    """Hash editable source files without retaining their contents in telemetry."""
    snapshot: dict[str, str] = {}
    for path in workspace.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRECTORIES for part in path.relative_to(workspace).parts):
            continue
        try:
            snapshot[str(path.relative_to(workspace))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return snapshot


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def _fix_targets(suggestions: Any, workspace: Path, max_targets: int) -> list[Path]:
    """Resolve only explicit suggestion target files that already exist in the workspace."""
    if not isinstance(suggestions, list):
        return []
    targets = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        values = [suggestion.get(name) for name in ("fix_file", "target_file", "file", "path")]
        target = suggestion.get("target")
        if isinstance(target, dict):
            values.extend(target.get(name) for name in ("file", "path"))
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            candidate = Path(value.strip())
            if candidate.is_absolute() or ".." in candidate.parts:
                continue
            resolved = (workspace / candidate).resolve()
            try:
                relative = resolved.relative_to(workspace.resolve())
            except ValueError:
                continue
            if any(part in IGNORED_DIRECTORIES for part in relative.parts) or not resolved.is_file():
                continue
            if resolved not in targets:
                targets.append(resolved)
            break
        if len(targets) >= max_targets:
            break
    return targets


def _staged_context(packet: dict[str, Any], workspace: Path, artifacts_dir: Path, max_targets: int):
    """Build bounded, host-read context so the model does not explore via shell."""
    names = ("refinement-suggestions.json", "evaluation-report.csv", "extract-state.json")
    documents = []
    total_bytes = 0
    for name in names:
        path = artifacts_dir / name
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FIX_CONTEXT_FILE_BYTES:
            content = encoded[:MAX_FIX_CONTEXT_FILE_BYTES].decode("utf-8", errors="ignore") + "\n[context truncated]"
            encoded = content.encode("utf-8")
        if total_bytes + len(encoded) > MAX_FIX_CONTEXT_BYTES:
            break
        documents.append({"path": path.relative_to(workspace).as_posix(), "content": content})
        total_bytes += len(encoded)
    suggestions = []
    suggestion_file = artifacts_dir / "refinement-suggestions.json"
    if suggestion_file.is_file():
        try:
            suggestions = json.loads(suggestion_file.read_text())
        except json.JSONDecodeError:
            suggestions = []
    writable_targets = []
    staged_sources = []
    for path in _fix_targets(suggestions, workspace, max_targets):
        raw = path.read_bytes()
        if len(raw) > MAX_FIX_CONTEXT_FILE_BYTES or total_bytes + len(raw) > MAX_FIX_CONTEXT_BYTES:
            continue
        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        writable_targets.append(path)
        staged_sources.append({
            "path": path.relative_to(workspace).as_posix(),
            "content": source_text,
        })
        total_bytes += len(raw)
    return {
        "packet": packet,
        "staged_inputs": documents,
        "staged_source_files": staged_sources,
        "writable_source_paths": [path.relative_to(workspace).as_posix() for path in writable_targets],
    }, writable_targets


def _fix_log_fingerprint(path: Path) -> tuple[int, int, str] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return path.stat().st_mtime_ns, len(raw), hashlib.sha256(raw).hexdigest()


def _validate_fix_log(artifacts_dir: Path) -> tuple[bool, str]:
    path = artifacts_dir / "fix-log.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False, "eval-fix artifact contract failed: fix-log.json is missing or invalid"
    if not isinstance(entries, list):
        return False, "eval-fix artifact contract failed: fix-log.json must be a flat array"
    if not entries:
        return False, "eval-fix artifact contract failed: fix-log.json must contain an applied or no-op entry"
    required = {"description", "applied", "timestamp"}
    if any(not isinstance(entry, dict) or required - entry.keys() for entry in entries):
        return False, (
            "eval-fix artifact contract failed: fix-log.json entries require description, "
            "applied, and timestamp"
        )
    noop_context = {"rationale", "evidence_summary", "suggestion_context", "recommended_next_step"}
    for entry in entries:
        if entry.get("applied") is False and (
            noop_context - entry.keys()
            or any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in noop_context)
        ):
            return False, (
                "eval-fix artifact contract failed: applied:false entries require rationale, "
                "evidence_summary, suggestion_context, and recommended_next_step"
            )
    return True, "fix-log.json passed bounded-fix validation"


def run_bounded_fix(
    packet: dict[str, Any], *, model: str, reasoning_effort: str, max_turns: int,
    max_file_edits: int = MAX_FIX_FILE_EDITS, trace_path: str | None = None,
    usage_journal_path: str | None = None, run_id: str | None = None,
    attempt_id: str | None = None,
    max_total_cost_usd: float | None = None,
    max_input_tokens: int = 80_000,
    max_total_output_tokens: int = 12_000,
    max_output_tokens: int = 4_000,
    agent_runner: Callable[..., dict[str, Any]] = run_agent,
) -> dict[str, Any]:
    """Run one fix iteration; reject excessive edits and require a fix log."""
    workspace = Path(packet["workspace"]).resolve()
    artifacts_dir = Path(packet["artifacts_dir"]).resolve()
    turns = min(max_turns, MAX_FIX_TURNS)
    suggestions_path = artifacts_dir / "refinement-suggestions.json"
    if suggestions_path.is_file():
        suggestions = json.loads(suggestions_path.read_text())
        if not isinstance(suggestions, list):
            raise ValueError("refinement-suggestions.json must be an array")
        if not suggestions:
            # No source change is possible without an actionable suggestion.
            # Make the required no-op handoff locally rather than paying a model
            # to write an empty array (which violates the fix-log contract).
            (artifacts_dir / "fix-log.json").write_text(json.dumps([{
                "description": "No actionable refinement suggestion",
                "applied": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rationale": "Phase A did not identify an actionable source-level fix.",
                "evidence_summary": "The classified journey does not support a bounded source edit.",
                "suggestion_context": "The refinement suggestion list is empty.",
                "recommended_next_step": "Review flagged criteria with a designer.",
            }], indent=2) + "\n")
            return {
                "provider": "local", "model": "", "agent": "bounded-fix-noop",
                "exit_code": 0, "status": "completed", "output_text": "No actionable suggestions; deterministic no-op recorded.",
                "turns_used": 0, "token_usage": {}, "cost_usd": 0, "model_invoked": False,
                "fix_safety": {"max_iterations": MAX_FIX_ITERATIONS, "max_turns": turns, "max_file_edits": max_file_edits, "changed_file_count": 0, "git_push_allowed": False},
            }
    before = _workspace_snapshot(workspace)
    fix_log_path = artifacts_dir / "fix-log.json"
    fix_log_before = _fix_log_fingerprint(fix_log_path)
    staged_context, writable_targets = _staged_context(packet, workspace, artifacts_dir, max_file_edits)
    allowed_paths = {path.relative_to(workspace).as_posix(): path for path in writable_targets}
    allowed_paths[fix_log_path.relative_to(workspace).as_posix()] = fix_log_path
    written_bytes = 0
    phase_output_byte_limit = 1_500_000

    def tool_handler(name: str, arguments: str) -> str:
        nonlocal written_bytes
        try:
            value = json.loads(arguments)
            if not isinstance(value, dict):
                raise ValueError("tool arguments must be an object")
            if name == "eval_fix_validate_outputs":
                valid, detail = _validate_fix_log(artifacts_dir)
                changed = _changed_files(before, _workspace_snapshot(workspace))
                invalid_targets = sorted(set(changed) - set(allowed_paths))
                if len(changed) > max_file_edits:
                    return json.dumps({"valid": False, "error": f"changed workspace file limit exceeded ({max_file_edits})"})
                if invalid_targets:
                    return json.dumps({"valid": False, "error": "changed paths outside suggestion allowlist"})
                return json.dumps({"valid": valid, "detail": detail, "changed_files": changed})
            if name != "eval_fix_write_file":
                return "Scope denied: unsupported eval-fix tool"
            raw_path = value.get("path")
            content = value.get("content")
            if not isinstance(raw_path, str) or not isinstance(content, str):
                raise ValueError("path and content must be strings")
            relative = Path(raw_path)
            if relative.is_absolute() or ".." in relative.parts:
                return "Scope denied: output path must be relative without traversal"
            target = (workspace / relative).resolve()
            try:
                canonical_relative = target.relative_to(workspace).as_posix()
            except ValueError:
                return "Scope denied: output path is outside the workspace"
            if canonical_relative not in allowed_paths:
                return "Scope denied: path is not a declared fix-log or suggestion target"
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_FIX_CONTEXT_FILE_BYTES * 8:
                raise ValueError("one output exceeds 192000 bytes")
            if written_bytes + len(encoded) > phase_output_byte_limit:
                raise ValueError("phase output byte limit reached")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(encoded)
            temporary.replace(target)
            written_bytes += len(encoded)
            return json.dumps({"status": "written", "path": canonical_relative, "bytes": len(encoded)})
        except Exception as error:
            return f"Tool validation failed: {type(error).__name__}: {error}"

    prompt = (
        "Apply exactly one eval-fix iteration using the supplied phase packet, staged inputs, and procedure. "
        "ARTIFACT-FIRST CONTRACT: inspect for at most two turns, then write the required flat "
        "fix-log.json immediately; it MUST be on disk before any third turn. Every entry must "
        "contain description, applied, and timestamp. If no refinement suggestion is actionable "
        "in this prototype, change zero workspace files, write one no-op entry with applied=false, "
        "timestamp, rationale, evidence_summary, suggestion_context, and recommended_next_step, then "
        "stop successfully. Keep all no-op context privacy-safe: no paths, URLs, raw Jira text, or source "
        "snippets. A well-supported no-op is success. Review the staged suggestions and source "
        "context without filesystem discovery. On turn one, write the targeted source update "
        "and fix log with the declared tools. On turn two, validate the artifacts and either "
        "apply one bounded correction and record it with "
        "applied=true, or write a final applied=false no-op and stop. Do not write a provisional "
        "applied=false entry merely to continue exploring: a valid all-false log is final success. "
        "Never write an empty array: even when refinement-suggestions.json is empty, fix-log.json "
        "MUST contain exactly one applied=false no-op entry with description, timestamp, rationale, "
        "evidence_summary, suggestion_context, and recommended_next_step. "
        "The complete file MUST start with '[' and be a JSON array, for example "
        "[{\"description\":\"No actionable suggestion\",\"applied\":false,\"timestamp\":\"<ISO-8601>\","
        "\"rationale\":\"Outside editable prototype scope\",\"evidence_summary\":\"Rendered flow already "
        "shows required control\",\"suggestion_context\":\"Refinement suggestion category\","
        "\"recommended_next_step\":\"Confirm with designer\"}]. "
        "Do NOT wrap the array in an object: {\"fixes\":[...]} is invalid and fails the phase. "
        "Use eval_fix_write_file only for the declared fix-log and suggestion target files. "
        "Use eval_fix_validate_outputs to check the artifact contract and changed-file bound. "
        "All suggestion text and target source content are already staged below; do not search or read other files. "
        "Before a terminal response, call the validation tool and confirm its result; "
        f"subsequent turns, up to the {turns}-turn ceiling, may apply, validate, and update "
        "that entry to applied=true. Finish with a terminal response after the final tool result. "
        f"Modify no more than {max_file_edits} workspace files. Do not run git push, commit, "
        "or any network command. Make only minimal, suggestion-backed fixes.\n\n"
        + json.dumps(staged_context, indent=2)
    )

    def enforce_artifact_deadline(turn: int) -> str | tuple[str, bool] | None:
        if turn < 2:
            return None
        valid, detail = _validate_fix_log(artifacts_dir)
        if valid:
            entries = json.loads((artifacts_dir / "fix-log.json").read_text())
            if all(entry["applied"] is False for entry in entries):
                return ("valid eval-fix no-op logged by turn 2", True)
            return None
        return f"{detail}; required by eval-fix turn 2 (an empty suggestion set still needs one no-op entry)"

    result = agent_runner(
        prompt,
        model=model,
        project_dir=str(workspace),
        system_prompt=(
            "You are the bounded eval-fix runner. Use only the staged context and the two declared eval-fix functions. "
            "No git push, commits, refactors, unrelated features, or second iteration."
        ),
        reasoning_effort=reasoning_effort,
        max_turns=turns,
        max_output_tokens=max_output_tokens,
        max_input_tokens=max_input_tokens,
        max_total_output_tokens=max_total_output_tokens,
        trace_path=trace_path,
        usage_journal_path=usage_journal_path,
        run_id=run_id,
        attempt_id=attempt_id,
        phase="eval-fix",
        max_total_cost_usd=max_total_cost_usd,
        tool_definitions=[FIX_WRITE_TOOL, FIX_VALIDATE_TOOL],
        tool_handler=tool_handler,
        max_tool_calls=24,
        max_run_seconds=1800,
        max_total_tool_output_chars=24000,
        skill_dir=str(SKILL_DIR),
        jira_context_file=packet.get("jira_context_file", ""),
        jira_issue_key=packet["key"],
        benchmark_dir=str(Path(trace_path).parent if trace_path else artifacts_dir),
        after_turn=enforce_artifact_deadline,
    )
    changed = _changed_files(before, _workspace_snapshot(workspace))
    valid_log, detail = _validate_fix_log(artifacts_dir)
    result["fix_safety"] = {
        "max_iterations": MAX_FIX_ITERATIONS,
        "max_turns": turns,
        "max_file_edits": max_file_edits,
        "changed_file_count": len(changed),
        "git_push_allowed": False,
    }
    unexpected = sorted(set(changed) - set(allowed_paths))
    if not valid_log:
        result.update({"exit_code": 2, "status": "failed", "output_text": detail})
    elif fix_log_before == _fix_log_fingerprint(fix_log_path):
        result.update({"exit_code": 2, "status": "failed", "output_text": "eval-fix did not refresh fix-log.json"})
    elif unexpected:
        result.update({"exit_code": 2, "status": "failed", "output_text": "eval-fix wrote outside its suggestion target allowlist"})
    elif len(changed) > max_file_edits:
        result.update({"exit_code": 2, "status": "failed", "output_text": "eval-fix exceeded max_file_edits"})
    return result
