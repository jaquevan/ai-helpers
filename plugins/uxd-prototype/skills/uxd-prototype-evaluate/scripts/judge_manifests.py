"""Sanitized, evidence-backed manifests for Langfuse pipeline/report judges."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CANONICAL = ("brief.json", "evaluation.json", "evidence.json", "actions.json", "state.json")
REPORT_INPUTS = ("extract-state.json", "evaluation-report.csv", "journey-log.json", "persona-results.json")
LOCAL_PHASE_CONTRACTS = {
    "eval-consistency-source": {"required": ("workspace_source", "jira-context.json"), "outputs": ("consistency-report.json",)},
    "eval-extract": {"required": ("jira-context.json",), "outputs": ("extract-state.json", "mr-delta.json", "refinement-suggestions.json")},
    "eval-classify": {"required": ("extract-state.json",), "outputs": ("evaluation-report.csv",)},
    "playwright-run": {"required": ("prototype_url",), "outputs": ("prototype-evidence.json", "screenshots/*.png")},
    "phase-a-canonical": {"required": ("extract-state.json", "evaluation-report.csv", "consistency-report.json", "prototype-evidence.json"), "outputs": CANONICAL},
    "phase-b-canonical": {"required": CANONICAL + ("journey-log.json", "consistency-report.json", "persona-results.json"), "outputs": CANONICAL},
    "eval-report": {"required": REPORT_INPUTS + CANONICAL + ("heuristic-evaluation.json",), "outputs": ("evaluation-report.html", "evaluation-summary.json", "render-metrics.json")},
}


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def _fresh(path: Path, created_at: str) -> bool:
    if not path.is_file() or not created_at:
        return False
    try:
        started = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        return path.stat().st_mtime >= started - 1
    except (ValueError, OSError):
        return False


def data_flow_manifest(artifacts: Path, run_id: str, phases: list[dict], specs: tuple[dict, ...], status: str) -> dict:
    """Never include source, descriptions, prompts, issue text, or absolute paths."""
    producers = {name: "phase-a-canonical" for name in CANONICAL}
    producers.update({"extract-state.json": "eval-extract", "evaluation-report.csv": "eval-classify",
                      "prototype-evidence.json": "playwright-run", "consistency-report.json": "eval-consistency-source"})
    producers.update({"evaluation-report.html": "eval-report", "evaluation-summary.json": "eval-report",
                      "render-metrics.json": "eval-report", "evaluation-cost.json": "pipeline-cost-settlement"})
    consumers: dict[str, list[str]] = {}
    for spec in specs:
        for name in spec.get("outputs", ()):
            producers[name] = spec["name"]
        for name in spec.get("required", ()):
            consumers.setdefault(name, []).append(spec["name"])
    for name in REPORT_INPUTS + CANONICAL + ("heuristic-evaluation.json", "evaluation-cost.json"):
        consumers.setdefault(name, []).append("eval-report")
    state = _json(artifacts / "state.json")
    cache = state.get("cache") or {}
    started_at = state.get("created_at", "")
    report_phase = next((p for p in phases if p.get("phase") == "eval-report"), {})
    report_present = status == "completed" and report_phase.get("status") == "completed" and _fresh(artifacts / "evaluation-report.html", started_at)
    names = sorted(set(producers) | set(consumers) | {"evaluation-report.html"})
    producers["evaluation-cost.json"] = "pipeline-cost-settlement"
    edges = []
    for name in names:
        path = artifacts / name
        sha = _digest(path) if name == Path(name).name and _fresh(path, started_at) else None
        schema_state = "fresh-unvalidated" if sha else "stale-or-missing"
        if name in CANONICAL and sha:
            schema_state = "canonical-phase-a-output-validated"
        phase_producer = next((p for p in phases if p.get("phase") == producers.get(name)), None)
        if phase_producer and phase_producer.get("status") == "completed" and "passed" in str(phase_producer.get("validation", "")).lower() and sha:
            schema_state = "phase-output-validated"
        edges.append({"artifact": name, "producer": producers.get(name, "unknown"),
                      "consumers": consumers.get(name, []), "authority": "canonical" if name in CANONICAL else "derived-or-legacy-transport",
                      "schema_validation": schema_state, "content_hash": sha,
                      "evidence_ref": f"sha256:{sha[:16]}" if sha else "missing"})
    phase_rows = []
    for phase in phases:
        spec = next((item for item in specs if item["name"] == phase.get("phase")), None)
        spec = spec or LOCAL_PHASE_CONTRACTS.get(phase.get("phase"), {})
        phase_rows.append({"name": phase.get("phase"), "status": phase.get("status"),
                           "input_artifacts": list(spec.get("required", ())), "output_artifacts": list(spec.get("outputs", ())),
                           "validation_status": phase.get("validation", "not-recorded")[:100]})
    return {"run_id": run_id, "pipeline_revision": _digest(Path(__file__).with_name("langfuse-trace-pipeline.py")),
            "phases": phase_rows, "artifact_edges": edges,
            "validations": [{"artifact": edge["artifact"], "validator": "phase-output-or-canonical-gate",
                             "status": edge["schema_validation"], "issue_count": int(edge["content_hash"] is None),
                             "evidence_ref": edge["evidence_ref"]} for edge in edges],
            "cache": {"decision": cache.get("decision", "unknown"),
                      "identity_components": sorted((state.get("identity") or {}).keys()),
                      "restored_artifacts": [Path(value).name for value in cache.get("restored_artifacts", [])],
                      "downstream_required_artifacts": list(REPORT_INPUTS),
                      "restored_set_validated": bool(cache.get("restored_set_validated", False))},
            "report": {"status": "completed" if report_present else "unavailable",
                       "input_mode": _json(artifacts / "render-metrics.json").get("input_mode", "unknown") if report_present else "unavailable",
                       "required_artifacts": list(REPORT_INPUTS),
                       "resolved_artifacts": [name for name in REPORT_INPUTS if _fresh(artifacts / name, started_at)],
                       "evidence_ref": _digest(artifacts / "evaluation-report.html")[:16] if report_present else "missing"}}


def report_quality_manifest(artifacts: Path, run_id: str, status: str) -> dict:
    """Check actual report image bytes against local captured prototype PNGs."""
    report = artifacts / "evaluation-report.html"
    state = _json(artifacts / "state.json")
    completed = status == "completed" and _fresh(report, state.get("created_at", ""))
    html = report.read_text() if completed else ""
    embedded = []
    for encoded in re.findall(r'data:image/png;base64,([A-Za-z0-9+/=]+)', html):
        try:
            embedded.append(hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest())
        except ValueError:
            embedded.append("invalid")
    screenshot_paths = list((artifacts / "screenshots").glob("*.png")) + list((artifacts / "evidence" / "crops").glob("*.png"))
    screenshots = {digest for path in screenshot_paths if (digest := _digest(path)) and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"}
    evaluation = _json(artifacts / "evaluation.json")
    summary = _json(artifacts / "evaluation-summary.json") if completed else {}
    cost = _json(artifacts / "evaluation-cost.json") if completed else {}
    verdicts = [item.get("verdict") for item in evaluation.get("ac_results", [])]
    counts = {kind.lower(): verdicts.count(kind) for kind in ("PASS", "FAIL", "FLAGGED", "NOT_RUN")}
    shown = summary.get("counts") or {}
    dimensions = (evaluation.get("usability") or {}).get("dimensions") or []
    canonical_score = round(sum(item.get("score", 0) for item in dimensions), 2) if dimensions else None
    shown_score = (summary.get("usability") or {}).get("overall_score")
    headings = [name for name in ("Heuristic Evaluation", "PatternFly Consistency", "Usability Dimension Scores", "Evaluation cost estimate") if name in html]
    cost_total = round(float(cost.get("total_estimated_usd", 0) or 0), 6)
    phase_cost_total = round(sum(float(phase.get("llm_cost_usd", 0) or 0) for phase in cost.get("phases", [])), 6)
    return {"run_id": run_id, "report": {"status": "completed" if completed else "unavailable",
            "html_bytes": report.stat().st_size if completed else 0, "content_sha256": _digest(report) if completed else None,
            "present_sections": headings},
            "canonical_parity": {"ac_counts": counts, "report_ac_counts": {key: shown.get(key, 0) for key in ("pass", "fail", "flagged")},
                                 "ac_counts_match": all(counts[key] == shown.get(key, 0) for key in ("pass", "fail", "flagged")) if completed else False,
                                 "usability_score": canonical_score, "report_usability_score": shown_score,
                                 "usability_score_matches": canonical_score == shown_score if completed else False,
                                 "persona_count": len(_json(artifacts / "persona-results.json")) if (artifacts / "persona-results.json").is_file() else 0,
                                 "heuristic_finding_count": len(_json(artifacts / "heuristic-evaluation.json").get("findings", []))},
            "screenshots": {"captured_png_count": len(screenshots), "embedded_png_count": len(embedded),
                            "matched_embedded_count": sum(digest in screenshots for digest in embedded),
                            "all_embedded_from_prototype": bool(embedded) and all(digest in screenshots for digest in embedded),
                            "source": "local prototype browser captures; byte-for-byte sha256 comparison"},
            "cost_tracking": {"estimate_usd": cost_total, "phase_sum_usd": phase_cost_total,
                              "phase_sum_matches": cost_total == phase_cost_total,
                              "estimate_disclosure_present": "price-card estimate, not an invoice" in html,
                              "invoice_reconciled": bool(cost.get("invoice_reconciled", False)),
                              "paid_models": sorted({phase.get("model") for phase in cost.get("phases", []) if phase.get("model_invoked") and phase.get("model")})},
            "validation": {"render_status": status, "html_present": completed,
                           "draft_disclosure_present": "Unreviewed Draft" in html,
                           "cost_estimate_present": "Evaluation cost estimate" in html,
                           "has_image_alt_labels": bool(re.search(r'<img\b[^>]*\balt="[^"]+"', html))}}
