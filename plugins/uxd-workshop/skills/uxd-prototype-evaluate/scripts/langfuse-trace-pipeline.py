#!/usr/bin/env python3
"""Run the evaluation pipeline with direct OpenAI API + Langfuse telemetry.

MLflow scripts remain in the repository for reference, but this is the active
pipeline path. Set EVAL_PROVIDER=anthropic to use the existing Claude CLI path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]
sys.path.insert(0, str(SCRIPT_DIR))

import langfuse_trace  # noqa: E402
from extract_jira_context import extract_context  # noqa: E402
from jira_context import load_jira_context  # noqa: E402
from model_defaults import detect_platform, model_for, provider_for  # noqa: E402
from openai_api_agent import MAX_AGENT_TURNS  # noqa: E402
from openai_structured_journey import (  # noqa: E402
    build_journey_prompt,
    run_structured_journey,
)
from openai_structured_visual import build_visual_prompt, run_structured_visual  # noqa: E402
from openai_live_usability import build_live_usability_prompt, run_live_usability  # noqa: E402
from run_evaluator import run_deterministic_source  # noqa: E402


PHASE_TURN_LIMIT = 2
OPENAI_PHASES = (
    {
        "name": "eval-journey",
        "model_phase": "eval-journey",
        "procedure": "api-phases/eval-journey.md",
        "arguments": "Judge one x-ray pass from local screenshot and DOM evidence.",
        "required": (
            "extract-state.json",
            "evaluation-report.csv",
            "prototype-evidence.json",
        ),
        "outputs": ("journey-log.json", "evaluation-report.csv"),
        "runner": "structured",
        "turn_limit": 1,
    },
    {
        "name": "eval-consistency-visual",
        "model_phase": "eval-consistency",
        "procedure": "eval-consistency.md",
        "arguments": "Run visual mode only. Preserve the validated source-mode findings.",
        "required": ("consistency-report.json", "journey-log.json", "prototype-evidence.json"),
        "outputs": ("consistency-report.json",),
        "runner": "structured_visual",
        "turn_limit": 1,
    },
    {
        "name": "eval-usability",
        "model_phase": "eval-usability",
        "procedure": "eval-usability.md",
        "arguments": "Run Phase B once using the extracted personas and captured journey.",
        "required": ("extract-state.json", "journey-log.json", "evaluation-report.csv"),
        "outputs": ("persona-results.json", "journey-log.json", "evaluation-report.csv"),
        "runner": "live_browser",
        "turn_limit": 10,
    },
)


def parse_args():
    parser = argparse.ArgumentParser(description="Run eval pipeline with Langfuse telemetry")
    parser.add_argument("--key", required=True, help="Jira key, for example PROJ-298")
    parser.add_argument("--url", required=True, help="Running prototype URL")
    parser.add_argument("--model", default=None, help="Model override for the whole run")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--platform", choices=["api", "codex", "cursor", "anthropic"], default=None)
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--jira-context",
        required=True,
        help="JSON staged by the host Atlassian MCP before model execution",
    )
    parser.add_argument(
        "--benchmark-dir",
        default=None,
        help="Gitignored directory for traces; defaults to tmp/benchmarks/<key>",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate local paths and Jira context without invoking a model",
    )
    parser.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Run validated source consistency without invoking a model",
    )
    parser.add_argument(
        "--phase-plan-only",
        action="store_true",
        help="Write bounded phase packets after source checks without invoking a model",
    )
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--all-files", action="store_true")
    parser.add_argument("--iterate-flags", default="")
    parser.add_argument("--experiment-label", default="eval-iterate")
    parser.add_argument("--reasoning-effort", default="low", choices=["none", "low", "medium", "high", "xhigh", "max"])
    parser.add_argument(
        "--max-turns",
        type=int,
        choices=range(1, MAX_AGENT_TURNS + 1),
        default=MAX_AGENT_TURNS,
    )
    return parser.parse_args()


def build_prompt(
    key: str,
    url: str,
    workspace: str,
    flags: str,
    *,
    jira_context_file: str,
    benchmark_dir: str,
    consistency_report: str,
) -> str:
    extra = f"\nAdditional flags: {flags}" if flags else ""
    return (
        f"Run the bounded uxd-prototype-evaluate phases for Jira key {key}.\n"
        f"Prototype URL: {url}\n"
        f"Prototype workspace: {workspace}\n"
        f"Local evaluator skill: {SKILL_DIR}\n"
        f"Local consistency skill: {SKILL_DIR.parent / 'uxd-consistency-check'}\n"
        f"MCP-staged Jira context: {jira_context_file}\n"
        f"Validated source consistency report: {consistency_report}\n"
        f"Benchmark output directory: {benchmark_dir}\n"
        "Each model invocation receives one inlined phase procedure and declared inputs. "
        "Use only those exact local paths. Do not discover, install, or inspect skills in "
        "home directories, .claude, .cursor plugin caches, or marketplace caches. "
        "Do not look up credentials or call Jira; the validated MCP context is authoritative. "
        "Source consistency is already complete and must not be rerun. Write artifacts under "
        f".artifacts/{key}/eval/, and finish with a concise summary of results."
        f"{extra}"
    )


def build_phase_packet(
    spec: dict[str, Any],
    *,
    key: str,
    url: str,
    workspace: str,
    jira_context_file: str,
) -> dict[str, Any]:
    """Describe one phase using only its declared inputs and outputs."""
    artifacts_dir = Path(workspace).resolve() / ".artifacts" / key / "eval"
    inputs = []
    for name in spec["required"]:
        path = Path(jira_context_file).resolve() if name == "jira_context" else artifacts_dir / name
        inputs.append({"name": name, "path": str(path)})
    return {
        "phase": spec["name"],
        "key": key,
        "prototype_url": url,
        "workspace": str(Path(workspace).resolve()),
        "artifacts_dir": str(artifacts_dir),
        "required_inputs": inputs,
        "expected_outputs": [str(artifacts_dir / name) for name in spec["outputs"]],
        "instruction": spec["arguments"],
    }


def build_phase_prompt(spec: dict[str, Any], packet: dict[str, Any]) -> str:
    """Inline exactly one phase procedure so discovery cannot consume a turn."""
    if spec.get("runner") == "structured":
        return build_journey_prompt(packet)
    if spec.get("runner") == "structured_visual":
        return build_visual_prompt(packet)
    if spec.get("runner") == "live_browser":
        return build_live_usability_prompt(packet)
    procedure_path = SKILL_DIR / "references" / "phases" / spec["procedure"]
    procedure = procedure_path.read_text()
    return (
        "Execute exactly one evaluator phase. Do not run another phase or read the "
        "top-level skill/orchestration documents. Use only the declared inputs, the "
        "prototype workspace when the procedure requires source, and bundled scripts.\n\n"
        f"PHASE PACKET\n{json.dumps(packet, indent=2)}\n\n"
        f"PHASE PROCEDURE ({spec['procedure']})\n{procedure}"
    )


def write_phase_plan(
    *,
    key: str,
    url: str,
    workspace: str,
    jira_context_file: str,
    benchmark_dir: str,
    platform: str,
    model_override: str | None,
) -> list[dict[str, Any]]:
    """Persist inspectable phase packets without invoking a provider."""
    packets_dir = Path(benchmark_dir) / "phase-packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    for stale_packet in packets_dir.glob("*.json"):
        stale_packet.unlink()
    plan = []
    for index, spec in enumerate(OPENAI_PHASES, start=1):
        packet = build_phase_packet(
            spec,
            key=key,
            url=url,
            workspace=workspace,
            jira_context_file=jira_context_file,
        )
        packet["model"] = model_override or model_for(spec["model_phase"], platform)
        packet["turn_limit"] = spec.get("turn_limit", PHASE_TURN_LIMIT)
        packet_path = packets_dir / f"{index:02d}-{spec['name']}.json"
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
        plan.append({**packet, "packet_file": str(packet_path)})
    return plan


def validate_phase_outputs(packet: dict[str, Any]) -> tuple[bool, str]:
    missing = [
        path
        for path in packet["expected_outputs"]
        if not Path(path).is_file() or Path(path).stat().st_size == 0
    ]
    if missing:
        return False, "missing outputs: " + ", ".join(missing)

    artifacts_dir = Path(packet["artifacts_dir"])
    phase = packet["phase"]
    if phase == "eval-extract":
        try:
            extract = json.loads((artifacts_dir / "extract-state.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            return False, f"extract-state.json is invalid: {error}"
        if not isinstance(extract.get("ac_list"), list) or not extract["ac_list"]:
            return False, "extract-state.json has no acceptance criteria"
        return True, "extract-state.json contains acceptance criteria"

    validators = {
        "eval-classify": ("validate-classify.js",),
        "eval-journey": ("validate-verdicts.js",),
        "eval-consistency-visual": ("validate-consistency.js",),
        "eval-usability": ("validate-phase-b-output.js",),
        "eval-report": ("validate-artifact-schemas.js", "validate-report-rendering.js"),
    }
    for script_name in validators.get(phase, ()):
        validation = subprocess.run(
            ["node", str(SCRIPT_DIR / script_name), str(artifacts_dir)],
            cwd=packet["workspace"],
            capture_output=True,
            text=True,
            check=False,
        )
        if validation.returncode != 0:
            detail = (validation.stdout + validation.stderr).strip()[-1000:]
            return False, f"{script_name} failed: {detail}"
    if phase == "eval-consistency-visual":
        try:
            consistency = json.loads((artifacts_dir / "consistency-report.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            return False, f"consistency-report.json is invalid: {error}"
        if (consistency.get("visual_mode") or {}).get("ran") is not True:
            return False, "consistency-report.json says visual_mode.ran is false"
    return True, "declared outputs passed phase validation"


def run_local_json_script(
    script_name: str, artifacts_dir: Path, *, benchmark_output: Path
) -> dict[str, Any]:
    """Run one packaged deterministic phase from the installed skill directory."""
    started = time.monotonic()
    command = ["node", str(SCRIPT_DIR / script_name), str(artifacts_dir), "--json"]
    completed = subprocess.run(
        command,
        cwd=str(artifacts_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    duration_s = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()[-2000:]
        raise ValueError(f"{script_name} failed: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"{script_name} returned invalid JSON: {error}") from error
    result["duration_s"] = duration_s
    result["script"] = str((SCRIPT_DIR / script_name).resolve())
    benchmark_output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def run_evidence_capture(
    url: str, artifacts_dir: Path, *, benchmark_output: Path
) -> dict[str, Any]:
    """Capture one deterministic screenshot and compact DOM snapshot locally."""
    started = time.monotonic()
    command = [
        "node",
        str(SCRIPT_DIR / "capture-prototype-evidence.js"),
        str(artifacts_dir),
        url,
        "--json",
    ]
    completed = subprocess.run(
        command,
        cwd=str(artifacts_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    duration_s = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()[-2000:]
        raise ValueError(f"capture-prototype-evidence.js failed: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"capture-prototype-evidence.js returned invalid JSON: {error}"
        ) from error
    result["duration_s"] = duration_s
    result["script"] = str((SCRIPT_DIR / "capture-prototype-evidence.js").resolve())
    benchmark_output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def run_openai_phases(
    *,
    key: str,
    url: str,
    workspace: str,
    jira_context_file: str,
    benchmark_dir: str,
    platform: str,
    model_override: str | None,
    reasoning_effort: str,
    max_turns: int,
    trace_dir: Path,
    structured_journey_runner: Callable[..., dict[str, Any]] = run_structured_journey,
    structured_visual_runner: Callable[..., dict[str, Any]] = run_structured_visual,
    live_usability_runner: Callable[..., dict[str, Any]] = run_live_usability,
    output_validator: Callable[[dict[str, Any]], tuple[bool, str]] = validate_phase_outputs,
    phase_tracer: Any | None = None,
) -> dict[str, Any]:
    """Run isolated judgment-based model phases under one shared turn budget."""
    started = time.monotonic()
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    phase_results = []
    telemetry_phases = []
    per_model: dict[str, dict[str, float | int]] = {}
    turns_used = 0
    failure = None
    packets_dir = Path(benchmark_dir) / "phase-packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    for stale_packet in packets_dir.glob("*.json"):
        stale_packet.unlink()

    for index, spec in enumerate(OPENAI_PHASES, start=1):
        remaining = max_turns - turns_used
        if remaining <= 0:
            failure = f"shared turn budget exhausted before {spec['name']}"
            break
        packet = build_phase_packet(
            spec,
            key=key,
            url=url,
            workspace=workspace,
            jira_context_file=jira_context_file,
        )
        missing_inputs = [
            item["path"] for item in packet["required_inputs"] if not Path(item["path"]).exists()
        ]
        if missing_inputs:
            failure = f"{spec['name']} missing required inputs: {', '.join(missing_inputs)}"
            break

        (packets_dir / f"{index:02d}-{spec['name']}.json").write_text(
            json.dumps(packet, indent=2) + "\n"
        )
        phase_model = model_override or model_for(spec["model_phase"], platform)
        phase_prompt = build_phase_prompt(spec, packet)
        phase_observation = (
            phase_tracer.start_phase(
                name=spec["name"], model=phase_model, input_text=phase_prompt
            )
            if phase_tracer
            else None
        )
        try:
            if spec.get("runner") == "structured":
                result = structured_journey_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=reasoning_effort,
                    trace_path=str(trace_dir / f"{index:02d}-{spec['name']}.jsonl"),
                )
            elif spec.get("runner") == "structured_visual":
                result = structured_visual_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=reasoning_effort,
                    trace_path=str(trace_dir / f"{index:02d}-{spec['name']}.jsonl"),
                )
            elif spec.get("runner") == "live_browser":
                result = live_usability_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    trace_path=str(trace_dir / f"{index:02d}-{spec['name']}.jsonl"),
                )
            else:
                raise ValueError(f"Unsupported model phase runner: {spec.get('runner')}")
        except (RuntimeError, ValueError) as error:
            result = {
                "exit_code": 2,
                "status": "failed",
                "duration_s": 0,
                "output_text": str(error),
                "turns_used": 0,
                "token_usage": {},
                "cost_usd": 0,
            }
        used = int(result.get("turns_used", 0) or 0)
        turns_used += used
        usage = result.get("token_usage") or {}
        for field in total_usage:
            total_usage[field] += int(usage.get(field, 0) or 0)
        model_totals = per_model.setdefault(
            phase_model,
            {"inputTokens": 0, "outputTokens": 0, "costUSD": 0.0},
        )
        model_totals["inputTokens"] += int(usage.get("input_tokens", 0) or 0)
        model_totals["outputTokens"] += int(usage.get("output_tokens", 0) or 0)
        model_totals["costUSD"] += float(result.get("cost_usd") or 0)
        valid, validation_detail = output_validator(packet)
        completed_at_limit = bool(result.get("turn_limit_reached") and valid)
        phase_status = (
            "completed"
            if valid and (result.get("exit_code") == 0 or completed_at_limit)
            else "failed"
        )
        phase_entry = {
            "phase": spec["name"],
            "model": phase_model,
            "provider": "openai",
            "status": phase_status,
            "turns_used": used,
            "duration_ms": int(float(result.get("duration_s", 0) or 0) * 1000),
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(usage.get("cached_input_tokens", 0) or 0),
            "llm_cost_usd": float(result.get("cost_usd") or 0),
            "validation": validation_detail,
        }
        telemetry_phases.append(phase_entry)
        phase_results.append({**phase_entry, "output_text": result.get("output_text", "")})
        if phase_tracer:
            phase_tracer.finish_phase(
                phase_observation,
                phase=phase_entry,
                output_text=result.get("output_text", ""),
            )
        if phase_status != "completed":
            failure = f"{spec['name']} failed: {validation_detail}"
            break

    total_cost = round(sum(float(item["costUSD"]) for item in per_model.values()), 8)
    status = "failed" if failure else "completed"
    return {
        "provider": "openai",
        "model": "phase-routed" if not model_override else model_override,
        "agent": "responses-api-phase-runner",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": 2 if failure else 0,
        "status": status,
        "output_text": failure or "All bounded model-based evaluator phases completed.",
        "token_usage": total_usage,
        "cost_usd": total_cost,
        "billing_source": "provider_estimate",
        "turns_used": turns_used,
        "max_turns": max_turns,
        "turn_limit_reached": bool(failure and "turn budget" in failure),
        "per_model_usage": per_model,
        "phase_results": phase_results,
        "phases": telemetry_phases,
    }


def resolve_local_inputs(
    *, key: str, workspace: str, jira_context_file: str, benchmark_dir: str | None
) -> dict[str, str]:
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace_path}")

    context_path = Path(jira_context_file).expanduser().resolve()
    load_jira_context(context_path, key)

    benchmark_path = (
        Path(benchmark_dir).expanduser().resolve()
        if benchmark_dir
        else (PROJECT_ROOT / "tmp" / "benchmarks" / key).resolve()
    )
    benchmark_path.mkdir(parents=True, exist_ok=True)
    if not (benchmark_path == (PROJECT_ROOT / "tmp").resolve() or (PROJECT_ROOT / "tmp").resolve() in benchmark_path.parents):
        raise ValueError("Benchmark directory must be inside the repository tmp/ directory")
    if not (context_path == benchmark_path or benchmark_path in context_path.parents):
        raise ValueError("Jira context must be stored inside the benchmark directory")

    return {
        "workspace": str(workspace_path),
        "jira_context_file": str(context_path),
        "benchmark_dir": str(benchmark_path),
    }


def normalize_prototype_url(url: str) -> str:
    """Accept a URL copied from chat when Markdown link syntax is included."""
    match = re.fullmatch(r"\[(https?://[^\]]+)\]\(https?://[^)]+\)", url.strip())
    return match.group(1) if match else url.strip()


def run_anthropic(prompt: str, model: str, project_dir: str, trace_path: Path) -> dict:
    """Compatibility path for designers who still use Anthropic models."""
    command = ["claude", "--print", "--model", model, "--output-format", "stream-json", "--verbose"]
    started = time.monotonic()
    proc = subprocess.run(command, input=prompt, cwd=project_dir, capture_output=True, text=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(proc.stdout)
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    cost = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            cost = event.get("total_cost_usd")
            usage.update({
                "input_tokens": event.get("usage", {}).get("input_tokens", 0),
                "output_tokens": event.get("usage", {}).get("output_tokens", 0),
            })
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return {
        "provider": "anthropic",
        "model": model,
        "agent": "claude-cli",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": proc.returncode,
        "token_usage": usage,
        "cost_usd": cost,
        "billing_source": "provider_reported" if cost is not None else "unavailable",
    }


def main() -> int:
    args = parse_args()
    platform = args.platform or detect_platform()
    provider = args.provider or os.environ.get("EVAL_PROVIDER") or provider_for(platform)
    model_override = args.model or os.environ.get("EVAL_MODEL")
    model = model_override or (
        model_for("eval-journey", platform) if provider == "anthropic" else "phase-routed"
    )
    try:
        local_inputs = resolve_local_inputs(
            key=args.key,
            workspace=args.workspace,
            jira_context_file=args.jira_context,
            benchmark_dir=args.benchmark_dir,
        )
    except ValueError as error:
        print(f"Preflight failed: {error}", file=sys.stderr)
        return 2

    if args.preflight_only:
        print(json.dumps({
            "status": "ready",
            "mode": "deterministic-preflight",
            "key": args.key,
            "skill_dir": str(SKILL_DIR),
            "max_turns": args.max_turns,
            **local_inputs,
        }, indent=2))
        return 0

    try:
        deterministic_result = run_deterministic_source(
            key=args.key,
            workspace=local_inputs["workspace"],
            jira_context_file=local_inputs["jira_context_file"],
            benchmark_dir=local_inputs["benchmark_dir"],
            base_ref=args.base_ref,
            all_files=args.all_files,
        )
    except ValueError as error:
        print(f"Deterministic source evaluation failed: {error}", file=sys.stderr)
        return 2
    if deterministic_result.get("status") != "completed":
        print(json.dumps(deterministic_result, indent=2), file=sys.stderr)
        return 2
    if args.deterministic_only:
        print(json.dumps({
            "status": "completed",
            "mode": "deterministic-only",
            "key": args.key,
            "model_invoked": False,
            "result": deterministic_result,
        }, indent=2))
        return 0

    extract_started = time.monotonic()
    try:
        deterministic_extract = extract_context(
            key=args.key,
            context_file=Path(local_inputs["jira_context_file"]),
            workspace=Path(local_inputs["workspace"]),
            artifacts_dir=(
                Path(local_inputs["workspace"])
                / ".artifacts"
                / args.key
                / "eval"
            ),
        )
    except (OSError, ValueError) as error:
        print(f"Deterministic Jira extraction failed: {error}", file=sys.stderr)
        return 2
    deterministic_extract["duration_s"] = round(time.monotonic() - extract_started, 3)
    (Path(local_inputs["benchmark_dir"]) / "deterministic-extract-result.json").write_text(
        json.dumps(deterministic_extract, indent=2) + "\n"
    )

    artifacts_dir = Path(local_inputs["workspace"]) / ".artifacts" / args.key / "eval"
    try:
        deterministic_classification = run_local_json_script(
            "run-classification.js",
            artifacts_dir,
            benchmark_output=(
                Path(local_inputs["benchmark_dir"])
                / "deterministic-classification-result.json"
            ),
        )
    except ValueError as error:
        print(f"Deterministic classification failed: {error}", file=sys.stderr)
        return 2

    url = normalize_prototype_url(args.url)
    deterministic_evidence = None
    if provider == "openai" or args.phase_plan_only:
        try:
            deterministic_evidence = run_evidence_capture(
                url,
                artifacts_dir,
                benchmark_output=(
                    Path(local_inputs["benchmark_dir"])
                    / "deterministic-evidence-result.json"
                ),
            )
        except ValueError as error:
            print(f"Deterministic prototype evidence capture failed: {error}", file=sys.stderr)
            return 2

    if args.phase_plan_only:
        plan = write_phase_plan(
            key=args.key,
            url=url,
            workspace=local_inputs["workspace"],
            jira_context_file=local_inputs["jira_context_file"],
            benchmark_dir=local_inputs["benchmark_dir"],
            platform=platform,
            model_override=model_override,
        )
        print(json.dumps({
            "status": "ready",
            "mode": "bounded-phase-plan",
            "model_invoked": False,
            "shared_turn_limit": args.max_turns,
            "deterministic_evidence": deterministic_evidence,
            "phases": plan,
        }, indent=2))
        return 0

    if provider == "openai" and "--no-fix" not in args.iterate_flags.split():
        print(
            "The bounded OpenAI runner currently requires --no-fix. "
            "Pass --iterate-flags='--no-fix --max-iterations=1'.",
            file=sys.stderr,
        )
        return 2
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. Export a replacement key in this shell "
            "before running the OpenAI pipeline.",
            file=sys.stderr,
        )
        return 2
    workspace = local_inputs["workspace"]
    prompt = build_prompt(
        args.key,
        url,
        workspace,
        args.iterate_flags,
        jira_context_file=local_inputs["jira_context_file"],
        benchmark_dir=local_inputs["benchmark_dir"],
        consistency_report=deterministic_result["consistency_report"],
    )
    trace_dir = Path(local_inputs["benchmark_dir"]) / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    trace_path = trace_dir / "responses.jsonl"
    eval_run_id = langfuse_trace.make_eval_run_id(args.key)
    initial_payload = {
        "prototype_key": args.key,
        "eval_run_id": eval_run_id,
        "experiment": args.experiment_label,
        "invocation": platform,
        "provider": provider,
        "model": model,
        "billing_source": "pending",
        "iterate_flags": args.iterate_flags,
        "prompt": prompt,
        "deterministic_source": deterministic_result,
        "deterministic_extract": deterministic_extract,
        "deterministic_classification": deterministic_classification,
        "deterministic_evidence": deterministic_evidence,
    }
    with langfuse_trace.LivePipelineTrace(initial_payload) as live_trace:
        started = time.monotonic()
        try:
            if provider == "openai":
                result = run_openai_phases(
                    key=args.key,
                    url=url,
                    workspace=workspace,
                    jira_context_file=local_inputs["jira_context_file"],
                    benchmark_dir=local_inputs["benchmark_dir"],
                    platform=platform,
                    model_override=model_override,
                    reasoning_effort=args.reasoning_effort,
                    max_turns=args.max_turns,
                    trace_dir=trace_dir,
                    phase_tracer=live_trace,
                )
            else:
                result = run_anthropic(prompt, model, workspace, trace_path)
        except (RuntimeError, ValueError) as error:
            result = {
                "provider": provider,
                "model": model,
                "agent": "responses-api" if provider == "openai" else "claude-cli",
                "duration_s": round(time.monotonic() - started, 1),
                "exit_code": 2,
                "output_text": langfuse_trace.redact_text(str(error), 1000),
                "token_usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "cost_usd": 0,
                "billing_source": "unavailable",
                "status": "failed",
            }

        deterministic_report = None
        if result.get("exit_code") == 0:
            report_started = time.monotonic()
            try:
                deterministic_report = run_local_json_script(
                    "run-report.js",
                    artifacts_dir,
                    benchmark_output=(
                        Path(local_inputs["benchmark_dir"])
                        / "deterministic-report-result.json"
                    ),
                )
                report_phase = {
                    "phase": "eval-report",
                    "model": None,
                    "provider": "local",
                    "status": "completed",
                    "turns_used": 0,
                    "duration_ms": int(
                        float(deterministic_report.get("duration_s", 0)) * 1000
                    ),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "llm_cost_usd": 0,
                    "validation": (
                        f"{deterministic_report.get('validation_pass_count', 0)} "
                        "rendering checks passed"
                    ),
                }
                result.setdefault("phases", []).append(report_phase)
                result.setdefault("phase_results", []).append(report_phase)
                result["output_text"] = (
                    f"{result.get('output_text', '').rstrip()} "
                    "Deterministic report rendering completed."
                ).strip()
            except ValueError as error:
                report_phase = {
                    "phase": "eval-report",
                    "model": None,
                    "provider": "local",
                    "status": "failed",
                    "turns_used": 0,
                    "duration_ms": int((time.monotonic() - report_started) * 1000),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "llm_cost_usd": 0,
                    "validation": str(error),
                }
                result.setdefault("phases", []).append(report_phase)
                result.setdefault("phase_results", []).append(report_phase)
                result["exit_code"] = 2
                result["status"] = "failed"
                result["output_text"] = f"Deterministic report rendering failed: {error}"

        result["status"] = langfuse_trace.pipeline_run_status(result)
        usage = result.get("token_usage", {})
        stdout_lines = trace_path.read_text().splitlines() if trace_path.is_file() else []
        artifact_phases = langfuse_trace.build_pipeline_phases(
            artifacts_dir,
            result,
            stdout_lines=stdout_lines,
        )
        phases = [
            {
                "phase": "eval-consistency-source",
                "model": None,
                "llm_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": int(float(deterministic_result.get("duration_s", 0)) * 1000),
                "status": "completed",
            },
            {
                "phase": "uxd-consistency-check",
                "model": None,
                "llm_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": int(float(deterministic_result.get("duration_s", 0)) * 1000),
                "status": "completed",
            },
            {
                "phase": "eval-extract",
                "model": None,
                "llm_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": int(float(deterministic_extract.get("duration_s", 0)) * 1000),
                "status": "completed",
                "acceptance_criteria": deterministic_extract.get("acceptance_criteria"),
                "changed_files": deterministic_extract.get("changed_files"),
            },
            {
                "phase": "eval-classify",
                "model": None,
                "provider": "local",
                "llm_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": int(
                    float(deterministic_classification.get("duration_s", 0)) * 1000
                ),
                "status": "completed",
                "criteria_count": deterministic_classification.get("criteria_count"),
                "tier_counts": deterministic_classification.get("tier_counts"),
            },
            *[dict(phase) for phase in result.get("phases") or []],
        ]
        phase_by_name = {phase.get("phase"): phase for phase in phases}
        for artifact_phase in artifact_phases:
            existing = phase_by_name.get(artifact_phase.get("phase"))
            if existing is None:
                phases.append(artifact_phase)
                phase_by_name[artifact_phase.get("phase")] = artifact_phase
                continue
            for field, value in artifact_phase.items():
                if value is not None and field not in existing:
                    existing[field] = value
        if not phases:
            phases = [{
                "phase": "uxd-prototype-evaluate",
                "model": model,
                "provider": provider,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "llm_cost_usd": result.get("cost_usd") or 0,
                "status": result["status"],
            }]
        payload = {
            **initial_payload,
            "billing_source": result.get("billing_source"),
            "run_result": result,
            "deterministic_report": deterministic_report,
            "phases": phases,
        }
        live_trace.finish(payload)
    summary = live_trace.summary
    print(json.dumps({**result, "eval_run_id": eval_run_id, **summary}, indent=2))
    return 0 if result.get("exit_code") == 0 else result.get("exit_code", 1)


if __name__ == "__main__":
    sys.exit(main())
