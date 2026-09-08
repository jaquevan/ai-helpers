#!/usr/bin/env python3
"""Load provider/platform-aware phase defaults from config/model-defaults.yaml.

Usage:
  python3 model_defaults.py                         # print the resolved defaults
  python3 model_defaults.py eval-extract           # print one model slug
  python3 model_defaults.py eval-extract anthropic # select a platform explicitly
"""
import os
from pathlib import Path
import sys

CONFIG = Path(__file__).resolve().parent.parent / "config" / "model-defaults.yaml"
FALLBACK = "gpt-5.6-terra"
PLATFORMS = {"api", "codex", "cursor", "anthropic"}


def load_config():
    if not CONFIG.is_file():
        raise FileNotFoundError(f"Missing model defaults: {CONFIG}")
    config = {"default_platform": "api", "platforms": {}}
    platform = None
    in_phases = False
    for raw in CONFIG.read_text().splitlines():
        uncommented = raw.split("#", 1)[0].rstrip()
        line = uncommented.strip()
        if not line or line == "platforms:":
            continue
        indent = len(uncommented) - len(uncommented.lstrip())
        if indent == 0 and line.startswith("default_platform:"):
            config["default_platform"] = line.split(":", 1)[1].strip().strip("'\"")
            continue
        if indent == 2 and line.endswith(":"):
            platform = line[:-1]
            config["platforms"].setdefault(platform, {"phases": {}})
            in_phases = False
            continue
        if platform and indent == 4 and line.startswith("provider:"):
            config["platforms"][platform]["provider"] = line.split(":", 1)[1].strip().strip("'\"")
            continue
        if platform and indent == 4 and line == "phases:":
            in_phases = True
            continue
        if platform and in_phases and indent >= 6 and ":" in line:
            key, value = line.split(":", 1)
            config["platforms"][platform]["phases"][key.strip()] = value.strip().strip("'\"")
    if not config["platforms"]:
        raise ValueError(f"No phases found in {CONFIG}")
    return config


def detect_platform(explicit=None):
    requested = explicit or os.environ.get("AI_HELPERS_PLATFORM") or os.environ.get("EVAL_PLATFORM")
    if requested:
        requested = requested.lower().strip()
        if requested in PLATFORMS:
            return requested
        raise ValueError(f"Unknown platform '{requested}'. Choose: {', '.join(sorted(PLATFORMS))}")

    # These signals are intentionally conservative. Direct API is the safe
    # non-interactive default when neither host exposes a stable marker.
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("CURSOR_AGENT") or os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    if sys.stdin.isatty() and not os.environ.get("CI"):
        answer = input(
            "AI helpers platform [api/codex/cursor/anthropic] (default: api): "
        ).strip().lower()
        if answer in PLATFORMS:
            return answer
    return load_config().get("default_platform", "api")


def model_for(phase, platform=None):
    config = load_config()
    selected = detect_platform(platform)
    entry = config["platforms"].get(selected) or config["platforms"].get(config["default_platform"], {})
    return entry.get("phases", {}).get(phase, FALLBACK)


def provider_for(platform=None):
    config = load_config()
    selected = detect_platform(platform)
    entry = config["platforms"].get(selected, {})
    return entry.get("provider", "openai")


if __name__ == "__main__":
    platform = sys.argv[2] if len(sys.argv) > 2 else None
    if len(sys.argv) > 1:
        print(model_for(sys.argv[1], platform))
        sys.exit(0)
    selected = detect_platform(platform)
    phases = load_config()["platforms"][selected]["phases"]
    print(f"platform {selected} provider {provider_for(selected)}")
    for phase, model in phases.items():
        print(f"{phase} {model}")
