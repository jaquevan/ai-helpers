#!/usr/bin/env python3
"""
langfuse_trace.py — Langfuse v4 SDK dual-write for uxd-prototype-evaluate.

Uses start_observation / create_event (not legacy ingestion API).
Privacy default: metadata_only — no raw screenshots, Jira text, or report HTML.

Env:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
  LANGFUSE_ENABLED=0 disables export (ledger still written by log-cost-ledger.js)

CLI:
  python3 langfuse_trace.py smoke
  python3 langfuse_trace.py phase --artifacts-dir DIR --phase NAME --action start|end [--duration-ms N]
  python3 langfuse_trace.py log-pipeline --json-file run_payload.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

MAX_TEXT_CHARS = 500
PHASE_NAMES = frozenset({
    "eval-extract", "eval-classify", "eval-consistency-source",
    "eval-journey", "eval-fix", "eval-consistency-visual",
    "eval-usability", "eval-report", "render-report.js",
    "validate-artifact-schemas", "playwright-run",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_enabled() -> bool:
    if os.environ.get("LANGFUSE_ENABLED", "1").lower() in ("0", "false", "no"):
        return False
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
        and os.environ.get("LANGFUSE_HOST")
    )


def _get_client():
    if not is_enabled():
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        print("langfuse package not installed; pip install langfuse", file=sys.stderr)
        return None
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"].rstrip("/"),
        environment=os.environ.get("LANGFUSE_ENVIRONMENT", "development"),
        release=os.environ.get("LANGFUSE_RELEASE"),
    )


def hash_user_id(username: str | None) -> str:
    if not username:
        return "anonymous"
    return hashlib.sha256(username.encode()).hexdigest()[:16]


def redact_text(text: str | None, max_chars: int = MAX_TEXT_CHARS) -> str | None:
    if text is None:
        return None
    s = str(text)
    s = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[REDACTED_KEY]", s)
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", s)
    if len(s) > max_chars:
        return s[:max_chars] + f"... [truncated {len(s) - max_chars} chars]"
    return s


def parse_iterate_flags(flags: str) -> dict[str, str]:
    flags = flags or ""
    run_mode = "fresh" if "--fresh" in flags.split() else "incremental"
    fix_mode = "no_fix" if "--no-fix" in flags.split() else "iterate"
    return {"run_mode": run_mode, "fix_mode": fix_mode, "iterate_flags": flags.strip()}


def infer_model_tier(model: str | None, invocation: str = "cli") -> str:
    if invocation == "cursor" and model and "grok" in model.lower():
        return "cursor_grok"
    if not model:
        return "premium"
    m = model.lower()
    if "haiku" in m:
        return "budget"
    if "sonnet" in m:
        return "standard"
    if "opus" in m:
        return "premium"
    if "luna" in m:
        return "budget"
    if "terra" in m:
        return "standard"
    if "sol" in m or "astra" in m:
        return "premium"
    return "standard"


def infer_provider(model: str | None, invocation: str = "cli") -> str:
    if invocation == "cursor":
        return "cursor"
    if model and (model.lower().startswith("gpt-") or "codex" in model.lower()):
        return "openai"
    if model and "claude" in model.lower():
        return "anthropic"
    return "unknown"


def make_eval_run_id(prototype_key: str, seed: str | None = None) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha256((seed or str(uuid.uuid4())).encode()).hexdigest()[:6]
    return f"eval-{prototype_key}-{ts}-{suffix}"


def langfuse_trace_id(eval_run_id: str) -> str:
    """Langfuse v4 requires a 32-char lowercase hex trace id."""
    return hashlib.sha256(eval_run_id.encode()).hexdigest()[:32]


PHASE_DOC_MAP = {
    "eval-extract.md": "eval-extract",
    "eval-classify.md": "eval-classify",
    "eval-consistency.md": "eval-consistency-source",
    "eval-journey.md": "eval-journey",
    "eval-fix.md": "eval-fix",
    "eval-usability.md": "eval-usability",
    "eval-report.md": "eval-report",
}

TIMING_SPECS = [
    ("extract_core_start", "extract_core_end", "eval-extract"),
    ("consistency_source_start", "consistency_source_end", "eval-consistency-source"),
    ("bridge_start", "bridge_end", "eval-consistency-visual"),
    ("bridge_end", "discover_end", "eval-usability"),
]

PHASE_ARTIFACTS = {
    "eval-extract": "extract-state.json",
    "eval-classify": "evaluation-report.csv",
    "eval-consistency-source": "consistency-report.json",
    "eval-journey": "journey-log.json",
    "eval-usability": "persona-results.json",
    "eval-report": "evaluation-report.html",
}


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    delta = (end - start).total_seconds() * 1000
    return max(int(delta), 0)


def load_eval_state(artifacts_dir: Path) -> dict[str, str]:
    path = artifacts_dir / "eval-state.yaml"
    state: dict[str, str] = {}
    if not path.is_file():
        return state
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        state[key.strip()] = val.strip()
    return state


def _try_parse_stream_line(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _event_timestamp(obj: dict) -> datetime | None:
    for key in ("timestamp", "ts", "created_at"):
        if obj.get(key):
            return _parse_iso_ts(str(obj[key]))
    return None


def _phase_from_doc_path(path: str) -> str | None:
    for doc, phase in PHASE_DOC_MAP.items():
        if doc in path:
            if doc == "eval-consistency.md" and "--mode=visual" in path:
                return "eval-consistency-visual"
            if doc == "eval-consistency.md" and "visual" in path.lower():
                return "eval-consistency-visual"
            return phase
    return None


def _phases_from_stream(stdout_lines: list[str]) -> list[dict[str, Any]]:
    """Infer phase boundaries from stream-json Read events on eval-*.md."""
    markers: list[tuple[str, datetime]] = []
    for line in stdout_lines:
        obj = _try_parse_stream_line(line)
        if not obj:
            continue
        ts = _event_timestamp(obj)
        if not ts:
            continue
        text = json.dumps(obj)
        phase = _phase_from_doc_path(text)
        if not phase:
            continue
        if markers and markers[-1][0] == phase:
            continue
        markers.append((phase, ts))

    phases: list[dict[str, Any]] = []
    for idx, (phase, start_ts) in enumerate(markers):
        end_ts = markers[idx + 1][1] if idx + 1 < len(markers) else None
        duration = _duration_ms(start_ts, end_ts) if end_ts else None
        entry: dict[str, Any] = {"phase": phase}
        if duration is not None:
            entry["duration_ms"] = duration
        phases.append(entry)
    return phases


def _phases_from_eval_state(state: dict[str, str]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    pipeline_start = _parse_iso_ts(state.get("pipeline_start"))

    for start_key, end_key, phase in TIMING_SPECS:
        start = _parse_iso_ts(state.get(start_key))
        end = _parse_iso_ts(state.get(end_key))
        if not start and end and pipeline_start:
            start = pipeline_start
        if not start and end and phases:
            prev_end_key = TIMING_SPECS[max(0, TIMING_SPECS.index((start_key, end_key, phase)) - 1)][1]
            start = _parse_iso_ts(state.get(prev_end_key))
        duration = _duration_ms(start, end)
        if duration is None:
            continue
        phases.append({"phase": phase, "duration_ms": duration})
    return phases


def _phases_from_artifact_mtimes(artifacts_dir: Path) -> list[dict[str, Any]]:
    """Fallback when eval-state timestamps are incomplete."""
    entries: list[tuple[float, str, int]] = []
    for phase, filename in PHASE_ARTIFACTS.items():
        path = artifacts_dir / filename
        if path.is_file():
            entries.append((path.stat().st_mtime, phase, path.stat().st_size))
    if len(entries) < 2:
        return []
    entries.sort()
    phases: list[dict[str, Any]] = []
    for idx, (mtime, phase, size) in enumerate(entries):
        duration = None
        if idx + 1 < len(entries):
            duration = max(int((entries[idx + 1][0] - mtime) * 1000), 1)
        phases.append({
            "phase": phase,
            "duration_ms": duration,
            "output_bytes": size,
        })
    return phases


def _artifact_bytes(artifacts_dir: Path, filename: str) -> int:
    path = artifacts_dir / filename
    if path.is_file():
        return path.stat().st_size
    return 0


def _non_llm_phases(artifacts_dir: Path) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
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

    screenshots_dir = artifacts_dir / "screenshots"
    if screenshots_dir.is_dir():
        shots = list(screenshots_dir.glob("*.png"))
        if shots:
            total_bytes = sum(p.stat().st_size for p in shots)
            phases.append({
                "phase": "playwright-run",
                "model": None,
                "llm_cost_usd": 0,
                "duration_ms": None,
                "output_bytes": total_bytes,
                "screenshot_count": len(shots),
            })

    if (artifacts_dir / "journey-log.json").is_file() or (
        artifacts_dir / "persona-results.json"
    ).is_file():
        phases.append({
            "phase": "validate-artifact-schemas",
            "model": None,
            "llm_cost_usd": 0,
            "duration_ms": None,
        })
    return phases


def _merge_phase_lists(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge by phase name; prefer entries with duration_ms and output_bytes."""
    merged: dict[str, dict[str, Any]] = {}
    for phase_list in lists:
        for entry in phase_list:
            name = entry.get("phase", "unknown")
            if name not in merged:
                merged[name] = dict(entry)
                continue
            existing = merged[name]
            for key, val in entry.items():
                if val is None:
                    continue
                if key not in existing or existing[key] in (None, 0, ""):
                    existing[key] = val
                elif key == "duration_ms":
                    existing[key] = max(int(existing[key]), int(val))
    return list(merged.values())


