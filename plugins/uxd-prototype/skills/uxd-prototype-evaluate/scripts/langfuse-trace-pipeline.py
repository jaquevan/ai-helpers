#!/usr/bin/env python3
"""Run the evaluation pipeline with direct OpenAI API + Langfuse telemetry.

This is the active pipeline path. Set EVAL_PROVIDER=anthropic to use the
existing Claude CLI path.
"""

from __future__ import annotations

import argparse
import importlib.util
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
from tracing_contract import phase_record, write_session_result, save_estimate, require_estimate, validate_session_mode
from model_defaults import detect_platform, model_for, provider_for  # noqa: E402
from model_routing import route_for  # noqa: E402
from openai_api_agent import MAX_AGENT_TURNS  # noqa: E402
from usage_journal import UsageJournal  # noqa: E402
from openai_bounded_fix import run_bounded_fix  # noqa: E402
from openai_structured_journey import (  # noqa: E402
    build_journey_prompt,
    run_structured_journey,
)
from openai_structured_visual import build_visual_prompt, run_structured_visual  # noqa: E402
from openai_live_usability import build_live_usability_prompt, run_live_usability  # noqa: E402
from openai_structured_heuristic import build_heuristic_prompt, run_structured_heuristic  # noqa: E402
from judge_manifests import data_flow_manifest, report_quality_manifest  # noqa: E402
from run_evaluator import run_deterministic_source  # noqa: E402


VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_langfuse", SCRIPT_DIR / "verify-langfuse.py"
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
verify_langfuse = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verify_langfuse)


