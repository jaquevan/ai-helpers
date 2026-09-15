#!/usr/bin/env python3
"""Verify deterministic phases stay local and providers use economical defaults."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_routing import route_for  # noqa: E402


def main() -> int:
    for phase in ("eval-extract", "eval-classify", "eval-consistency-source", "eval-report"):
        route = route_for(phase, "api")
        assert route["execution"] == "local"
        assert route["provider"] == "none"
        assert route["model"] == ""
        try:
            route_for(phase, "api", "gpt-5.6-sol")
        except ValueError as error:
            assert "deterministic" in str(error)
        else:
            raise AssertionError("Local phase accepted a model override")

    assert route_for("eval-journey", "api")["model"] == "gpt-5.6-luna"
    assert route_for("eval-consistency-visual", "anthropic")["model"] == "claude-haiku-4-5"
    assert route_for("eval-usability", "api")["model"] == "gpt-5.6-terra"
    assert route_for("eval-fix", "api")["reasoning_effort"] == "high"
    assert route_for("eval-journey", "anthropic")["provider"] == "anthropic-compatible"
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
