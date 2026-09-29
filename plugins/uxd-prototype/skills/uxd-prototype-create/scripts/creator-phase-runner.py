#!/usr/bin/env python3
"""Run one bounded, OpenAI-priced prototype-creator phase.

The ordinary creator skill remains conversational. This runner is the measured
pipeline path: it requires a zero-spend estimate and explicit approval for each
phase, reserves against a creator-only $15 ledger, and records full phase
content in the creator Langfuse project with credential redaction.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[3]
EVALUATOR_SCRIPTS_DIR = (
    SKILL_DIR.parents[2]
    / "uxd-prototype"
    / "skills"
    / "uxd-prototype-evaluate"
    / "scripts"
)
CONSISTENCY_CHECK_DIR = (
    SKILL_DIR.parents[2] / "uxd-workshop" / "skills" / "uxd-consistency-check"
)
PROTOTYPE_EXPORT_DIR = (
    SKILL_DIR.parents[2] / "uxd-prototype" / "skills" / "uxd-prototype-export"
)
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(EVALUATOR_SCRIPTS_DIR))

import langfuse_trace  # noqa: E402
from openai_api_agent import run_agent  # noqa: E402
from usage_journal import UsageJournal  # noqa: E402
from pipeline_mode import (  # noqa: E402
    CREATOR_OPENAI_CAP_USD,
    CREATOR_OPENAI_PHASE_BOUNDS,
    CREATOR_LEDGER_FILENAME,
    creator_cost_authority,
    creator_trace_context_path,
    load_creator_routing,
    validated_url,
)
from creator_phase_tools import (  # noqa: E402
    _run_consistency_check,
    build_context_packet,
    make_tool_handler,
    tool_definitions,
)


VERIFY_SPEC = importlib.util.spec_from_file_location(
    "creator_phase_verify_langfuse", EVALUATOR_SCRIPTS_DIR / "verify-langfuse.py"
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
verify_langfuse = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verify_langfuse)

KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SYSTEM_PROMPT = """You are the model for exactly one bounded UX prototype-creator phase.
Work only from the staged task and reference packet. You have no shell, network,
Jira, arbitrary file-read, or repository-search tool. Use creator_write_output
for files in the declared phase output roots and creator_validate_outputs to
run host-owned schemas, freshness checks, and the deterministic consistency
checker. Create every required output, call validation, correct its findings,
and stop when the output contract passes or a configured bound is reached.
Never claim validation passed without its host-generated result."""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def workspace_revision(workspace: Path) -> str | None:
    if not (workspace / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def parse_args() -> argparse.Namespace:
    routing = load_creator_routing()
    parser = argparse.ArgumentParser(description="Run one bounded OpenAI creator phase")
    parser.add_argument("--key", required=True)
    parser.add_argument("--phase", required=True, choices=sorted(routing["phases"]))
    parser.add_argument("--workspace", required=True, help="Consumer project root")
    parser.add_argument("--jira-url", help="Jira issue URL attached to the shared creator trace")
    parser.add_argument("--artifacts-dir", help="Defaults to <workspace>/.artifacts/<key>")
    parser.add_argument("--benchmark-dir", help="Defaults to <artifacts-dir>/benchmark")
    parser.add_argument("--prompt-file", required=True, help="Phase task saved inside the workspace")
    parser.add_argument("--mode", choices=("standalone", "workspace"), default="standalone")
    parser.add_argument("--model", help="OpenAI model override; must have configured pricing")
    parser.add_argument("--run-id", help="Reuse this ID across all phases of one creator run")
    parser.add_argument(
        "--attempt-id",
        help="Unique namespace for a separately approved attempt of the same phase/run",
    )
    parser.add_argument("--comparison-id", help="Shared Langfuse comparison tag")
    parser.add_argument("--benchmark-name", default="prototype-creator-costs")
    parser.add_argument("--env-file", help="Local OpenAI/Langfuse env file")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--approve-estimate", action="store_true")
    return parser.parse_args()


def resolve_inputs(args: argparse.Namespace) -> dict[str, Any]:
    if not KEY_PATTERN.fullmatch(args.key):
        raise ValueError("--key must contain only letters, numbers, dots, underscores, or hyphens")
    attempt_id = getattr(args, "attempt_id", None)
    if attempt_id and not KEY_PATTERN.fullmatch(attempt_id):
        raise ValueError("--attempt-id must contain only letters, numbers, dots, underscores, or hyphens")
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace}")
    artifacts = (
        Path(args.artifacts_dir).expanduser().resolve()
        if args.artifacts_dir
        else workspace / ".artifacts" / args.key
    )
    benchmark = (
        Path(args.benchmark_dir).expanduser().resolve()
        if args.benchmark_dir
        else artifacts / "benchmark"
    )
    for label, path in (("artifacts directory", artifacts), ("benchmark directory", benchmark)):
        try:
            path.relative_to(workspace)
        except ValueError as error:
            raise ValueError(f"{label} must be inside the workspace") from error
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    try:
        prompt_file.relative_to(workspace)
    except ValueError as error:
        raise ValueError("--prompt-file must be inside the workspace") from error
    if not prompt_file.is_file():
        raise ValueError(f"Prompt file does not exist: {prompt_file}")
    prompt = prompt_file.read_text()
    phase_spec = load_creator_routing()["phases"][args.phase]
    if len(prompt.encode("utf-8")) > int(phase_spec.get("max_prompt_bytes", 65536)):
        raise ValueError("Phase prompt exceeds its configured byte limit")
    model = args.model or phase_spec["model"]
    if model not in langfuse_trace.OPENAI_PRICING_PER_MTOK:
        raise ValueError(f"No configured OpenAI price card for model {model}")
    run_id = args.run_id or os.environ.get("UXD_TRACE_RUN_ID") or f"create-{args.key}-{uuid.uuid4().hex[:10]}"
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("--run-id contains unsupported characters")
    if os.environ.get("UXD_TRACE_RUN_ID") and args.run_id and args.run_id != os.environ["UXD_TRACE_RUN_ID"]:
        raise ValueError("--run-id must match the consent launcher trace ID")
    raw_jira_url = getattr(args, "jira_url", None)
    jira_url = validated_url(raw_jira_url, "--jira-url") if raw_jira_url else None
    return {
        "workspace": workspace,
        "artifacts": artifacts,
        "benchmark": benchmark,
        "prompt_file": prompt_file,
        "prompt": prompt,
        "prompt_sha256": sha256(prompt),
        "phase_spec": phase_spec,
        "model": model,
        "run_id": run_id,
        "jira_url": jira_url,
        "source_revision": workspace_revision(workspace),
    }


def expected_outputs(args: argparse.Namespace, resolved: dict[str, Any]) -> list[Path]:
    phase = args.phase
    outputs = [resolved["artifacts"] / name for name in resolved["phase_spec"]["expected_outputs"]]
    if phase == "create-generate":
        if args.mode == "standalone":
            outputs.append(resolved["artifacts"] / "prototype" / "index.html")
        else:
            outputs.append(resolved["artifacts"] / "code")
    return outputs


def output_fingerprint(path: Path) -> tuple[int, int, str] | None:
    if not path.exists():
        return None
    if path.is_dir():
        files = [item for item in sorted(path.rglob("*")) if item.is_file()]
        if not files:
            return None
        digest = hashlib.sha256()
        newest = 0
        total = 0
        for item in files:
            data = item.read_bytes()
            relative = item.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8") + b"\0" + data)
            newest = max(newest, item.stat().st_mtime_ns)
            total += len(data)
        return newest, total, digest.hexdigest()
    if not path.is_file():
        return None
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest())


def snapshot_phase_outputs(args: argparse.Namespace, resolved: dict[str, Any]) -> dict[str, Any]:
    return {str(path): output_fingerprint(path) for path in expected_outputs(args, resolved)}


def phase_trace_artifact_paths(args: argparse.Namespace, resolved: dict[str, Any]) -> list[str]:
    """Select task/phase outputs and changed code files for full trace capture."""
    artifacts: Path = resolved["artifacts"]
    selected: set[str] = set()
    candidates = [resolved.get("prompt_file"), artifacts / "workspace-analysis.json"]
    candidates.extend(expected_outputs(args, resolved))
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        try:
            selected.add(candidate.resolve().relative_to(artifacts.resolve()).as_posix())
        except ValueError:
            continue

    if args.mode == "workspace" and args.phase in {"create-generate", "create-refine"}:
        code_root = artifacts / "code"
        if code_root.is_dir() and (code_root / ".git").exists():
            changed = subprocess.run(
                ["git", "-C", str(code_root), "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, check=False,
            )
            untracked = subprocess.run(
                ["git", "-C", str(code_root), "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, check=False,
            )
            if changed.returncode == 0 and untracked.returncode == 0:
                for relative_text in (*changed.stdout.splitlines(), *untracked.stdout.splitlines()):
                    relative = Path(relative_text)
                    if relative.is_absolute() or ".." in relative.parts:
                        continue
                    candidate = (code_root / relative).resolve()
                    try:
                        candidate.relative_to(code_root.resolve())
                    except ValueError:
                        continue
                    if candidate.is_file():
                        selected.add(candidate.relative_to(artifacts.resolve()).as_posix())
    return sorted(selected)


def manifest_artifact_paths(args: argparse.Namespace, resolved: dict[str, Any]) -> list[str]:
    """Select run outputs without enumerating a checked-out source repository."""
    if getattr(args, "phase", None) and resolved.get("phase_spec"):
        return phase_trace_artifact_paths(args, resolved)

    artifacts: Path = resolved["artifacts"]
    selected = {
        path.relative_to(artifacts).as_posix()
        for path in artifacts.rglob("*")
        if path.is_file()
        and not any(part in {"benchmark", "node_modules", ".git", "code"} for part in path.relative_to(artifacts).parts)
        and not path.name.endswith(".tmp")
    }
    code_root = artifacts / "code"
    if code_root.is_dir() and (code_root / ".git").exists():
        changed = subprocess.run(
            ["git", "-C", str(code_root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        untracked = subprocess.run(
            ["git", "-C", str(code_root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=False,
        )
        if changed.returncode == 0 and untracked.returncode == 0:
            for value in (*changed.stdout.splitlines(), *untracked.stdout.splitlines()):
                relative = Path(value)
                if relative.is_absolute() or ".." in relative.parts:
                    continue
                candidate = (code_root / relative).resolve()
                try:
                    candidate.relative_to(code_root.resolve())
                except ValueError:
                    continue
                if candidate.is_file():
                    selected.add(candidate.relative_to(artifacts.resolve()).as_posix())
    prompt_file = resolved.get("prompt_file")
    if prompt_file and prompt_file.is_file():
        try:
            selected.add(prompt_file.resolve().relative_to(artifacts.resolve()).as_posix())
        except ValueError:
            pass
    return sorted(selected)


def validate_phase_artifacts(
    args: argparse.Namespace,
    resolved: dict[str, Any],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check required outputs exist and JSON artifacts are parseable/structured."""
    missing: list[str] = []
    invalid: list[str] = []
    stale: list[str] = []
    for path in expected_outputs(args, resolved):
        if not path.exists() or (path.is_file() and path.stat().st_size == 0):
            missing.append(str(path))
            continue
        if baseline is not None and baseline.get(str(path)) == output_fingerprint(path):
            stale.append(str(path))
        if path.is_dir():
            continue
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                invalid.append(f"{path}: invalid JSON ({error})")
                continue
            if not isinstance(data, (dict, list)) or not data:
                invalid.append(f"{path}: expected a non-empty JSON object or array")
                continue
            if path.name == "journeys.json" and not (
                isinstance(data, dict) and isinstance(data.get("journeys"), list) and data["journeys"]
            ):
                invalid.append(f"{path}: expected a non-empty journeys array")
            elif path.name == "journeys.json":
                for journey_index, journey in enumerate(data["journeys"]):
                    steps = journey.get("steps") if isinstance(journey, dict) else None
                    if not isinstance(steps, list) or not steps:
                        invalid.append(f"{path}: journeys[{journey_index}] requires non-empty steps")
                        continue
                    for step_index, step in enumerate(steps):
                        if not isinstance(step, dict) or not all(
                            isinstance(step.get(field), str) and step[field]
                            for field in ("id", "name", "route")
                        ):
                            invalid.append(
                                f"{path}: journeys[{journey_index}].steps[{step_index}] "
                                "requires id, name, and route"
                            )
                            continue
                        if "actions" in step and not isinstance(step["actions"], list):
                            invalid.append(
                                f"{path}: journeys[{journey_index}].steps[{step_index}].actions "
                                "must be an array"
                            )
            elif path.name == "scenarios.json" and not (
                isinstance(data, dict) and isinstance(data.get("pages"), list) and data["pages"]
            ):
                invalid.append(f"{path}: expected a non-empty pages array (not routes)")
            elif path.name == "scenarios.json":
                for page_index, page in enumerate(data["pages"]):
                    scenarios = page.get("scenarios") if isinstance(page, dict) else None
                    if not isinstance(page, dict) or not isinstance(page.get("route"), str):
                        invalid.append(f"{path}: pages[{page_index}] requires a route")
                    if not isinstance(scenarios, list) or not scenarios:
                        invalid.append(f"{path}: pages[{page_index}] requires non-empty scenarios")
                    elif not any(
                        isinstance(scenario, dict)
                        and (scenario.get("default") is True or scenario.get("id") == "default")
                        for scenario in scenarios
                    ):
                        invalid.append(f"{path}: pages[{page_index}] requires a default scenario")
    if args.phase == "create-plan" and not missing:
        try:
            from creator_phase_tools import _validate_plan_artifacts
            _validate_plan_artifacts(resolved["artifacts"])
        except (OSError, ValueError, json.JSONDecodeError) as error:
            invalid.append(f"creator plan schema: {error}")
    return {
        "present": not missing and not invalid and not stale,
        "missing": missing,
        "invalid": invalid,
        "stale": stale,
    }


