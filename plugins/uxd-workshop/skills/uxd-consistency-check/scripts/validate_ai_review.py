#!/usr/bin/env python3
"""Validate and trace supplemental, non-deterministic consistency findings."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
GUIDELINES_DIR = SKILL_DIR / "guidelines"
LANGFUSE_TRACE_SCRIPT_DIR = SKILL_DIR.parent / "uxd-prototype-evaluate" / "scripts"


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _guidelines() -> dict[str, dict[str, str]]:
    result = {}
    for path in sorted(GUIDELINES_DIR.rglob("*.md")):
        meta = _frontmatter(path.read_text(encoding="utf-8"))
        if not meta.get("id"):
            continue
        result[meta["id"]] = {
            "title": meta.get("title", meta["id"]),
            "category": meta.get("category", path.parent.name),
            "severity": meta.get("severity", "warning"),
            "automation_result": meta.get("automation_result", ""),
        }
    return result


def _safe_relative_file(value: Any, source_root: Path) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise ValueError("finding file must be a non-empty relative path")
    relative = PurePosixPath(value.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"finding path escapes source root: {value}")
    source_root = source_root.resolve()
    target = (source_root / Path(*relative.parts)).resolve()
    if source_root not in target.parents or not target.is_file():
        raise ValueError(f"finding file is missing or outside source root: {value}")
    return relative.as_posix(), target


def _normalized_severity(guideline: dict[str, str], confidence: str) -> tuple[str, str]:
    if guideline["automation_result"] == "candidate" or confidence != "high":
        return "warning", "FLAGGED"
    if guideline["severity"] == "error":
        return "error", "VIOLATION"
    return "warning", "FLAGGED"


def _validate_source_finding(
    finding: dict[str, Any], guidelines: dict[str, dict[str, str]], source_root: Path, model: str
) -> dict[str, Any]:
    required = ("guideline_id", "file", "line_start", "line_end", "evidence", "rationale", "suggestion", "confidence")
    missing = [key for key in required if key not in finding]
    if missing:
        raise ValueError(f"source finding is missing required fields: {', '.join(missing)}")
    guideline_id = finding["guideline_id"]
    if guideline_id not in guidelines:
        raise ValueError(f"unknown guideline_id: {guideline_id}")
    guideline = guidelines[guideline_id]
    file_name, path = _safe_relative_file(finding["file"], source_root)
    start, end = finding["line_start"], finding["line_end"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
        raise ValueError(f"invalid source line range for {file_name}: {start}-{end}")
    evidence = finding["evidence"]
    window = "\n".join(lines[start - 1 : end])
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in window:
        raise ValueError(f"evidence does not match {file_name}:{start}-{end}")
    confidence = finding["confidence"]
    if confidence not in {"high", "medium", "low"}:
        raise ValueError(f"invalid confidence for {guideline_id}: {confidence}")
    severity, verdict = _normalized_severity(guideline, confidence)
    for field in ("rationale", "suggestion"):
        if not isinstance(finding[field], str) or not finding[field].strip():
            raise ValueError(f"source finding {field} must be non-empty")
    return {
        "guideline_id": guideline_id,
        "guideline_title": guideline["title"],
        "category": guideline["category"],
        "severity": severity,
        "verdict": verdict,
        "confidence": confidence,
        "review_candidate": severity == "warning",
        "file": file_name,
        "line": start,
        "line_end": end,
        "evidence": evidence,
        "description": finding["rationale"].strip(),
        "suggestion": finding["suggestion"].strip(),
        "check_method": "model_review",
        "model": model,
    }


def _validate_visual_finding(
    finding: dict[str, Any], guidelines: dict[str, dict[str, str]], screenshots: set[str], model: str
) -> dict[str, Any]:
    required = ("guideline_id", "screenshot", "rationale", "suggestion", "confidence")
    missing = [key for key in required if key not in finding]
    if missing:
        raise ValueError(f"visual finding is missing required fields: {', '.join(missing)}")
    guideline_id = finding["guideline_id"]
    if guideline_id not in guidelines:
        raise ValueError(f"unknown guideline_id: {guideline_id}")
    screenshot = finding["screenshot"]
    if screenshot not in screenshots:
        raise ValueError(f"visual finding references an unreviewed screenshot: {screenshot}")
    guideline = guidelines[guideline_id]
    confidence = finding["confidence"]
    if confidence not in {"high", "medium", "low"}:
        raise ValueError(f"invalid confidence for {guideline_id}: {confidence}")
    severity, verdict = _normalized_severity(guideline, confidence)
    for field in ("rationale", "suggestion"):
        if not isinstance(finding[field], str) or not finding[field].strip():
            raise ValueError(f"visual finding {field} must be non-empty")
    seen_on = finding.get("seen_on", [screenshot])
    if not isinstance(seen_on, list) or not seen_on or any(path not in screenshots for path in seen_on):
        raise ValueError("seen_on must contain only supplied screenshot paths")
    return {
        "guideline_id": guideline_id,
        "guideline_title": guideline["title"],
        "category": guideline["category"],
        "severity": severity,
        "verdict": verdict,
        "confidence": confidence,
        "screenshot": screenshot,
        "seen_on": sorted(set(seen_on)),
        "description": finding["rationale"].strip(),
        "suggestion": finding["suggestion"].strip(),
        "check_method": "model_review",
        "model": model,
    }


def validate_review(
    raw: Any, *, mode: str, model: str, source_root: Path, screenshots: list[str]
) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("status") != "completed":
        raise ValueError("AI review must be a completed JSON object")
    if raw.get("model") != model:
        raise ValueError(f"AI review model must match requested model {model}")
    if raw.get("mode") != mode:
        raise ValueError(f"AI review mode must match requested mode {mode}")
    if raw.get("non_deterministic") is not True:
        raise ValueError("AI review must declare non_deterministic=true")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ValueError("AI review findings must be an array")
    guidelines = _guidelines()
    allowed_screenshots = set(screenshots)
    if mode == "visual" and not allowed_screenshots:
        raise ValueError("visual review requires at least one supplied screenshot")
    if mode == "visual":
        missing_screenshots = [path for path in allowed_screenshots if not Path(path).is_file()]
        if missing_screenshots:
            raise ValueError(f"supplied screenshot does not exist: {missing_screenshots[0]}")
    normalized = []
    seen = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("each AI finding must be an object")
        item = (
            _validate_source_finding(finding, guidelines, source_root, model)
            if mode == "source"
            else _validate_visual_finding(finding, guidelines, allowed_screenshots, model)
        )
        key = (item["guideline_id"], item.get("file", item.get("screenshot")), item.get("line"))
        if key in seen:
            raise ValueError(f"duplicate AI finding: {key}")
        seen.add(key)
        normalized.append(item)
    return {
        "status": "completed",
        "mode": mode,
        "model": model,
        "non_deterministic": True,
        "findings": normalized,
        "summary": {
            "finding_count": len(normalized),
            "error_count": sum(item["severity"] == "error" for item in normalized),
            "warning_count": sum(item["severity"] == "warning" for item in normalized),
        },
    }


def trace_review(review: dict[str, Any], *, ticket: str, prototype_url: str, benchmark_name: str) -> str:
    if os.environ.get("UXD_TRACE_COMPONENT") != "consistency":
        raise RuntimeError("AI review tracing requires UXD_TRACE_COMPONENT=consistency")
    sys.path.insert(0, str(LANGFUSE_TRACE_SCRIPT_DIR))
    import langfuse_trace  # noqa: PLC0415

    if not langfuse_trace.injected_trace_context():
        raise RuntimeError("AI review tracing requires an OpenCode-injected Langfuse parent context")
    phase = f"consistency-{review['mode']}-ai"
    run_id = f"{phase}-{ticket}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    summary = {
        "status": "completed",
        "mode": review["mode"],
        "model": review["model"],
        "model_invoked": True,
        **review["summary"],
    }
    trace = langfuse_trace.log_metadata_trace(
        root_name=phase,
        run_id=run_id,
        metadata={
            "component": "consistency",
            "prototype_key": ticket,
            "program_run_id": run_id,
            "benchmark_name": benchmark_name,
            "prototype_url": prototype_url,
            "privacy_mode": "metadata_only",
            "model_invoked": True,
            "model": review["model"],
        },
        events=[{
            "phase": phase,
            "status": "completed",
            "mode": review["mode"],
            "model": review["model"],
            "model_invoked": True,
            "finding_count": review["summary"]["finding_count"],
            "violation_count": review["summary"]["error_count"],
            "warning_count": review["summary"]["warning_count"],
            "prototype_url": prototype_url,
            "output": summary,
        }],
        output=summary,
    )
    if not trace.get("logged"):
        raise RuntimeError("Langfuse did not confirm the nested OpenCode AI-review phase")
    return trace["langfuse_trace_url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "visual"), required=True)
    parser.add_argument("--input", required=True, help="Raw JSON emitted by the model review")
    parser.add_argument("--output", required=True, help="Path for the validated model-review JSON")
    parser.add_argument("--source-root", required=True, help="Read-only prototype source root")
    parser.add_argument("--screenshot", action="append", default=[], help="Allowed screenshot path; repeat for each image")
    parser.add_argument("--model", required=True, help="Exact provider/model used for the review")
    parser.add_argument("--ticket", default="none")
    parser.add_argument("--prototype-url", default="")
    parser.add_argument("--benchmark-name", default="consistency-ai-review")
    parser.add_argument("--trace-phase", action="store_true", help="Record a summary-only phase under the active OpenCode trace")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    input_path = Path(args.input)
    output_path = Path(args.output)
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        review = validate_review(
            raw, mode=args.mode, model=args.model, source_root=source_root, screenshots=args.screenshot
        )
        if args.trace_phase:
            review["trace_url"] = trace_review(
                review, ticket=args.ticket, prototype_url=args.prototype_url, benchmark_name=args.benchmark_name
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(f"AI review validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": review["status"], "mode": args.mode, "model": args.model, **review["summary"]}))
    if review.get("trace_url"):
        print(f"Langfuse phase: {review['trace_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
