#!/usr/bin/env python3
"""Append a content-free creator output/data-flow manifest to its Langfuse trace."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER_PATH = SCRIPT_DIR / "creator-phase-runner.py"
SPEC = importlib.util.spec_from_file_location("creator_manifest_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifacts-dir", help="Run-scoped artifact root inside the workspace")
    parser.add_argument("--benchmark-dir", help="Run-scoped benchmark directory inside the workspace")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comparison-id", required=True)
    parser.add_argument("--benchmark-name", default="prototype-creator-costs")
    parser.add_argument("--env-file", help="Creator Langfuse env file; defaults to repository .env.creator")
    return parser.parse_args()


def manifest_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    workspace = Path(args.workspace).expanduser().resolve()
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
    return workspace, artifacts, benchmark


def manifest_payload(args: argparse.Namespace) -> dict[str, Any]:
    workspace, artifacts, benchmark = manifest_paths(args)
    if not workspace.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace}")
    if not artifacts.is_dir():
        raise ValueError(f"Creator artifacts do not exist: {artifacts}")
    task_file = workspace / "create-refine.md"
    if not task_file.is_file():
        task_file = next(iter(sorted(workspace.glob("create-*.md"))), None)
    resolved = {
        "workspace": workspace,
        "artifacts": artifacts,
        "benchmark": benchmark,
        "prompt_file": task_file,
        "run_id": args.run_id,
    }
    manifest_args = SimpleNamespace(
        key=args.key,
        run_id=args.run_id,
        comparison_id=args.comparison_id,
        benchmark_name=args.benchmark_name,
    )
    return runner.build_creator_artifact_manifest(manifest_args, resolved)


def load_creator_langfuse(args: argparse.Namespace) -> None:
    env_file = Path(args.env_file).expanduser().resolve() if args.env_file else runner.creator_env_file()
    loaded = runner.verify_langfuse.load_env_file(env_file)
    if loaded is None:
        raise RuntimeError(f"Creator Langfuse env file does not exist: {env_file}")
    runner.force_creator_langfuse_env(env_file)
    required = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("missing required Langfuse variables: " + ", ".join(missing))
    runner.verify_langfuse.check_health(os.environ["LANGFUSE_HOST"])
    runner.verify_langfuse.check_auth(
        os.environ["LANGFUSE_HOST"],
        os.environ["LANGFUSE_PUBLIC_KEY"],
        os.environ["LANGFUSE_SECRET_KEY"],
    )


def main() -> int:
    args = parse_args()
    try:
        load_creator_langfuse(args)
        manifest = manifest_payload(args)
        workspace, artifacts, benchmark = manifest_paths(args)
        payload = {
            "component": "creator",
            "pipeline": "prototype-creator",
            "prototype_key": args.key,
            "eval_run_id": args.run_id,
            "provider": "openai",
            "experiment": "creator-paid-phases",
            "billing_source": "local_no_model_cost",
            "privacy_mode": "metadata_only",
            "trace_content": "metadata",
            "trace_context_path": str(runner.creator_trace_context_path(benchmark, args.run_id)),
            "benchmark": {
                "benchmark_name": args.benchmark_name,
                "comparison_id": args.comparison_id,
            },
        }
        with runner.langfuse_trace.LivePipelineTrace(payload) as trace:
            if not trace.client:
                raise RuntimeError("Langfuse client unavailable; manifest not uploaded")
            trace.record_audit(
                "creator-artifact-manifest",
                manifest,
                audit_type="prototype-creator-output-manifest",
            )
            summary = trace.finish({
                **payload,
                "run_result": {
                    "status": "completed",
                    "exit_code": 0,
                    "cost_usd": 0,
                    "billing_source": "local_no_model_cost",
                    "duration_s": 0,
                },
                "phases": [],
                "metrics": {"artifact_count": len(manifest["data_flow"]["outputs"])},
            })
        print(json.dumps({
            "status": "logged" if summary.get("logged") else "failed",
            "run_id": args.run_id,
            "langfuse_trace_url": summary.get("langfuse_trace_url", ""),
            "artifact_count": len(manifest["data_flow"]["outputs"]),
            "phase_attempt_count": len(manifest["data_flow"]["phase_attempts"]),
            "privacy_mode": manifest["privacy_mode"],
        }, indent=2))
        return 0 if summary.get("logged") else 2
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Artifact manifest not logged: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
