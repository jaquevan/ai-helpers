#!/usr/bin/env python3
"""Python pipeline adapter for the packaged browser-only persona runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from openai_api_agent import _cost
from usage_journal import UsageJournal


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PERSONAS_DIR = SKILL_DIR.parents[1] / "knowledge" / "personas"


def build_live_usability_prompt(packet: dict[str, Any]) -> str:
    """Build the safe, inspectable phase input used by Langfuse telemetry."""
    artifacts = Path(packet["artifacts_dir"]).resolve()
    extract = json.loads((artifacts / "extract-state.json").read_text())
    personas = []
    for selected_id in (extract.get("persona_selection") or {}).get("selected") or []:
        role, _, overlay = selected_id.partition("+")
        card = PERSONAS_DIR / f"{role}.md"
        if not card.is_file():
            raise ValueError(f"Bundled persona card not found: {role}")
        personas.append({
            "id": selected_id,
            "profile": card.read_text()[:9000],
            "experience_overlay": overlay,
        })
    context = {
        "prototype_url": packet["prototype_url"],
        "personas": personas,
        "tasks": extract.get("tasks_to_be_done") or [],
        "acceptance_criteria": extract.get("ac_list") or [],
        "available_tools": [
            "browser_observe", "browser_click", "browser_type",
            "browser_navigate", "browser_press",
        ],
        "forbidden_capabilities": [
            "shell", "filesystem", "file search", "grep", "workspace exploration",
        ],
    }
    procedure = (SKILL_DIR / "references" / "api-phases" / "eval-usability-live.md").read_text().strip()
    return f"{procedure}\n\nLIVE PERSONA INPUT\n{json.dumps(context, indent=2)}"


def run_live_usability(
    packet: dict[str, Any], *, model: str, reasoning_effort: str = "low",
    max_turns: int = 12, max_output_tokens: int = 4000,
    trace_path: str | None = None, usage_journal_path: str | None = None,
    run_id: str | None = None, attempt_id: str | None = None,
    timeout_seconds: int = 1200,
) -> dict[str, Any]:
    command = [
        "node", str(SCRIPT_DIR / "openai-browser-persona.js"),
        "--artifacts-dir", packet["artifacts_dir"], "--url", packet["prototype_url"],
        "--model", model, "--reasoning-effort", reasoning_effort,
        "--max-turns", str(max_turns),
        "--max-output-tokens", str(max_output_tokens),
    ]
    if trace_path:
        command.extend(["--trace", trace_path])
    if usage_journal_path:
        command.extend(["--usage-journal", usage_journal_path])
    if run_id:
        command.extend(["--run-id", run_id])
    if attempt_id:
        command.extend(["--attempt-id", attempt_id])
    try:
        completed = subprocess.run(
            command, cwd=packet["artifacts_dir"], capture_output=True,
            text=True, check=False, timeout=max(1, int(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Live browser persona child exceeded its wall-time bound") from error
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        detail = (completed.stdout + completed.stderr)[-2000:]
        raise ValueError(f"Live browser persona runner returned invalid JSON: {error}; {detail}") from error
    result["cost_usd"] = _cost(model, result.get("token_usage") or {})
    usage_summary = (
        UsageJournal(
            usage_journal_path, run_id=run_id, attempt_id=attempt_id,
            phase="eval-usability", model=model,
        ).summary()
        if usage_journal_path else None
    )
    if usage_summary:
        result["token_usage"] = usage_summary["token_usage"]
        result["usage_known"] = usage_summary["usage_known"]
        result["usage_unknown"] = usage_summary["usage_unknown"]
        result["unknown_request_ids"] = usage_summary["unknown_request_ids"]
        result["known_usage_cost_usd"] = usage_summary["known_usage_cost_usd"]
        result["cost_usd"] = (
            usage_summary["cost_usd"]
            if usage_summary["usage_known"] and usage_summary["cost_known"] else None
        )
    else:
        result["usage_known"] = result.get("usage_known", True)
    result["billing_source"] = "provider_estimate" if result["cost_usd"] is not None else "unavailable"
    if completed.returncode != 0 and result.get("status") != "failed":
        raise ValueError(f"Live browser persona runner failed: {(completed.stdout + completed.stderr)[-2000:]}")
    return result