PHASE_TURN_LIMIT = 4
PIPELINE_MAX_TURNS = 30
OPENAI_PHASES = (
    {
        "name": "eval-journey",
        "procedure": "api-phases/eval-journey.md",
        "arguments": "Judge one x-ray pass from local screenshot and DOM evidence.",
        "required": (
            "brief.json",
            "evaluation.json",
            "evidence.json",
            "actions.json",
            "state.json",
        ),
        "outputs": ("journey-log.json",),
        "runner": "structured",
        "turn_limit": 1,
    },
    {
        "name": "eval-fix",
        "procedure": "eval-fix.md",
        "arguments": (
            "Apply one minimal, suggestion-backed workspace fix pass. Limit to twelve model turns, "
            "eight changed workspace files, and no git push."
        ),
        "required": ("refinement-suggestions.json", "evaluation-report.csv", "extract-state.json"),
        "outputs": ("fix-log.json",),
        "runner": "bounded_fix",
        "turn_limit": 12,
        "max_file_edits": 8,
        "max_iterations": 1,
    },
    {
        "name": "eval-consistency-visual",
        "procedure": "eval-consistency.md",
        "arguments": "Run visual mode only. Preserve the validated source-mode findings.",
        "required": ("consistency-report.json", "journey-log.json", "prototype-evidence.json"),
        "outputs": ("consistency-report.json",),
        "runner": "structured_visual",
        "turn_limit": 1,
    },
    {
        "name": "eval-heuristic",
        "procedure": "eval-heuristic.md",
        "arguments": "Run the sibling heuristic skill in unattended default mode and preserve its unreviewed-draft labeling.",
        "required": ("consistency-report.json", "journey-log.json", "prototype-evidence.json"),
        "outputs": ("heuristic-evaluation.json", "heuristic-evaluation.md", "heuristic-evaluation.html"),
        "runner": "structured_heuristic",
        "turn_limit": 1,
    },
    {
        "name": "eval-usability",
        "procedure": "eval-usability.md",
        "arguments": "Run Phase B once using the extracted personas and captured journey.",
        "required": ("extract-state.json", "journey-log.json"),
        "outputs": ("persona-results.json", "journey-log.json"),
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
        "--estimate-only",
        action="store_true",
        help="Run complete zero-spend preflight and print bounded estimates",
    )
    parser.add_argument(
        "--personal-run",
        action="store_true",
        help="Use the designer path: skip benchmark canonical-state requirements",
    )
    parser.add_argument(
        "--approve-estimate",
        action="store_true",
        help="Required for any paid OpenAI benchmark execution after preflight",
    )
    parser.add_argument("--source-revision", default=None)
    parser.add_argument(
        "--personas",
        default="data-scientist+junior,data-scientist+senior",
        help="Two persona overlays; defaults to the standard designer pair",
    )
    parser.add_argument(
        "--canonical-state", action="append", default=[], metavar="CONDITION=PATH",
        help="Preflight states for legacy, optimized-cold, and optimized-warm",
    )
    parser.add_argument(
        "--condition-workspace", action="append", default=[], metavar="CONDITION=PATH",
        help="Disposable workspace that produced each program-preflight canonical state",
    )
    parser.add_argument("--warm-cache-root", default=None)
    parser.add_argument("--paired-cold-state", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument(
        "--trace-sanitized-artifacts", action="store_true",
        help="Opt in to sanitized structured artifact outputs; default is metadata_only",
    )
    parser.add_argument(
        "--trace-content", choices=("full", "sanitized", "metadata"), default=None,
        help="Content profile for Langfuse. Controlled benchmarks default to full content.",
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
    parser.add_argument("--no-fix", action="store_true", help="Exclude the paid eval-fix phase")
    parser.add_argument("--no-report", action="store_true", help="Skip full report rendering")
    parser.add_argument("--no-iterate", action="store_true", help="Do not enter any fix loop")
    parser.add_argument("--cold-run", action="store_true", help="Bypass both X-Ray cache restore paths")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--experiment-label", default="eval-iterate")
    parser.add_argument("--benchmark-name", default=None)
    parser.add_argument(
        "--comparison-id",
        default=None,
        help="Pair legacy and canonical traces for one quality comparison",
    )
    parser.add_argument(
        "--condition", choices=["calibration", "legacy", "optimized-cold", "optimized-warm"], default=None
    )
    parser.add_argument("--screenshot-mode", default=None)
    parser.add_argument("--artifact-mode", default=None)
    parser.add_argument("--csv-used", choices=["true", "false"], default=None)
    parser.add_argument("--reasoning-effort", default=None, choices=["none", "low", "medium", "high", "xhigh", "max"],
                        help="override per-phase routing effort")
    parser.add_argument(
        "--max-turns",
        type=int,
        choices=range(1, PIPELINE_MAX_TURNS + 1),
        default=PIPELINE_MAX_TURNS,
    )
    return parser.parse_args()


def run_step_zero(args: argparse.Namespace) -> dict[str, Any]:
    """Run shared $0 preflight before an estimate or paid benchmark execution."""
    required = ("source_revision", "personas")
    missing = [name.replace("_", "-") for name in required if not getattr(args, name)]
    if missing or not args.canonical_state:
        details = ", ".join("--" + name for name in missing)
        if not args.canonical_state:
            details = ", ".join(filter(None, (details, "--canonical-state")))
        raise ValueError("Step 0 requires " + details)
    preflight_args = argparse.Namespace(
        env_file=args.env_file,
        key=args.key,
        url=args.url,
        workspace=args.workspace,
        jira_context=args.jira_context,
        source_revision=args.source_revision,
        personas=args.personas,
        canonical_state=args.canonical_state,
        condition_workspace=args.condition_workspace,
        benchmark_name=args.benchmark_name,
    )
    preflight = verify_langfuse.run_preflight(preflight_args)
    return apply_fix_mode_to_estimate(preflight, no_fix=bool(getattr(args, "no_fix", False)))


def run_personal_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """Run the same safety checks for one designer run without benchmark state."""
    if importlib.util.find_spec("langfuse") is None:
        raise RuntimeError(
            "Langfuse Python package is required for personal runs; run "
            ".venv/bin/python -m pip install langfuse"
        )
    env_path = verify_langfuse.load_env_file(Path(args.env_file) if args.env_file else None)
    required = ("OPENAI_API_KEY", "LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")

    workspace = Path(args.workspace).expanduser().resolve()
    context = Path(args.jira_context).expanduser().resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Workspace directory does not exist: {workspace}")
    load_jira_context(context, args.key)
    personas = [persona.strip() for persona in args.personas.split(",") if persona.strip()]
    if len(personas) != 2 or len(set(personas)) != 2:
        raise RuntimeError("exactly two distinct personas are required")

    verify_langfuse.check_openai_auth(
        os.environ["OPENAI_API_KEY"], os.environ.get("OPENAI_BASE_URL")
    )
    host = os.environ["LANGFUSE_HOST"]
    verify_langfuse.check_health(host)
    verify_langfuse.check_auth(
        host, os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]
    )
    verify_langfuse.check_prototype_url(args.url)

    estimate = verify_langfuse.expected_openai_cost()
    if getattr(args, "no_fix", False):
        estimate = apply_fix_mode_to_estimate({"expected_cost": estimate}, no_fix=True)["expected_cost"]
    one_run = round(sum(item["openai_cost_usd"] for item in estimate["phases"]), 6)
    preflight = {
        "status": "ready",
        "mode": "personal",
        "model_invoked": False,
        "environment_file_loaded": bool(env_path),
        "jira_key": args.key,
        "prototype_url": args.url,
        "workspace": str(workspace),
        "personas": personas,
        "estimate": {
            "single_run_openai_cost_usd": one_run,
            "openai_cap_usd": langfuse_trace.OPENAI_CAP_USD,
            "phases": estimate["phases"],
        },
    }
    return apply_fix_mode_to_estimate(preflight, no_fix=bool(getattr(args, "no_fix", False)))


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
        "Write artifacts under "
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
    artifact_mode: str | None = None,
) -> dict[str, Any]:
    """Describe one phase using only its declared inputs and outputs."""
    artifacts_dir = Path(workspace).resolve() / ".artifacts" / key / "eval"
    inputs = []
    required = spec["required"]
    if spec["name"] == "eval-journey" and artifact_mode == "legacy-csv":
        required = (
            "evaluation-report.csv",
            "extract-state.json",
            "prototype-evidence.json",
        )
    for name in required:
        path = Path(jira_context_file).resolve() if name == "jira_context" else artifacts_dir / name
        inputs.append({"name": name, "path": str(path)})
    return {
        "phase": spec["name"],
        "key": key,
        "prototype_url": url,
        "workspace": str(Path(workspace).resolve()),
        "jira_context_file": str(Path(jira_context_file).resolve()),
        "artifact_mode": artifact_mode,
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
    if spec.get("runner") == "structured_heuristic":
        return build_heuristic_prompt(packet)
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


def selected_openai_phases(*, no_fix: bool = False) -> tuple[dict[str, Any], ...]:
    """Return the executable phase graph after applying the fix-mode gate."""
    if no_fix:
        return tuple(spec for spec in OPENAI_PHASES if spec["name"] != "eval-fix")
    return OPENAI_PHASES


def trace_content_policy(args: argparse.Namespace) -> str:
    """Require full Langfuse content for controlled benchmarks; keep personal runs opt-in."""
    controlled = bool(
        not getattr(args, "personal_run", False)
        and (
            getattr(args, "benchmark_name", None)
            or getattr(args, "comparison_id", None)
            or getattr(args, "condition", None)
        )
    )
    requested = getattr(args, "trace_content", None)
    if controlled:
        if requested not in (None, "full") or getattr(args, "trace_sanitized_artifacts", False):
            raise ValueError("Controlled benchmark runs require trace_content=full")
        return "full"
    if requested:
        return requested
    if getattr(args, "trace_sanitized_artifacts", False):
        return "sanitized"
    return "metadata"


def normalize_execution_flags(args: argparse.Namespace) -> None:
    """Make metadata flags effective runner controls and preserve their record."""
    flags = args.iterate_flags.split()
    args.no_fix = bool(args.no_fix or "--no-fix" in flags)
    args.no_report = bool(args.no_report or "--no-report" in flags)
    args.no_iterate = bool(args.no_iterate or "--no-iterate" in flags)
    args.cold_run = bool(args.cold_run or "--fresh" in flags or "--cold-run" in flags)
    max_flag = next(
        (item.split("=", 1)[1] for item in flags if item.startswith("--max-iterations=")),
        None,
    )
    if max_flag is not None:
        args.max_iterations = int(max_flag)
    if not 1 <= args.max_iterations <= 3:
        raise ValueError("--max-iterations must be between 1 and 3")
    if args.no_iterate:
        args.no_fix = True
    effective = list(flags)
    for flag, enabled in (
        ("--no-fix", args.no_fix),
        ("--no-report", args.no_report),
        ("--no-iterate", args.no_iterate),
        ("--fresh", args.cold_run),
    ):
        if enabled and flag not in effective:
            effective.append(flag)
    max_recorded = f"--max-iterations={args.max_iterations}"
    if not any(item.startswith("--max-iterations=") for item in effective):
        effective.append(max_recorded)
    args.iterate_flags = " ".join(effective)


def should_render_report(*, no_report: bool, exit_code: int) -> bool:
    """The report renderer is local, but --no-report must skip its execution."""
    return not no_report and exit_code in {0, 3}


def apply_fix_mode_to_estimate(preflight: dict[str, Any], *, no_fix: bool) -> dict[str, Any]:
    """Make the zero-spend estimate use the same paid-phase set as execution."""
    if not no_fix:
        return preflight
    estimate_key = "estimate" if isinstance(preflight.get("estimate"), dict) else "expected_cost"
    estimate = preflight.get(estimate_key)
    if not isinstance(estimate, dict) or not isinstance(estimate.get("phases"), list):
        raise ValueError("Preflight did not return a phase-level cost estimate")
    estimate["phases"] = [phase for phase in estimate["phases"] if phase.get("phase") != "eval-fix"]
    one_run = round(sum(float(phase.get("openai_cost_usd", phase.get("reserved_estimate_usd", 0)) or 0)
                        for phase in estimate["phases"]), 6)
    estimate["single_run_openai_cost_usd"] = one_run
    estimate["openai_cost_usd"] = one_run
    estimate["fix_mode"] = "no_fix"
    estimate["estimate_label"] = "bounded no-fix phase estimate"
    estimate["excluded_phases"] = ["eval-fix"]
    if isinstance(estimate.get("conditions"), dict):
        for name, repetitions in (("calibration", 1), ("legacy", 3), ("optimized-cold", 3)):
            if name in estimate["conditions"]:
                estimate["conditions"][name]["openai_cost_usd"] = round(one_run * repetitions, 6)
        if "optimized-warm" in estimate["conditions"]:
            estimate["conditions"]["optimized-warm"]["openai_cost_usd"] = 0.0
        estimate["program_openai_cost_usd"] = round(
            sum(float(value.get("openai_cost_usd", 0) or 0) for value in estimate["conditions"].values()),
            6,
        )
    preflight[estimate_key] = estimate
    return preflight


def write_phase_plan(
    *,
    key: str,
    url: str,
    workspace: str,
    jira_context_file: str,
    benchmark_dir: str,
    artifact_mode: str | None = None,
    no_fix: bool = False,
) -> list[dict[str, Any]]:
    """Persist inspectable phase packets without invoking a provider."""
    packets_dir = Path(benchmark_dir) / "phase-packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    for stale_packet in packets_dir.glob("*.json"):
        stale_packet.unlink()
    plan = []
    for index, spec in enumerate(selected_openai_phases(no_fix=no_fix), start=1):
        packet = build_phase_packet(
            spec,
            key=key,
            url=url,
            workspace=workspace,
            jira_context_file=jira_context_file,
            artifact_mode=artifact_mode,
        )
        packet["turn_limit"] = spec.get("turn_limit", PHASE_TURN_LIMIT)
        if "max_file_edits" in spec:
            packet["max_file_edits"] = spec["max_file_edits"]
        if "max_iterations" in spec:
            packet["max_iterations"] = spec["max_iterations"]
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
        "eval-fix": (),
        "eval-consistency-visual": ("validate-consistency.js",),
        "eval-heuristic": (),
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
    if phase == "eval-fix":
        try:
            fix_log = json.loads((artifacts_dir / "fix-log.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            return False, f"fix-log.json is invalid: {error}"
        if not isinstance(fix_log, list):
            return False, "fix-log.json must be a flat array"
    if phase == "eval-consistency-visual":
        try:
            consistency = json.loads((artifacts_dir / "consistency-report.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            return False, f"consistency-report.json is invalid: {error}"
        if (consistency.get("visual_mode") or {}).get("ran") is not True:
            return False, "consistency-report.json says visual_mode.ran is false"
    if phase == "eval-heuristic":
        try:
            heuristic = json.loads((artifacts_dir / "heuristic-evaluation.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            return False, f"heuristic-evaluation.json is invalid: {error}"
        if heuristic.get("source") != "uxd-research-heuristic-eval":
            return False, "heuristic-evaluation.json has an unexpected source"
        if heuristic.get("status") != "unreviewed-draft" or heuristic.get("defaults_assumed") is not True:
            return False, "heuristic evaluation must preserve unattended review labeling"
        for name in ("heuristic-evaluation.md", "heuristic-evaluation.html"):
            if "Unreviewed Draft" not in (artifacts_dir / name).read_text():
                return False, f"{name} is missing the unreviewed-draft disclosure"
    return True, "declared outputs passed phase validation"


def phase_outcome_metrics(phase: str, artifacts_dir: Path) -> dict[str, Any]:
    """Extract compact outcome metrics; never include finding text or reasoning."""
    metrics: dict[str, Any] = {
        "retries": 0,
        "fallbacks": 0,
        "recovery_actions": [],
        "confidence_available": False,
    }
    try:
        if phase == "eval-extract":
            extract = json.loads((artifacts_dir / "extract-state.json").read_text())
            metrics["phase_decisions"] = {
                "acceptance_criteria": len(extract.get("ac_list") or []),
                "persona_selection_method": (extract.get("persona_selection") or {}).get("method"),
                "decision_context_present": bool((extract.get("decision_context") or {}).get("has_decisions")),
            }
        elif phase in {"eval-consistency-visual", "eval-consistency-source"}:
            report = json.loads((artifacts_dir / "consistency-report.json").read_text())
            section = report.get("visual_mode" if phase.endswith("visual") else "source_mode") or {}
            findings = section.get("findings") or section.get("violations") or []
            verdict_counts: dict[str, int] = {}
            severity_counts: dict[str, int] = {}
            for finding in findings:
                for key, target in (("verdict", verdict_counts), ("severity", severity_counts)):
                    value = finding.get(key)
                    if value:
                        target[value] = target.get(value, 0) + 1
            metrics["finding_count"] = len(findings)
            metrics["decision_counts"] = {
                "verdict": verdict_counts,
                "severity": severity_counts,
            }
            input_metrics = report.get("visual_mode", {}).get("input_metrics") or {}
            if input_metrics:
                metrics["screenshot_count"] = int(input_metrics.get("screenshots_analyzed", 0) or 0)
                metrics["screenshot_bytes"] = int(input_metrics.get("input_bytes", 0) or 0)
        elif phase == "eval-heuristic":
            report = json.loads((artifacts_dir / "heuristic-evaluation.json").read_text())
            findings = report.get("findings") or []
            metrics["finding_count"] = len(findings)
            metrics["decision_counts"] = {
                "severity": {
                    severity: sum(item.get("suggested_severity") == severity for item in findings)
                    for severity in ("critical", "major", "minor", "cosmetic")
                },
                "agreement": {
                    agreement: sum(item.get("agreement") == agreement for item in findings)
                    for agreement in ("unanimous", "majority", "single")
                },
            }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return metrics


def run_local_json_script(
    script_name: str, artifacts_dir: Path, *, benchmark_output: Path,
    extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run one packaged deterministic phase from the installed skill directory."""
    started = time.monotonic()
    command = ["node", str(SCRIPT_DIR / script_name), str(artifacts_dir), *extra_args, "--json"]
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


def run_phase_b_canonical_sync(
    artifacts_dir: Path,
    *,
    provider: str,
    model: str,
    benchmark_output: Path,
) -> dict[str, Any]:
    """Validate and atomically merge paid phase outputs into canonical JSON."""
    started = time.monotonic()
    canonical_provider = "openai" if provider == "openai" else "anthropic-compatible"
    command = [
        "node",
        str(SCRIPT_DIR / "sync-phase-b-canonical.js"),
        str(artifacts_dir),
        "--provider",
        canonical_provider,
        "--model",
        model,
        "--json",
    ]
    completed = subprocess.run(
        command,
        cwd=str(artifacts_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()[-2000:]
        raise ValueError(f"sync-phase-b-canonical.js failed: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"sync-phase-b-canonical.js returned invalid JSON: {error}"
        ) from error
    result["duration_s"] = round(time.monotonic() - started, 3)
    result["script"] = str((SCRIPT_DIR / "sync-phase-b-canonical.js").resolve())
    benchmark_output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def write_evaluation_cost(artifacts_dir: Path, result: dict[str, Any], eval_run_id: str) -> dict[str, Any]:
    """Persist designer-readable per-phase provider estimates and usage splits."""
    phases = []
    for phase in result.get("phases") or []:
        phases.append({key: phase.get(key) for key in (
            "phase", "model", "provider", "model_invoked", "status", "input_tokens",
            "output_tokens", "cache_read_tokens", "cache_write_tokens", "llm_cost_usd",
        )})
    report = {
        "run_id": eval_run_id,
        "status": result.get("status", "unknown"),
        "provider": result.get("provider"),
        "billing_source": "provider_usage_price_card_estimate",
        "price_basis": "OpenAI standard short-context per-token rates; cache read/write rates applied separately",
        "pricing_reference": "https://developers.openai.com/api/docs/pricing",
        "invoice_reconciled": False,
        "total_estimated_usd": (
            float(result["cost_usd"]) if result.get("cost_usd") is not None else None
        ),
        "known_usage_estimated_usd": result.get("known_usage_cost_usd", result.get("cost_usd")),
        "usage_known": bool(result.get("usage_known", True)),
        "usage_unknown": bool(result.get("usage_unknown", False)),
        "total_tokens": int((result.get("token_usage") or {}).get("total_tokens", 0) or 0),
        "cached_input_tokens": int((result.get("token_usage") or {}).get("cached_input_tokens", 0) or 0),
        "cache_write_tokens": int((result.get("token_usage") or {}).get("cache_write_tokens", 0) or 0),
        "phases": phases,
        "excluded_costs": ["OpenCode session model billing"],
    }
    (Path(artifacts_dir) / "evaluation-cost.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def run_openai_phases(
    *,
    key: str,
    url: str,
    workspace: str,
    jira_context_file: str,
    benchmark_dir: str,
    platform: str,
    model_override: str | None,
    reasoning_effort: str | None,
    max_turns: int,
    trace_dir: Path,
    structured_journey_runner: Callable[..., dict[str, Any]] = run_structured_journey,
    structured_visual_runner: Callable[..., dict[str, Any]] = run_structured_visual,
    live_usability_runner: Callable[..., dict[str, Any]] = run_live_usability,
    structured_heuristic_runner: Callable[..., dict[str, Any]] = run_structured_heuristic,
    bounded_fix_runner: Callable[..., dict[str, Any]] = run_bounded_fix,
    output_validator: Callable[[dict[str, Any]], tuple[bool, str]] = validate_phase_outputs,
    phase_tracer: Any | None = None,
    cost_authority: langfuse_trace.OpenAICostAuthority | None = None,
    study_routing: bool = False,
    artifact_mode: str | None = None,
    no_fix: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run isolated judgment-based model phases under one shared turn budget."""
    started = time.monotonic()
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    phase_results = []
    telemetry_phases = []
    per_model: dict[str, dict[str, float | int]] = {}
    authority = cost_authority or langfuse_trace.OpenAICostAuthority(
        ledger_path=Path(benchmark_dir) / "openai-budget-ledger.json"
    )
    # This authority survives process boundaries. Report only spend settled by
    # this invocation, not the cumulative ledger amount from older runs.
    completed_before_run = authority.completed_usd
    turns_used = 0
    failure = None
    run_usage_unknown = False
    packets_dir = Path(benchmark_dir) / "phase-packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    for stale_packet in packets_dir.glob("*.json"):
        stale_packet.unlink()

    phase_packets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    prior_phase_outputs: set[str] = set()
    active_phases = selected_openai_phases(no_fix=no_fix)
    for spec in active_phases:
        packet = build_phase_packet(
            spec,
            key=key,
            url=url,
            workspace=workspace,
            jira_context_file=jira_context_file,
            artifact_mode=artifact_mode,
        )
        missing_static_inputs = [
            item["path"]
            for item in packet["required_inputs"]
            if item["name"] not in prior_phase_outputs and not Path(item["path"]).exists()
        ]
        if missing_static_inputs:
            raise ValueError(
                f"{spec['name']} missing required inputs: {', '.join(missing_static_inputs)}"
            )
        phase_packets.append((spec, packet))
        prior_phase_outputs.update(spec["outputs"])

    for index, (spec, packet) in enumerate(phase_packets, start=1):
        remaining = max_turns - turns_used
        if remaining <= 0:
            failure = f"shared turn budget exhausted before {spec['name']}"
            break
        missing_inputs = [
            item["path"] for item in packet["required_inputs"] if not Path(item["path"]).exists()
        ]
        if missing_inputs:
            failure = f"{spec['name']} missing required inputs: {', '.join(missing_inputs)}"
            break

        (packets_dir / f"{index:02d}-{spec['name']}.json").write_text(
            json.dumps(packet, indent=2) + "\n"
        )
        phase_route = route_for(
            spec["name"], platform, model_override, study=study_routing
        )
        phase_model = phase_route["model"]
        phase_reasoning_effort = reasoning_effort or phase_route["reasoning_effort"]
        phase_prompt = build_phase_prompt(spec, packet)
        attempt_id = f"{run_id or 'eval'}-{index:02d}-{spec['name']}-{time.time_ns()}"
        phase_trace_path = trace_dir / f"{index:02d}-{spec['name']}.jsonl"
        usage_journal_path = trace_dir / f"{index:02d}-{spec['name']}-usage.jsonl"
        local_fix_noop = spec.get("runner") == "bounded_fix" and json.loads(
            (Path(packet["artifacts_dir"]) / "refinement-suggestions.json").read_text()
        ) == []
        reservation = authority.reserve(spec["name"], phase_model)
        if reservation is None:
            phase_entry = {
                "phase": spec["name"], "model": phase_model, "provider": "openai",
                "status": "blocked", "turns_used": 0, "duration_ms": 0,
                "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                "llm_cost_usd": 0, "reserved_openai_usd": 0,
                "completed_openai_usd": authority.completed_usd,
                "error_category": "budget_cap", "recovery_actions": ["budget_stop"],
                "validation": "not called: $25 OpenAI cap would be exceeded",
            }
            telemetry_phases.append(phase_entry)
            phase_results.append(phase_entry)
            failure = f"OpenAI budget cap blocked before {spec['name']}"
            break
        phase_observation = (
            phase_tracer.start_phase(
                name=spec["name"], model=None if local_fix_noop else phase_model,
                provider="local" if local_fix_noop else None, input_text=phase_prompt
            )
            if phase_tracer
            else None
        )
        try:
            if spec.get("runner") == "structured":
                result = structured_journey_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=phase_reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    trace_path=str(phase_trace_path),
                    usage_journal_path=str(usage_journal_path), run_id=run_id,
                    attempt_id=attempt_id,
                )
            elif spec.get("runner") == "structured_visual":
                result = structured_visual_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=phase_reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    trace_path=str(phase_trace_path),
                    usage_journal_path=str(usage_journal_path), run_id=run_id,
                    attempt_id=attempt_id,
                )
            elif spec.get("runner") == "live_browser":
                result = live_usability_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=phase_reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    trace_path=str(phase_trace_path),
                    usage_journal_path=str(usage_journal_path), run_id=run_id,
                    attempt_id=attempt_id,
                )
            elif spec.get("runner") == "structured_heuristic":
                result = structured_heuristic_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=phase_reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    trace_path=str(phase_trace_path),
                    usage_journal_path=str(usage_journal_path), run_id=run_id,
                    attempt_id=attempt_id,
                )
            elif spec.get("runner") == "bounded_fix":
                fix_input_bound, fix_output_bound = langfuse_trace.OPENAI_PHASE_BOUNDS[spec["name"]]
                result = bounded_fix_runner(
                    packet,
                    model=phase_model,
                    reasoning_effort=phase_reasoning_effort,
                    max_turns=min(spec.get("turn_limit", PHASE_TURN_LIMIT), remaining),
                    max_file_edits=spec.get("max_file_edits", 8),
                    trace_path=str(phase_trace_path),
                    usage_journal_path=str(usage_journal_path), run_id=run_id,
                    attempt_id=attempt_id,
                    max_total_cost_usd=float(reservation["reserved_usd"]),
                    max_input_tokens=fix_input_bound,
                    max_total_output_tokens=fix_output_bound,
                )
            else:
                raise ValueError(f"Unsupported model phase runner: {spec.get('runner')}")
        except Exception as error:
            usage_snapshot = UsageJournal(
                usage_journal_path, run_id=run_id, attempt_id=attempt_id,
                phase=spec["name"], model=phase_model,
            ).summary()
            result = {
                "exit_code": 2,
                "status": "failed",
                "duration_s": 0,
                "output_text": str(error),
                "turns_used": 0,
                "token_usage": usage_snapshot["token_usage"],
                "usage_known": usage_snapshot["usage_known"],
                "usage_unknown": usage_snapshot["usage_unknown"],
                "unknown_request_ids": usage_snapshot["unknown_request_ids"],
                "cost_usd": None,
            }
        usage_snapshot = UsageJournal(
            usage_journal_path, run_id=run_id, attempt_id=attempt_id,
            phase=spec["name"], model=phase_model,
        ).summary()
        if usage_snapshot["responses_recorded"] or usage_snapshot["usage_unknown"]:
            result["token_usage"] = usage_snapshot["token_usage"]
            result["usage_known"] = usage_snapshot["usage_known"]
            result["usage_unknown"] = usage_snapshot["usage_unknown"]
            result["unknown_request_ids"] = usage_snapshot["unknown_request_ids"]
            result["known_usage_cost_usd"] = usage_snapshot["known_usage_cost_usd"]
            result["cost_known"] = usage_snapshot["cost_known"]
        else:
            # Injectable adapters can return aggregate usage without a local
            # journal. Let settlement price that aggregate conservatively;
            # canonical production runners always provide per-response journals.
            result["known_usage_cost_usd"] = None
            result["cost_known"] = False
        used = int(result.get("turns_used", 0) or 0)
        turns_used += used
        usage = result.get("token_usage") or {}
        usage_known = bool(result.get("usage_known", True)) and not bool(result.get("usage_unknown"))
        run_usage_unknown = run_usage_unknown or not usage_known
        settlement_usage = {
            **usage,
            "known_usage_cost_usd": result["known_usage_cost_usd"],
            "cost_known": result["cost_known"],
        }
        settlement = (
            authority.settle(reservation, settlement_usage)
            if usage_known
            else authority.settle_partial_unknown(
                reservation, settlement_usage,
                request_ids=list(result.get("unknown_request_ids") or []),
            )
        )
        provider_cost = result.get("cost_usd")
        result["known_usage_cost_usd"] = settlement["settled_usd"]
        result["cost_usd"] = settlement["settled_usd"] if usage_known else None
        for field in total_usage:
            total_usage[field] += int(usage.get(field, 0) or 0)
        model_totals = per_model.setdefault(
            phase_model,
            {"inputTokens": 0, "outputTokens": 0},
        )
        model_totals["inputTokens"] += int(usage.get("input_tokens", 0) or 0)
        model_totals["outputTokens"] += int(usage.get("output_tokens", 0) or 0)
        valid, validation_detail = output_validator(packet)
        if result.get("exit_code") != 0 and result.get("output_text"):
            validation_detail = f"{validation_detail}; model error: {result['output_text']}"
        input_bound, output_bound = langfuse_trace.OPENAI_PHASE_BOUNDS.get(spec["name"], (None, None))
        phase_bounds_exceeded = (
            (input_bound is not None and int(usage.get("input_tokens", 0) or 0) > input_bound)
            or (output_bound is not None and int(usage.get("output_tokens", 0) or 0) > output_bound)
        )
        phase_status = (
            "completed"
            if valid and result.get("exit_code") == 0 and usage_known and not phase_bounds_exceeded
            else "failed"
        )
        phase_entry = {
            "phase": spec["name"],
            "attempt_id": attempt_id,
            "run_id": run_id,
            "model": phase_model if result.get("model_invoked") is not False else None,
            "provider": "openai" if result.get("model_invoked") is not False else "local",
            "model_invoked": result.get("model_invoked") is not False,
            "status": phase_status,
            "turns_used": used,
            "duration_ms": int(float(result.get("duration_s", 0) or 0) * 1000),
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(usage.get("cached_input_tokens", 0) or 0),
            "cache_write_tokens": int(usage.get("cache_write_tokens", 0) or 0),
            "llm_cost_usd": float(result["cost_usd"]) if result.get("cost_usd") is not None else None,
            "known_usage_cost_usd": settlement["settled_usd"],
            "usage_known": usage_known,
            "usage_unknown": not usage_known,
            "unknown_request_ids": result.get("unknown_request_ids", []),
            "unknown_reserved_openai_usd": settlement.get("retained_unknown_usage_usd", 0),
            "phase_token_bound_exceeded": phase_bounds_exceeded,
            "provider_cost_usd": provider_cost,
            "pricing_discrepancy_usd": (
                None if provider_cost is None else round(float(provider_cost) - settlement["settled_usd"], 8)
            ),
            "reserved_openai_usd": settlement["reserved_usd"],
            "completed_openai_usd": settlement["completed_openai_usd"],
            "validation": validation_detail,
            **phase_outcome_metrics(spec["name"], Path(packet["artifacts_dir"])),
        }
        if phase_status != "completed":
            phase_entry["error_category"] = langfuse_trace.error_category(
                result.get("output_text") or validation_detail
            )
            if not usage_known:
                phase_entry["error_category"] = "usage_unknown"
        if result.get("fix_safety"):
            phase_entry["fix_safety"] = result["fix_safety"]
        prompt_cache = result.get("prompt_cache") or {}
        if prompt_cache:
            phase_entry["prompt_cache"] = prompt_cache
        reserve_exceeded = settlement["settled_usd"] > settlement["reserved_usd"]
        if reserve_exceeded:
            phase_entry["error_category"] = "reservation_exceeded"
            phase_entry["recovery_actions"] = ["stop_remaining_phases", "report_reserve_breach"]
        phase_entry = phase_record(phase_entry)
        telemetry_phases.append(phase_entry)
        phase_results.append({**phase_entry, "output_text": result.get("output_text", "")})
        if phase_tracer:
            trace_events = []
            if phase_trace_path.is_file():
                for line in phase_trace_path.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        trace_events.append(event)
            phase_tracer.finish_phase(
                phase_observation,
                phase=phase_entry,
                output_text=result.get("output_text", ""),
                sanitized_output=(
                    langfuse_trace.sanitized_phase_artifact(
                        spec["name"], Path(packet["artifacts_dir"])
                    )
                    if getattr(phase_tracer, "payload", {}).get("privacy_mode") == "sanitized_artifact_output"
                    else None
                ),
                trace_events=trace_events if getattr(phase_tracer, "trace_content", "metadata") == "full" else None,
                artifacts_dir=Path(packet["artifacts_dir"]),
            )
        if not usage_known:
            failure = f"{spec['name']} has usage that cannot yet be reconciled"
            break
        if phase_bounds_exceeded:
            failure = f"{spec['name']} exceeded its configured input/output token bounds"
            break
        if phase_status != "completed":
            failure = f"{spec['name']} failed: {validation_detail}"
            break
        if reserve_exceeded:
            failure = (
                f"{spec['name']} settled ${settlement['settled_usd']:.8f}, exceeding its "
                f"${settlement['reserved_usd']:.8f} reservation"
            )
            break

    total_cost = round(authority.completed_usd - completed_before_run, 8)
    status = "blocked" if failure and "budget cap" in failure else "failed" if failure else "completed"
    return {
        "provider": "openai",
        "model": "phase-routed" if not model_override else model_override,
        "agent": "responses-api-phase-runner",
        "duration_s": round(time.monotonic() - started, 1),
        "exit_code": 3 if status == "blocked" else 2 if failure else 0,
        "status": status,
        "output_text": failure or "All bounded model-based evaluator phases completed.",
        "token_usage": total_usage,
        "cost_usd": None if run_usage_unknown else total_cost,
        "known_usage_cost_usd": total_cost,
        "usage_known": not run_usage_unknown,
        "usage_unknown": run_usage_unknown,
        "billing_source": "provider_usage_price_card_estimate" if not run_usage_unknown else "partial_provider_usage_unknown",
        "turns_used": turns_used,
        "max_turns": max_turns,
        "turn_limit_reached": bool(failure and "turn budget" in failure),
        "per_model_usage": per_model,
        "phase_results": phase_results,
        "phases": telemetry_phases,
        "budget": {
            "cap_usd": authority.cap_usd,
            "completed_openai_usd": authority.completed_usd,
            "active_reserved_openai_usd": round(sum(authority.active_reservations.values()), 8),
            "ledger_path": str(authority.ledger_path) if authority.ledger_path else None,
        },
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
    try:
        langfuse_trace.injected_trace_context()
    except ValueError as error:
        print(f"Trace bridge failed: {error}", file=sys.stderr)
        return 2
    try:
        normalize_execution_flags(args)
    except (TypeError, ValueError) as error:
        print(f"Invalid evaluator execution flags: {error}", file=sys.stderr)
        return 2
    if args.personal_run and not args.benchmark_name:
        args.benchmark_name = "personal-evaluation"
    platform = args.platform or detect_platform()
    provider = args.provider or os.environ.get("EVAL_PROVIDER") or provider_for(platform)
    try:
        validate_session_mode(args, provider)
    except ValueError as error:
        print(f"Session approval gate: {error}", file=sys.stderr)
        return 2
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

    if args.estimate_only:
        try:
            preflight = (
                run_personal_preflight(args)
                if args.personal_run
                else run_step_zero(args)
            )
        except (RuntimeError, ValueError) as error:
            print(f"Preflight failed: {error}", file=sys.stderr)
            return 2
        save_estimate(args, preflight)
        write_session_result({"status": "estimate_ready", "cost_usd": 0,
                              "known_usage_cost_usd": 0, "usage_known": True,
                              "billing_source": "local_no_model_cost"})
        print(json.dumps({
            "status": "ready",
            "mode": "estimate-only",
            "model_invoked": False,
            "preflight": preflight,
        }, indent=2))
        return 0

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

    if provider == "openai":
        if not args.approve_estimate:
            print(
                "Paid OpenAI execution blocked. Run --estimate-only, review its output, "
                "then rerun with --approve-estimate and the same Step 0 inputs.",
                file=sys.stderr,
            )
            return 2
        try:
            program_preflight = (
                run_personal_preflight(args)
                if args.personal_run
                else run_step_zero(args)
            )
            require_estimate(args, program_preflight)
        except (RuntimeError, ValueError) as error:
            print(f"Preflight failed: {error}", file=sys.stderr)
            return 2
        if args.condition == "optimized-warm":
            if not args.warm_cache_root or not args.paired_cold_state:
                print(
                    "Optimized warm runs require --warm-cache-root and --paired-cold-state.",
                    file=sys.stderr,
                )
                return 2
            try:
                verify_langfuse.validate_cache_entry(
                    Path(args.warm_cache_root).expanduser(),
                    verify_langfuse.load_canonical_state(Path(args.paired_cold_state).expanduser()),
                )
            except RuntimeError as error:
                print(f"Warm preflight failed: {error}", file=sys.stderr)
                return 2
    else:
        program_preflight = {}

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

    try:
        canonical_phase_a = run_local_json_script(
            "assemble-phase-a-canonical.js",
            artifacts_dir,
            benchmark_output=(
                Path(local_inputs["benchmark_dir"])
                / "deterministic-phase-a-canonical-result.json"
            ),
            extra_args=("--no-cache",) if args.cold_run else (),
        )
    except ValueError as error:
        print(f"Canonical Phase A gate failed before model execution: {error}", file=sys.stderr)
        return 2

    if args.cold_run and canonical_phase_a.get("skip_paid_phases"):
        print(
            "Cold-run cache gate failed: Phase A restored a full cache; stopping before model invocation.",
            file=sys.stderr,
        )
        return 2

    image_token_expectations = langfuse_trace.calibration_image_token_expectations(artifacts_dir)
    (Path(local_inputs["benchmark_dir"]) / "calibration-image-token-estimate.json").write_text(
        json.dumps(image_token_expectations, indent=2) + "\n"
    )

    if args.phase_plan_only:
        plan = write_phase_plan(
            key=args.key,
            url=url,
            workspace=local_inputs["workspace"],
            jira_context_file=local_inputs["jira_context_file"],
            benchmark_dir=local_inputs["benchmark_dir"],
            artifact_mode=args.artifact_mode,
            no_fix=args.no_fix,
        )
        print(json.dumps({
            "status": "ready",
            "mode": "bounded-phase-plan",
            "model_invoked": False,
            "shared_turn_limit": args.max_turns,
            "deterministic_evidence": deterministic_evidence,
            "canonical_phase_a": canonical_phase_a,
            "image_token_expectations": image_token_expectations,
            "phases": plan,
        }, indent=2))
        return 0

    if provider == "openai" and not canonical_phase_a.get("skip_paid_phases") and not os.environ.get("OPENAI_API_KEY"):
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
    # The consent launcher supplies one run identity shared with its long-lived
    # OpenCode root. Standalone benchmarks retain their independently generated ID.
    eval_run_id = os.environ.get("UXD_TRACE_RUN_ID") or langfuse_trace.make_eval_run_id(args.key)
    trace_content = trace_content_policy(args)
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
        "trace_content": trace_content,
        "privacy_mode": {
            "full": "full_raw", "sanitized": "sanitized_artifact_output",
            "metadata": "metadata_only",
        }[trace_content],
        "trace_context_path": str(Path(local_inputs["benchmark_dir"]) / "langfuse-trace-context.json"),
        "artifacts_dir": str(artifacts_dir),
        "deterministic_source": deterministic_result,
        "deterministic_extract": deterministic_extract,
        "deterministic_classification": deterministic_classification,
        "deterministic_evidence": deterministic_evidence,
        "canonical_phase_a": canonical_phase_a,
    }
    identity = {}
    try:
        identity = json.loads((artifacts_dir / "state.json").read_text()).get("identity", {})
    except (OSError, json.JSONDecodeError):
        pass
    initial_payload["benchmark"] = {
        "benchmark_name": args.benchmark_name,
        "comparison_id": args.comparison_id,
        "condition": args.condition,
        "prototype_key": args.key,
        "build_key": identity.get("build_key"),
        "evaluator_key": identity.get("evaluator_key"),
        "provider_model": f"{provider}/{model}",
        "cache_decision": (canonical_phase_a.get("cache") or "unknown"),
        "screenshot_mode": args.screenshot_mode,
        "artifact_mode": args.artifact_mode,
        "csv_used": None if args.csv_used is None else args.csv_used == "true",
    }
    deterministic_trace_phases = [
        {
            "phase": "eval-consistency-source",
            "model": None,
            "provider": "local",
            "llm_cost_usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": int(float(deterministic_result.get("duration_s", 0)) * 1000),
            "status": "completed",
            "validation": "deterministic source consistency completed",
        },
        {
            "phase": "eval-extract",
            "model": None,
            "provider": "local",
            "llm_cost_usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": int(float(deterministic_extract.get("duration_s", 0)) * 1000),
            "status": "completed",
            "validation": "deterministic Jira extraction completed",
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
            "validation": "deterministic criterion classification completed",
            "criteria_count": deterministic_classification.get("criteria_count"),
            "tier_counts": deterministic_classification.get("tier_counts"),
        },
    ]
    with langfuse_trace.LivePipelineTrace(initial_payload) as live_trace:
        started = time.monotonic()
        for phase in deterministic_trace_phases:
            phase_observation = live_trace.start_phase(
                name=phase["phase"],
                model=None,
                provider="local",
                input_text=json.dumps({"phase": phase["phase"], "prototype_key": args.key}),
            )
            live_trace.finish_phase(
                phase_observation,
                phase=phase,
                output_text=phase["validation"],
            )
        if canonical_phase_a.get("skip_paid_phases"):
            result = {
                "provider": provider,
                "model": "cache",
                "agent": "xray-cache",
                "duration_s": 0,
                "exit_code": 0,
                "output_text": "Restored validated canonical evaluation from X-Ray cache.",
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "cost_usd": 0,
                "billing_source": "cache",
                "status": "completed",
                "cache_hit": True,
                "phases": [],
                "phase_results": [],
            }
        else:
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
                        study_routing=bool(args.benchmark_name),
                        artifact_mode=args.artifact_mode,
                        no_fix=args.no_fix,
                        run_id=eval_run_id,
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
                        "input_tokens": None,
                        "output_tokens": None,
                        "total_tokens": None,
                    },
                    "cost_usd": None,
                    "known_usage_cost_usd": None,
                    "usage_known": False,
                    "usage_unknown": True,
                    "billing_source": "unavailable",
                    "status": "failed",
                }

        canonical_phase_b = None
        evaluation_cost = write_evaluation_cost(artifacts_dir, result, eval_run_id)
        result["evaluation_cost"] = evaluation_cost
        if result.get("exit_code") == 0 and not result.get("cache_hit"):
            try:
                canonical_phase_b = run_phase_b_canonical_sync(
                    artifacts_dir,
                    provider=provider,
                    model=model,
                    benchmark_output=(
                        Path(local_inputs["benchmark_dir"])
                        / "canonical-phase-b-result.json"
                    ),
                )
                result["canonical_phase_b"] = canonical_phase_b
            except ValueError as error:
                result["exit_code"] = 2
                result["status"] = "failed"
                result["output_text"] = f"Canonical Phase B synchronization failed: {error}"

        deterministic_report = None
        if args.no_report:
            result["report_skipped"] = True
            result["output_text"] = (
                f"{result.get('output_text', '').rstrip()} Full report rendering skipped by --no-report."
            ).strip()
        elif should_render_report(
            no_report=args.no_report,
            exit_code=int(result.get("exit_code", 0) or 0),
        ):
            report_started = time.monotonic()
            report_observation = live_trace.start_phase(
                name="eval-report",
                model=None,
                provider="local",
                input_text=json.dumps({"phase": "eval-report", "prototype_key": args.key}),
            )
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
            live_trace.finish_phase(
                report_observation,
                phase=report_phase,
                output_text=report_phase["validation"],
            )

        result["status"] = langfuse_trace.pipeline_run_status(result)
        if args.condition == "calibration":
            provider_input = int((result.get("token_usage") or {}).get("input_tokens", 0) or 0)
            expected_auto = image_token_expectations["auto_detail_expected_tokens"]
            expected_high = image_token_expectations["high_detail_tokens"]
            calibration = {
                **image_token_expectations,
                "measurement_status": "measured" if result.get("exit_code") == 0 else "not_measured",
                "provider_reported_input_tokens": provider_input,
                "delta_vs_high_tokens": provider_input - expected_high,
                "formula_discrepancy_tokens": provider_input - expected_auto,
                "comparison_scope": "provider input includes text/reasoning; image-token breakdown is provider-dependent",
            }
            result["calibration"] = calibration
            (Path(local_inputs["benchmark_dir"]) / "calibration-report.json").write_text(
                json.dumps(calibration, indent=2) + "\n"
            )
        usage = result.get("token_usage", {})
        stdout_lines = trace_path.read_text().splitlines() if trace_path.is_file() else []
        artifact_phases = langfuse_trace.build_pipeline_phases(
            artifacts_dir,
            result,
            stdout_lines=stdout_lines,
        )
        if args.no_report:
            artifact_phases = [
                phase for phase in artifact_phases
                if phase.get("phase") not in {"eval-report", "render-report.js"}
            ]
        phases = [
            *[dict(phase) for phase in deterministic_trace_phases],
            {
                "phase": "uxd-consistency-check",
                "model": None,
                "llm_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": int(float(deterministic_result.get("duration_s", 0)) * 1000),
                "status": "completed",
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
            "metrics": {
                "turns_used": int(result.get("turns_used", 0) or 0),
                "retries": sum(int(phase.get("retries", 0) or 0) for phase in phases),
                "fallbacks": sum(int(phase.get("fallbacks", 0) or 0) for phase in phases),
                "recovery_actions": [
                    action
                    for phase in phases
                    for action in (phase.get("recovery_actions") or [])
                ],
                "confidence_available": any(
                    phase.get("confidence_available") is True for phase in phases
                ),
            },
        }
        if args.trace_sanitized_artifacts:
            sanitized = langfuse_trace.sanitized_evaluation_artifact(artifacts_dir)
            if sanitized is not None:
                payload["sanitized_artifact_output"] = sanitized
        if result.get("exit_code"):
            payload["metrics"]["error_category"] = langfuse_trace.error_category(
                result.get("output_text")
            )
        audit_phases = [*phases,
                        {"phase": "phase-a-canonical", "status": canonical_phase_a.get("status", "unknown"),
                         "validation": "phase A canonical validation completed" if canonical_phase_a.get("status") == "completed" else "not validated"}]
        if canonical_phase_b:
            audit_phases.append({"phase": "phase-b-canonical", "status": canonical_phase_b.get("status"),
                                 "validation": "phase B canonical synchronization completed" if canonical_phase_b.get("status") == "completed" else "not validated"})
        flow_manifest = data_flow_manifest(
            artifacts_dir,
            eval_run_id,
            audit_phases,
            selected_openai_phases(no_fix=args.no_fix),
            result["status"],
        )
        audit_dir = Path(local_inputs["benchmark_dir"])
        (audit_dir / "data-flow-manifest.json").write_text(json.dumps(flow_manifest, indent=2) + "\n")
        live_trace.record_audit("eval-data-flow-audit", flow_manifest, audit_type="evaluator-pipeline-data-flow")
        if result["status"] == "completed" and deterministic_report:
            report_manifest = report_quality_manifest(artifacts_dir, eval_run_id, result["status"])
            (audit_dir / "report-quality-manifest.json").write_text(json.dumps(report_manifest, indent=2) + "\n")
            live_trace.record_audit("eval-report-quality-audit", report_manifest, audit_type="evaluator-report-quality")
        live_trace.finish(payload)
    summary = live_trace.summary
    ledger_payload = {
        "eval_run_id": eval_run_id, "prototype_key": args.key, "invocation": "api",
        "model": result.get("model"), "iterate_flags": args.iterate_flags,
        "phases": [phase_record(item) for item in result.get("phases", [])],
        "totals": {"llm_cost_usd": result.get("cost_usd"),
                   "known_usage_cost_usd": result.get("known_usage_cost_usd"),
                   "usage_known": result.get("usage_known", True),
                   "total_tokens": (result.get("token_usage") or {}).get("total_tokens")},
        "langfuse_trace_url": summary.get("langfuse_trace_url", ""),
        "privacy_mode": initial_payload["privacy_mode"],
        "trace_content": initial_payload["trace_content"],
        "notes": "Provider-usage short-context price-card estimate; excludes OpenCode session model billing.",
    }
    ledger = subprocess.run(
        ["node", str(SCRIPT_DIR / "log-cost-ledger.js"), "--artifacts-dir", str(artifacts_dir)],
        input=json.dumps(ledger_payload), text=True, capture_output=True,
        cwd=local_inputs["workspace"], check=False,
    )
    if ledger.returncode:
        result["cost_ledger_status"] = f"failed: {ledger.stderr.strip()[-300:]}"
    else:
        result["cost_ledger_status"] = "written"
    write_session_result({**result, "artifacts_dir": str(artifacts_dir)})
    print(json.dumps({**result, "eval_run_id": eval_run_id, **summary}, indent=2))
    return 2 if ledger.returncode else 0 if result.get("exit_code") == 0 else result.get("exit_code", 1)


if __name__ == "__main__":
    sys.exit(main())