def artifact_completion_gate(
    args: argparse.Namespace,
    resolved: dict[str, Any],
    baseline: dict[str, Any],
):
    def after_turn(turn: int):
        state = validate_phase_artifacts(args, resolved, baseline)
        if state["present"]:
            return (f"Required outputs are present and valid after tool round {turn}.", True)
        return None

    return after_turn


def artifact_feedback(
    args: argparse.Namespace,
    resolved: dict[str, Any],
    baseline: dict[str, Any],
):
    def after_turn(_turn: int) -> str | None:
        state = validate_phase_artifacts(args, resolved, baseline)
        if state["present"]:
            return None
        problems = state["missing"] + state["invalid"] + [
            f"{path}: output is unchanged from before this phase; update it or record the inspection result"
            for path in state["stale"]
        ]
        if not problems:
            return None
        return (
            "Artifact validation feedback: " + "; ".join(problems[:8])
            + ". Correct the listed files using the bundled schemas, then continue. "
            "For scenarios.json the top-level collection is pages[], not routes[]; "
            "for journeys.json each step needs id, name, and route, and interactions "
            "belong in an actions[] array."
        )

    return after_turn


def estimate(args: argparse.Namespace, resolved: dict[str, Any]) -> dict[str, Any]:
    authority = creator_cost_authority(
        resolved["benchmark"], phase_bounds=CREATOR_OPENAI_PHASE_BOUNDS
    )
    authority.initialize()
    phase_spec = resolved["phase_spec"]
    reserved = authority.estimate(args.phase, resolved["model"])
    active = round(sum(authority.active_reservations.values()), 8)
    estimate_record = {
        "run_id": resolved["run_id"],
        "key": args.key,
        "phase": args.phase,
        "model": resolved["model"],
        "prompt_sha256": resolved["prompt_sha256"],
        "comparison_id": args.comparison_id,
        "input_tokens_bound": int(phase_spec["input_tokens_bound"]),
        "output_tokens_bound": int(phase_spec["output_tokens_bound"]),
        "max_turns": phase_spec.get("max_turns"),
        "reserved_estimate_usd": reserved,
        "cap_usd": CREATOR_OPENAI_CAP_USD,
        "completed_openai_usd": round(authority.completed_usd, 8),
        "active_reserved_openai_usd": active,
        "remaining_cap_after_estimate_usd": round(
            CREATOR_OPENAI_CAP_USD - authority.completed_usd - active - reserved, 8
        ),
        "model_invoked": False,
        "billing_source": "pinned-price-card-estimate",
    }
    return estimate_record


