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
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from model_pricing import PRICING as OPENAI_PRICING_PER_MTOK, estimated_cost

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

MAX_TEXT_CHARS = 500
MAX_SANITIZED_ARTIFACT_CHARS = 20_000
PHASE_NAMES = frozenset({
    "eval-extract", "eval-classify", "eval-consistency-source",
    "eval-journey", "eval-fix", "eval-consistency-visual", "eval-heuristic",
    "eval-usability", "eval-report", "render-report.js",
    "validate-artifact-schemas", "playwright-run", "source-reader",
    "uxd-consistency-check", "uxd-prototype-create",
    "uxd-prototype-evaluate", "prototype-iteration",
    "create-plan", "create-generate", "create-refine",
})

NON_LLM_PHASES = frozenset({
    "eval-consistency-source",
    "render-report.js",
    "validate-artifact-schemas",
    "playwright-run",
    "source-reader",
    "uxd-consistency-check",
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
    # Compact decision and reliability metrics. These are intentionally
    # allowlisted so phase telemetry cannot accidentally include raw output.
    "phase_decision",
    "phase_decisions",
    "decision_count",
    "decision_counts",
    "error_category",
    "error_categories",
    "recovery_action",
    "recovery_actions",
    "retries",
    "fallbacks",
    "turns_used",
    "confidence_available",
    "confidence_count",
    "confidence_mean",
    "confidence_min",
    "confidence_max",
    "verdict_counts",
    "finding_count",
    "skipped",
    "skip_reason",
    "parity",
    "semantic_parity",
    "screenshot_count",
    "screenshot_dimensions",
    "screenshot_bytes",
    "crop_pixel_reduction",
    "crop_byte_reduction",
    "artifact_count",
    "artifact_bytes",
    "artifact_manifest",
    "expected_outputs_present",
    "tool_calls",
    "tool_failures",
})

BENCHMARK_FIELDS = (
    "benchmark_name",
    "comparison_id",
    "condition",
    "prototype_key",
    "build_key",
    "evaluator_key",
    "provider_model",
    "cache_decision",
    "screenshot_mode",
    "artifact_mode",
    "csv_used",
)

PHASE_DISPLAY_ORDER = {
    "eval-consistency-source": (1, "deterministic"),
    "eval-extract": (2, "deterministic"),
    "eval-classify": (3, "deterministic"),
    "eval-journey": (4, "paid"),
    "eval-fix": (5, "paid"),
    "eval-consistency-visual": (6, "paid"),
    "eval-heuristic": (7, "paid"),
    "eval-usability": (8, "paid"),
    "eval-report": (9, "deterministic"),
    "create-plan": (20, "creator-paid"),
    "create-generate": (21, "creator-paid"),
    "create-refine": (22, "creator-paid"),
}

# One authority for OpenAI study pricing, reservations, settlement, and trace
# allocation. Bounds are worst-case ceilings: observed maxima get 25% headroom
# and round up; visual input uses the static 5,000-finding prompt ceiling.
OPENAI_CAP_USD = 25.0
OPENAI_PHASE_BOUNDS = {
    # Highest completed journey usage was 8,022 input / 1,291 output tokens.
    # Apply the documented 25% headroom and round each token bound upward.
    "eval-journey": (10_028, 1_614),
    "eval-fix": (80_000, 12_000),
    "eval-consistency-visual": (991_781, 400),
    "eval-heuristic": (120_000, 16_000),
    "eval-usability": (60_000, 2_500),
}


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
    s = re.sub(r"(?i)\bpk-lf-[A-Za-z0-9_-]{10,}", "[REDACTED_KEY]", s)
    s = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[REDACTED_KEY]", s)
    s = re.sub(
        r"(?i)\b(?:Bearer|Basic|Token|ApiKey)\s+[A-Za-z0-9._~+/-]+=*",
        lambda match: match.group(0).split()[0] + " [REDACTED]",
        s,
    )
    s = re.sub(
        r"(?im)(authorization\s*[:=]\s*)(?:(?:bearer|basic|token|apikey)\s+)?[^\s,;]+",
        r"\1[REDACTED]",
        s,
    )
    s = re.sub(r"(?im)((?:set-cookie|cookie)\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", s)
    s = re.sub(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret[_-]?key)\b\s*[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]+",
        r"\1[REDACTED]",
        s,
    )
    s = re.sub(
        r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|token|secret)=)[^&#\s]+",
        r"\1[REDACTED]",
        s,
    )
    for name, value in os.environ.items():
        if re.search(r"(?i)(key|token|secret|password|cookie|credential)", name) and len(value) >= 8:
            s = s.replace(value, "[REDACTED_ENV_SECRET]")
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", s)
    if len(s) > max_chars:
        return s[:max_chars] + f"... [truncated {len(s) - max_chars} chars]"
    return s


def complete_redacted_text(text: str | None) -> str | None:
    """Redact secrets without truncating telemetry payloads."""
    if text is None:
        return None
    return redact_text(text, max_chars=max(len(str(text)), MAX_TEXT_CHARS))


def redact_content(value: Any) -> Any:
    """Redact credential-shaped strings recursively without removing product content."""
    def sensitive_key(key: Any) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        return any(normalized.endswith(name) for name in (
            "authorization", "cookie", "apikey", "publickey", "accesstoken", "refreshtoken",
            "clientsecret", "secretkey", "password", "credential", "credentials",
            "privatekey", "token", "secret",
        ))

    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if sensitive_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_content(item)
        return result
    if isinstance(value, list):
        return [redact_content(item) for item in value]
    if isinstance(value, tuple):
        return [redact_content(item) for item in value]
    if isinstance(value, bytes):
        return "[BINARY_REDACTED]"
    if isinstance(value, str):
        return complete_redacted_text(value)
    return value


def model_response_for_trace(value: Any) -> Any:
    """Keep provider-visible answers and tool calls; omit private reasoning items."""
    if not isinstance(value, dict):
        return redact_content(value)
    response = dict(value)
    output = response.get("output")
    if isinstance(output, list):
        response["output"] = [
            item for item in output
            if not isinstance(item, dict) or item.get("type") != "reasoning"
        ]
    return redact_content(response)


