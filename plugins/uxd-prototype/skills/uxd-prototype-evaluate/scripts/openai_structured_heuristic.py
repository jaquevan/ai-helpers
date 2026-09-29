#!/usr/bin/env python3
"""Run the sibling heuristic skill as one bounded structured visual phase."""

from __future__ import annotations

import base64
import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openai_api_agent import _cost, _request, _usage, request_with_capture
from openai_structured_journey import _image_content, _object, _output_text, _validate
from openai_structured_visual import _load_inputs
from prompt_cache import prefix_metrics


SKILL_DIR = Path(__file__).resolve().parent.parent
HEURISTIC_DIR = SKILL_DIR.parents[2] / "uxd-research" / "skills" / "uxd-research-heuristic-eval"
FRAMEWORK_PATH = HEURISTIC_DIR / "references" / "heuristic-frameworks.md"
HEURISTICS = [
    ("nielsen-1", "Visibility of system status"),
    ("nielsen-2", "Match between system and the real world"),
    ("nielsen-3", "User control and freedom"),
    ("nielsen-4", "Consistency and standards"),
    ("nielsen-5", "Error prevention"),
    ("nielsen-6", "Recognition rather than recall"),
    ("nielsen-7", "Flexibility and efficiency of use"),
    ("nielsen-8", "Aesthetic and minimalist design"),
    ("nielsen-9", "Help users recognize, diagnose, and recover from errors"),
    ("nielsen-10", "Help and documentation"),
]
FINDING_IDS = [f"V-{number:02d}" for number in range(1, 11)]
CANDIDATE_IDS = [f"{evaluator}{number}" for evaluator in "ABC" for number in range(1, 11)]


def _framework_text() -> str:
    text = FRAMEWORK_PATH.read_text()
    start = text.index("## Nielsen's 10 Usability Heuristics")
    end = text.index("\n## ", start + 3)
    return text[start:end].strip()


def heuristic_schema(screenshots: list[str]) -> dict[str, Any]:
    evaluator_properties = {
        "id": {"type": "string", "enum": ["A", "B", "C"]},
        "candidate_ids": {"type": "array", "items": {"type": "string", "enum": CANDIDATE_IDS}, "maxItems": 10},
    }
    evaluator = _object(evaluator_properties, list(evaluator_properties))
    finding_properties = {
        "id": {"type": "string", "enum": FINDING_IDS},
        "candidate_ids": {"type": "array", "items": {"type": "string", "enum": CANDIDATE_IDS}, "minItems": 1, "maxItems": 30},
        "title": {"type": "string"},
        "screenshot": {"type": "string", "enum": screenshots},
        "location": {"type": "string"},
        "heuristic_id": {"type": "string", "enum": [item[0] for item in HEURISTICS]},
        "observation": {"type": "string"},
        "evidence": {"type": "string"},
        "suggested_severity": {"type": "string", "enum": ["critical", "major", "minor", "cosmetic"]},
        "agreement": {"type": "string", "enum": ["unanimous", "majority", "single"]},
        "identified_by": {"type": "array", "items": {"type": "string", "enum": ["A", "B", "C"]}, "minItems": 1, "maxItems": 3},
        "borderline": {"type": "boolean"},
        "user_testing_signal": {"type": "string"},
    }
    finding = _object(finding_properties, list(finding_properties))
    properties = {
        "evaluators": {"type": "array", "items": evaluator, "minItems": 3, "maxItems": 3},
        "findings": {"type": "array", "items": finding, "maxItems": 10},
        "coverage_limitations": {"type": "array", "items": {"type": "string"}},
    }
    return _object(properties, list(properties))


def build_heuristic_static_prefix() -> str:
    return (
        "Run an unattended heuristic inspection using three simulated independent passes. "
        "Evaluator A inspects visual hierarchy and affordances; B follows the task flow; C checks edge cases and missing states. "
        "Reconcile duplicate candidates. Report observable violations only: no recommendations, accessibility claims, or confirmed severity. "
        "Use candidate IDs A1–A10, B1–B10, C1–C10 and finding IDs V-01–V-10. "
        "All severities are suggestions in an unreviewed draft. Report at most ten consolidated findings; "
        "keep each observation, evidence statement, and user-testing signal concise. Return strict schema data only.\n\n"
        + _framework_text()
    )


def build_heuristic_prompt(packet: dict[str, Any]) -> str:
    inputs = _load_inputs(packet)
    context = {
        "review_subject": packet["key"],
        "source_url": packet["prototype_url"],
        "task_context": [item.get("title") for item in inputs["journey"].get("journeys", [])],
        "screenshots": inputs["screenshots"],
        "page_evidence": inputs["evidence"].get("page", {}),
        "journeys": inputs["journey"].get("journeys", []),
        "mode": {"framework": "Nielsen's 10", "review": "none", "defaults_assumed": True},
    }
    return f"HEURISTIC EVALUATION INPUT\n{json.dumps(context, indent=2)}"


