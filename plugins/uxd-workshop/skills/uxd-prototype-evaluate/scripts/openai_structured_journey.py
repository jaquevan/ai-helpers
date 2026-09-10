#!/usr/bin/env python3
"""Run eval-journey with Responses API Structured Outputs and image inputs."""

from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openai_api_agent import _cost, _request, _usage


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROCEDURE_PATH = SKILL_DIR / "references" / "api-phases" / "eval-journey.md"
VERDICTS = ("PASS", "FAIL", "FLAGGED")


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def journey_schema(
    *, screenshot_paths: list[str], criterion_ids: list[str], persona_ids: list[str]
) -> dict[str, Any]:
    """Build a strict schema whose paths and identifiers are locally constrained."""
    string = {"type": "string"}
    screenshot = {"type": "string", "enum": screenshot_paths}
    criterion_id = {"type": "string", "enum": criterion_ids}
    persona_id = {"type": "string", "enum": persona_ids}
    step = _object(
        {
            "step": {"type": "integer", "minimum": 1},
            "action": string,
            "result": {"type": "string", "enum": ["success", "fail"]},
            "screenshot": screenshot,
            "narration": string,
        },
        ["step", "action", "result", "screenshot", "narration"],
    )
    journey = _object(
        {
            "id": {"type": "string", "pattern": "^journey-[0-9]+$"},
            "title": string,
            "persona": persona_id,
            "source": string,
            "steps_expected": {"type": "integer", "minimum": 1},
            "steps_completed": {"type": "integer", "minimum": 0},
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "verdict_detail": string,
            "ac_ids": {
                "type": "array",
                "items": criterion_id,
                "minItems": 1,
            },
            "steps": {"type": "array", "items": step, "minItems": 1},
        },
        [
            "id", "title", "persona", "source", "steps_expected",
            "steps_completed", "verdict", "verdict_detail", "ac_ids", "steps",
        ],
    )
    persona_selection = _object(
        {
            "method": string,
            "selected": {
                "type": "array", "items": persona_id, "minItems": 1
            },
            "target_audience_text": string,
            "target_audience_source": string,
            "reasoning": string,
            "considered_but_rejected": {"type": "array", "items": string},
        },
        [
            "method", "selected", "target_audience_text", "target_audience_source",
            "reasoning", "considered_but_rejected",
        ],
    )
    criterion_result = _object(
        {
            "criterion_id": criterion_id,
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "rationale": string,
            "evidence": {"type": "string", "enum": ["", *screenshot_paths]},
            "fix_action": string,
            "fix_file": string,
            "human_action": string,
        },
        [
            "criterion_id", "verdict", "rationale", "evidence",
            "fix_action", "fix_file", "human_action",
        ],
    )
    exploration = _object(
        {
            "id": string,
            "title": string,
            "steps": {"type": "array", "items": step},
        },
        ["id", "title", "steps"],
    )
    return _object(
        {
            "depth": {"type": "string", "enum": ["quick", "deep"]},
            "prototype_url": string,
            "evaluated_at": {"type": "string"},
            "persona_selection": persona_selection,
            "journeys": {"type": "array", "items": journey, "minItems": 1},
            "exploration": {"type": "array", "items": exploration},
            "criterion_results": {"type": "array", "items": criterion_result},
        },
        [
            "depth", "prototype_url", "evaluated_at", "persona_selection",
            "journeys", "exploration", "criterion_results",
        ],
    )


