#!/usr/bin/env python3
"""Ensure failed browser workers return paid usage to pipeline telemetry."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("live_usability_adapter", SCRIPT_DIR / "openai_live_usability.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def main() -> int:
    payload = {
        "provider": "openai", "model": "gpt-5.6-terra", "status": "failed",
        "exit_code": 2, "output_text": "provider unavailable", "turns_used": 2,
        "token_usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10, "cached_input_tokens": 0, "reasoning_tokens": 0},
    }
    original = adapter.subprocess.run
    adapter.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout=json.dumps(payload), stderr="")
    try:
        result = adapter.run_live_usability({"artifacts_dir": ".", "prototype_url": "http://localhost"}, model="gpt-5.6-terra")
    finally:
        adapter.subprocess.run = original
    assert result["status"] == "failed"
    assert result["turns_used"] == 2
    assert result["token_usage"]["total_tokens"] == 10
    assert result["cost_usd"] is not None
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