def _allocate_costs(
    phases: list[dict[str, Any]],
    *,
    total_cost: float,
    token_usage: dict,
    per_model: dict,
    default_model: str | None,
) -> list[dict[str, Any]]:
    llm_phases = [
        p for p in phases
        if p.get("phase") not in (
            "render-report.js", "validate-artifact-schemas", "playwright-run"
        )
    ]
    if not llm_phases:
        return phases

    input_tok = int(
        token_usage.get("input_tokens", 0) or token_usage.get("input", 0) or 0
    )
    output_tok = int(
        token_usage.get("output_tokens", 0) or token_usage.get("output", 0) or 0
    )

    if per_model and len(per_model) == 1:
        model_name, usage = next(iter(per_model.items()))
        weights = [
            max(p.get("duration_ms") or 1, 1) for p in llm_phases
        ]
        weight_sum = sum(weights) or len(llm_phases)
        for phase, weight in zip(llm_phases, weights):
            share = weight / weight_sum
            phase.setdefault("model", model_name)
            phase["llm_cost_usd"] = round(float(usage.get("costUSD", total_cost)) * share, 6)
            phase["input_tokens"] = int(usage.get("inputTokens", input_tok) * share)
            phase["output_tokens"] = int(usage.get("outputTokens", output_tok) * share)
        return phases

    # Multiple models or no per-model split: duration-weight total cost
    weights = [max(p.get("duration_ms") or 1, 1) for p in llm_phases]
    weight_sum = sum(weights) or len(llm_phases)
    primary_model = default_model
    if per_model:
        primary_model = max(per_model, key=lambda m: per_model[m].get("costUSD", 0))
    for phase, weight in zip(llm_phases, weights):
        share = weight / weight_sum
        phase.setdefault("model", primary_model)
        phase["llm_cost_usd"] = round(float(total_cost or 0) * share, 6)
        phase["input_tokens"] = int(input_tok * share)
        phase["output_tokens"] = int(output_tok * share)
    return phases


