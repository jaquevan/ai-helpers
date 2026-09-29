#!/usr/bin/env python3
"""Phase-scoped inputs, write tools, and host-owned creator validation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


WRITE_TOOL = {
    "type": "function",
    "name": "creator_write_output",
    "description": "Write one output artifact within this phase's approved output paths.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    "strict": True,
}

VALIDATE_TOOL = {
    "type": "function",
    "name": "creator_validate_outputs",
    "description": "Run deterministic artifact and consistency validation for this phase.",
    "parameters": {
        "type": "object", "properties": {}, "required": [],
        "additionalProperties": False,
    },
    "strict": True,
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _staged_file(path: Path, *, max_bytes: int = 24000) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    if len(raw) > max_bytes:
        text = text[:max_bytes] + f"\n[staged context limited; original bytes={len(raw)}]"
    return {"name": path.name, "content": text}


def build_context_packet(args, resolved: dict[str, Any], required_outputs: list[Path]) -> dict[str, Any]:
    """Stage only the user task, prior phase artifacts, and named skill references."""
    phase = args.phase
    artifacts: Path = resolved["artifacts"]
    reference_names = {
        "create-plan": ("output-formats.md", "decision-points.yaml", "scenario-brainstorm.md"),
        "create-generate": ("output-formats.md", "scenario-mocks.md"),
        "create-refine": ("refinement-procedure.md", "output-formats.md"),
    }[phase]
    references = []
    for name in reference_names:
        item = _staged_file(Path(__file__).resolve().parents[1] / "references" / name)
        if item:
            references.append(item)
    prior_names = {
        "create-plan": (),
        "create-generate": ("user-stories.json", "journeys.json", "scenarios.json"),
        "create-refine": (
            "metadata.json", "prototype-summary.yaml", "changeset.md",
            "consistency-report.json", "verification.json",
        ),
    }[phase]
    prior = []
    for name in prior_names:
        item = _staged_file(artifacts / name, max_bytes=32000)
        if item:
            prior.append(item)
    staged_source_files = []
    if phase == "create-generate" and args.mode == "workspace":
        analysis = _read_json(artifacts / "workspace-analysis.json") or {}
        for relative in ["package.json", *analysis.get("relevant_areas", [])[:6]]:
            path = (artifacts / "code" / relative).resolve()
            try:
                path.relative_to((artifacts / "code").resolve())
            except ValueError:
                continue
            item = _staged_file(path, max_bytes=8000)
            if item:
                item["path"] = path.relative_to(artifacts / "code").as_posix()
                staged_source_files.append(item)
    elif phase == "create-refine":
        changeset = (artifacts / "changeset.md").read_text(errors="replace") if (artifacts / "changeset.md").is_file() else ""
        candidates = re.findall(r"`([^`]+)`", changeset)
        source_roots = [artifacts / ("code" if args.mode == "workspace" else "prototype")]
        for candidate in candidates[:20]:
            relative = Path(candidate)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            relative_variants = [relative]
            artifact_prefix = Path(".artifacts") / args.key
            try:
                relative_variants.append(relative.relative_to(artifact_prefix))
            except ValueError:
                pass
            for variant in tuple(relative_variants):
                for source_name in ("code", "prototype"):
                    if variant.parts and variant.parts[0] == source_name:
                        relative_variants.append(Path(*variant.parts[1:]))
            matching = next((
                root / item
                for root in source_roots
                for item in relative_variants
                if item.parts and (root / item).is_file()
            ), None)
            if matching is None:
                continue
            item = _staged_file(matching, max_bytes=12000)
            if item:
                item["path"] = matching.relative_to(artifacts).as_posix()
                staged_source_files.append(item)
    return {
        "phase": phase,
        "prototype_key": args.key,
        "mode": args.mode,
        "task": resolved["prompt"],
        "required_outputs": [
            str(Path(path).resolve().relative_to(Path(resolved["workspace"]).resolve()))
            for path in required_outputs
        ],
        "prior_phase_artifacts": prior,
        "staged_source_files": staged_source_files,
        "references": references,
        "tool_contract": {
            "write": "creator_write_output writes only phase-allowlisted files; no shell or arbitrary reads.",
            "validate": "creator_validate_outputs checks freshness and required structure; create-refine also refreshes consistency output.",
        },
    }


def tool_definitions() -> list[dict[str, Any]]:
    return [WRITE_TOOL, VALIDATE_TOOL]


def allowed_output(
    path_text: str,
    *,
    phase: str,
    mode: str,
    key: str,
    workspace: Path,
    artifacts: Path | None = None,
) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("output path must be relative and cannot traverse parent directories")
    resolved = (workspace / candidate).resolve()
    artifact_root = (artifacts or (workspace / ".artifacts" / key)).resolve()
    try:
        artifact_root.relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError("artifact root must remain inside the workspace") from error
    generated_root = artifact_root / ("code" if mode == "workspace" else "prototype")
    direct_model_outputs = {
        "create-plan": {"user-stories.json", "journeys.json", "scenarios.json"},
        "create-generate": {"metadata.json", "prototype-summary.yaml"},
        "create-refine": {"changeset.md"},
    }[phase]
    relative = resolved.relative_to(artifact_root) if artifact_root in resolved.parents else None
    direct_write = relative is not None and len(relative.parts) == 1 and relative.name in direct_model_outputs
    source_write = (
        phase in {"create-generate", "create-refine"}
        and resolved != generated_root
        and generated_root in resolved.parents
    )
    if not direct_write and not source_write:
        raise ValueError("output path is outside this phase's allowed artifact roots")
    if any(part in {"benchmark", "eval", "screenshots"} for part in candidate.parts):
        raise ValueError("output path targets a reserved artifact directory")
    return resolved


def _validate_plan_artifacts(artifacts: Path) -> None:
    schemas = json.loads((Path(__file__).resolve().parents[1] / "config" / "creator-artifact-schemas.json").read_text())
    stories = _read_json(artifacts / "user-stories.json")
    journeys = _read_json(artifacts / "journeys.json")
    scenarios = _read_json(artifacts / "scenarios.json")
    for filename, value in (
        ("user-stories.json", stories), ("journeys.json", journeys),
        ("scenarios.json", scenarios),
    ):
        _validate_schema(value, schemas["artifacts"][filename], filename)
    for index, journey in enumerate(journeys["journeys"]):
        for step_index, step in enumerate(journey["steps"]):
            if "actions" in step and not isinstance(step["actions"], list):
                raise ValueError(f"journeys[{index}].steps[{step_index}].actions must be an array")
    routes = {step["route"] for journey in journeys["journeys"] for step in journey["steps"]}
    scenario_routes = set()
    for page_index, page in enumerate(scenarios["pages"]):
        scenario_routes.add(page["route"])
        variants = page.get("scenarios")
        if not any(isinstance(item, dict) and (item.get("default") is True or item.get("id") == "default") for item in variants):
            raise ValueError(f"scenarios.pages[{page_index}] requires a default scenario")
        ids = [item.get("id") for item in variants if isinstance(item, dict)]
        if len(ids) != len(set(ids)) or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9-]+", item) for item in ids):
            raise ValueError(f"scenarios.pages[{page_index}] has invalid or duplicate scenario IDs")
    if routes - scenario_routes:
        raise ValueError("scenarios.json is missing journey routes: " + ", ".join(sorted(routes - scenario_routes)))


def _validate_schema(value: Any, schema: dict[str, Any], at: str) -> None:
    expected = schema.get("type")
    valid_type = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
    }.get(expected)
    if valid_type and not valid_type(value):
        raise ValueError(f"{at} must be {expected}")
    if expected == "object":
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise ValueError(f"{at} missing required fields: {', '.join(missing)}")
        if len(value) < int(schema.get("minProperties", 0)):
            raise ValueError(f"{at} requires at least {schema['minProperties']} properties")
        for key, child in schema.get("properties", {}).items():
            if key in value:
                _validate_schema(value[key], child, f"{at}.{key}")
    elif expected == "array":
        if len(value) < int(schema.get("minItems", 0)):
            raise ValueError(f"{at} requires at least {schema['minItems']} items")
        for index, item in enumerate(value):
            _validate_schema(item, schema.get("items", {}), f"{at}[{index}]")
    elif expected == "string":
        if len(value) < int(schema.get("minLength", 0)):
            raise ValueError(f"{at} must contain at least {schema['minLength']} characters")
        if schema.get("enum") is not None and value not in schema["enum"]:
            raise ValueError(f"{at} must be one of {schema['enum']}")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{at} does not match the required pattern")


def _source_dir(args, resolved: dict[str, Any]) -> Path:
    name = "code" if args.mode == "workspace" else "prototype"
    source = resolved["artifacts"] / name
    if not source.is_dir():
        raise ValueError(f"prototype source directory is missing: {name}")
    return source


def _changed_source_paths(source: Path) -> set[str]:
    changed = subprocess.run(
        ["git", "-C", str(source), "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    untracked = subprocess.run(
        ["git", "-C", str(source), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=False,
    )
    if changed.returncode or untracked.returncode:
        raise RuntimeError("cannot determine changed prototype source files")
    return {
        Path(value).as_posix().removeprefix("./")
        for value in (*changed.stdout.splitlines(), *untracked.stdout.splitlines())
        if value.strip()
    }


def _run_consistency_check(args, resolved: dict[str, Any]) -> dict[str, Any]:
    source = _source_dir(args, resolved)
    report_path = resolved["artifacts"] / "consistency-report.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[4] / "uxd-workshop" / "skills" / "uxd-consistency-check" / "scripts" / "analyze.py"),
        f"--src={source}", "--json-file", str(report_path),
    ]
    if args.mode == "workspace":
        command.extend(["--changed", "--base-ref=HEAD"])
    safe_env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    safe_env["NO_COLOR"] = "1"
    completed = subprocess.run(
        command, cwd=str(source), env=safe_env, capture_output=True, text=True,
        timeout=300, check=False,
    )
    try:
        report = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("consistency checker did not write valid JSON") from error
    baseline_errors = []
    if completed.returncode != 0:
        findings = (report.get("source_mode") or {}).get("violations", [])
        errors = [
            item for item in findings
            if isinstance(item, dict) and item.get("severity") == "error"
        ]
        if args.mode == "workspace" and errors:
            changed_paths = _changed_source_paths(source)
            blocking_errors = []
            for finding in errors:
                path = str(finding.get("file") or "").removeprefix("./")
                if not path or path in changed_paths:
                    blocking_errors.append(finding)
                else:
                    baseline_errors.append({
                        "guideline_id": finding.get("guideline_id"),
                        "file": path,
                        "severity": "error",
                    })
            if blocking_errors:
                raise RuntimeError(
                    f"consistency checker found {len(blocking_errors)} error(s) in changed source files"
                )
        else:
            raise RuntimeError(f"consistency checker failed with exit code {completed.returncode}")
    raw = report_path.read_bytes()
    validation = {
        "schema_version": 1,
        "phase": args.phase,
        "status": "completed_with_baseline_findings" if baseline_errors else "completed",
        "checker": "uxd-consistency-check/analyze.py",
        "validation_scope": "changed_workspace_files" if args.mode == "workspace" else "full_prototype",
        "baseline_errors": baseline_errors,
        "source_sha256": hashlib.sha256("".join(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.rglob("*")) if path.is_file()
        ).encode()).hexdigest(),
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "summary": report.get("summary", {}),
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    validation_path = resolved["artifacts"] / "refine-validation.json"
    validation_path.write_text(json.dumps(validation, indent=2) + "\n")
    return {"validation": validation, "report": report}


def make_tool_handler(args, resolved: dict[str, Any], baseline: dict[str, Any], validator: Callable[[], dict[str, Any]]) -> Callable[[str, str], str]:
    workspace: Path = resolved["workspace"]
    allowed_outputs: set[str] = set()
    written_bytes = 0
    max_writes = int(resolved["phase_spec"].get("max_output_files", 48))
    max_bytes = int(resolved["phase_spec"].get("max_output_bytes", 1_500_000))

    def handle(name: str, arguments: str) -> str:
        nonlocal written_bytes
        try:
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                raise ValueError("tool arguments must be an object")
            if name == "creator_write_output":
                relative = parsed.get("path")
                content = parsed.get("content")
                if not isinstance(relative, str) or not isinstance(content, str):
                    raise ValueError("path and content must be strings")
                target = allowed_output(
                    relative, phase=args.phase, mode=args.mode, key=args.key,
                    workspace=workspace, artifacts=resolved["artifacts"],
                )
                artifact_relative = target.relative_to(workspace).as_posix()
                if artifact_relative not in allowed_outputs and len(allowed_outputs) >= max_writes:
                    raise ValueError(f"phase output file limit reached ({max_writes})")
                encoded = content.encode("utf-8")
                if len(encoded) > max_bytes:
                    raise ValueError(f"one phase output exceeds {max_bytes} bytes")
                if written_bytes + len(encoded) > max_bytes:
                    raise ValueError(f"phase output byte limit reached ({max_bytes})")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(encoded)
                temporary.replace(target)
                written_bytes += len(encoded)
                allowed_outputs.add(artifact_relative)
                return json.dumps({"status": "written", "path": artifact_relative, "bytes": len(encoded)})
            if name == "creator_validate_outputs":
                state = validator()
                return json.dumps(state, ensure_ascii=False)
            return "Scope denied: unsupported creator tool"
        except Exception as error:
            return f"Tool validation failed: {type(error).__name__}: {error}"

    return handle
