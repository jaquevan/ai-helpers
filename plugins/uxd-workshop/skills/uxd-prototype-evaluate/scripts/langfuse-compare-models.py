#!/usr/bin/env python3
"""Small direct-API model comparison runner.

Each model is run against one skill prompt, then usage/cost/quality metadata is
sent to Langfuse. It intentionally does not depend on MLflow or agent-eval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]
sys.path.insert(0, str(SCRIPT_DIR))
import langfuse_trace  # noqa: E402
from openai_api_agent import run_agent  # noqa: E402


PHASE_DOCS = {
    "eval-extract": "eval-extract.md",
    "eval-classify": "eval-classify.md",
    "eval-journey": "eval-journey.md",
    "eval-consistency": "eval-consistency.md",
    "eval-usability": "eval-usability.md",
    "eval-report": "eval-report.md",
}


def phase_command(skill: str, *, key: str, workspace: str, jira_context: Path, benchmark_dir: Path) -> str:
    artifacts = Path(workspace).resolve() / ".artifacts" / key / "eval"
    if skill == "eval-extract":
        return (
            f"python3 {SKILL_DIR / 'scripts' / 'extract_jira_context.py'} "
            f"--key={key} --jira-context={jira_context} --workspace={workspace} "
            f"--artifacts-dir={artifacts}"
        )
    if skill == "eval-consistency":
        return (
            f"python3 {SKILL_DIR / 'scripts' / 'run_evaluator.py'} "
            f"--key={key} --workspace={workspace} --jira-context={jira_context} "
            f"--benchmark-dir={benchmark_dir} --all-files"
        )
    return ""


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _confidence_values(value: object) -> list[float]:
    values: list[float] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"confidence", "confidence_score"} and isinstance(item, (int, float)):
                if 0 <= float(item) <= 1:
                    values.append(float(item))
            else:
                values.extend(_confidence_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_confidence_values(item))
    return values


def artifact_metrics(artifacts_dir: Path) -> dict:
    """Return compact outcome metrics without copying artifact content to telemetry."""
    files = sorted(path for path in artifacts_dir.rglob("*") if path.is_file()) if artifacts_dir.is_dir() else []
    manifest = [
        {
            "name": str(path.relative_to(artifacts_dir)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files[:20]
    ]
    metrics = {
        "artifact_count": len(files),
        "artifact_bytes": sum(path.stat().st_size for path in files),
        "artifact_manifest": manifest,
        "expected_outputs_present": {
            "extract_state": (artifacts_dir / "extract-state.json").is_file(),
            "mr_delta": (artifacts_dir / "mr-delta.json").is_file(),
            "consistency_report": (artifacts_dir / "consistency-report.json").is_file(),
        },
        "retries": 0,
        "fallbacks": 0,
        "recovery_actions": [],
    }
    extract = _read_json(artifacts_dir / "extract-state.json")
    report = _read_json(artifacts_dir / "consistency-report.json")
    decisions = {}
    if extract:
        decisions["acceptance_criteria"] = len(extract.get("ac_list") or [])
        persona = extract.get("persona_selection") or {}
        if persona.get("method"):
            decisions["persona_selection_method"] = persona["method"]
        decisions["decision_context_present"] = bool(
            (extract.get("decision_context") or {}).get("has_decisions")
        )
    source = report.get("source_mode") or {}
    visual = report.get("visual_mode") or {}
    findings = [*(source.get("violations") or []), *(visual.get("findings") or [])]
    verdict_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for finding in findings:
        verdict = finding.get("verdict")
        severity = finding.get("severity")
        if verdict:
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        if severity:
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
    if verdict_counts:
        decisions["verdict_counts"] = verdict_counts
    if severity_counts:
        decisions["severity_counts"] = severity_counts
    if decisions:
        metrics["phase_decisions"] = decisions
    if findings:
        metrics["finding_count"] = len(findings)
    input_metrics = visual.get("input_metrics") or {}
    if input_metrics:
        metrics["screenshot_count"] = int(input_metrics.get("screenshots_analyzed", 0) or 0)
        metrics["screenshot_bytes"] = int(input_metrics.get("input_bytes", 0) or 0)
    confidence = _confidence_values({"extract": extract, "report": report})
    metrics["confidence_available"] = bool(confidence)
    if confidence:
        metrics.update({
            "confidence_count": len(confidence),
            "confidence_mean": round(sum(confidence) / len(confidence), 4),
            "confidence_min": min(confidence),
            "confidence_max": max(confidence),
        })
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare OpenAI models with Langfuse")
    parser.add_argument("--key", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:9204")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--project-dir", default=None, help="Isolated project root for model-written artifacts")
    parser.add_argument("--jira-context", required=True, help="MCP-staged context JSON; no Jira fallback")
    parser.add_argument("--benchmark-dir", default=None)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--skills", nargs="+", default=["eval-extract", "eval-classify", "eval-consistency", "eval-report"])
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_dir or PROJECT_ROOT).resolve()
    workspace = str(Path(args.workspace).resolve()) if args.workspace else str(project_root / "workspace" / "rhoai-https")
    jira_context = Path(args.jira_context).resolve()
    benchmark_dir = Path(args.benchmark_dir or (PROJECT_ROOT / "tmp" / "benchmarks" / args.key)).resolve()
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for skill in args.skills:
        if skill not in PHASE_DOCS:
            raise SystemExit(f"Unknown skill: {skill}")
        prompt = (
            f"Read {SKILL_DIR / 'references' / 'phases' / PHASE_DOCS[skill]} and execute only that phase.\n"
            f"Key: {args.key}\nURL: {args.url}\nWorkspace: {workspace}\n"
            f"MCP-staged context: {jira_context}\nBenchmark directory: {benchmark_dir}\n"
            f"Write artifacts under {Path(workspace).resolve() / '.artifacts' / args.key / 'eval'}. "
            "Do not call Jira or inspect credentials. "
            f"Run this exact command once, then stop: {phase_command(skill, key=args.key, workspace=workspace, jira_context=jira_context, benchmark_dir=benchmark_dir)}"
        )
        for model in args.models:
            print(f"{skill} {model}", file=sys.stderr)
            if args.dry_run:
                print(prompt)
                continue
            trace_path = benchmark_dir / "model-traces" / f"{skill}-{model}.jsonl"
            result = run_agent(
                prompt,
                model=model,
                project_dir=str(project_root),
                system_prompt=(
                    "You are a direct-API evaluation agent. Use run_shell to execute the requested "
                    "phase and verify its artifacts. Follow repository instructions."
                ),
                reasoning_effort="low" if "luna" in model else "medium",
                trace_path=str(trace_path),
                skill_dir=str(SKILL_DIR),
                jira_context_file=str(jira_context),
                jira_issue_key=args.key,
                benchmark_dir=str(benchmark_dir),
                max_turns=args.max_turns,
            )
            usage = result.get("token_usage", {})
            metrics = artifact_metrics(Path(workspace).resolve() / ".artifacts" / args.key / "eval")
            metrics["tool_calls"] = int(result.get("tool_calls", 0) or 0)
            metrics["tool_failures"] = int(result.get("tool_failures", 0) or 0)
            if result.get("error_categories"):
                metrics["error_categories"] = result["error_categories"]
            if result.get("recovery_actions"):
                metrics["recovery_actions"] = result["recovery_actions"]
            if result.get("exit_code"):
                metrics["error_category"] = langfuse_trace.error_category(result.get("output_text"))
            metrics["turns_used"] = int(result.get("turns_used", 0) or 0)
            metrics["phase_decision"] = result.get("status", "unknown")
            eval_run_id = langfuse_trace.make_eval_run_id(args.key)
            summary = langfuse_trace.log_pipeline_run({
                "prototype_key": args.key,
                "eval_run_id": eval_run_id,
                "experiment": f"compare-{skill}-{model}",
                "invocation": "api",
                "provider": "openai",
                "model": model,
                "billing_source": result.get("billing_source"),
                "run_result": result,
                "metrics": metrics,
                "phases": [{
                    "phase": skill,
                    "model": model,
                    "provider": "openai",
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "llm_cost_usd": result.get("cost_usd") or 0,
                    **metrics,
                }],
            })
            results.append({"skill": skill, "model": model, **result, **summary})

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
