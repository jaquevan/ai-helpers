#!/usr/bin/env python3
"""Python pipeline adapter for the packaged browser-only persona runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from openai_api_agent import _cost


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


def run_live_usability(packet: dict[str, Any], *, model: str, reasoning_effort: str = "low", max_turns: int = 12, trace_path: str | None = None) -> dict[str, Any]:
    command = [
        "node", str(SCRIPT_DIR / "openai-browser-persona.js"),
        "--artifacts-dir", packet["artifacts_dir"], "--url", packet["prototype_url"],
        "--model", model, "--reasoning-effort", reasoning_effort,
        "--max-turns", str(max_turns),
    ]
    if trace_path:
        command.extend(["--trace", trace_path])
    completed = subprocess.run(command, cwd=packet["artifacts_dir"], capture_output=True, text=True, check=False)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        detail = (completed.stdout + completed.stderr)[-2000:]
        raise ValueError(f"Live browser persona runner returned invalid JSON: {error}; {detail}") from error
    result["cost_usd"] = _cost(model, result.get("token_usage") or {})
    result["billing_source"] = "provider_estimate" if result["cost_usd"] is not None else "unavailable"
    if completed.returncode != 0 and result.get("status") != "failed":
        raise ValueError(f"Live browser persona runner failed: {(completed.stdout + completed.stderr)[-2000:]}")
    return result