def _acceptance_rows(csv_text: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = csv_text.splitlines()
    section = None
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    for line in lines:
        if line.startswith("# "):
            section = line[2:].strip().upper()
            headers = None
            continue
        if section != "ACCEPTANCE CRITERIA" or not line.strip():
            continue
        parsed = next(csv.reader([line]))
        if headers is None:
            headers = parsed
            continue
        padded = parsed + [""] * max(0, len(headers) - len(parsed))
        rows.append(dict(zip(headers, padded)))
    if not headers or "criterion_id" not in headers:
        raise ValueError("evaluation-report.csv has no acceptance-criteria header")
    if not rows:
        raise ValueError("evaluation-report.csv has no acceptance-criteria rows")
    return lines, rows


def _load_inputs(packet: dict[str, Any]) -> dict[str, Any]:
    artifacts_dir = Path(packet["artifacts_dir"]).resolve()
    extract = json.loads((artifacts_dir / "extract-state.json").read_text())
    evidence = json.loads((artifacts_dir / "prototype-evidence.json").read_text())
    csv_text = (artifacts_dir / "evaluation-report.csv").read_text()
    _lines, rows = _acceptance_rows(csv_text)
    screenshot_paths = evidence.get("screenshots") or []
    if not screenshot_paths:
        raise ValueError("prototype-evidence.json contains no screenshots")
    if len(set(screenshot_paths)) != len(screenshot_paths):
        raise ValueError("prototype-evidence.json contains duplicate screenshot paths")
    for relative in screenshot_paths:
        screenshot_path = (artifacts_dir / relative).resolve()
        if artifacts_dir not in screenshot_path.parents or not screenshot_path.is_file():
            raise ValueError(f"Screenshot is missing or outside artifacts directory: {relative}")
    criterion_ids = [row["criterion_id"] for row in rows]
    persona_ids = list((extract.get("persona_selection") or {}).get("selected") or [])
    if not persona_ids:
        raise ValueError("extract-state.json contains no selected personas")
    return {
        "artifacts_dir": artifacts_dir,
        "extract": extract,
        "evidence": evidence,
        "csv_text": csv_text,
        "rows": rows,
        "screenshot_paths": screenshot_paths,
        "criterion_ids": criterion_ids,
        "persona_ids": persona_ids,
    }


def build_journey_prompt(packet: dict[str, Any]) -> str:
    """Create the compact text input logged to telemetry and sent with images."""
    inputs = _load_inputs(packet)
    extract = inputs["extract"]
    criteria = [
        {
            "criterion_id": row["criterion_id"],
            "tier": row.get("tier", ""),
            "criterion_text": row.get("criterion_text", ""),
            "existing_verdict": row.get("verdict", ""),
            "human_action": row.get("human_action", ""),
        }
        for row in inputs["rows"]
    ]
    evidence = dict(inputs["evidence"])
    if isinstance(evidence.get("page"), dict):
        evidence["page"] = dict(evidence["page"])
        evidence["page"]["body_text"] = evidence["page"].get("body_text", "")[:12000]
    evaluated_at = datetime.now(timezone.utc).isoformat()
    context = {
        "prototype_url": packet["prototype_url"],
        "evaluated_at": evaluated_at,
        "persona_selection": extract.get("persona_selection"),
        "journey_definitions": extract.get("journey_definitions") or [],
        "tasks_to_be_done": extract.get("tasks_to_be_done") or [],
        "acceptance_criteria": criteria,
        "prototype_evidence": evidence,
        "allowed_screenshot_paths": inputs["screenshot_paths"],
    }
    return f"{PROCEDURE_PATH.read_text().strip()}\n\nEVALUATION INPUT\n{json.dumps(context, indent=2)}"


def _image_content(artifacts_dir: Path, relative: str) -> dict[str, str]:
    image_path = (artifacts_dir / relative).resolve()
    if artifacts_dir not in image_path.parents:
        raise ValueError(f"Screenshot path escapes artifacts directory: {relative}")
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        raise ValueError(f"Unsupported screenshot type: {mime_type}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded}",
        "detail": "high",
    }


def build_journey_request(
    packet: dict[str, Any], *, model: str, reasoning_effort: str = "low"
) -> dict[str, Any]:
    """Build one tool-free Responses request with strict Structured Outputs."""
    inputs = _load_inputs(packet)
    prompt = build_journey_prompt(packet)
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        _image_content(inputs["artifacts_dir"], relative)
        for relative in inputs["screenshot_paths"]
    )
    schema = journey_schema(
        screenshot_paths=inputs["screenshot_paths"],
        criterion_ids=inputs["criterion_ids"],
        persona_ids=inputs["persona_ids"],
    )
    return {
        "model": model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "You are the isolated eval-journey worker. Use only the supplied "
                    "text and images. Return data that exactly matches the strict schema."
                ),
            },
            {"role": "user", "content": content},
        ],
        "reasoning": {"effort": reasoning_effort},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "uxd_journey_log",
                "strict": True,
                "schema": schema,
            },
            "verbosity": "low",
        },
        "max_output_tokens": 6000,
        "store": False,
    }