def creator_env_file() -> Path:
    return REPO_ROOT / ".env.creator"


def force_creator_langfuse_env(env_file: Path) -> None:
    """Override LANGFUSE_* values from the creator env file.

    verify_langfuse.load_env_file uses setdefault, so an evaluator project key
    already exported in the environment would otherwise win and send creator
    traces to the wrong Langfuse project. The creator file is authoritative.
    """
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("export "):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or not name.strip().replace("_", "").isalnum():
            continue
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name in {"LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"}:
            os.environ[name] = value


def load_paid_preflight(args: argparse.Namespace) -> None:
    # The creator always uses its own .env.creator (creator-project keys).
    # It never falls back to the evaluator's .env.local, so creator traces
    # cannot land in the evaluator Langfuse project.
    env_file = verify_langfuse.load_env_file(Path(args.env_file) if args.env_file else creator_env_file())
    if env_file is None:
        raise RuntimeError(
            f"Creator Langfuse env file not found at {creator_env_file()} or --env-file; "
            "refusing an untraced paid creator phase"
        )
    force_creator_langfuse_env(env_file)
    required = ("OPENAI_API_KEY", "LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("missing required environment variables: " + ", ".join(missing))
    verify_langfuse.check_openai_auth(os.environ["OPENAI_API_KEY"], os.environ.get("OPENAI_BASE_URL"))
    verify_langfuse.check_health(os.environ["LANGFUSE_HOST"])
    verify_langfuse.check_auth(
        os.environ["LANGFUSE_HOST"],
        os.environ["LANGFUSE_PUBLIC_KEY"],
        os.environ["LANGFUSE_SECRET_KEY"],
    )
    if env_file:
        os.environ.setdefault("LANGFUSE_BASE_URL", os.environ["LANGFUSE_HOST"])


def phase_contract(args: argparse.Namespace, resolved: dict[str, Any]) -> str:
    packet = build_context_packet(args, resolved, expected_outputs(args, resolved))
    resolved["context_packet"] = packet
    return json.dumps(packet, ensure_ascii=False, indent=2)


def write_phase_result(benchmark: Path, run_id: str, phase: dict[str, Any]) -> None:
    benchmark.mkdir(parents=True, exist_ok=True)
    path = benchmark / "creator-phase-results.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"run_id": run_id, **phase}, sort_keys=True) + "\n")


MANIFEST_PHASE_FIELDS = (
    "run_id", "attempt_id", "comparison_id", "phase", "status", "provider", "model",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "llm_cost_usd", "reserved_openai_usd", "turns_used", "tool_calls",
    "tool_failures", "error_categories", "recovery_actions", "validation",
    "expected_outputs_present", "expected_outputs_fresh",
    "langfuse_trace_url", "input_sha256",
)


def file_manifest_entry(path: Path, workspace: Path) -> dict[str, Any]:
    content = path.read_bytes()
    relative_path = path.relative_to(workspace).as_posix()
    return {
        "path": relative_path,
        "file_uri": path.resolve().as_uri(),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_recorded": not any(
            part in {"benchmark", "node_modules", ".git"} for part in Path(relative_path).parts
        ) and not path.name.endswith(".tmp"),
    }