def build_pipeline_phases(
    artifacts_dir: Path,
    run_result: dict[str, Any],
    stdout_lines: list[str] | None = None,
) -> list[dict[str, Any]]:
    """CP-E2E-1: per-phase Langfuse children from eval-state, stream, and artifacts."""
    artifacts_dir = Path(artifacts_dir)
    state = load_eval_state(artifacts_dir)

    from_state = _phases_from_eval_state(state)
    from_stream = _phases_from_stream(stdout_lines or []) if stdout_lines else []
    from_mtimes = _phases_from_artifact_mtimes(artifacts_dir)
    merged = _merge_phase_lists(from_state, from_stream, from_mtimes)

    for entry in merged:
        artifact = PHASE_ARTIFACTS.get(entry.get("phase", ""))
        if artifact:
            entry["output_bytes"] = _artifact_bytes(artifacts_dir, artifact)

    non_llm = _non_llm_phases(artifacts_dir)
    merged = _merge_phase_lists(merged, non_llm)

    if not merged:
        per_model = run_result.get("per_model_usage") or {}
        for model_name, usage in per_model.items():
            merged.append({
                "phase": f"generation/{model_name}",
                "model": model_name,
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "llm_cost_usd": usage.get("costUSD", 0),
            })
        return merged

    return _allocate_costs(
        merged,
        total_cost=float(run_result.get("cost_usd") or 0),
        token_usage=run_result.get("token_usage") or {},
        per_model=run_result.get("per_model_usage") or {},
        default_model=run_result.get("model"),
    )


