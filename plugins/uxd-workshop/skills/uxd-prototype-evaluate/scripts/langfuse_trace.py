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
    "validate-artifact-schemas", "playwright-run", "source-reader",
    "uxd-consistency-check", "uxd-prototype-create",
    "uxd-prototype-evaluate", "prototype-iteration",
})

NON_LLM_PHASES = frozenset({
    "eval-consistency-source",
    "render-report.js",
    "validate-artifact-schemas",
    "playwright-run",
    "source-reader",
    "uxd-consistency-check",
    "uxd-prototype-create",
    "prototype-iteration",
})

PHASE_METADATA_FIELDS = frozenset({
    "acceptance_criteria",
    "affected_files",
    "after_match_count",
    "artifact_sha256",
    "audience",
    "base_ref",
    "before_match_count",
    "changed_file_count",
    "changed_files",
    "changed_line_count",
    "decision_count",
    "fixed_count",
    "guideline_count",
    "guidelines_version",
    "high_confidence_findings",
    "issue_count",
    "match_count",
    "source_mode",
    "status",
    "review_candidates",
    "screenshots_analyzed",
    "screenshots_considered",
    "guidelines_analyzed",
    "input_bytes",
    "violation_groups",
    "warning_groups",
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


def complete_redacted_text(text: str | None) -> str | None:
    """Redact secrets without truncating telemetry payloads."""
    if text is None:
        return None
    return redact_text(text, max_chars=max(len(str(text)), MAX_TEXT_CHARS))


def content_sha256(text: str | None) -> str:
    return hashlib.sha256(str(text or "").encode()).hexdigest()


def langfuse_usage(phase: dict[str, Any]) -> dict[str, int]:
    """Map OpenAI inclusive input usage to Langfuse exclusive cache fields."""
    total_input = int(phase.get("input_tokens", 0) or 0)
    cache_read = int(phase.get("cache_read_tokens", 0) or 0)
    return {
        "input": max(total_input - cache_read, 0),
        "output": int(phase.get("output_tokens", 0) or 0),
        "cache_read_input_tokens": min(cache_read, total_input),
    }


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


def detect_invocation(explicit: str | None = None) -> str:
    """Identify the agent host without falsely attributing phase events."""
    invocation = (
        explicit
        or os.environ.get("LANGFUSE_INVOCATION")
        or os.environ.get("AI_HELPERS_PLATFORM")
    )
    if invocation:
        normalized = invocation.strip().lower()
        if normalized in {"api", "anthropic", "cli", "codex", "cursor"}:
            return normalized
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
        return "codex"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_SESSION_ID"):
        return "cursor"
    return "cli"


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

    consistency_path = artifacts_dir / "consistency-report.json"
    if consistency_path.is_file():
        try:
            report = json.loads(consistency_path.read_text())
            summary = report.get("summary") or {}
            source_mode = report.get("source_mode") or {}
            visual_mode = report.get("visual_mode") or {}
            visual_metrics = visual_mode.get("input_metrics") or {}
            source_findings = source_mode.get("violations") or []
            affected_files = {
                finding.get("file") for finding in source_findings if finding.get("file")
            }
            phases.append({
                "phase": "uxd-consistency-check",
                "model": None,
                "llm_cost_usd": 0,
                "output_bytes": consistency_path.stat().st_size,
                "guideline_count": summary.get("total_guidelines_checked", 0),
                "guidelines_version": report.get("guidelines_version", "unknown"),
                "violation_groups": summary.get("violations", 0),
                "warning_groups": summary.get("warnings", 0),
                "match_count": len(source_findings),
                "affected_files": len(affected_files),
                "source_mode": bool(source_mode.get("ran")),
                "audience": ["developer", "designer"],
            })
            if visual_mode.get("ran") and visual_metrics:
                phases.append({
                    "phase": "eval-consistency-visual",
                    "screenshots_considered": visual_metrics.get("screenshots_considered", 0),
                    "screenshots_analyzed": visual_metrics.get("screenshots_analyzed", 0),
                    "guidelines_analyzed": visual_metrics.get("guidelines_analyzed", 0),
                    "input_bytes": visual_metrics.get("input_bytes", 0),
                })
        except (json.JSONDecodeError, OSError):
            pass
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
        if p.get("phase") not in NON_LLM_PHASES
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


def pipeline_run_status(run_result: dict[str, Any]) -> str:
    explicit = str(run_result.get("status") or "").lower()
    if explicit in {"completed", "blocked", "failed"}:
        return explicit
    if int(run_result.get("exit_code", 0) or 0) != 0:
        return "failed"
    output = str(run_result.get("output_text") or "").lower()
    if "workflow blocked" in output or "blocked at preflight" in output:
        return "blocked"
    return "completed"


def _trace_values(payload: dict[str, Any]) -> dict[str, Any]:
    prototype_key = payload.get("prototype_key", "unknown")
    eval_run_id = payload.get("eval_run_id") or make_eval_run_id(prototype_key)
    dims = parse_iterate_flags(payload.get("iterate_flags", ""))
    invocation = payload.get("invocation", "cli")
    model = payload.get("model")
    provider = payload.get("provider") or infer_provider(model, invocation)
    model_tier = payload.get("model_tier") or infer_model_tier(model, invocation)
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
    return {
        "prototype_key": prototype_key,
        "eval_run_id": eval_run_id,
        "provider": provider,
        "model": model,
        "metadata": metadata,
        "trace_id": langfuse_trace_id(eval_run_id),
    }


def _record_pipeline_content(
    client,
    root,
    payload: dict[str, Any],
    values: dict[str, Any],
    *,
    skip_phases: frozenset[str] = frozenset(),
) -> None:
    run_result = payload.get("run_result", {})
    token_usage = run_result.get("token_usage") or {}
    cost_usd = run_result.get("cost_usd") or 0
    per_model = run_result.get("per_model_usage") or {}
    status = pipeline_run_status(run_result)
    level = "ERROR" if status == "failed" else "WARNING" if status == "blocked" else "DEFAULT"

    for phase in payload.get("phases") or []:
        phase_name = phase.get("phase", "unknown")
        if phase_name in skip_phases:
            continue
        phase_metadata = {
            key: value for key, value in phase.items()
            if key in PHASE_METADATA_FIELDS and value is not None
        }
        is_llm = phase_name not in NON_LLM_PHASES
        if is_llm and phase.get("model"):
            usage = langfuse_usage(phase)
            cost_details = {}
            if phase.get("llm_cost_usd") is not None:
                cost_details["total"] = float(phase["llm_cost_usd"])
            observation = client.start_observation(
                name=phase_name,
                as_type="generation",
                model=phase.get("model"),
                input=complete_redacted_text(payload.get("prompt", "")),
                output=complete_redacted_text(run_result.get("output_text")),
                usage_details=usage,
                cost_details=cost_details or None,
                level=level,
                metadata={
                    "phase": phase_name,
                    "provider": phase.get("provider") or values["provider"],
                    "status": status,
                    **phase_metadata,
                },
            )
            observation.end()
        else:
            client.create_event(
                name=phase_name,
                metadata={
                    "phase": phase_name,
                    "duration_ms": phase.get("duration_ms"),
                    "output_bytes": phase.get("output_bytes"),
                    "llm_cost_usd": 0,
                    **phase_metadata,
                },
            )

    if not payload.get("phases") and per_model:
        for model_name, usage in per_model.items():
            client.start_observation(
                name=f"generation/{model_name}",
                as_type="generation",
                model=model_name,
                input=redact_text(payload.get("prompt", "")[:200]),
                output=redact_text(run_result.get("output_text")),
                usage_details={
                    "input": usage.get("inputTokens", 0),
                    "output": usage.get("outputTokens", 0),
                },
                cost_details={"total": usage.get("costUSD", 0)},
                level=level,
                metadata={"status": status},
            ).end()

    for score_name, value in (payload.get("quality") or {}).items():
        if value is not None and score_name != "golden_verdict":
            try:
                client.create_score(
                    trace_id=values["trace_id"],
                    name=score_name,
                    value=float(value) if isinstance(value, (int, float)) else value,
                )
            except Exception:
                pass

    output = run_result.get("output_text") or (
        f"cost_usd={cost_usd} tokens_in={token_usage.get('input_tokens', 0)}"
    )
    root.update(
        output=redact_text(output),
        level=level,
        status_message=redact_text(output, 200),
        metadata={
            **values["metadata"],
            "status": status,
            "duration_ms": int(float(run_result.get("duration_s") or 0) * 1000),
            "llm_cost_usd": cost_usd,
            "billing_source": run_result.get("billing_source", "unknown"),
        },
    )


class LivePipelineTrace:
    """Keep Langfuse observations open for the actual model runtime."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.values = _trace_values(payload)
        self.client = _get_client()
        self.root = None
        self.generation = None
        self._root_context = None
        self._attributes_context = None
        self.live_phase_names: set[str] = set()
        self.finished = False
        self.summary = {
            "eval_run_id": self.values["eval_run_id"],
            "langfuse_trace_url": "",
            "langfuse_enabled": bool(self.client),
            "llm_cost_usd": 0,
            "logged": False,
        }

    def __enter__(self):
        if not self.client:
            return self
        from langfuse import propagate_attributes

        self._root_context = self.client.start_as_current_observation(
            trace_context={"trace_id": self.values["trace_id"]},
            name=f"eval-iterate/{self.values['prototype_key']}",
            as_type="span",
            input=complete_redacted_text(self.payload.get("prompt", "")),
            metadata=self.values["metadata"],
        )
        self.root = self._root_context.__enter__()
        self._attributes_context = propagate_attributes(
            user_id=self.values["metadata"]["designer_id_hash"],
            metadata={
                "prototype_key": self.values["prototype_key"],
                "eval_run_id": self.values["eval_run_id"],
            },
            tags=[
                "team:uxd",
                "pipeline:prototype-evaluator",
                f"provider:{self.values['provider']}",
            ],
        )
        self._attributes_context.__enter__()
        self.generation = self.client.start_observation(
            name="uxd-prototype-evaluate",
            as_type="span",
            input=complete_redacted_text(self.payload.get("prompt", "")),
            metadata={
                "phase": "uxd-prototype-evaluate",
                "provider": self.values["provider"],
                "status": "running",
                "telemetry_role": "pipeline-summary-no-usage",
            },
        )
        return self

    def start_phase(self, *, name: str, model: str, input_text: str):
        """Open a model phase while its provider work is actually running."""
        if not self.client or not self.root:
            return None
        observation = self.client.start_observation(
            name=name,
            as_type="generation",
            model=model,
            input=complete_redacted_text(input_text),
            metadata={
                "phase": name,
                "provider": self.values["provider"],
                "status": "running",
                "input_chars": len(input_text),
                "input_sha256": content_sha256(input_text),
                "input_complete": True,
            },
        )
        self.live_phase_names.add(name)
        return observation

    def finish_phase(self, observation, *, phase: dict[str, Any], output_text: str) -> None:
        """Close a live model phase with exact usage, cost, and status."""
        if observation is None:
            return
        phase_status = phase.get("status", "failed")
        level = "ERROR" if phase_status == "failed" else "DEFAULT"
        observation.update(
            output=complete_redacted_text(output_text),
            usage_details=langfuse_usage(phase),
            cost_details={"total": float(phase.get("llm_cost_usd", 0) or 0)},
            level=level,
            status_message=redact_text(output_text, 200),
            metadata={
                "phase": phase.get("phase"),
                "provider": phase.get("provider") or self.values["provider"],
                "status": phase_status,
                "duration_ms": phase.get("duration_ms"),
                "turns_used": phase.get("turns_used"),
                "validation": phase.get("validation"),
                "output_chars": len(output_text),
                "output_sha256": content_sha256(output_text),
                "output_complete": True,
            },
        )
        observation.end()

    def finish(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        run_result = payload.get("run_result", {})
        status = pipeline_run_status(run_result)
        level = "ERROR" if status == "failed" else "WARNING" if status == "blocked" else "DEFAULT"
        cost = float(run_result.get("cost_usd") or 0)
        self.summary["llm_cost_usd"] = cost

        if self.client and self.generation and self.root:
            self.generation.update(
                output=complete_redacted_text(run_result.get("output_text")),
                level=level,
                status_message=redact_text(run_result.get("output_text"), 200),
                metadata={
                    "phase": "uxd-prototype-evaluate",
                    "provider": self.values["provider"],
                    "status": status,
                    "duration_ms": int(float(run_result.get("duration_s") or 0) * 1000),
                    "billing_source": run_result.get("billing_source", "unknown"),
                    "telemetry_role": "pipeline-summary-no-usage",
                },
            )
            self.generation.end()
            self.generation = None
            _record_pipeline_content(
                self.client,
                self.root,
                payload,
                self.values,
                skip_phases=frozenset({"uxd-prototype-evaluate", *self.live_phase_names}),
            )
            self.finished = True
        return self.summary

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.generation:
                self.generation.update(
                    level="ERROR",
                    status_message=redact_text(str(exc_value or "pipeline ended before finish"), 200),
                )
                self.generation.end()
                self.generation = None
            if self.root and not self.finished:
                self.root.update(
                    level="ERROR",
                    status_message=redact_text(str(exc_value or "pipeline ended before finish"), 200),
                )
        finally:
            if self._attributes_context:
                self._attributes_context.__exit__(exc_type, exc_value, traceback)
            if self._root_context:
                self._root_context.__exit__(exc_type, exc_value, traceback)
            if self.client:
                self.client.flush()
                self.summary["langfuse_trace_url"] = _trace_url(
                    self.client, self.values["trace_id"]
                )
                self.summary["logged"] = self.finished
                self.client.shutdown()
        return False


def log_pipeline_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Log a full pipeline run to Langfuse. Returns summary with trace_url."""
    client = _get_client()
    values = _trace_values(payload)
    run_result = payload.get("run_result", {})
    cost_usd = run_result.get("cost_usd") or 0
    summary = {
        "eval_run_id": values["eval_run_id"],
        "langfuse_trace_url": "",
        "langfuse_enabled": is_enabled(),
        "llm_cost_usd": cost_usd,
        "logged": False,
    }

    if not client:
        return summary

    try:
        from langfuse import propagate_attributes

        with client.start_as_current_observation(
            trace_context={"trace_id": values["trace_id"]},
            name=f"eval-iterate/{values['prototype_key']}",
            as_type="span",
            input=redact_text(payload.get("prompt", "")[:200]),
            metadata=values["metadata"],
        ) as root:
            with propagate_attributes(
                user_id=values["metadata"]["designer_id_hash"],
                metadata={
                    "prototype_key": values["prototype_key"],
                    "eval_run_id": values["eval_run_id"],
                },
                tags=[
                    "team:uxd",
                    "pipeline:prototype-evaluator",
                    f"provider:{values['provider']}",
                ],
            ):
                _record_pipeline_content(client, root, payload, values)

        client.flush()
        summary["langfuse_trace_url"] = _trace_url(client, values["trace_id"])
        summary["logged"] = True
    except Exception as e:
        print(f"Langfuse export failed: {e}", file=sys.stderr)
    finally:
        client.shutdown()

    return summary


def log_phase_span(
    artifacts_dir: str,
    phase: str,
    action: str,
    duration_ms: int | None = None,
    metadata: dict | None = None,
    invocation: str | None = None,
) -> None:
    """Record a coarse phase boundary for the active agent host."""
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
    safe_metadata = {
        key: value for key, value in (metadata or {}).items()
        if key in PHASE_METADATA_FIELDS and value is not None
    }
    meta = {
        "phase": phase,
        "action": action,
        "invocation": detect_invocation(invocation),
        **safe_metadata,
    }
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
    metadata = None
    if args.metadata_file:
        metadata = json.loads(Path(args.metadata_file).read_text())
        if not isinstance(metadata, dict):
            raise ValueError("phase metadata file must contain a JSON object")
    log_phase_span(
        args.artifacts_dir,
        args.phase,
        args.action,
        duration_ms=args.duration_ms,
        metadata=metadata,
        invocation=args.invocation,
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
    phase_p.add_argument(
        "--invocation",
        choices=["api", "anthropic", "cli", "codex", "cursor"],
        default=None,
        help="Agent host; auto-detected when omitted",
    )
    phase_p.add_argument("--duration-ms", type=int, default=None)
    phase_p.add_argument(
        "--metadata-file",
        help="Path to a metadata-only JSON object; never include source or Jira text",
    )

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