def full_artifact_bundle(
    artifacts_dir: Path,
    *,
    include_paths: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Read complete non-credential artifacts for the explicit full trace profile.

    Callers may scope capture to run outputs and changed source files. This is
    important for creator runs whose ``code/`` directory is a full checkout:
    the staged inputs and generated edits belong in the trace, the whole source
    repository does not.
    """
    import base64

    root = Path(artifacts_dir).resolve()
    bundle = []
    selected = None
    if include_paths is not None:
        selected = set()
        for value in include_paths:
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("artifact include paths must stay inside the artifact root")
            selected.add(relative.as_posix())
    credential_extensions = {".key", ".pem", ".p12", ".pfx", ".keystore"}
    candidates = (
        (root / relative for relative in selected)
        if selected is not None
        else root.rglob("*")
    )
    for path in sorted(candidates):
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        if not path.is_file() or any(
            part in {"benchmark", "node_modules", ".git"} for part in path.relative_to(root).parts
        ) or path.name.endswith(".tmp"):
            continue
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        normalized_name = path.name.lower()
        credential_named = (
            normalized_name.startswith(".env")
            or bool(re.search(r"(^|[._-])(auth|authorization|credential|credentials|token|tokens|cookie|cookies|secret|secrets)([._-]|$)", normalized_name))
            or path.suffix.lower() in credential_extensions
        )
        if credential_named:
            content = {"encoding": "omitted", "reason": "credential_file"}
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                mime_type = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
                content = {
                    "encoding": "data-uri",
                    "mime_type": mime_type,
                    "data": f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}",
                }
            else:
                content = {"encoding": "utf-8", "text": text}
        bundle.append({
            "path": relative,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content": redact_content(content),
        })
    return bundle


def sanitized_artifact(artifacts_dir: Path, filename: str) -> dict[str, Any] | None:
    """Return bounded artifact output with no screenshot, binary, or source fields."""
    path = Path(artifacts_dir) / filename
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, (dict, list)):
        return None

    blocked_key_parts = (
        "screenshot", "image", "binary", "base64", "attachment", "media",
        "crop", "raw_", "path", "locator", "url", "dom", "html",
    )

    def scrub(value: Any, *, depth: int = 0) -> Any:
        if depth > 8:
            return "[truncated depth]"
        if isinstance(value, dict):
            return {
                str(key): scrub(item, depth=depth + 1)
                for key, item in value.items()
                if not any(part in str(key).lower() for part in blocked_key_parts)
            }
        if isinstance(value, list):
            return [scrub(item, depth=depth + 1) for item in value[:50]]
        if isinstance(value, str):
            return redact_text(value, max_chars=500)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[unsupported value]"

    content = scrub(raw)
    encoded = json.dumps(content, separators=(",", ":"), ensure_ascii=True)
    if len(encoded) > MAX_SANITIZED_ARTIFACT_CHARS:
        content = (
            {
                "artifact_type": content.get("artifact_type"),
                "schema_version": content.get("schema_version"),
                "status": content.get("status"),
                "summary": content.get("summary"),
                "truncated": True,
            }
            if isinstance(content, dict)
            else {"item_count": len(content), "truncated": True}
        )
    return {
        "artifact": filename,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content": content,
    }


def sanitized_evaluation_artifact(artifacts_dir: Path) -> dict[str, Any] | None:
    return sanitized_artifact(artifacts_dir, "evaluation.json")


def consistency_visual_judge_envelope(artifacts_dir: Path) -> dict[str, Any] | None:
    """Project visual findings into a compact, privacy-safe judge contract.

    The full consistency report contains source-mode paths and may become large.
    A judge needs visual verdicts and remediation, not screenshots, DOM, URLs,
    source locations, or Jira context.
    """
    path = Path(artifacts_dir) / "consistency-report.json"
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict):
        return None

    visual = report.get("visual_mode")
    visual = visual if isinstance(visual, dict) else {}
    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    raw_findings = visual.get("findings")
    raw_findings = raw_findings if isinstance(raw_findings, list) else []
    findings = []
    for item in raw_findings[:50]:
        if not isinstance(item, dict):
            continue
        findings.append({
            "guideline": {
                "id": redact_text(item.get("guideline_id"), 120) or "unknown",
                "title": redact_text(item.get("guideline_title"), 180) or "",
                "category": redact_text(item.get("category"), 80) or "",
            },
            "severity": redact_text(item.get("severity"), 40) or "warning",
            "verdict": redact_text(item.get("verdict"), 40) or "FLAGGED",
            "finding": redact_text(item.get("description"), 500) or "",
            "remediation": redact_text(item.get("suggestion"), 500) or "",
        })
    finding_count = len(findings)
    return {
        "artifact": "consistency-report.json",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content": {
            "artifact_type": "uxd-consistency-visual-judge-envelope",
            "schema_version": "1.0",
            "status": "completed",
            "summary": {
                "total_guidelines_checked": int(summary.get("total_guidelines_checked", 0) or 0),
                "violations": int(summary.get("violations", 0) or 0),
                "warnings": int(summary.get("warnings", 0) or 0),
                "passes": int(summary.get("passes", 0) or 0),
                "screenshots_checked": int(visual.get("screenshots_checked", 0) or 0),
                "visual_finding_count": finding_count,
            },
            "verdict": "PASS" if finding_count == 0 else "FLAGGED",
            # Keep the zero-finding case explicit. An empty object was scored
            # as an incomplete artifact in completed benchmark traces.
            "findings": findings,
        },
    }


def sanitized_phase_artifact(phase: str, artifacts_dir: Path) -> dict[str, Any] | None:
    filenames = {
        "eval-journey": "journey-log.json",
        "eval-fix": "fix-log.json",
        "eval-consistency-visual": "consistency-report.json",
        "eval-heuristic": "heuristic-evaluation.json",
        "eval-usability": "persona-results.json",
    }
    if phase == "eval-consistency-visual":
        return consistency_visual_judge_envelope(artifacts_dir)
    filename = filenames.get(phase)
    return sanitized_artifact(artifacts_dir, filename) if filename else None


def telemetry_artifact_output(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Only opt-in, pre-sanitized structured output can enter a trace."""
    if payload.get("privacy_mode") != "sanitized_artifact_output":
        return None
    value = payload.get("sanitized_artifact_output")
    return value if isinstance(value, dict) else None


def high_detail_image_tokens(width: int, height: int) -> int:
    """Compute the documented 512px high-detail tiling estimate, with no API call."""
    width, height = max(int(width), 1), max(int(height), 1)
    scale = min(1.0, 2048 / max(width, height))
    width, height = width * scale, height * scale
    scale = 768 / min(width, height)
    tiles = math.ceil(width * scale / 512) * math.ceil(height * scale / 512)
    return 85 + 170 * tiles


def calibration_image_token_expectations(artifacts_dir: Path) -> dict[str, Any]:
    """Estimate high/auto vision input bounds from canonical targeted-crop dimensions."""
    try:
        evidence = json.loads((Path(artifacts_dir) / "evidence.json").read_text())
    except (OSError, json.JSONDecodeError):
        evidence = {}
    crops = []
    for item in evidence.get("items") or []:
        image = item.get("image") or {}
        if not isinstance(image.get("width"), int) or not isinstance(image.get("height"), int):
            continue
        high = high_detail_image_tokens(image["width"], image["height"])
        crops.append({
            "id": item.get("id", "unknown"),
            "width": image["width"], "height": image["height"],
            "high_detail_tokens": high,
            # auto selection is model-controlled. High-detail tiling is its safe,
            # comparable expectation until a provider response proves otherwise.
            "auto_detail_expected_tokens": high,
            "auto_assumption": "conservative_high_tiling_bound",
        })
    total_high = sum(crop["high_detail_tokens"] for crop in crops)
    return {
        "model_invoked": False,
        "formula": "85 + 170 * ceil(scaled_width/512) * ceil(scaled_height/512); max side 2048, min side 768",
        "crops": crops,
        "high_detail_tokens": total_high,
        "auto_detail_expected_tokens": total_high,
        "measurement_status": "not_measured",
    }


def error_category(detail: str | None) -> str:
    """Map failures to a small privacy-safe category without logging detail."""
    value = str(detail or "").lower()
    if any(token in value for token in ("missing required", "missing required input", "no screenshots", "does not exist")):
        return "missing_input"
    if any(token in value for token in ("max_turns", "turn budget", "turn_limit", "turn limit")):
        return "turn_budget"
    if any(token in value for token in ("timed out", "timeout", "time limit")):
        return "timeout"
    if any(token in value for token in ("401", "403", "api key", "authentication", "unauthorized")):
        return "provider_auth"
    if any(token in value for token in ("responses api", "http ", "connection", "urlopen")):
        return "provider_transport"
    if any(token in value for token in ("schema", "invalid json", "validation", "validator")):
        return "validation"
    if any(token in value for token in ("playwright", "browser", "screenshot")):
        return "browser_capture"
    if any(token in value for token in ("cache", "compound key")):
        return "cache"
    return "runtime"


def content_sha256(text: str | None) -> str:
    return hashlib.sha256(str(text or "").encode()).hexdigest()


def langfuse_usage(phase: dict[str, Any]) -> dict[str, int]:
    """Map OpenAI inclusive input usage to Langfuse exclusive cache fields."""
    total_input = int(phase.get("input_tokens", 0) or 0)
    cache_read = int(phase.get("cache_read_tokens", 0) or 0)
    cache_write = int(phase.get("cache_write_tokens", 0) or 0)
    return {
        "input": max(total_input - cache_read - cache_write, 0),
        "output": int(phase.get("output_tokens", 0) or 0),
        "cache_read_input_tokens": min(cache_read, total_input),
        "cache_write_input_tokens": min(cache_write, max(total_input - cache_read, 0)),
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


def injected_trace_context() -> dict[str, str] | None:
    """Return launcher-provided W3C context only when both IDs are valid."""
    trace_id = os.environ.get("LANGFUSE_TRACE_ID", "")
    parent_span_id = os.environ.get("LANGFUSE_PARENT_SPAN_ID", "")
    if re.fullmatch(r"[0-9a-f]{32}", trace_id) and re.fullmatch(r"[0-9a-f]{16}", parent_span_id):
        return {"trace_id": trace_id, "parent_span_id": parent_span_id}
    return None


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
    "eval-heuristic": "heuristic-evaluation.json",
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


def _artifact_run_started(artifacts_dir: Path) -> datetime | None:
    """Read this run's canonical creation time to exclude leftover artifacts."""
    try:
        state = json.loads((Path(artifacts_dir) / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    started = _parse_iso_ts(state.get("created_at"))
    if started:
        return started
    legacy = load_eval_state(Path(artifacts_dir))
    return _parse_iso_ts(legacy.get("pipeline_start"))


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


def _phases_from_eval_state(state: dict[str, str], run_started: datetime | None = None) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    pipeline_start = _parse_iso_ts(state.get("pipeline_start"))

    for start_key, end_key, phase in TIMING_SPECS:
        start = _parse_iso_ts(state.get(start_key))
        end = _parse_iso_ts(state.get(end_key))
        if run_started and end and end < run_started:
            continue
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


def _phases_from_artifact_mtimes(artifacts_dir: Path, run_started: datetime | None = None) -> list[dict[str, Any]]:
    """Fallback when eval-state timestamps are incomplete."""
    entries: list[tuple[float, str, int]] = []
    for phase, filename in PHASE_ARTIFACTS.items():
        path = artifacts_dir / filename
        if path.is_file():
            mtime = path.stat().st_mtime
            if run_started and mtime < run_started.timestamp() - 1:
                continue
            entries.append((mtime, phase, path.stat().st_size))
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


def _non_llm_phases(artifacts_dir: Path, run_started: datetime | None = None) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    def fresh(path: Path) -> bool:
        return path.is_file() and (run_started is None or path.stat().st_mtime >= run_started.timestamp() - 1)
    metrics_path = artifacts_dir / "render-metrics.json"
    if fresh(metrics_path):
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
        shots = [path for path in screenshots_dir.glob("*.png") if fresh(path)]
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

    if fresh(artifacts_dir / "journey-log.json") or fresh(artifacts_dir / "persona-results.json"):
        phases.append({
            "phase": "validate-artifact-schemas",
            "model": None,
            "llm_cost_usd": 0,
            "duration_ms": None,
        })

    consistency_path = artifacts_dir / "consistency-report.json"
    if fresh(consistency_path):
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
    default_model: str | None,
) -> list[dict[str, Any]]:
    """Normalize legacy phase fields without inventing or reallocating spend.

    OpenAICostAuthority is the only writer of OpenAI cost. Historical callers
    without phase settlement retain zero cost rather than a duration-weighted
    attribution that could disagree with the provider ledger.
    """
    llm_phases = [
        p for p in phases
        if p.get("phase") not in NON_LLM_PHASES
    ]
    if not llm_phases:
        return phases

    for phase in llm_phases:
        phase.setdefault("model", default_model)
        phase.setdefault("llm_cost_usd", 0)
    return phases


class OpenAICostAuthority:
    """Bounded OpenAI spend reservation and settlement for one program ledger."""

    def __init__(
        self,
        cap_usd: float = OPENAI_CAP_USD,
        ledger_path: Path | None = None,
        *,
        phase_bounds: dict[str, tuple[int, int]] | None = None,
        reservation_namespace: str | None = None,
    ):
        self.cap_usd = float(cap_usd)
        self.ledger_path = Path(ledger_path).resolve() if ledger_path else None
        self.phase_bounds = phase_bounds if phase_bounds is not None else OPENAI_PHASE_BOUNDS
        self.reservation_namespace = reservation_namespace
        self.completed_usd = 0.0
        self.active_reservations: dict[str, float] = {}
        self.pending_usage_unknown: set[str] = set()
        self.events: list[dict[str, Any]] = []
        if self.ledger_path and self.ledger_path.exists():
            self._load_ledger()

    def _load_ledger(self) -> None:
        try:
            ledger = json.loads(self.ledger_path.read_text())
            stored_cap = float(ledger["cap_usd"])
            completed = float(ledger["completed_openai_usd"])
            active = {
                str(key): float(value)
                for key, value in (ledger.get("active_reservations") or {}).items()
            }
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ValueError(f"OpenAI budget ledger is invalid: {self.ledger_path}") from error
        if stored_cap != self.cap_usd or completed < 0 or any(value < 0 for value in active.values()):
            raise ValueError(f"OpenAI budget ledger has invalid cap or balances: {self.ledger_path}")
        self.completed_usd = completed
        self.active_reservations = active
        self.events = list(ledger.get("events") or [])
        self.pending_usage_unknown = set(ledger.get("pending_usage_unknown") or [])
        if not self.pending_usage_unknown:
            resolved = {
                str(event.get("id")) for event in self.events
                if event.get("event") in {"settle", "release", "reconcile_unknown_usage"}
            }
            self.pending_usage_unknown = {
                str(event.get("id")) for event in self.events
                if event.get("event") == "interrupted_usage_unknown"
                and str(event.get("id")) not in resolved
            }

    def _persist(self, event: dict[str, Any]) -> None:
        if not self.ledger_path:
            return
        # ponytail: sequential claims only under the $25 program ceiling; upgrade
        # to an atomic shared claim store before allowing parallel paid runs.
        self.events.append(event)
        payload = {
            "version": 1,
            "cap_usd": self.cap_usd,
            "completed_openai_usd": round(self.completed_usd, 8),
            "active_reservations": self.active_reservations,
            "pending_usage_unknown": sorted(self.pending_usage_unknown),
            "events": self.events,
        }
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.ledger_path.with_suffix(self.ledger_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.ledger_path)

    def initialize(self) -> None:
        """Materialize an empty component ledger without reserving model spend."""
        if self.ledger_path and not self.ledger_path.exists():
            self._persist({"event": "initialize", "at": _utc_now()})

    def estimate(self, phase: str, model: str) -> float:
        """Price the configured token bound without writing a reservation."""
        try:
            input_tokens, output_tokens = self.phase_bounds[phase]
        except KeyError as error:
            raise ValueError(f"No bounded estimate configured for {phase}") from error
        return estimated_cost(model, input_tokens, output_tokens)

    @staticmethod
    def settle_estimate(reservation: dict[str, Any], usage: dict[str, Any]) -> float:
        """Use durable per-response pricing when available, otherwise a conservative total."""
        recorded = usage.get("known_usage_cost_usd")
        if (
            isinstance(recorded, (int, float)) and recorded >= 0
            and usage.get("cost_known", True)
        ):
            return round(float(recorded), 8)
        return estimated_cost(
            reservation["model"],
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
            int(usage.get("cached_input_tokens", 0) or 0),
            int(usage.get("cache_write_tokens", 0) or 0),
        )

    def reserve(self, phase: str, model: str) -> dict[str, Any] | None:
        if self.pending_usage_unknown:
            return None
        if self.reservation_namespace and not phase.startswith(f"{self.reservation_namespace}-"):
            raise ValueError(
                f"Reservation phase must use the {self.reservation_namespace}- namespace: {phase}"
            )
        try:
            input_tokens, output_tokens = self.phase_bounds[phase]
        except KeyError as error:
            raise ValueError(f"No bounded reservation configured for {phase}") from error
        amount = estimated_cost(model, input_tokens, output_tokens)
        active = sum(self.active_reservations.values())
        if self.completed_usd + active + amount > self.cap_usd:
            return None
        reservation_id = f"{phase}-{uuid.uuid4().hex}"
        self.active_reservations[reservation_id] = amount
        reservation = {
            "id": reservation_id,
            "phase": phase,
            "model": model,
            "input_tokens_bound": input_tokens,
            "output_tokens_bound": output_tokens,
            "reserved_usd": amount,
        }
        self._persist({"event": "reserve", "at": _utc_now(), **reservation})
        return reservation

    def release(self, reservation: dict[str, Any], *, reason: str) -> dict[str, float]:
        """Release an abandoned pre-call reservation without recording model spend."""
        reservation_id = reservation["id"]
        reserved = self.active_reservations.pop(reservation_id, None)
        if reserved is None:
            raise ValueError("Unknown or already-finalized OpenAI reservation")
        self._persist({
            "event": "release", "at": _utc_now(), "id": reservation_id,
            "phase": reservation["phase"], "model": reservation["model"],
            "reserved_usd": reserved, "reason": reason,
        })
        return {
            "reserved_usd": reserved,
            "settled_usd": 0.0,
            "completed_openai_usd": self.completed_usd,
            "active_reserved_openai_usd": round(sum(self.active_reservations.values()), 8),
        }

    def mark_interrupted(self, reservation_id: str) -> float:
        """Keep an interrupted call's cap hold until its provider bill is known."""
        amount = self.active_reservations.get(reservation_id)
        if amount is None:
            raise ValueError("No unsettled reservation with this ID")
        self.pending_usage_unknown.add(reservation_id)
        if not any(event.get("event") == "interrupted_usage_unknown" and event.get("id") == reservation_id for event in self.events):
            self._persist({"event": "interrupted_usage_unknown", "at": _utc_now(),
                           "id": reservation_id, "reserved_usd": amount,
                           "reason": "client timeout before provider response; billed usage unavailable"})
        return amount

    def settle(self, reservation: dict[str, Any], usage: dict[str, Any]) -> dict[str, float]:
        reservation_id = reservation["id"]
        reserved = self.active_reservations.pop(reservation_id, None)
        if reserved is None:
            raise ValueError("Unknown or already-settled OpenAI reservation")
        actual = self.settle_estimate(reservation, usage)
        self.completed_usd = round(self.completed_usd + actual, 8)
        was_unknown = reservation_id in self.pending_usage_unknown
        self.pending_usage_unknown.discard(reservation_id)
        self._persist({
            "event": "settle", "at": _utc_now(), "id": reservation_id,
            "phase": reservation["phase"], "model": reservation["model"],
            "reserved_usd": reserved, "settled_usd": actual,
            "reconciled_after_interruption": was_unknown,
        })
        return {
            "reserved_usd": reserved,
            "settled_usd": actual,
            "completed_openai_usd": self.completed_usd,
            "active_reserved_openai_usd": round(sum(self.active_reservations.values()), 8),
        }

    def settle_partial_unknown(
        self, reservation: dict[str, Any], usage: dict[str, Any], *, request_ids: list[str]
    ) -> dict[str, float]:
        """Settle journaled responses and retain the unused cap hold for unknown usage."""
        reservation_id = reservation["id"]
        reserved = self.active_reservations.get(reservation_id)
        if reserved is None:
            raise ValueError("Unknown or already-settled OpenAI reservation")
        actual = self.settle_estimate(reservation, usage)
        residual = round(max(reserved - actual, 0.0), 8)
        self.completed_usd = round(self.completed_usd + actual, 8)
        self.active_reservations[reservation_id] = residual
        self.pending_usage_unknown.add(reservation_id)
        self._persist({
            "event": "partial_settle_usage_unknown", "at": _utc_now(),
            "id": reservation_id, "phase": reservation["phase"],
            "model": reservation["model"], "reserved_usd": reserved,
            "settled_known_usage_usd": actual,
            "retained_unknown_usage_usd": residual,
            "request_ids": sorted(set(request_ids)),
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        })
        return {
            "reserved_usd": reserved,
            "settled_usd": actual,
            "retained_unknown_usage_usd": residual,
            "completed_openai_usd": self.completed_usd,
            "active_reserved_openai_usd": round(sum(self.active_reservations.values()), 8),
        }

    def reconcile_unknown_usage(self, reservation_id: str, usage: dict[str, Any]) -> float:
        """Settle one previously unknown response after provider usage is recovered."""
        if reservation_id not in self.pending_usage_unknown:
            raise ValueError("Reservation has no pending unknown provider usage")
        event = next((item for item in reversed(self.events)
                      if item.get("event") == "partial_settle_usage_unknown"
                      and item.get("id") == reservation_id), None)
        if event is None:
            interrupted = next((item for item in reversed(self.events)
                                if item.get("event") == "interrupted_usage_unknown"
                                and item.get("id") == reservation_id), None)
            if interrupted is None:
                raise ValueError("Unknown usage reservation has no durable ledger event")
            phase = interrupted["phase"]
            model = interrupted["model"]
        else:
            phase, model = event["phase"], event["model"]
        amount = self.settle_estimate({"phase": phase, "model": model}, usage)
        self.completed_usd = round(self.completed_usd + amount, 8)
        self.active_reservations.pop(reservation_id, None)
        self.pending_usage_unknown.discard(reservation_id)
        self._persist({
            "event": "reconcile_unknown_usage", "at": _utc_now(),
            "id": reservation_id, "phase": phase, "model": model,
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage["output_tokens"]),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
            "cache_write_tokens": int(usage.get("cache_write_tokens", 0)),
            "settled_unknown_usage_usd": amount,
        })
        return amount

    def reconcile_settlement(self, reservation_id: str, usage: dict[str, Any]) -> float:
        """Correct one historical zero-usage settlement from provider-reported usage."""
        original = next((event for event in self.events if event.get("event") == "settle" and event.get("id") == reservation_id), None)
        if not original or original.get("settled_usd") != 0 or any(
            event.get("event") == "reconcile" and event.get("id") == reservation_id for event in self.events
        ):
            raise ValueError("Settlement cannot be reconciled more than once or was not zero")
        amount = self.settle_estimate(
            {"phase": original["phase"], "model": original["model"]}, usage
        )
        if amount <= 0 or self.completed_usd + amount > self.cap_usd:
            raise ValueError("Reconciled provider usage is invalid or exceeds the OpenAI cap")
        self.completed_usd = round(self.completed_usd + amount, 8)
        self._persist({"event": "reconcile", "at": _utc_now(), "id": reservation_id, "phase": original["phase"], "model": original["model"], "input_tokens": usage["input_tokens"], "cached_input_tokens": usage.get("cached_input_tokens", 0), "cache_write_tokens": usage.get("cache_write_tokens", 0), "output_tokens": usage["output_tokens"], "settled_usd": amount, "reason": "provider-reported usage on incomplete response"})
        return amount


def build_pipeline_phases(
    artifacts_dir: Path,
    run_result: dict[str, Any],
    stdout_lines: list[str] | None = None,
) -> list[dict[str, Any]]:
    """CP-E2E-1: per-phase Langfuse children from eval-state, stream, and artifacts."""
    artifacts_dir = Path(artifacts_dir)
    state = load_eval_state(artifacts_dir)
    run_started = _artifact_run_started(artifacts_dir)

    from_state = _phases_from_eval_state(state, run_started)
    from_stream = _phases_from_stream(stdout_lines or []) if stdout_lines else []
    from_mtimes = _phases_from_artifact_mtimes(artifacts_dir, run_started)
    merged = _merge_phase_lists(from_state, from_stream, from_mtimes)

    for entry in merged:
        artifact = PHASE_ARTIFACTS.get(entry.get("phase", ""))
        if artifact:
            entry["output_bytes"] = _artifact_bytes(artifacts_dir, artifact)

    non_llm = _non_llm_phases(artifacts_dir, run_started)
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

    return _allocate_costs(merged, default_model=run_result.get("model"))


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
    component = payload.get("component", "evaluator")
    pipeline = payload.get("pipeline", "prototype-evaluator")
    dims = parse_iterate_flags(payload.get("iterate_flags", ""))
    if component == "creator":
        dims = {"run_mode": "create", "fix_mode": "not_applicable", "iterate_flags": ""}
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
        "privacy_mode": payload.get("privacy_mode", "metadata_only"),
        "trace_content": payload.get("trace_content", "metadata"),
        "iterate_flags": dims["iterate_flags"],
        "team": "uxd",
        "component": component,
        "pipeline": pipeline,
        "designer_id_hash": hash_user_id(
            payload.get("designer") or os.environ.get("USER") or os.environ.get("USERNAME")
        ),
    }
    if payload.get("jira_url"):
        metadata["jira_url"] = str(payload["jira_url"])
    if payload.get("source_revision"):
        metadata["source_revision"] = str(payload["source_revision"])
    if payload.get("depth_tier"):
        metadata["depth_tier"] = payload["depth_tier"]
    if payload.get("experiment"):
        metadata["experiment"] = payload["experiment"]
    metrics = payload.get("metrics") or {}
    for field in PHASE_METADATA_FIELDS:
        value = metrics.get(field)
        if value is not None and value != "":
            metadata[field] = value
    benchmark = payload.get("benchmark") or {}
    for field in BENCHMARK_FIELDS:
        value = benchmark.get(field)
        if value is not None and value != "":
            metadata[field] = value
    benchmark_tags = [
        f"{field}={metadata[field]}"
        for field in BENCHMARK_FIELDS
        if field in metadata
    ]
    return {
        "prototype_key": prototype_key,
        "eval_run_id": eval_run_id,
        "provider": provider,
        "model": model,
        "metadata": metadata,
        "tags": benchmark_tags,
        "trace_id": langfuse_trace_id(eval_run_id),
        "trace_content": payload.get("trace_content", "metadata"),
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
    cost_usd = run_result.get("cost_usd")
    per_model = run_result.get("per_model_usage") or {}
    status = pipeline_run_status(run_result)
    level = "ERROR" if status == "failed" else "WARNING" if status == "blocked" else "DEFAULT"
    artifact_output = (
        redact_content(payload.get("full_trace_content"))
        if values["metadata"].get("trace_content") == "full"
        else telemetry_artifact_output(payload)
    )

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
                input=None,
                output=None,
                usage_details=usage,
                cost_details=cost_details or None,
                level=level,
                metadata={
                    "phase": phase_name,
                    "provider": phase.get("provider") or values["provider"],
                    "status": status,
                    "privacy_mode": values["metadata"]["privacy_mode"],
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
                    "privacy_mode": values["metadata"]["privacy_mode"],
                    **phase_metadata,
                },
            )

    if not payload.get("phases") and per_model:
        for model_name, usage in per_model.items():
            client.start_observation(
                name=f"generation/{model_name}",
                as_type="generation",
                model=model_name,
                input=None,
                output=None,
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

    root.update(
        output=artifact_output,
        level=level,
        status_message=f"status={status} cost_usd={cost_usd if cost_usd is not None else 'unknown'}",
        metadata={
            **values["metadata"],
            "status": status,
            "duration_ms": int(float(run_result.get("duration_s") or 0) * 1000),
            "llm_cost_usd": cost_usd,
            "known_usage_cost_usd": run_result.get("known_usage_cost_usd"),
            "billing_source": run_result.get("billing_source", "unknown"),
            "privacy_mode": values["metadata"]["privacy_mode"],
            "usage_known": run_result.get("usage_known", True),
            "usage_unknown": run_result.get("usage_unknown", False),
        },
    )


class LivePipelineTrace:
    """Keep Langfuse observations open for an evaluator or creator runtime."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.values = _trace_values(payload)
        self.bridge_context = injected_trace_context()
        self.trace_content = payload.get("trace_content") or {
            "full_raw": "full",
            "sanitized_artifact_output": "sanitized",
            "metadata_only": "metadata",
        }.get(payload.get("privacy_mode"), "full" if self.bridge_context else "metadata")
        if self.trace_content not in {"full", "sanitized", "metadata"}:
            raise ValueError("trace_content must be full, sanitized, or metadata")
        self.raw_capture = self.trace_content == "full"
        self.trace_context_path = Path(payload["trace_context_path"]) if payload.get("trace_context_path") else None
        if not self.bridge_context and self.trace_context_path and self.trace_context_path.is_file():
            try:
                stored = json.loads(self.trace_context_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("Stored Langfuse trace context is invalid") from error
            if stored.get("trace_id") != self.values["trace_id"]:
                raise ValueError("Stored Langfuse trace context belongs to another run ID")
            if re.fullmatch(r"[0-9a-f]{16}", str(stored.get("parent_span_id", ""))):
                self.bridge_context = {
                    "trace_id": self.values["trace_id"],
                    "parent_span_id": stored["parent_span_id"],
                }
        if self.bridge_context:
            # The OpenCode tool span owns this trace. The pipeline must not
            # generate a second root merely because it runs in another process.
            self.values["trace_id"] = self.bridge_context["trace_id"]
        self.client = _get_client()
        self.root = None
        self.generation = None
        self._root_context = None
        self._pipeline_context = None
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
        if self.trace_content == "full" and not self.client:
            raise RuntimeError("Full-content benchmark tracing is unavailable; refusing a silent metadata-only downgrade")
        if not self.client:
            return self
        from langfuse import propagate_attributes

        trace_label = (
            self.values["metadata"].get("comparison_id")
            or self.values["metadata"].get("condition")
            or self.values["metadata"].get("run_mode")
            or "run"
        )
        trace_context = self.bridge_context or {"trace_id": self.values["trace_id"]}
        component = self.values["metadata"].get("component", "evaluator")
        pipeline = self.values["metadata"].get("pipeline", "prototype-evaluator")
        root_family = "creation" if component == "creator" else "evaluation"
        self._root_context = self.client.start_as_current_observation(
            trace_context=trace_context,
            name=(
                f"{root_family}-pipeline/{self.values['eval_run_id']}"
                if self.bridge_context
                else f"{root_family}/{self.values['prototype_key']}/{trace_label}"
            ),
            as_type="span",
            input=redact_content(self.values["metadata"]) if self.raw_capture else None,
            metadata=self.values["metadata"],
        )
        self.root = self._root_context.__enter__()
        if (
            self.trace_context_path and not self.bridge_context
            and re.fullmatch(r"[0-9a-f]{16}", str(getattr(self.root, "id", "")))
        ):
            self.trace_context_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.trace_context_path.with_suffix(self.trace_context_path.suffix + ".tmp")
            temporary.write_text(json.dumps({
                "trace_id": self.values["trace_id"],
                "parent_span_id": self.root.id,
                "eval_run_id": self.values["eval_run_id"],
            }) + "\n")
            os.chmod(temporary, 0o600)
            temporary.replace(self.trace_context_path)
        self._attributes_context = propagate_attributes(
            user_id=self.values["metadata"]["designer_id_hash"],
            metadata={
                "prototype_key": self.values["prototype_key"],
                "eval_run_id": self.values["eval_run_id"],
                "component": component,
            },
            tags=[
                "team:uxd",
                f"pipeline:{pipeline}",
                f"provider:{self.values['provider']}",
                *self.values["tags"],
            ],
        )
        self._attributes_context.__enter__()
        self._pipeline_context = self.client.start_as_current_observation(
            name="evaluation-phases" if component == "evaluator" else f"{component}-phases",
            as_type="span",
            input=redact_content({"run_id": self.values["eval_run_id"]}) if self.raw_capture else None,
            metadata={
                "phase": pipeline,
                "component": component,
                "pipeline": pipeline,
                "provider": self.values["provider"],
                "status": "running",
                "telemetry_role": "pipeline-summary-no-usage",
            },
        )
        self.generation = self._pipeline_context.__enter__()
        return self

    def start_phase(
        self, *, name: str, model: str | None, input_text: str,
        provider: str | None = None,
    ):
        """Open one paid or deterministic phase through the shared observation path."""
        if not self.client or not self.root:
            return None
        phase_order, phase_group = PHASE_DISPLAY_ORDER.get(name, (99, "other"))
        observation_kwargs = {
            "name": name,
            # In full-content mode every billable Responses request is a
            # child generation. Keep the phase container a span so aggregate
            # phase usage is not counted again by Langfuse Metrics.
            "as_type": "span" if self.raw_capture else "generation",
            "input": redact_content(input_text) if self.raw_capture else None,
            "metadata": {
                "phase": name,
                "component": self.values["metadata"].get("component", "evaluator"),
                "pipeline": self.values["metadata"].get("pipeline", "prototype-evaluator"),
                "model": model,
                "model_invoked": model is not None,
                "provider": provider or self.values["provider"],
                "status": "running",
                "benchmark_name": self.values["metadata"].get("benchmark_name"),
                "comparison_id": self.values["metadata"].get("comparison_id"),
                "condition": self.values["metadata"].get("condition"),
                "artifact_mode": self.values["metadata"].get("artifact_mode"),
                "csv_used": self.values["metadata"].get("csv_used"),
                "phase_order": phase_order,
                "phase_group": phase_group,
                "privacy_mode": self.values["metadata"]["privacy_mode"],
                "input_chars": len(input_text),
                "input_sha256": content_sha256(input_text),
                "input_complete": True,
            },
        }
        if not self.raw_capture:
            observation_kwargs["model"] = model
        observation = self.client.start_observation(
            **observation_kwargs,
        )
        self.live_phase_names.add(name)
        return observation

    def finish_phase(
        self, observation, *, phase: dict[str, Any], output_text: str,
        sanitized_output: dict[str, Any] | None = None,
        trace_events: list[dict[str, Any]] | None = None,
        artifacts_dir: Path | None = None,
        artifact_paths: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> None:
        """Close a live model phase with exact usage, cost, and status."""
        if observation is None:
            return
        phase_status = phase.get("status", "failed")
        level = "ERROR" if phase_status == "failed" else "DEFAULT"
        phase_name = phase.get("phase") or "unknown"
        phase_order, phase_group = PHASE_DISPLAY_ORDER.get(phase_name, (99, "other"))
        child_observation_counts = {"requests": 0, "tools": 0, "artifacts": 0}
        child_observation_error = None
        if self.raw_capture:
            try:
                child_observation_counts, child_observation_error = self._record_full_children(
                    observation, phase, trace_events or [], artifacts_dir, artifact_paths,
                )
            except Exception as error:
                # Keep accounting intact if the detailed nested observations
                # cannot be exported; surface the failure in phase metadata.
                child_observation_error = type(error).__name__
            output = redact_content({
                "model_output": output_text,
                "detail_location": "nested_request_tool_artifact_observations",
            })
        elif self.values["metadata"]["privacy_mode"] == "sanitized_artifact_output":
            output = redact_content(sanitized_output)
        else:
            output = None
        known_cost = phase.get("known_usage_cost_usd", phase.get("llm_cost_usd"))
        phase_update = {
            "output": output,
            "level": level,
        }
        if not self.raw_capture:
            phase_update["usage_details"] = langfuse_usage(phase)
            phase_update["cost_details"] = (
                {"total": float(known_cost)} if known_cost is not None else None
            )
            if phase.get("model"):
                phase_update["model"] = phase["model"]
        phase_update.update({
            "status_message": redact_text(output_text, 200),
            "metadata": {
                "phase": phase.get("phase"),
                "component": self.values["metadata"].get("component", "evaluator"),
                "pipeline": self.values["metadata"].get("pipeline", "prototype-evaluator"),
                "model": phase.get("model"),
                "model_invoked": phase.get("model_invoked", bool(phase.get("model"))),
                "provider": phase.get("provider") or self.values["provider"],
                "billing_source": "provider_usage_price_card_estimate" if phase.get("model") else "local_no_model_cost",
                "pricing_reference": "https://developers.openai.com/api/docs/pricing" if phase.get("model") else None,
                "input_tokens_including_cache": int(phase.get("input_tokens", 0) or 0),
                "cached_input_tokens": int(phase.get("cache_read_tokens", 0) or 0),
                "cache_write_tokens": int(phase.get("cache_write_tokens", 0) or 0),
                "estimated_cost_usd": known_cost,
                "usage_known": bool(phase.get("usage_known", True)),
                "usage_unknown": bool(phase.get("usage_unknown", False)),
                "unknown_request_ids": phase.get("unknown_request_ids", []),
                "status": phase_status,
                "benchmark_name": self.values["metadata"].get("benchmark_name"),
                "comparison_id": self.values["metadata"].get("comparison_id"),
                "condition": self.values["metadata"].get("condition"),
                "artifact_mode": self.values["metadata"].get("artifact_mode"),
                "csv_used": self.values["metadata"].get("csv_used"),
                "phase_order": phase_order,
                "phase_group": phase_group,
                "privacy_mode": self.values["metadata"]["privacy_mode"],
                "trace_content": self.trace_content,
                "child_observation_counts": child_observation_counts,
                "child_observation_error_category": child_observation_error,
                "duration_ms": phase.get("duration_ms"),
                "turns_used": phase.get("turns_used"),
                "validation": phase.get("validation"),
                "expected_outputs_present": phase.get("expected_outputs_present"),
                "expected_outputs_fresh": phase.get("expected_outputs_fresh"),
                "tool_calls": phase.get("tool_calls"),
                "tool_failures": phase.get("tool_failures"),
                "tool_failure_diagnostics": phase.get("tool_failure_diagnostics"),
                "tool_failure_diagnostics_truncated": phase.get("tool_failure_diagnostics_truncated"),
                "error_categories": phase.get("error_categories"),
                "recovery_actions": phase.get("recovery_actions"),
                "provider_error_category": phase.get("provider_error_category"),
                "provider_http_status": phase.get("provider_http_status"),
                "turn_limit_reached": phase.get("turn_limit_reached"),
                "input_token_bound_reached": phase.get("input_token_bound_reached"),
                "output_token_bound_reached": phase.get("output_token_bound_reached"),
                "cost_bound_reached": phase.get("cost_bound_reached"),
                "artifact_gate_failure": phase.get("artifact_gate_failure"),
                "artifact_gate_completed": phase.get("artifact_gate_completed"),
                "output_chars": len(output_text),
                "output_sha256": content_sha256(output_text),
                "output_complete": (
                    bool(trace_events is not None)
                    if self.raw_capture else bool(sanitized_output)
                ),
            },
        })
        observation.update(**phase_update)
        observation.end()

    def _record_full_children(
        self, parent, phase: dict[str, Any], events: list[dict[str, Any]],
        artifacts_dir: Path | None,
        artifact_paths: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> tuple[dict[str, int], str | None]:
        """Attach one child generation per API request plus tool and artifact spans."""
        counts = {"requests": 0, "tools": 0, "artifacts": 0}
        pending: dict[str, Any] = {}
        seen_request_ids: set[str] = set()
        seen_tool_ids: set[str] = set()
        seen_tools_without_id: set[str] = set()
        first_error = None
        model = phase.get("model")

        def request_usage(event: dict[str, Any]) -> tuple[dict[str, int] | None, float | None, bool]:
            record = event.get("usage") or {}
            usage = record.get("usage") if isinstance(record, dict) and isinstance(record.get("usage"), dict) else record
            if not isinstance(usage, dict):
                return None, None, False
            if not all(isinstance(usage.get(key), int) and usage[key] >= 0 for key in ("input_tokens", "output_tokens")):
                return None, None, bool(record.get("usage_known", event.get("usage_known", False)))
            normalized = {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cache_read_tokens": int(
                    usage.get("cache_read_tokens", usage.get("cached_input_tokens", 0)) or 0
                ),
                "cache_write_tokens": int(usage.get("cache_write_tokens", 0) or 0),
            }
            known = bool(record.get("usage_known", event.get("usage_known", True)))
            cost = record.get("estimated_cost_usd") if isinstance(record, dict) else None
            if cost is None and known and model in OPENAI_PRICING_PER_MTOK:
                cost = estimated_cost(
                    model, normalized["input_tokens"], normalized["output_tokens"],
                    normalized["cache_read_tokens"], normalized["cache_write_tokens"],
                )
            return normalized, float(cost) if cost is not None else None, known

        for event in events:
            event_type = event.get("event")
            request_id = str(event.get("request_id") or uuid.uuid4().hex)
            if event_type == "request":
                # Trace recovery can replay journaled exchanges after the live
                # event stream has already been appended. A request id is the
                # durable identity; never create a second billable observation.
                if request_id in seen_request_ids:
                    continue
                seen_request_ids.add(request_id)
                try:
                    child = parent.start_observation(
                        name=f"model-request/{phase.get('phase', 'unknown')}",
                        as_type="generation",
                        model=event.get("model") or model,
                        input=redact_content(event.get("payload")),
                        metadata={
                            "run_id": self.values["eval_run_id"],
                            "attempt_id": phase.get("attempt_id"),
                            "phase": phase.get("phase"),
                            "request_id": request_id,
                            "trace_content": "full",
                            "status": "running",
                        },
                    )
                    pending[request_id] = child
                    counts["requests"] += 1
                except Exception as error:
                    first_error = first_error or type(error).__name__
            elif event_type == "response":
                child = pending.pop(request_id, None)
                if child is None:
                    continue
                normalized, cost, known = request_usage(event)
                update = {
                    "output": model_response_for_trace(event.get("response")),
                    "level": "DEFAULT",
                    "metadata": {
                        "status": "completed",
                        "usage_known": known,
                        "usage_unknown": not known,
                        "estimated_cost_usd": cost,
                        "trace_content": "full",
                    },
                }
                if normalized is not None:
                    update["usage_details"] = langfuse_usage(normalized)
                if cost is not None:
                    update["cost_details"] = {"total": cost}
                try:
                    child.update(**update)
                    child.end()
                except Exception as error:
                    first_error = first_error or type(error).__name__
            elif event_type == "request_failed":
                child = pending.pop(request_id, None)
                if child is None:
                    continue
                try:
                    child.update(
                        output=redact_content({
                            "status": "failed",
                            "status_code": event.get("status_code"),
                            "error_category": event.get("error_category"),
                            "usage_unknown": event.get("usage_unknown"),
                        }),
                        level="ERROR",
                        metadata={
                            "status": "failed",
                            "error_category": event.get("error_category"),
                            "usage_known": not bool(event.get("usage_unknown")),
                            "usage_unknown": bool(event.get("usage_unknown")),
                            "trace_content": "full",
                        },
                    )
                    child.end()
                except Exception as error:
                    first_error = first_error or type(error).__name__
            elif event_type == "tool_exchange":
                call = event.get("call") or {}
                call_id = str(call.get("call_id") or call.get("id") or "")
                if call_id:
                    if call_id in seen_tool_ids:
                        continue
                    seen_tool_ids.add(call_id)
                else:
                    fingerprint = hashlib.sha256(json.dumps(
                        event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
                    ).encode("utf-8")).hexdigest()
                    if fingerprint in seen_tools_without_id:
                        continue
                    seen_tools_without_id.add(fingerprint)
                tool_name = str(call.get("name") or "tool")
                try:
                    child = parent.start_observation(
                        name=f"tool/{tool_name}", as_type="tool",
                        input=redact_content(call),
                        metadata={
                            "run_id": self.values["eval_run_id"],
                            "attempt_id": phase.get("attempt_id"),
                            "phase": phase.get("phase"),
                            "turn": event.get("turn"),
                            "tool_name": tool_name,
                            "trace_content": "full",
                        },
                    )
                    child.update(output=redact_content(event.get("output")))
                    child.end()
                    counts["tools"] += 1
                except Exception as error:
                    first_error = first_error or type(error).__name__

        for request_id, child in pending.items():
            try:
                child.update(
                    output={"status": "interrupted", "usage_unknown": True},
                    level="ERROR",
                    metadata={"status": "interrupted", "usage_unknown": True},
                )
                child.end()
            except Exception as error:
                first_error = first_error or type(error).__name__

        if artifacts_dir:
            for artifact in full_artifact_bundle(artifacts_dir, include_paths=artifact_paths):
                try:
                    child = parent.start_observation(
                        name="artifact",
                        as_type="span",
                        input={"path": artifact["path"], "size_bytes": artifact["size_bytes"]},
                        metadata={
                            "run_id": self.values["eval_run_id"],
                            "attempt_id": phase.get("attempt_id"),
                            "phase": phase.get("phase"),
                            "path": artifact["path"],
                            "sha256": artifact["sha256"],
                            "size_bytes": artifact["size_bytes"],
                            "trace_content": "full",
                        },
                    )
                    child.update(output=redact_content(artifact["content"]))
                    child.end()
                    counts["artifacts"] += 1
                except Exception as error:
                    first_error = first_error or type(error).__name__
        return counts, first_error

    def record_audit(self, name: str, manifest: dict[str, Any], *, audit_type: str) -> None:
        """Publish an allowlisted audit record with credential-shaped values redacted."""
        if not self.client or not self.root:
            return
        observation = self.client.start_observation(
            name=name, as_type="span", input=None, output=redact_content(manifest),
            metadata={
                "audit_type": audit_type,
                "privacy_mode": self.values["metadata"]["privacy_mode"],
                "trace_content": self.trace_content,
                "run_id": self.values["eval_run_id"], "model_invoked": False,
            },
        )
        observation.end()

    def finish(
        self,
        payload: dict[str, Any],
        *,
        artifact_paths: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload)
        if self.raw_capture and payload.get("artifacts_dir"):
            payload["full_trace_content"] = {
                "run_summary": redact_content(payload.get("run_result") or {}),
                "artifacts": full_artifact_bundle(
                    Path(payload["artifacts_dir"]), include_paths=artifact_paths
                ),
            }
        self.payload = payload
        run_result = payload.get("run_result", {})
        status = pipeline_run_status(run_result)
        level = "ERROR" if status == "failed" else "WARNING" if status == "blocked" else "DEFAULT"
        raw_cost = run_result.get("cost_usd")
        cost = float(raw_cost) if raw_cost is not None else None
        self.summary["llm_cost_usd"] = cost

        if self.client and self.generation and self.root:
            self.generation.update(
                output=None,
                level=level,
                status_message=f"status={status} cost_usd={cost if cost is not None else 'unknown'}",
                metadata={
                    "phase": self.values["metadata"].get("pipeline", "prototype-evaluator"),
                    "component": self.values["metadata"].get("component", "evaluator"),
                    "provider": self.values["provider"],
                    "status": status,
                    "duration_ms": int(float(run_result.get("duration_s") or 0) * 1000),
                    "billing_source": run_result.get("billing_source", "unknown"),
                    "usage_known": run_result.get("usage_known", True),
                    "usage_unknown": run_result.get("usage_unknown", False),
                    "trace_content": self.trace_content,
                    "telemetry_role": "pipeline-summary-no-usage",
                },
            )
            _record_pipeline_content(
                self.client,
                self.root,
                payload,
                self.values,
                skip_phases=frozenset({
                    self.values["metadata"].get("pipeline", "prototype-evaluator"),
                    *self.live_phase_names,
                }),
            )
            if self._pipeline_context:
                self._pipeline_context.__exit__(None, None, None)
                self._pipeline_context = None
            else:
                self.generation.end()
            self.generation = None
            self.finished = True
        return self.summary

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.generation:
                self.generation.update(
                    level="ERROR",
                    status_message=redact_text(str(exc_value or "pipeline ended before finish"), 200),
                )
                if self._pipeline_context:
                    self._pipeline_context.__exit__(exc_type, exc_value, traceback)
                    self._pipeline_context = None
                else:
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
    if injected_trace_context():
        # LivePipelineTrace is already attached to the OpenCode tool span. A
        # second logger here would duplicate every phase as a separate root.
        return {
            "eval_run_id": payload.get("eval_run_id"),
            "langfuse_trace_url": "",
            "langfuse_enabled": is_enabled(),
            "llm_cost_usd": (payload.get("run_result") or {}).get("cost_usd") or 0,
            "logged": False,
            "bridge_attached": True,
        }
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
            input=None,
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
                    *values["tags"],
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


def log_metadata_trace(
    *,
    root_name: str,
    run_id: str,
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export a metadata-only trace through the evaluator's shared SDK transport."""
    bridge_context = injected_trace_context()
    client = _get_client()
    trace_id = bridge_context["trace_id"] if bridge_context else langfuse_trace_id(run_id)
    trace_context = bridge_context or {"trace_id": trace_id}
    summary = {
        "trace_id": trace_id,
        "langfuse_trace_url": "",
        "langfuse_enabled": bool(client),
        "logged": False,
    }
    if not client:
        return summary

    root_metadata = {
        **{key: value for key, value in metadata.items() if value is not None},
        "privacy_mode": metadata.get("privacy_mode", "metadata_only"),
        "model_invoked": bool(metadata.get("model_invoked", False)),
    }
    try:
        from langfuse import propagate_attributes

        with client.start_as_current_observation(
            trace_context=trace_context,
            name=root_name,
            as_type="span",
            input=None,
            metadata=root_metadata,
        ) as root:
            with propagate_attributes(
                metadata={
                    key: root_metadata[key]
                    for key in ("component", "prototype_key", "program_run_id", "benchmark_name")
                    if root_metadata.get(key) is not None
                },
                tags=[
                    "team:uxd",
                    f"component:{root_metadata.get('component', 'unknown')}",
                ],
            ):
                for event in events:
                    event_name = str(event.get("phase") or event.get("name") or "metadata-event")
                    event_output = event.get("output")
                    client.create_event(
                        name=event_name,
                        input=None,
                        output=event_output,
                        metadata={
                            **{
                                key: value for key, value in event.items()
                                if key != "output" and value is not None
                            },
                            "privacy_mode": root_metadata["privacy_mode"],
                            "model_invoked": root_metadata["model_invoked"],
                        },
                    )
            root.update(
                output=output,
                metadata=root_metadata,
                status_message=f"sanitized structured output; model_invoked={root_metadata['model_invoked']}",
            )
        client.flush()
        summary["langfuse_trace_url"] = _trace_url(client, trace_id)
        summary["logged"] = True
    except Exception as error:
        print(f"Langfuse metadata export failed: {error}", file=sys.stderr)
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