def _trace_url(client, trace_id: str) -> str:
    host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
    if not host:
        return ""
    try:
        return client.get_trace_url(trace_id=trace_id) or f"{host}/trace/{trace_id}"
    except Exception:
        return f"{host}/trace/{trace_id}"


def log_pipeline_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Log a full pipeline run to Langfuse. Returns summary with trace_url."""
    client = _get_client()
    prototype_key = payload.get("prototype_key", "unknown")
    eval_run_id = payload.get("eval_run_id") or make_eval_run_id(prototype_key)
    iterate_flags = payload.get("iterate_flags", "")
    dims = parse_iterate_flags(iterate_flags)
    invocation = payload.get("invocation", "cli")
    model = payload.get("model")
    provider = payload.get("provider") or infer_provider(model, invocation)
    model_tier = payload.get("model_tier") or infer_model_tier(model, invocation)

    run_result = payload.get("run_result", {})
    token_usage = run_result.get("token_usage") or {}
    cost_usd = run_result.get("cost_usd") or 0
    per_model = run_result.get("per_model_usage") or {}
    phases = payload.get("phases") or []

    summary = {
        "eval_run_id": eval_run_id,
        "langfuse_trace_url": "",
        "langfuse_enabled": is_enabled(),
        "llm_cost_usd": cost_usd,
        "logged": False,
    }

    if not client:
        return summary

    trace_id = langfuse_trace_id(eval_run_id)
    trace_context = {"trace_id": trace_id}
    metadata = {
        "prototype_key": prototype_key,
        "eval_run_id": eval_run_id,
        "run_mode": dims["run_mode"],
        "fix_mode": dims["fix_mode"],
        "model_tier": model_tier,
        "provider": provider,
        "billing_source": payload.get("billing_source", "unknown"),
        "invocation": invocation,
        "privacy_mode": "metadata_only",
        "iterate_flags": dims["iterate_flags"],
        "team": "uxd",
        "pipeline": "prototype-evaluator",
        "designer_id_hash": hash_user_id(
            payload.get("designer") or os.environ.get("USER") or os.environ.get("USERNAME")
        ),
    }
    if payload.get("depth_tier"):
        metadata["depth_tier"] = payload["depth_tier"]
    if payload.get("experiment"):
        metadata["experiment"] = payload["experiment"]

    try:
        # The root observation is active while children are created. Passing the
        # trace_context to every child would mark each one as another root in
        # Langfuse v4, so child observations intentionally rely on context.
        from langfuse import propagate_attributes

        with client.start_as_current_observation(
            trace_context=trace_context,
            name=f"eval-iterate/{prototype_key}",
            as_type="span",
            input=redact_text(payload.get("prompt", "")[:200]),
            metadata=metadata,
        ) as root:
            with propagate_attributes(
                user_id=metadata["designer_id_hash"],
                metadata={"prototype_key": prototype_key, "eval_run_id": eval_run_id},
                tags=["team:uxd", "pipeline:prototype-evaluator", f"provider:{provider}"],
            ):
                for phase in phases:
                    phase_name = phase.get("phase", "unknown")
                    is_llm = phase_name not in (
                        "render-report.js", "validate-artifact-schemas", "playwright-run"
                    )
                    if is_llm and phase.get("model"):
                        usage = {
                            "input": phase.get("input_tokens", 0),
                            "output": phase.get("output_tokens", 0),
                        }
                        if phase.get("cache_read_tokens"):
                            usage["cache_read_input_tokens"] = phase["cache_read_tokens"]
                        cost_details = {}
                        if phase.get("llm_cost_usd") is not None:
                            cost_details["total"] = float(phase["llm_cost_usd"])
                        client.start_observation(
                            name=phase_name,
                            as_type="generation",
                            model=phase.get("model"),
                            usage_details=usage,
                            cost_details=cost_details or None,
                            metadata={
                                "phase": phase_name,
                                "provider": phase.get("provider") or provider,
                            },
                        ).end()
                    else:
                        client.create_event(
                            name=phase_name,
                            metadata={
                                "phase": phase_name,
                                "duration_ms": phase.get("duration_ms"),
                                "output_bytes": phase.get("output_bytes"),
                                "llm_cost_usd": 0,
                            },
                        )

                if not phases and per_model:
                    for model_name, usage in per_model.items():
                        client.start_observation(
                            name=f"generation/{model_name}",
                            as_type="generation",
                            model=model_name,
                            usage_details={
                                "input": usage.get("inputTokens", 0),
                                "output": usage.get("outputTokens", 0),
                            },
                            cost_details={"total": usage.get("costUSD", 0)},
                        ).end()

                quality = payload.get("quality") or {}
                if quality:
                    for score_name, value in quality.items():
                        if value is not None and score_name != "golden_verdict":
                            try:
                                client.create_score(
                                    trace_id=trace_id,
                                    name=score_name,
                                    value=float(value) if isinstance(value, (int, float)) else value,
                                )
                            except Exception:
                                pass

                root.update(
                    output=redact_text(
                        f"cost_usd={cost_usd} tokens_in={token_usage.get('input_tokens', 0)}"
                    ),
                    metadata={**metadata, "llm_cost_usd": cost_usd},
                )

        client.flush()
        summary["langfuse_trace_url"] = _trace_url(client, trace_id)
        summary["logged"] = True
    except Exception as e:
        print(f"Langfuse export failed: {e}", file=sys.stderr)

    return summary


def log_phase_span(
    artifacts_dir: str,
    phase: str,
    action: str,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Record coarse phase boundary for Cursor runs."""
    state_path = Path(artifacts_dir) / "eval-state.yaml"
    eval_run_id = None
    if state_path.exists():
        for line in state_path.read_text().splitlines():
            if line.startswith("eval_run_id:"):
                eval_run_id = line.split(":", 1)[1].strip()
                break

    if not eval_run_id:
        key = Path(artifacts_dir).parent.name
        eval_run_id = make_eval_run_id(key)

    client = _get_client()
    if not client:
        return

    trace_id = langfuse_trace_id(eval_run_id)
    trace_context = {"trace_id": trace_id}
    meta = {"phase": phase, "action": action, "invocation": "cursor", **(metadata or {})}
    if duration_ms is not None:
        meta["duration_ms"] = duration_ms

    try:
        # This helper is invoked in separate shell processes for start/end, so
        # an observation cannot safely remain open across calls. Events preserve
        # both boundaries without leaving orphaned spans in Langfuse.
        client.create_event(
            trace_context=trace_context,
            name=f"{phase}/{action}",
            metadata=meta,
        )
        client.flush()
    except Exception as e:
        print(f"Langfuse phase span failed: {e}", file=sys.stderr)


