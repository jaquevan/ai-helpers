#!/usr/bin/env python3
"""Resolve the cheapest allowed execution route for one evaluator phase."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG = Path(__file__).resolve().parent.parent / "config" / "phase-routing.json"


def load_routes() -> dict[str, Any]:
    payload = json.loads(CONFIG.read_text())
    if not payload.get("phases") or not payload.get("platform_providers"):
        raise ValueError(f"Invalid phase routing config: {CONFIG}")
    return payload


def route_for(phase: str, platform: str | None = None, model_override: str | None = None) -> dict[str, Any]:
    config = load_routes()
    selected_platform = platform or config["default_platform"]
    provider = config["platform_providers"].get(selected_platform)
    if not provider:
        raise ValueError(f"Unsupported evaluator platform: {selected_platform}")
    phase_config = config["phases"].get(phase)
    if not phase_config:
        raise ValueError(f"Unknown evaluator phase: {phase}")
    if phase_config["execution"] == "local":
        if model_override:
            raise ValueError(f"{phase} is deterministic and cannot accept a model override")
        return {
            "phase": phase,
            "platform": selected_platform,
            "execution": "local",
            "provider": "none",
            "model": "",
            "reasoning_effort": "none",
        }
    model = model_override or phase_config["models"].get(provider)
    if not model:
        raise ValueError(f"No {provider} model route for {phase}")
    return {
        "phase": phase,
        "platform": selected_platform,
        "execution": "model",
        "provider": provider,
        "model": model,
        "reasoning_effort": phase_config["reasoning_effort"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("phase")
    parser.add_argument("--platform")
    parser.add_argument("--model")
    args = parser.parse_args()
    print(json.dumps(route_for(args.phase, args.platform, args.model), separators=(",", ":")))