def build_creator_artifact_manifest(
    args: argparse.Namespace,
    resolved: dict[str, Any],
    current_phase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a content-free but linkable audit manifest for Langfuse."""
    workspace: Path = resolved["workspace"]
    artifacts: Path = resolved["artifacts"]
    benchmark: Path = resolved["benchmark"]
    outputs = []
    for relative in manifest_artifact_paths(args, resolved):
        path = artifacts / relative
        if not path.is_file():
            continue
        outputs.append(file_manifest_entry(path, workspace))

    task_files = sorted(workspace.glob("create-*.md"))
    prompt_file = resolved.get("prompt_file")
    if prompt_file and prompt_file.is_file() and prompt_file not in task_files:
        task_files.append(prompt_file)
    input_tasks = [file_manifest_entry(path, workspace) for path in task_files if path.is_file()]
    phase_attempts: list[dict[str, Any]] = []
    result_path = benchmark / "creator-phase-results.jsonl"
    if result_path.is_file():
        for line in result_path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            phase_attempts.append({key: row[key] for key in MANIFEST_PHASE_FIELDS if key in row})
    if current_phase is not None and not any(
        row.get("run_id") == resolved["run_id"] and row.get("phase") == current_phase.get("phase")
        for row in phase_attempts
    ):
        phase_attempts.append({
            key: current_phase[key] for key in MANIFEST_PHASE_FIELDS if key in current_phase
        })

    try:
        ledger = json.loads((benchmark / CREATOR_LEDGER_FILENAME).read_text())
    except (OSError, json.JSONDecodeError):
        ledger = {}
    active_reservations = ledger.get("active_reservations", {})
    unknown_attempts = []
    attempts_dir = benchmark / "paid-attempts"
    for attempt_path in sorted(attempts_dir.glob("*.json")) if attempts_dir.is_dir() else ():
        try:
            attempt = json.loads(attempt_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if attempt.get("key") != args.key or attempt.get("state") != "interrupted-usage-unknown":
            continue
        reservation_id = attempt.get("reservation_id")
        unknown_attempts.append({
            "run_id": attempt.get("run_id"),
            "phase": attempt.get("phase"),
            "state": attempt.get("state"),
            "reserved_openai_usd": active_reservations.get(reservation_id),
        })

    has_paid_phase_content = bool(phase_attempts)
    return {
        "schema_version": 1,
        "audit_type": "prototype-creator-output-manifest",
        "component": "creator",
        "pipeline": "prototype-creator",
        "prototype_key": args.key,
        "jira_url": resolved.get("jira_url"),
        "source": {
            "type": "jira",
            "reference": args.key,
            "url": f"https://redhat.atlassian.net/browse/{args.key}",
            "source_revision": resolved.get("source_revision"),
        },
        "run_id": resolved["run_id"],
        "comparison_id": args.comparison_id,
        "privacy_mode": "full_raw" if has_paid_phase_content else "metadata_only",
        "trace_content": "full" if has_paid_phase_content else "metadata",
        "data_flow": {
            "input_tasks": input_tasks,
            "phase_attempts": phase_attempts,
            "outputs": outputs,
            "unknown_usage_attempts": unknown_attempts,
            "cost_ledger": {
                "cap_usd": ledger.get("cap_usd"),
                "completed_openai_usd": ledger.get("completed_openai_usd"),
                "active_reserved_openai_usd": round(sum(active_reservations.values()), 8),
                "billing_source": "pinned-price-card-estimate",
            },
        },
    }


def attempt_path_for(
    benchmark: Path, run_id: str, phase: str, attempt_id: str | None = None
) -> Path:
    attempt_identity = f"{run_id}:{phase}" + (f":{attempt_id}" if attempt_id else "")
    identity = hashlib.sha256(attempt_identity.encode("utf-8")).hexdigest()
    return benchmark / "paid-attempts" / f"{identity}.json"


APPROVAL_IDENTITY_FIELDS = (
    "run_id", "key", "phase", "model", "prompt_sha256", "comparison_id",
    "input_tokens_bound", "output_tokens_bound", "max_turns", "reserved_estimate_usd",
    "cap_usd", "billing_source",
)


def estimate_approval_matches(approved: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Match the approved work/cap while allowing spent-ledger totals to advance."""
    return bool(approved) and all(
        approved.get(field) == current.get(field) for field in APPROVAL_IDENTITY_FIELDS
    )


def begin_paid_attempt(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump({**record, "state": "started"}, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as error:
        raise RuntimeError(
            "This run ID and phase already has a paid attempt; do not retry it"
        ) from error


def update_paid_attempt(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def run_paid_phase(args: argparse.Namespace, resolved: dict[str, Any], estimate_record: dict[str, Any]) -> dict[str, Any]:
    attempt_path = attempt_path_for(
        resolved["benchmark"], resolved["run_id"], args.phase, getattr(args, "attempt_id", None)
    )
    if attempt_path.exists():
        raise RuntimeError("This run ID and phase already has a paid attempt; do not retry it")
    load_paid_preflight(args)
    estimate_path = resolved["benchmark"] / "creator-phase-estimates.json"
    try:
        saved = json.loads(estimate_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("No matching zero-spend estimate was found; run --estimate-only first") from error
    approval_key = f"{resolved['run_id']}:{args.phase}"
    approved = saved.get("estimates", {}).get(approval_key)
    if not estimate_approval_matches(approved, estimate_record):
        raise RuntimeError("Estimate inputs changed or do not match; re-run --estimate-only")
    if estimate_record["remaining_cap_after_estimate_usd"] < 0:
        raise RuntimeError("Creator estimate exceeds remaining $15 cap; blocked before model call")

    resolved["benchmark"].mkdir(parents=True, exist_ok=True)
    context_file = resolved["benchmark"] / "creator-context.json"
    if not context_file.exists():
        context_file.write_text(json.dumps({"key": args.key, "source": "approved-creator-task"}) + "\n")
    else:
        try:
            context = json.loads(context_file.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("creator-context.json is invalid") from error
        if context.get("key") != args.key:
            raise RuntimeError("creator-context.json belongs to a different ticket")

    authority = creator_cost_authority(
        resolved["benchmark"], phase_bounds=CREATOR_OPENAI_PHASE_BOUNDS
    )
    reservation = authority.reserve(args.phase, resolved["model"])
    if reservation is None:
        raise RuntimeError("Creator $15 budget cap blocked this phase before model invocation")

    run_started = time.monotonic()
    usage_journal_path = attempt_path.with_suffix(".usage.jsonl")
    trace_path = attempt_path.with_suffix(".trace.jsonl")
    output_baseline = snapshot_phase_outputs(args, resolved)
    prompt = phase_contract(args, resolved)
    if len(prompt.encode("utf-8")) > int(resolved["phase_spec"].get("max_prompt_bytes", 65536)):
        raise ValueError("Staged phase context exceeds its configured byte limit")

    def validate_outputs() -> dict[str, Any]:
        state = validate_phase_artifacts(args, resolved, output_baseline)
        if args.phase in {"create-generate", "create-refine"}:
            try:
                checked = _run_consistency_check(args, resolved)
                state["consistency_summary"] = checked["validation"].get("summary", {})
            except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                state["invalid"].append(f"consistency validation failed: {type(error).__name__}: {error}")
            refreshed = validate_phase_artifacts(args, resolved, output_baseline)
            refreshed["invalid"].extend(state["invalid"])
            if "consistency_summary" in state:
                refreshed["consistency_summary"] = state["consistency_summary"]
            refreshed["present"] = refreshed["present"] and not refreshed["invalid"]
            state = refreshed
        return state

    creator_tool_handler = make_tool_handler(args, resolved, output_baseline, validate_outputs)
    initial_payload = {
        "component": "creator",
        "pipeline": "prototype-creator",
        "prototype_key": args.key,
        "jira_url": resolved.get("jira_url"),
        "source_revision": resolved.get("source_revision"),
        "eval_run_id": resolved["run_id"],
        "provider": "openai",
        "model": resolved["model"],
        "experiment": "creator-paid-phases",
        "billing_source": "provider_usage_price_card_estimate",
        "privacy_mode": "full_raw",
        "trace_content": "full",
        "trace_context_path": str(creator_trace_context_path(
            resolved["benchmark"], resolved["run_id"]
        )),
        "artifacts_dir": str(resolved["artifacts"]),
        "benchmark": {
            "benchmark_name": args.benchmark_name,
            "comparison_id": args.comparison_id,
            "provider_model": f"openai/{resolved['model']}",
        },
    }
    phase_observation = None
    attempt_started = False
    try:
        with langfuse_trace.LivePipelineTrace(initial_payload) as live_trace:
            if not live_trace.client:
                authority.release(reservation, reason="Langfuse client unavailable before request")
                raise RuntimeError("Langfuse is unavailable; refusing an untraced paid creator phase")
            phase_observation = live_trace.start_phase(
                name=args.phase,
                model=resolved["model"],
                provider="openai",
                input_text=prompt,
            )
            if phase_observation is None:
                authority.release(reservation, reason="Langfuse phase observation could not be started")
                raise RuntimeError("Langfuse phase observation unavailable; blocked before model invocation")
            begin_paid_attempt(attempt_path, {
                "run_id": resolved["run_id"],
                "attempt_id": getattr(args, "attempt_id", None),
                "key": args.key,
                "phase": args.phase,
                "model": resolved["model"],
                "prompt_sha256": resolved["prompt_sha256"],
                "comparison_id": args.comparison_id,
                "reservation_id": reservation["id"],
                "usage_journal": str(usage_journal_path.relative_to(resolved["benchmark"])),
            })
            attempt_started = True
            result = run_agent(
                prompt,
                model=resolved["model"],
                project_dir=str(resolved["workspace"]),
                system_prompt=SYSTEM_PROMPT,
                reasoning_effort=resolved["phase_spec"]["reasoning_effort"],
                max_turns=resolved["phase_spec"].get("max_turns"),
                max_output_tokens=int(resolved["phase_spec"]["max_output_tokens_per_turn"]),
                max_input_tokens=int(resolved["phase_spec"]["input_tokens_bound"]),
                max_total_output_tokens=int(resolved["phase_spec"]["output_tokens_bound"]),
                max_total_cost_usd=float(reservation["reserved_usd"]),
                usage_journal_path=str(usage_journal_path),
                trace_path=str(trace_path),
                run_id=resolved["run_id"],
                attempt_id=getattr(args, "attempt_id", None),
                phase=args.phase,
                tool_definitions=tool_definitions(),
                tool_handler=creator_tool_handler,
                max_tool_calls=int(resolved["phase_spec"].get("max_tool_calls", 64)),
                max_run_seconds=int(resolved["phase_spec"].get("max_run_seconds", 3600)),
                max_total_tool_output_chars=int(resolved["phase_spec"].get("max_tool_output_chars", 64000)),
                skill_dir=str(SKILL_DIR),
                jira_context_file=str(context_file),
                jira_issue_key=args.key,
                benchmark_dir=str(resolved["benchmark"]),
                after_turn=artifact_completion_gate(args, resolved, output_baseline),
                turn_feedback=artifact_feedback(args, resolved, output_baseline),
                additional_allowed_roots=tuple(
                    str(path)
                    for path in (CONSISTENCY_CHECK_DIR, PROTOTYPE_EXPORT_DIR)
                    if path.is_dir()
                ),
                consistency_check_dir=str(CONSISTENCY_CHECK_DIR)
                if CONSISTENCY_CHECK_DIR.is_dir() else None,
                prototype_export_dir=str(PROTOTYPE_EXPORT_DIR)
                if PROTOTYPE_EXPORT_DIR.is_dir() else None,
            )
            usage = result.get("token_usage") or {}
            journal_summary = UsageJournal(
                usage_journal_path, run_id=resolved["run_id"],
                attempt_id=getattr(args, "attempt_id", None), phase=args.phase,
                model=resolved["model"],
            ).summary()
            if journal_summary["responses_recorded"] or journal_summary["usage_unknown"]:
                usage = journal_summary["token_usage"]
                result["usage_known"] = journal_summary["usage_known"]
                result["usage_unknown"] = journal_summary["usage_unknown"]
                result["unknown_request_ids"] = journal_summary["unknown_request_ids"]
            settlement_usage = {
                **usage,
                "known_usage_cost_usd": journal_summary["known_usage_cost_usd"],
                "cost_known": journal_summary["cost_known"],
            }
            usage_known = bool(result.get("usage_known", True)) and not bool(result.get("usage_unknown"))
            settlement = (
                authority.settle(reservation, settlement_usage)
                if usage_known else authority.settle_partial_unknown(
                    reservation, settlement_usage,
                    request_ids=list(result.get("unknown_request_ids") or []),
                )
            )
            artifact_state = validate_phase_artifacts(args, resolved, output_baseline)
            missing = artifact_state["missing"]
            input_bound_exceeded = int(usage.get("input_tokens", 0) or 0) > int(
                resolved["phase_spec"]["input_tokens_bound"]
            )
            output_bound_exceeded = int(usage.get("output_tokens", 0) or 0) > int(
                resolved["phase_spec"]["output_tokens_bound"]
            )
            reservation_exceeded = settlement["settled_usd"] > settlement["reserved_usd"]
            output_valid = (
                artifact_state["present"]
                and result.get("exit_code") == 0
                and usage_known
                and not input_bound_exceeded
                and not output_bound_exceeded
                and not reservation_exceeded
            )
            validation = (
                "required phase outputs present"
                if output_valid
                else "phase usage exceeded its reserved token/cost bound"
                if input_bound_exceeded or output_bound_exceeded or reservation_exceeded
                else result.get("provider_error")
                if result.get("provider_error")
                else "invalid required outputs: " + "; ".join(artifact_state["invalid"])
                if artifact_state["invalid"]
                else "required outputs were not refreshed in this phase: " + ", ".join(artifact_state["stale"])
                if artifact_state["stale"]
                else "missing required outputs: " + ", ".join(missing)
                if missing
                else result.get("output_text", "phase runner failed")[:300]
            )
            phase = {
                "attempt_id": getattr(args, "attempt_id", None),
                "phase": args.phase,
                "provider": "openai",
                "model": resolved["model"],
                "model_invoked": True,
                "status": "completed" if output_valid else "failed",
                "turns_used": int(result.get("turns_used", 0) or 0),
                "duration_ms": int((time.monotonic() - run_started) * 1000),
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cache_read_tokens": int(usage.get("cached_input_tokens", 0) or 0),
                "cache_write_tokens": int(usage.get("cache_write_tokens", 0) or 0),
                "llm_cost_usd": settlement["settled_usd"] if usage_known else None,
                "known_usage_cost_usd": settlement["settled_usd"],
                "usage_known": usage_known,
                "usage_unknown": not usage_known,
                "unknown_request_ids": result.get("unknown_request_ids", []),
                "unknown_reserved_openai_usd": settlement.get("retained_unknown_usage_usd", 0),
                "reserved_openai_usd": settlement["reserved_usd"],
                "completed_openai_usd": settlement["completed_openai_usd"],
                "validation": validation,
                "expected_outputs_present": not missing and not artifact_state["invalid"],
                "expected_outputs_fresh": not artifact_state["stale"],
                "input_token_bound_exceeded": input_bound_exceeded,
                "output_token_bound_exceeded": output_bound_exceeded,
                "reservation_exceeded": reservation_exceeded,
                "turn_limit_reached": bool(result.get("turn_limit_reached")),
                "input_token_bound_reached": bool(result.get("input_token_bound_reached")),
                "output_token_bound_reached": bool(result.get("output_token_bound_reached")),
                "cost_bound_exceeded": bool(result.get("cost_bound_exceeded")),
                "cost_bound_reached": bool(result.get("cost_bound_reached")),
                "artifact_gate_failure": result.get("artifact_gate_failure"),
                "artifact_gate_completed": result.get("artifact_gate_completed"),
                "tool_calls": int(result.get("tool_calls", 0) or 0),
                "tool_failures": int(result.get("tool_failures", 0) or 0),
                "tool_failure_diagnostics": result.get("tool_failure_diagnostics", []),
                "tool_failure_diagnostics_truncated": bool(
                    result.get("tool_failure_diagnostics_truncated")
                ),
                "error_categories": result.get("error_categories", []),
                "recovery_actions": result.get("recovery_actions", []),
                "provider_error_category": result.get("provider_error_category"),
                "provider_http_status": result.get("provider_http_status"),
                "input_sha256": resolved["prompt_sha256"],
                "comparison_id": args.comparison_id,
                "benchmark_name": args.benchmark_name,
            }
            try:
                recorded_trace_events = []
                if trace_path.is_file():
                    for line in trace_path.read_text(encoding="utf-8").splitlines():
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            recorded_trace_events.append(event)
            except OSError:
                recorded_trace_events = []
            trace_artifact_paths = phase_trace_artifact_paths(args, resolved)
            live_trace.finish_phase(
                phase_observation,
                phase=phase,
                output_text=result.get("output_text", ""),
                trace_events=recorded_trace_events,
                artifacts_dir=resolved["artifacts"],
                artifact_paths=trace_artifact_paths,
            )
            phase["artifact_manifest_logged"] = False
            try:
                live_trace.record_audit(
                    "creator-artifact-manifest",
                    build_creator_artifact_manifest(args, resolved, phase),
                    audit_type="prototype-creator-output-manifest",
                )
                live_trace.record_audit(
                    "creator-artifact-content",
                    {
                        "run_id": resolved["run_id"],
                        "artifacts": langfuse_trace.full_artifact_bundle(
                            resolved["artifacts"],
                            include_paths=trace_artifact_paths,
                        ),
                    },
                    audit_type="prototype-creator-full-artifacts",
                )
                phase["artifact_manifest_logged"] = bool(live_trace.client)
            except Exception:
                # Artifact indexing is useful but must not invalidate a paid
                # phase whose outputs and provider usage are already settled.
                phase["artifact_manifest_error_category"] = "langfuse_manifest_export"
            run_result = {
                "status": phase["status"],
                "exit_code": 0 if output_valid else 2,
                "cost_usd": settlement["settled_usd"] if usage_known else None,
                "known_usage_cost_usd": settlement["settled_usd"],
                "usage_known": usage_known,
                "usage_unknown": not usage_known,
                "billing_source": "provider_usage_price_card_estimate" if usage_known else "partial_provider_usage_unknown",
                "duration_s": round(time.monotonic() - run_started, 3),
                "token_usage": usage,
                "model": resolved["model"],
                "tool_calls": phase["tool_calls"],
                "tool_failures": phase["tool_failures"],
                "tool_failure_diagnostics": phase["tool_failure_diagnostics"],
                "error_categories": phase["error_categories"],
                "provider_error_category": phase["provider_error_category"],
                "provider_http_status": phase["provider_http_status"],
            }
            live_trace.finish({
                **initial_payload,
                "run_result": run_result,
                "phases": [phase],
                "metrics": {
                    "turns_used": phase["turns_used"],
                    "tool_calls": phase["tool_calls"],
                    "tool_failures": phase["tool_failures"],
                    "error_categories": phase["error_categories"],
                },
            }, artifact_paths=trace_artifact_paths)
            summary = live_trace.summary
    except Exception as error:
        # A transport error after request submission may still be billed. Keep
        # only an unresolved in-flight request reserved; journaled responses
        # are settled even if the caller fails after receiving them.
        journal_summary = UsageJournal(
            usage_journal_path, run_id=resolved["run_id"],
            attempt_id=getattr(args, "attempt_id", None), phase=args.phase,
            model=resolved["model"],
        ).summary()
        if reservation["id"] in authority.active_reservations:
            if journal_summary["usage_unknown"]:
                authority.settle_partial_unknown(
                    reservation, {
                        **journal_summary["token_usage"],
                        "known_usage_cost_usd": journal_summary["known_usage_cost_usd"],
                        "cost_known": journal_summary["cost_known"],
                    },
                    request_ids=journal_summary["unknown_request_ids"],
                )
            elif journal_summary["responses_recorded"]:
                authority.settle(reservation, {
                    **journal_summary["token_usage"],
                    "known_usage_cost_usd": journal_summary["known_usage_cost_usd"],
                    "cost_known": journal_summary["cost_known"],
                })
            elif not attempt_started:
                authority.release(reservation, reason="failed before paid request attempt started")
            else:
                authority.release(reservation, reason="no provider request was journaled")
        if attempt_started:
            update_paid_attempt(attempt_path, {
                "run_id": resolved["run_id"],
                "attempt_id": getattr(args, "attempt_id", None),
                "key": args.key,
                "phase": args.phase,
                "model": resolved["model"],
                "prompt_sha256": resolved["prompt_sha256"],
                "comparison_id": args.comparison_id,
                "reservation_id": reservation["id"],
                "state": "interrupted-usage-unknown" if journal_summary["usage_unknown"] else "failed",
                "known_usage": journal_summary["token_usage"],
                "usage_known": journal_summary["usage_known"],
                "unknown_request_ids": journal_summary["unknown_request_ids"],
                "error_category": langfuse_trace.error_category(str(error)),
            })
        raise

    phase["langfuse_trace_url"] = summary.get("langfuse_trace_url", "")
    phase["langfuse_logged"] = bool(summary.get("logged"))
    if not phase["langfuse_logged"]:
        phase["status"] = "failed"
        phase["validation"] = "paid phase completed but Langfuse export was not confirmed; do not retry"
    update_paid_attempt(attempt_path, {
        "run_id": resolved["run_id"],
        "attempt_id": getattr(args, "attempt_id", None),
        "key": args.key,
        "phase": args.phase,
        "model": resolved["model"],
        "prompt_sha256": resolved["prompt_sha256"],
        "comparison_id": args.comparison_id,
        "reservation_id": reservation["id"],
        "state": phase["status"],
        "input_tokens": phase["input_tokens"],
        "output_tokens": phase["output_tokens"],
        "llm_cost_usd": phase["llm_cost_usd"],
        "known_usage_cost_usd": phase["known_usage_cost_usd"],
        "usage_known": phase["usage_known"],
        "usage_unknown": phase["usage_unknown"],
        "unknown_request_ids": phase["unknown_request_ids"],
        "turns_used": phase["turns_used"],
        "tool_calls": phase["tool_calls"],
        "tool_failures": phase["tool_failures"],
        "tool_failure_diagnostics": phase["tool_failure_diagnostics"],
        "tool_failure_diagnostics_truncated": phase["tool_failure_diagnostics_truncated"],
        "error_categories": phase["error_categories"],
        "provider_error_category": phase["provider_error_category"],
        "provider_http_status": phase["provider_http_status"],
        "validation": phase["validation"],
        "artifact_manifest_logged": phase.get("artifact_manifest_logged", False),
        "artifact_manifest_error_category": phase.get("artifact_manifest_error_category"),
    })
    phase["billing_note"] = "OpenAI usage priced with the pinned price card; not an invoice"
    write_phase_result(resolved["benchmark"], resolved["run_id"], phase)
    return {"run_id": resolved["run_id"], **phase}


def main() -> int:
    args = parse_args()
    try:
        resolved = resolve_inputs(args)
        resolved["benchmark"].mkdir(parents=True, exist_ok=True)
        if args.approve_estimate and args.estimate_only:
            raise ValueError("--approve-estimate cannot be combined with --estimate-only")
        estimate_record = estimate(args, resolved)
        if estimate_record["remaining_cap_after_estimate_usd"] < 0:
            print(json.dumps({"status": "blocked", **estimate_record}, indent=2))
            return 2
        if args.estimate_only:
            estimate_path = resolved["benchmark"] / "creator-phase-estimates.json"
            try:
                saved = json.loads(estimate_path.read_text())
            except (OSError, json.JSONDecodeError):
                saved = {"estimates": {}}
            saved.setdefault("estimates", {})[
                f"{resolved['run_id']}:{args.phase}"
            ] = estimate_record
            estimate_path.write_text(json.dumps(saved, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "ready", **estimate_record}, indent=2))
            return 0
        if not args.approve_estimate:
            raise ValueError("Paid creator phase blocked. Run --estimate-only, review, then use --approve-estimate")
        result = run_paid_phase(args, resolved, estimate_record)
        print(json.dumps({"status": result["status"], **result}, indent=2))
        return 0 if result["status"] == "completed" else 2
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Creator phase blocked or failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