def build_heuristic_request(packet: dict[str, Any], *, model: str, reasoning_effort: str = "low") -> dict[str, Any]:
    inputs = _load_inputs(packet)
    content = [{"type": "input_text", "text": build_heuristic_prompt(packet)}]
    content.extend(_image_content(inputs["artifacts"], path) for path in inputs["screenshots"])
    return {
        "model": model,
        "input": [
            {"role": "developer", "content": build_heuristic_static_prefix()},
            {"role": "user", "content": content},
        ],
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": {"type": "json_schema", "name": "uxd_heuristic_evaluation", "strict": True, "schema": heuristic_schema(inputs["screenshots"])}, "verbosity": "low"},
        "max_output_tokens": 16000,
        "store": False,
    }


def validate_heuristic_output(output: dict[str, Any], packet: dict[str, Any]) -> None:
    inputs = _load_inputs(packet)
    _validate(output, heuristic_schema(inputs["screenshots"]))
    if [item["id"] for item in output["evaluators"]] != ["A", "B", "C"]:
        raise ValueError("Heuristic output must contain evaluator passes A, B, and C in order")
    finding_ids = [item["id"] for item in output["findings"]]
    if len(finding_ids) != len(set(finding_ids)):
        raise ValueError("Heuristic findings contain duplicate IDs")
    for finding in output["findings"]:
        expected = {"single": 1, "majority": 2, "unanimous": 3}[finding["agreement"]]
        if len(set(finding["identified_by"])) != len(finding["identified_by"]):
            raise ValueError(f"{finding['id']} identified_by contains duplicate evaluators")
        if len(finding["identified_by"]) != expected:
            raise ValueError(f"{finding['id']} agreement does not match identified_by")


def _document(packet: dict[str, Any], output: dict[str, Any], screenshots: list[str]) -> dict[str, Any]:
    return {
        "source": "uxd-research-heuristic-eval",
        "status": "unreviewed-draft",
        "framework": "Nielsen's 10 Usability Heuristics",
        "defaults_assumed": True,
        "review_subject": {
            "title": packet["key"],
            "source_url": packet["prototype_url"],
            "source_files": screenshots,
            "input_type": "URL and captured screenshots",
            "task_context": "Prototype journey evaluation",
            "evaluation_date": datetime.now(timezone.utc).date().isoformat(),
        },
        **output,
    }


def _render_markdown(document: dict[str, Any]) -> str:
    subject = document["review_subject"]
    lines = [
        f"# Heuristic Evaluation: {subject['title']}", "",
        "> **Unreviewed Draft**", ">", "> Severity ratings are AI-suggested and have not been confirmed by a researcher.",
        "> Defaults assumed: framework=Nielsen's 10, review=none, no specialist passes.", "",
        f"**Source URL:** {subject['source_url']}  ", f"**Evaluation date:** {subject['evaluation_date']}  ",
        f"**Source files:** {', '.join(subject['source_files'])}", "", "## Evaluator Legend", "",
        "| Evaluator | Lens | Focus |", "|---|---|---|",
        "| A | Visual inspection | Labels, layout, hierarchy, affordances, and feedback |",
        "| B | Task flow | Transitions, action feedback, and lost context |",
        "| C | Edge cases | Empty, error, long-content, and missing states |", "",
        "## Consolidated Findings", "",
    ]
    if not document["findings"]:
        lines.append("No heuristic violations were identified in the supplied evidence.")
    for finding in document["findings"]:
        name = dict(HEURISTICS)[finding["heuristic_id"]]
        lines.extend([
            f"### {finding['id']}. {finding['title']}",
            f"- Heuristic: {name}", f"- Screen/location: {finding['location']}",
            f"- Observation: {finding['observation']}", f"- Evidence: {finding['evidence']} ({finding['screenshot']})",
            f"- Suggested severity: {finding['suggested_severity'].title()}",
            f"- Agreement: {finding['agreement'].title()} ({', '.join(finding['identified_by'])})",
            f"- User testing signal: {finding['user_testing_signal'] or 'None'}", "",
        ])
    lines.extend(["## Coverage Notes", ""] + [f"- {item}" for item in document["coverage_limitations"]])
    lines.extend(["- Accessibility / WCAG conformance was not evaluated.", "", "*AI-simulated heuristic evaluation; researcher review required.*", ""])
    return "\n".join(lines)