def _output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise ValueError(f"OpenAI refused the journey request: {content.get('refusal', '')}")
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    if not chunks:
        raise ValueError("OpenAI response contained no structured output text")
    return "".join(chunks)


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the strict schema locally before any artifact is written."""
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        required = set(schema.get("required") or [])
        missing = required - set(value)
        extra = set(value) - set(schema.get("properties") or {})
        if missing:
            raise ValueError(f"{path} missing fields: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False and extra:
            raise ValueError(f"{path} has unexpected fields: {', '.join(sorted(extra))}")
        for key, child in value.items():
            if key in schema.get("properties", {}):
                _validate(child, schema["properties"][key], f"{path}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        if len(value) < int(schema.get("minItems", 0)):
            raise ValueError(f"{path} has too few items")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ValueError(f"{path} must contain unique items")
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path} does not match {schema['pattern']}")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} must be >= {schema['minimum']}")


def _render_updated_csv(csv_text: str, output: dict[str, Any]) -> str:
    results = {item["criterion_id"]: item for item in output["criterion_results"]}
    if len(results) != len(output["criterion_results"]):
        raise ValueError("criterion_results contains duplicate criterion IDs")
    _lines, rows = _acceptance_rows(csv_text)
    testable_ids = {row["criterion_id"] for row in rows if row.get("tier") in {"T1", "T2"}}
    missing_testable = testable_ids - set(results)
    if missing_testable:
        raise ValueError(
            "criterion_results must cover every T1/T2 criterion; "
            f"missing {sorted(missing_testable)}"
        )

    output_lines = []
    section = None
    headers: list[str] | None = None
    required_headers = [
        "criterion_id", "verdict", "rationale", "evidence",
        "fix_action", "fix_file", "human_action",
    ]
    for line in csv_text.splitlines():
        if line.startswith("# "):
            section = line[2:].strip().upper()
            headers = None
            output_lines.append(line)
            continue
        if section != "ACCEPTANCE CRITERIA" or not line.strip():
            output_lines.append(line)
            continue
        parsed = next(csv.reader([line]))
        if headers is None:
            headers = parsed
            missing = set(required_headers) - set(headers)
            if missing:
                raise ValueError(f"evaluation-report.csv missing columns: {sorted(missing)}")
            output_lines.append(line)
            continue
        parsed += [""] * max(0, len(headers) - len(parsed))
        row = dict(zip(headers, parsed))
        criterion = row["criterion_id"]
        if row.get("tier") in {"T1", "T2"}:
            result = results[criterion]
            for field in required_headers[1:]:
                row[field] = result[field]
        elif row.get("tier") == "T4":
            row["verdict"] = "FLAGGED"
            row["rationale"] = "Requires design-process evidence outside the prototype."
        stream = io.StringIO()
        csv.writer(stream, lineterminator="").writerow([row.get(header, "") for header in headers])
        output_lines.append(stream.getvalue())
    return "\n".join(output_lines).rstrip() + "\n"


def validate_journey_output(output: dict[str, Any], packet: dict[str, Any]) -> None:
    inputs = _load_inputs(packet)
    schema = journey_schema(
        screenshot_paths=inputs["screenshot_paths"],
        criterion_ids=inputs["criterion_ids"],
        persona_ids=inputs["persona_ids"],
    )
    _validate(output, schema)
    expected_personas = inputs["extract"]["persona_selection"]
    if output["prototype_url"] != packet["prototype_url"]:
        raise ValueError("prototype_url does not match the requested prototype")
    try:
        datetime.fromisoformat(output["evaluated_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("evaluated_at is not an ISO-8601 timestamp") from error
    if output["persona_selection"] != expected_personas:
        raise ValueError("persona_selection does not match deterministic extraction")
    known_ids = set(inputs["criterion_ids"])
    expected_journey_ids = {
        item.get("id")
        for item in inputs["extract"].get("journey_definitions") or []
        if item.get("id")
    }
    received_journey_ids = {item["id"] for item in output["journeys"]}
    if len(received_journey_ids) != len(output["journeys"]):
        raise ValueError("journeys contains duplicate journey IDs")
    if expected_journey_ids and received_journey_ids != expected_journey_ids:
        raise ValueError(
            "journeys must exactly cover extracted journey definitions; "
            f"expected {sorted(expected_journey_ids)}, received {sorted(received_journey_ids)}"
        )
    for journey in output["journeys"]:
        if not set(journey["ac_ids"]).issubset(known_ids):
            raise ValueError(f"{journey['id']} contains an unknown criterion ID")
        if len(set(journey["ac_ids"])) != len(journey["ac_ids"]):
            raise ValueError(f"{journey['id']} contains duplicate criterion IDs")
        if journey["steps_completed"] > journey["steps_expected"]:
            raise ValueError(f"{journey['id']} completed more steps than expected")
    _render_updated_csv(inputs["csv_text"], output)


def run_structured_journey(
    packet: dict[str, Any],
    *,
    model: str,
    reasoning_effort: str = "low",
    trace_path: str | None = None,
    request_fn: Callable[[dict[str, Any]], dict[str, Any]] = _request,
) -> dict[str, Any]:
    """Execute one structured request and atomically write validated artifacts."""
    started = time.monotonic()
    request = build_journey_request(packet, model=model, reasoning_effort=reasoning_effort)
    response = request_fn(request)
    if trace_path:
        trace_file = Path(trace_path)
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        trace_file.write_text(json.dumps(response) + "\n")
    if response.get("status") not in {None, "completed"}:
        raise ValueError(f"OpenAI journey response status was {response.get('status')}")
    output_text = _output_text(response)
    usage = _usage(response)
    cost = _cost(model, usage)
    try:
        output = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"OpenAI journey output was not valid JSON: {error}") from error
    validate_journey_output(output, packet)

    inputs = _load_inputs(packet)
    updated_csv = _render_updated_csv(inputs["csv_text"], output)
    artifacts_dir = inputs["artifacts_dir"]
    journey_path = artifacts_dir / "journey-log.json"
    csv_path = artifacts_dir / "evaluation-report.csv"
    journey_temp = journey_path.with_suffix(".json.tmp")
    csv_temp = csv_path.with_suffix(".csv.tmp")
    testable_ids = {
        row["criterion_id"] for row in inputs["rows"] if row.get("tier") in {"T1", "T2"}
    }
    artifact_output = {
        **output,
        "criterion_results": [
            result
            for result in output["criterion_results"]
            if result["criterion_id"] in testable_ids
        ],
    }
    journey_temp.write_text(json.dumps(artifact_output, indent=2) + "\n")
    csv_temp.write_text(updated_csv)
    journey_temp.replace(journey_path)
    csv_temp.replace(csv_path)

    return {
        "provider": "openai",
        "model": model,
        "agent": "responses-api-structured-journey",
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": 0,
        "status": "completed",
        "output_text": output_text,
        "token_usage": usage,
        "cost_usd": cost,
        "billing_source": "provider_estimate" if cost is not None else "unavailable",
        "turns_used": 1,
        "turn_limit_reached": False,
    }
