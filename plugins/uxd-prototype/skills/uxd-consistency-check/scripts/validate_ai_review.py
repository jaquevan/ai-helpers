#!/usr/bin/env python3
"""Validate supplemental, non-deterministic consistency findings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from guideline_sources import load_guidelines, public_context


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


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


def _guidelines(context: dict) -> dict[str, dict[str, str]]:
    result = {}
    for document in context["documents"]:
        meta = document["metadata"]
        result[document["id"]] = {
            "title": document["title"],
            "category": document["category"],
            "severity": meta.get("severity", "warning"),
            "automation_result": meta.get("automation_result", ""),
            "sources": document["sources"],
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
    if not isinstance(guideline_id, str) or guideline_id not in guidelines:
        raise ValueError(f"unknown guideline_id: {guideline_id}")
    guideline = guidelines[guideline_id]
    file_name, path = _safe_relative_file(finding["file"], source_root)
    start, end = finding["line_start"], finding["line_end"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if type(start) is not int or type(end) is not int or start < 1 or end < start or end > len(lines):
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
        "guideline_sources": guideline["sources"],
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
    if not isinstance(guideline_id, str) or guideline_id not in guidelines:
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
    raw: Any, *, mode: str, model: str, source_root: Path, screenshots: list[str],
    provided_guidelines: list[str] | None = None,
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
    context = load_guidelines(source_root, provided_guidelines)
    guidelines = _guidelines(context)
    if mode != "internal" and not guidelines:
        raise ValueError("Guideline compliance cannot be reviewed without a guideline source; use --mode internal for peer comparison")
    if mode == "internal":
        return validate_internal_review(raw, source_root, model, context)
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
        "guideline_context": public_context(context),
        "summary": {
            "finding_count": len(normalized),
            "error_count": sum(item["severity"] == "error" for item in normalized),
            "warning_count": sum(item["severity"] == "warning" for item in normalized),
        },
    }


def _peer_excerpt(raw: Any, source_root: Path) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Internal comparison evidence must be an object")
    file_name, path = _safe_relative_file(raw.get("file"), source_root)
    start, end = raw.get("line_start"), raw.get("line_end")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
        raise ValueError(f"Invalid peer-comparison line range for {file_name}")
    evidence = raw.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in "\n".join(lines[start - 1:end]):
        raise ValueError(f"Ungrounded peer-comparison excerpt for {file_name}")
    return {"file": file_name, "line_start": start, "line_end": end, "evidence": evidence}


def validate_internal_review(raw: dict, source_root: Path, model: str, context: dict) -> dict:
    comparisons = raw.get("comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("Internal review requires a comparisons array, even when no comparable examples exist")
    grounded = []
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            raise ValueError("Each internal comparison must be an object")
        target = _peer_excerpt(comparison.get("target"), source_root)
        peers = comparison.get("peers")
        if not isinstance(peers, list) or not peers:
            raise ValueError("An internal comparison requires at least one similar peer")
        peers = [_peer_excerpt(peer, source_root) for peer in peers]
        if len({(peer['file'], peer['line_start'], peer['line_end']) for peer in peers}) != len(peers):
            raise ValueError("Repeated peer evidence cannot inflate comparison confidence")
        if any(peer["file"] == target["file"] and peer["line_start"] == target["line_start"] for peer in peers):
            raise ValueError("A target cannot be its own comparison evidence")
        rationale = comparison.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Explain why the peer examples are comparable")
        conclusion = comparison.get("conclusion")
        if conclusion not in {"consistent", "review_candidate", "intentional_improvement"}:
            raise ValueError("Internal conclusions must distinguish candidates from intentional improvements")
        grounded.append({"target": target, "peers": peers, "rationale": rationale, "conclusion": conclusion})
    normalized = []
    for finding in raw["findings"]:
        if not isinstance(finding, dict):
            raise ValueError("Each internal finding must be an object")
        index = finding.get("comparison_index")
        if type(index) is not int or not 0 <= index < len(grounded):
            raise ValueError("Internal finding must reference a grounded comparison")
        if grounded[index]["conclusion"] != "review_candidate":
            raise ValueError("Consistent or intentionally improved areas cannot become internal violations")
        for field in ("rationale", "suggestion"):
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                raise ValueError(f"Internal finding requires {field}")
        target = grounded[index]["target"]
        normalized.append({
            "guideline_id": "internal-consistency", "guideline_title": "Peer comparison (not product policy)",
            "category": "internal", "severity": "warning", "verdict": "FLAGGED",
            "confidence": "low" if len(grounded[index]["peers"]) == 1 else "medium",
            "review_candidate": True, "file": target["file"], "line": target["line_start"],
            "description": finding["rationale"], "suggestion": finding["suggestion"],
            "check_method": "internal_comparison", "comparison_index": index,
        })
    return {
        "status": "completed", "mode": "internal", "model": model, "non_deterministic": True,
        "coverage": "reviewed" if grounded else "insufficient_comparators",
        "guideline_compliance": "separate_review_required" if context["documents"] else "not_evaluated",
        "guideline_context": public_context(context), "comparisons": grounded, "findings": normalized,
        "summary": {"finding_count": len(normalized), "error_count": 0, "warning_count": len(normalized)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "visual", "internal"), required=True)
    parser.add_argument("--input", required=True, help="Raw JSON emitted by the model review")
    parser.add_argument("--output", required=True, help="Path for the validated model-review JSON")
    parser.add_argument("--workspace", "--source-root", dest="source_root", required=True, help="Read-only prototype workspace")
    parser.add_argument("--guidelines", action="append", default=[], help="Supplement workspace guidelines with a local path or raw Markdown URL")
    parser.add_argument("--screenshot", action="append", default=[], help="Allowed screenshot path; repeat for each image")
    parser.add_argument("--model", required=True, help="Exact provider/model used for the review")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    input_path = Path(args.input)
    output_path = Path(args.output)
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        review = validate_review(
            raw, mode=args.mode, model=args.model, source_root=source_root, screenshots=args.screenshot,
            provided_guidelines=args.guidelines,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(f"AI review validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": review["status"], "mode": args.mode, "model": args.model, **review["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