def _render_html(document: dict[str, Any], artifacts: Path) -> str:
    subject = document["review_subject"]
    images = []
    for relative in document["review_subject"]["source_files"]:
        data = base64.b64encode((artifacts / relative).read_bytes()).decode()
        images.append(f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(relative)}"><figcaption>{html.escape(relative)}</figcaption></figure>')
    findings = []
    for item in document["findings"]:
        name = dict(HEURISTICS)[item["heuristic_id"]]
        findings.append(f'<article><h3>{html.escape(item["id"])}. {html.escape(item["title"])}</h3><p><strong>{html.escape(name)}</strong> · Suggested severity: {html.escape(item["suggested_severity"].title())} · {html.escape(item["agreement"].title())}</p><p>{html.escape(item["observation"])}</p><p><strong>Evidence:</strong> {html.escape(item["evidence"])}</p></article>')
    legend = '<table><thead><tr><th>Evaluator</th><th>Lens</th><th>Focus</th></tr></thead><tbody><tr><td>A</td><td>Visual inspection</td><td>Labels, layout, hierarchy, affordances, and feedback</td></tr><tr><td>B</td><td>Task flow</td><td>Transitions, action feedback, and lost context</td></tr><tr><td>C</td><td>Edge cases</td><td>Empty, error, long-content, and missing states</td></tr></tbody></table>'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Heuristic Evaluation: {html.escape(subject['title'])}</title><style>body{{font:16px/1.5 system-ui;max-width:1100px;margin:auto;padding:2rem;color:#151515}}.warning{{background:#fff3cd;border:1px solid #ffecb5;border-left:4px solid #ffc107;padding:1rem}}article,figure{{border:1px solid #d2d2d2;border-radius:8px;padding:1rem;margin:1rem 0}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d2d2d2;padding:.5rem;text-align:left}}</style><body><h1>Heuristic Evaluation: {html.escape(subject['title'])}</h1><div class="warning"><strong>Unreviewed Draft</strong><br>Severity ratings are AI-suggested and have not been confirmed by a researcher. Defaults assumed: framework=Nielsen's 10, review=none, no specialist passes.</div><p><strong>Source URL:</strong> <a href="{html.escape(subject['source_url'])}">{html.escape(subject['source_url'])}</a><br><strong>Evaluation date:</strong> {subject['evaluation_date']}</p><h2>Evaluator Legend</h2>{legend}<details><summary>Source screenshots</summary>{''.join(images) or '<p>No source screenshots.</p>'}</details><h2>Consolidated Findings</h2>{''.join(findings) or '<p>No heuristic violations were identified in the supplied evidence.</p>'}<h2>Coverage Notes</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in document['coverage_limitations'])}<li>Accessibility / WCAG conformance was not evaluated.</li></ul><p><em>AI-simulated heuristic evaluation; researcher review required.</em></p></body></html>'''


def run_structured_heuristic(
    packet: dict[str, Any], *, model: str, reasoning_effort: str = "low",
    max_turns: int = 1, trace_path: str | None = None,
    usage_journal_path: str | None = None, run_id: str | None = None,
    attempt_id: str | None = None,
    request_fn: Callable[[dict[str, Any]], dict[str, Any]] = _request,
) -> dict[str, Any]:
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")
    started = time.monotonic()
    request = build_heuristic_request(packet, model=model, reasoning_effort=reasoning_effort)
    response = request_with_capture(
        request, request_fn=request_fn, usage_journal_path=usage_journal_path,
        trace_path=trace_path, run_id=run_id, attempt_id=attempt_id,
        phase="eval-heuristic", model=model,
    )
    if response.get("status") not in {None, "completed"}:
        # Incomplete Responses still consume provider tokens. Return their usage
        # to the pipeline so the cap ledger can settle the reservation accurately.
        usage = _usage(response)
        detail = (response.get("incomplete_details") or {}).get("reason")
        usage_known = isinstance(response.get("usage"), dict) and all(
            isinstance(response["usage"].get(field), int)
            for field in ("input_tokens", "output_tokens")
        )
        return {"provider": "openai", "model": model, "agent": "responses-api-structured-heuristic", "duration_s": round(time.monotonic() - started, 3), "exit_code": 2, "status": "failed", "output_text": f"OpenAI heuristic response {response.get('status')} ({detail or 'no reason supplied'})", "token_usage": usage, "usage_known": usage_known, "cost_usd": _cost(model, usage) if usage_known else None, "billing_source": "provider_estimate" if usage_known else "unavailable", "turns_used": 1, "turn_limit_reached": detail == "max_output_tokens"}
    output_text = _output_text(response)
    output = json.loads(output_text)
    validate_heuristic_output(output, packet)
    inputs = _load_inputs(packet)
    document = _document(packet, output, inputs["screenshots"])
    targets = {
        "heuristic-evaluation.json": json.dumps(document, indent=2) + "\n",
        "heuristic-evaluation.md": _render_markdown(document),
        "heuristic-evaluation.html": _render_html(document, inputs["artifacts"]),
    }
    for name, content in targets.items():
        target = inputs["artifacts"] / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content); temporary.replace(target)
    usage = _usage(response); cost = _cost(model, usage)
    usage_known = isinstance(response.get("usage"), dict) and all(
        isinstance(response["usage"].get(field), int)
        for field in ("input_tokens", "output_tokens")
    )
    return {"provider": "openai", "model": model, "agent": "responses-api-structured-heuristic", "duration_s": round(time.monotonic() - started, 3), "exit_code": 0, "status": "completed", "output_text": output_text, "token_usage": usage, "usage_known": usage_known, "cost_usd": cost if usage_known else None, "billing_source": "provider_estimate" if cost is not None and usage_known else "unavailable", "turns_used": 1, "turn_limit_reached": False, "prompt_cache": prefix_metrics(build_heuristic_static_prefix(), build_heuristic_prompt(packet))}
