#!/usr/bin/env python3
"""Run visual consistency with direct images and strict Structured Outputs."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openai_api_agent import _cost, _request, _usage
from openai_structured_journey import _image_content, _object, _output_text, _validate


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
GUIDELINES_DIR = SKILL_DIR.parent / "uxd-consistency-check" / "guidelines"
PROCEDURE_PATH = SKILL_DIR / "references" / "api-phases" / "eval-consistency-visual.md"


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip('"\'')
    return result


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def load_guideline_specs() -> list[dict[str, str]]:
    """Extract only reviewable rules; examples and shell snippets stay out of prompts."""
    specs = []
    for path in sorted(GUIDELINES_DIR.rglob("*.md")):
        text = path.read_text()
        meta = _frontmatter(text)
        if not meta.get("id") or not _section(text, "Rule"):
            continue
        specs.append({
            "id": meta["id"],
            "title": meta.get("title", meta["id"]),
            "category": meta.get("category", path.parent.name),
            "severity": meta.get("severity", "warning"),
            "rule": _section(text, "Rule")[:4000],
            "manual_review": _section(text, "Manual Review Checklist")[:1800],
        })
    if not specs:
        raise ValueError(f"No guideline rules found in bundled checker: {GUIDELINES_DIR}")
    return specs


def _load_inputs(packet: dict[str, Any]) -> dict[str, Any]:
    artifacts = Path(packet["artifacts_dir"]).resolve()
    report = json.loads((artifacts / "consistency-report.json").read_text())
    journey = json.loads((artifacts / "journey-log.json").read_text())
    evidence_path = artifacts / "prototype-evidence.json"
    evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {}
    paths = list(evidence.get("screenshots") or [])
    for item in journey.get("journeys") or []:
        paths.extend(step.get("screenshot") for step in item.get("steps") or [])
    screenshots = list(dict.fromkeys(path for path in paths if path))
    if not screenshots:
        raise ValueError("No screenshots are available for visual consistency")
    for relative in screenshots:
        target = (artifacts / relative).resolve()
        if artifacts not in target.parents or not target.is_file():
            raise ValueError(f"Screenshot is missing or outside artifacts: {relative}")
    return {
        "artifacts": artifacts,
        "report": report,
        "journey": journey,
        "evidence": evidence,
        "screenshots": screenshots,
        "specs": load_guideline_specs(),
    }


def visual_schema(*, screenshots: list[str], specs: list[dict[str, str]]) -> dict[str, Any]:
    by_id = {spec["id"]: spec for spec in specs}
    finding = _object({
        "screenshot": {"type": "string", "enum": screenshots},
        "guideline_id": {"type": "string", "enum": list(by_id)},
        "guideline_title": {"type": "string", "enum": sorted({s["title"] for s in specs})},
        "category": {"type": "string", "enum": sorted({s["category"] for s in specs})},
        "severity": {"type": "string", "enum": ["error", "warning"]},
        "verdict": {"type": "string", "enum": ["VIOLATION", "FLAGGED"]},
        "description": {"type": "string"},
        "suggestion": {"type": "string"},
        "seen_on": {"type": "array", "items": {"type": "string", "enum": screenshots}},
    }, ["screenshot", "guideline_id", "guideline_title", "category", "severity", "verdict", "description", "suggestion", "seen_on"])
    return _object({
        "findings": {"type": "array", "items": finding},
    }, ["findings"])


def build_visual_prompt(packet: dict[str, Any]) -> str:
    inputs = _load_inputs(packet)
    context = {
        "prototype_url": packet["prototype_url"],
        "reference_specs": inputs["specs"],
        "screenshots": inputs["screenshots"],
        "page_evidence": inputs["evidence"].get("page", {}),
        "journeys": inputs["journey"].get("journeys", []),
        "existing_source_findings": (inputs["report"].get("source_mode") or {}).get("violations", []),
    }
    return f"{PROCEDURE_PATH.read_text().strip()}\n\nVISUAL INPUT\n{json.dumps(context, indent=2)}"


def build_visual_request(packet: dict[str, Any], *, model: str, reasoning_effort: str = "low") -> dict[str, Any]:
    inputs = _load_inputs(packet)
    content = [{"type": "input_text", "text": build_visual_prompt(packet)}]
    content.extend(_image_content(inputs["artifacts"], path) for path in inputs["screenshots"])
    return {
        "model": model,
        "input": [
            {"role": "developer", "content": "Compare only the supplied screenshots against the supplied reference rules. Return only strict schema data."},
            {"role": "user", "content": content},
        ],
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": {"type": "json_schema", "name": "uxd_visual_consistency", "strict": True, "schema": visual_schema(screenshots=inputs["screenshots"], specs=inputs["specs"])}, "verbosity": "low"},
        "max_output_tokens": 5000,
        "store": False,
    }


def validate_visual_output(output: dict[str, Any], packet: dict[str, Any]) -> None:
    inputs = _load_inputs(packet)
    _validate(output, visual_schema(screenshots=inputs["screenshots"], specs=inputs["specs"]))
    by_id = {spec["id"]: spec for spec in inputs["specs"]}
    seen = set()
    for finding in output["findings"]:
        spec = by_id[finding["guideline_id"]]
        if finding["guideline_title"] != spec["title"] or finding["category"] != spec["category"]:
            raise ValueError(f"Finding metadata does not match {spec['id']}")
        if finding["verdict"] == "FLAGGED" and finding["severity"] != "warning":
            raise ValueError("FLAGGED visual findings must be warnings")
        if finding["verdict"] == "VIOLATION" and finding["severity"] != "error":
            raise ValueError("VIOLATION visual findings must be errors")
        key = (finding["guideline_id"], tuple(sorted(finding["seen_on"])))
        if key in seen:
            raise ValueError("Duplicate visual finding")
        seen.add(key)


def _merge_report(inputs: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    report = dict(inputs["report"])
    input_bytes = sum((inputs["artifacts"] / path).stat().st_size for path in inputs["screenshots"])
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    report["visual_mode"] = {
        "ran": True,
        "screenshots_checked": len(inputs["screenshots"]),
        "input_metrics": {
            "screenshots_considered": len(inputs["screenshots"]),
            "screenshots_analyzed": len(inputs["screenshots"]),
            "guidelines_analyzed": len(inputs["specs"]),
            "input_bytes": input_bytes,
        },
        "findings": output["findings"],
    }
    all_findings = list((report.get("source_mode") or {}).get("violations") or []) + output["findings"]
    errors = {item["guideline_id"] for item in all_findings if item.get("severity") == "error"}
    warnings = {item["guideline_id"] for item in all_findings if item.get("severity") == "warning"} - errors
    total = max(len(inputs["specs"]), int((report.get("summary") or {}).get("total_guidelines_checked", 0)))
    report["summary"] = {"total_guidelines_checked": total, "violations": len(errors), "warnings": len(warnings), "passes": max(total - len(errors) - len(warnings), 0)}
    return report


def run_structured_visual(packet: dict[str, Any], *, model: str, reasoning_effort: str = "low", trace_path: str | None = None, request_fn: Callable[[dict[str, Any]], dict[str, Any]] = _request) -> dict[str, Any]:
    started = time.monotonic()
    response = request_fn(build_visual_request(packet, model=model, reasoning_effort=reasoning_effort))
    if trace_path:
        trace = Path(trace_path); trace.parent.mkdir(parents=True, exist_ok=True); trace.write_text(json.dumps(response) + "\n")
    if response.get("status") not in {None, "completed"}:
        raise ValueError(f"OpenAI visual response status was {response.get('status')}")
    output_text = _output_text(response)
    try:
        output = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"OpenAI visual output was not valid JSON: {error}") from error
    validate_visual_output(output, packet)
    inputs = _load_inputs(packet)
    report = _merge_report(inputs, output)
    target = inputs["artifacts"] / "consistency-report.json"
    temp = target.with_suffix(".json.tmp"); temp.write_text(json.dumps(report, indent=2) + "\n"); temp.replace(target)
    usage = _usage(response); cost = _cost(model, usage)
    return {"provider": "openai", "model": model, "agent": "responses-api-structured-visual", "duration_s": round(time.monotonic() - started, 3), "exit_code": 0, "status": "completed", "output_text": output_text, "token_usage": usage, "cost_usd": cost, "billing_source": "provider_estimate" if cost is not None else "unavailable", "turns_used": 1, "turn_limit_reached": False}