def cmd_smoke(_args: list[str]) -> int:
    payload = {
        "prototype_key": "SMOKE-TEST",
        "eval_run_id": make_eval_run_id("SMOKE-TEST", seed="smoke"),
        "invocation": "cli",
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "iterate_flags": "--fresh --no-fix --max-iterations=1",
        "experiment": "langfuse-smoke",
        "run_result": {
            "cost_usd": 0.001,
            "token_usage": {"input_tokens": 100, "output_tokens": 50},
            "per_model_usage": {
                "gpt-5.6-terra": {
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "costUSD": 0.001,
                }
            },
        },
        "phases": [
            {
                "phase": "eval-extract",
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "input_tokens": 100,
                "output_tokens": 50,
                "llm_cost_usd": 0.001,
            },
            {
                "phase": "render-report.js",
                "duration_ms": 1200,
                "output_bytes": 2621440,
                "llm_cost_usd": 0,
            },
        ],
        "quality": {"ac_pass_rate": 1.0},
    }
    result = log_pipeline_run(payload)
    print(json.dumps(result, indent=2))
    if not is_enabled():
        print("LANGFUSE_* not set — smoke ran in dry-run mode", file=sys.stderr)
        return 0
    return 0 if result.get("logged") else 1


def cmd_phase(args: argparse.Namespace) -> int:
    log_phase_span(
        args.artifacts_dir,
        args.phase,
        args.action,
        duration_ms=args.duration_ms,
    )
    return 0


def cmd_log_pipeline(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.json_file).read_text())
    result = log_pipeline_run(payload)
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Langfuse trace helper")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("smoke")

    phase_p = sub.add_parser("phase")
    phase_p.add_argument("--artifacts-dir", required=True)
    phase_p.add_argument("--phase", required=True, choices=sorted(PHASE_NAMES))
    phase_p.add_argument("--action", required=True, choices=["start", "end"])
    phase_p.add_argument("--duration-ms", type=int, default=None)

    log_p = sub.add_parser("log-pipeline")
    log_p.add_argument("--json-file", required=True)

    args = parser.parse_args()
    if args.command == "smoke":
        return cmd_smoke([])
    if args.command == "phase":
        return cmd_phase(args)
    if args.command == "log-pipeline":
        return cmd_log_pipeline(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
