#!/usr/bin/env python3
"""
mlflow-trace-pipeline.py

Wraps a full eval-iterate pipeline run via claude --print with stream-json
capture. Logs the orchestrator session as an MLflow trace, then runs
mlflow-trace-eval.py against the generated artifacts to populate per-skill
validation experiments.

Usage:
  eval "$(make mlflow-env)"

  # Full pipeline run with Sonnet 5:
  uv run python3 plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/mlflow-trace-pipeline.py \
    --key PROJ-298 --url http://127.0.0.1:9204 --model claude-sonnet-5

  # Full pipeline run with Opus 4.6:
  uv run python3 plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/mlflow-trace-pipeline.py \
    --key PROJ-298 --url http://127.0.0.1:9204 --model claude-opus-4-6

  # With extra eval-iterate flags:
  uv run python3 plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/mlflow-trace-pipeline.py \
    --key PROJ-298 --url http://127.0.0.1:9204 --model claude-opus-4-6 \
    --iterate-flags="--no-fix --fresh"
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]  # ai-helpers root

sys.path.insert(0, str(PROJECT_ROOT))

def _agent_eval_harness_paths():
    """Discover agent-eval-harness without pinning a cache version."""
    paths = []
    env = os.environ.get("AGENT_EVAL_HARNESS_PATH")
    if env:
        paths.append(os.path.expanduser(env))
    cache = os.path.expanduser(
        "~/.claude/plugins/cache/opendatahub-skills/agent-eval-harness")
    if os.path.isdir(cache):
        versions = sorted(
            (os.path.join(cache, p) for p in os.listdir(cache)
             if os.path.isdir(os.path.join(cache, p))),
            reverse=True,
        )
        paths.extend(versions)
    return paths

for _harness in _agent_eval_harness_paths():
    sys.path.insert(0, _harness)

import mlflow
from agent_eval.agent.stream_capture import (
    extract_usage,
    make_prompt_event,
    inject_timestamp,
)
from agent_eval.mlflow.trace_builder import build_trace, log_trace

# Langfuse dual-write (local skill module)
sys.path.insert(0, str(SCRIPT_DIR))
import langfuse_trace  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Wrap eval-iterate with MLflow tracing")
    parser.add_argument("--key", required=True,
                        help="Jira key (e.g., PROJ-298)")
    parser.add_argument("--url", required=True,
                        help="Prototype URL (e.g., http://127.0.0.1:9204)")
    parser.add_argument("--model", default="claude-opus-4-6",
                        help="Model to use for all sub-skills")
    parser.add_argument("--workspace", default=None,
                        help="Workspace path (auto-detected if omitted)")
    parser.add_argument("--iterate-flags", default="",
                        help="Extra flags for eval-iterate (e.g., '--no-fix --fresh')")
    parser.add_argument("--experiment", default="eval-iterate",
                        help="MLflow experiment name for the orchestrator trace")
    parser.add_argument("--no-validation", action="store_true",
                        help="Skip running mlflow-trace-eval.py after pipeline")
    parser.add_argument("--experiment-label", default=None,
                        help="Ledger experiment name (e.g. golden-a-opus)")
    parser.add_argument("--no-langfuse", action="store_true",
                        help="Skip Langfuse + cost ledger dual-write")
    return parser.parse_args()


def resolve_workspace(project_dir: str, key: str, override: str | None) -> str:
    if override:
        return override
    state_path = Path(project_dir) / ".artifacts" / key / "eval" / "eval-state.yaml"
    if state_path.is_file():
        for line in state_path.read_text().splitlines():
            if line.startswith("workspace:"):
                ws = line.split(":", 1)[1].strip()
                if ws:
                    return ws
    legacy = Path(project_dir) / ".artifacts" / key / "workspace"
    if legacy.is_dir():
        return str(legacy)
    return str(Path(project_dir) / "workspace" / "rhoai-https")


def build_eval_iterate_prompt(key: str, url: str, workspace: str,
                               model: str, extra_flags: str) -> str:
    parts = [f"/uxd-prototype-evaluate {key} {url}"]
    if workspace:
        parts.append(f"--workspace={workspace}")
    if extra_flags:
        parts.append(extra_flags)
    return " ".join(parts)


def _build_phases_from_usage(per_model_usage: dict, artifacts_dir: Path,
                              run_result: dict | None = None,
                              stdout_lines: list | None = None) -> list:
    if run_result is not None:
        phases = langfuse_trace.build_pipeline_phases(
            artifacts_dir, run_result, stdout_lines=stdout_lines,
        )
        if phases:
            return phases
    phases = []
    for model_name, usage in (per_model_usage or {}).items():
        phases.append({
            "phase": f"generation/{model_name}",
            "model": model_name,
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "llm_cost_usd": usage.get("costUSD", 0),
        })
    metrics_path = artifacts_dir / "render-metrics.json"
    if metrics_path.is_file():
        try:
            metrics = json.loads(metrics_path.read_text())
            phases.append({
                "phase": "render-report.js",
                "model": None,
                "llm_cost_usd": 0,
                "duration_ms": metrics.get("duration_ms", 0),
                "output_bytes": metrics.get("output_bytes", 0),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return phases


def _write_cost_ledger(project_dir: str, key: str, payload: dict) -> None:
    artifacts_dir = Path(project_dir) / ".artifacts" / key / "eval"
    ledger_script = SCRIPT_DIR / "log-cost-ledger.js"
    node = "node"
    proc = subprocess.run(
        [node, str(ledger_script), f"--artifacts-dir={artifacts_dir}"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=project_dir,
    )
    if proc.returncode != 0:
        print(f"  Cost ledger write failed: {proc.stderr[:300]}", file=sys.stderr)
    else:
        print(f"  Cost ledger: {proc.stdout.strip()}", file=sys.stderr)


def run_pipeline_traced(prompt: str, model: str, experiment: str,
                        trace_dir: Path, project_dir: str, *,
                        prototype_key: str = "", iterate_flags: str = "",
                        experiment_label: str | None = None,
                        skip_langfuse: bool = False) -> dict:
    cmd = [
        "claude", "--print", "--model", model,
        "--output-format", "stream-json", "--verbose",
    ]

    trace_dir.mkdir(parents=True, exist_ok=True)

    print(f"╔══════════════════════════════════════════════════════════╗", file=sys.stderr)
    print(f"║  eval-iterate pipeline run", file=sys.stderr)
    print(f"║  Model: {model}", file=sys.stderr)
    print(f"║  Experiment: {experiment}", file=sys.stderr)
    print(f"║  Trace dir: {trace_dir}", file=sys.stderr)
    print(f"╚══════════════════════════════════════════════════════════╝", file=sys.stderr)

    start = time.monotonic()
    stdout_lines = []
    resolved_model = None

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=project_dir,
    )

    stderr_lines = []
    def _drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)
    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    proc.stdin.write(prompt)
    proc.stdin.close()

    stdout_lines.append(make_prompt_event(prompt))

    last_progress = time.monotonic()
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line.strip():
            stdout_lines.append(line)
            continue
        try:
            line = inject_timestamp(line)
            obj = json.loads(line)
            if (not resolved_model
                    and obj.get("type") == "system"
                    and obj.get("subtype") == "init"):
                resolved_model = obj.get("model")
            if time.monotonic() - last_progress > 60:
                elapsed = time.monotonic() - start
                print(f"  ... {elapsed:.0f}s elapsed, {len(stdout_lines)} events",
                      file=sys.stderr)
                last_progress = time.monotonic()
            if obj.get("type") == "result":
                cost = obj.get("total_cost_usd", 0)
                turns = obj.get("num_turns", 0)
                print(f"  Pipeline complete ({turns} turns, ${cost:.2f}, "
                      f"{time.monotonic() - start:.0f}s)", file=sys.stderr)
        except (json.JSONDecodeError, ValueError):
            pass
        stdout_lines.append(line)

    proc.wait()
    stderr_thread.join(timeout=10)

    duration = time.monotonic() - start

    stdout_text = "\n".join(stdout_lines)
    (trace_dir / "stdout.log").write_text(stdout_text)
    if stderr_lines:
        (trace_dir / "stderr.log").write_text("".join(stderr_lines))

    (token_usage, cost_usd, num_turns, stream_ids, models_seen,
     per_model_usage, _) = extract_usage(stdout_lines)

    run_result = {
        "exit_code": proc.returncode,
        "duration_s": round(duration, 1),
        "token_usage": token_usage,
        "cost_usd": cost_usd,
        "per_model_usage": per_model_usage,
        "num_turns": num_turns,
        "model": resolved_model or model,
        "agent": "claude-code",
    }
    with open(trace_dir / "run_result.json", "w") as f:
        json.dump(run_result, f, indent=2)

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    exp = mlflow.get_experiment_by_name(experiment)
    experiment_id = exp.experiment_id if exp else "0"

    try:
        run_id = trace_dir.name
        trace_name = f"eval-iterate/{resolved_model or model} ({run_id})"
        trace_dict = build_trace(
            stdout_path=trace_dir / "stdout.log",
            run_result=run_result,
            run_id=run_id,
            experiment_id=experiment_id,
            trace_name=trace_name,
        )
        if trace_dict:
            trace_id = log_trace(trace_dict)
            num_spans = len(trace_dict["data"]["spans"])
            print(f"  Trace {trace_id} ({num_spans} spans) → {tracking_uri}",
                  file=sys.stderr)
    except Exception as e:
        print(f"  Trace push failed: {e}", file=sys.stderr)

    with mlflow.start_run(run_name=f"eval-iterate/{resolved_model or model}"):
        mlflow.set_tag("model", resolved_model or model)
        mlflow.set_tag("pipeline", "eval-iterate")
        mlflow.set_tag("exit_code", str(proc.returncode))
        mlflow.log_param("model", resolved_model or model)
        mlflow.log_param("prompt", prompt[:250])

        if token_usage:
            input_tok = token_usage.get("input_tokens", 0) or token_usage.get("input", 0)
            output_tok = token_usage.get("output_tokens", 0) or token_usage.get("output", 0)
            cache_read = (token_usage.get("cache_read_input_tokens", 0)
                          or token_usage.get("cache_read", 0))
            mlflow.log_metric("input_tokens", input_tok)
            mlflow.log_metric("output_tokens", output_tok)
            mlflow.log_metric("total_tokens", input_tok + output_tok)
            mlflow.log_metric("cache_read_tokens", cache_read)
        if cost_usd:
            mlflow.log_metric("cost_usd", cost_usd)
        mlflow.log_metric("duration_s", duration)
        mlflow.log_metric("num_turns", num_turns or 0)

        if per_model_usage:
            for model_name, usage in per_model_usage.items():
                safe = model_name.replace("/", "_").replace("-", "_")
                mlflow.log_metric(f"model/{safe}/input_tokens",
                                  usage.get("inputTokens", 0))
                mlflow.log_metric(f"model/{safe}/output_tokens",
                                  usage.get("outputTokens", 0))
                mlflow.log_metric(f"model/{safe}/cost_usd",
                                  usage.get("costUSD", 0))

    artifacts_dir = Path(project_dir) / ".artifacts" / prototype_key / "eval"
    eval_run_id = langfuse_trace.make_eval_run_id(prototype_key)
    dims = langfuse_trace.parse_iterate_flags(iterate_flags)
    input_tok = ((token_usage or {}).get("input_tokens", 0) or (token_usage or {}).get("input", 0))
    output_tok = ((token_usage or {}).get("output_tokens", 0) or (token_usage or {}).get("output", 0))

    if not skip_langfuse:
        lf_payload = {
            "prototype_key": prototype_key,
            "eval_run_id": eval_run_id,
            "iterate_flags": iterate_flags,
            "invocation": "cli",
            "model": resolved_model or model,
            "experiment": experiment_label or experiment,
            "prompt": prompt,
            "run_result": run_result,
            "phases": _build_phases_from_usage(
                per_model_usage, artifacts_dir, run_result=run_result,
                stdout_lines=stdout_lines,
            ),
        }
        lf_summary = langfuse_trace.log_pipeline_run(lf_payload)
        run_result["eval_run_id"] = eval_run_id
        run_result["langfuse_trace_url"] = lf_summary.get("langfuse_trace_url", "")

        obs_cost = float(os.environ.get("LANGFUSE_OBS_COST_PER_RUN", "0.05"))
        ledger_payload = {
            "eval_run_id": eval_run_id,
            "prototype_key": prototype_key,
            "experiment": experiment_label or experiment,
            "iterate_flags": iterate_flags,
            "run_mode": dims["run_mode"],
            "fix_mode": dims["fix_mode"],
            "invocation": "cli",
            "model": resolved_model or model,
            "phases": lf_payload["phases"],
            "totals": {
                "llm_cost_usd": cost_usd or 0,
                "observability_cost_usd": obs_cost if langfuse_trace.is_enabled() else 0,
                "total_tokens": input_tok + output_tok,
            },
            "langfuse_trace_url": lf_summary.get("langfuse_trace_url", ""),
        }
        _write_cost_ledger(project_dir, prototype_key, ledger_payload)

        eval_state_path = artifacts_dir / "eval-state.yaml"
        if eval_state_path.parent.exists():
            subprocess.run(
                ["python3", str(SCRIPT_DIR / "eval_state.py"), "set",
                 str(eval_state_path),
                 f"eval_run_id={eval_run_id}",
                 f"llm_cost_usd={cost_usd or 0}",
                 f"langfuse_trace_url={lf_summary.get('langfuse_trace_url', '')}"],
                capture_output=True, text=True,
            )

    return run_result


def run_validation(key: str, model: str, project_dir: str):
    script = str(SCRIPT_DIR / "mlflow-trace-eval.py")
    artifacts_dir = os.path.join(project_dir, ".artifacts", key, "eval")
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    python_cmd = str(venv_python) if venv_python.is_file() else sys.executable

    print(f"\n  Running validation scorers against {artifacts_dir}...", file=sys.stderr)
    result = subprocess.run(
        [python_cmd, script, artifacts_dir,
         "--model", model, "--prototype-key", key, "--scorers", "all"],
        capture_output=True, text=True, cwd=project_dir,
    )
    print(result.stdout, file=sys.stderr)
    if result.returncode != 0:
        print(f"  Validation had failures (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            print(f"  {result.stderr[:200]}", file=sys.stderr)


def main():
    args = parse_args()

    project_dir = str(PROJECT_ROOT)
    workspace = resolve_workspace(project_dir, args.key, args.workspace)

    prompt = build_eval_iterate_prompt(
        args.key, args.url, workspace, args.model, args.iterate_flags)

    print(f"\n  Prompt: {prompt}\n", file=sys.stderr)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_safe = args.model.replace("/", "-")
    trace_dir = (Path(project_dir) / "tmp" / "trace-runs"
                 / f"pipeline-{args.key}-{model_safe}-{ts}")

    result = run_pipeline_traced(
        prompt=prompt,
        model=args.model,
        experiment=args.experiment,
        trace_dir=trace_dir,
        project_dir=project_dir,
        prototype_key=args.key,
        iterate_flags=args.iterate_flags,
        experiment_label=args.experiment_label,
        skip_langfuse=args.no_langfuse,
    )

    if not args.no_validation:
        run_validation(args.key, args.model, project_dir)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  PIPELINE RUN SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Model:    {result.get('model', args.model)}", file=sys.stderr)
    print(f"  Duration: {result.get('duration_s', 0):.0f}s", file=sys.stderr)
    print(f"  Turns:    {result.get('num_turns', 0)}", file=sys.stderr)
    print(f"  Cost:     ${result.get('cost_usd', 0) or 0:.2f}", file=sys.stderr)
    tokens = result.get("token_usage", {})
    if tokens:
        print(f"  Tokens:   {tokens.get('input_tokens', 0):,} in / "
              f"{tokens.get('output_tokens', 0):,} out", file=sys.stderr)
    print(f"  Exit:     {result.get('exit_code', 'unknown')}", file=sys.stderr)
    print(f"  Trace:    {trace_dir}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
