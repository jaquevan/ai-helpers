#!/usr/bin/env python3
"""Verify deterministic phases stay local and providers use economical defaults."""

from pathlib import Path
import importlib.util
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_routing import route_for  # noqa: E402
from model_defaults import model_for  # noqa: E402
from model_pricing import estimated_cost  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("verify_langfuse", SCRIPT_DIR / "verify-langfuse.py")
verify_langfuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_langfuse)
estimator_spec = importlib.util.spec_from_file_location("langfuse_cost_estimate", SCRIPT_DIR / "langfuse-cost-estimate.py")
estimator = importlib.util.module_from_spec(estimator_spec)
estimator_spec.loader.exec_module(estimator)


def main() -> int:
    for phase in ("eval-extract", "eval-classify", "eval-consistency-source", "eval-report"):
        route = route_for(phase, "api")
        assert route["execution"] == "local"
        assert route["provider"] == "none"
        assert route["model"] == ""
        try:
            route_for(phase, "api", "gpt-6-sol")
        except ValueError as error:
            assert "deterministic" in str(error)
        else:
            raise AssertionError("Local phase accepted a model override")

    assert route_for("eval-journey", "api")["model"] == "gpt-6-sol"
    for platform in ("api", "codex", "cursor"):
        assert model_for("eval-journey", platform) == route_for("eval-journey", platform)["model"]
    for phase, model in verify_langfuse.OPENAI_PHASE_MODELS.items():
        assert route_for(phase, "api")["model"] == model, f"cost preflight disagrees with {phase} runtime route"
    assert estimator.OPENAI_PHASE_MODELS == verify_langfuse.OPENAI_PHASE_MODELS
    assert estimated_cost("gpt-6-sol", 1000, 100, 200, 300) == 0.00279
    assert route_for("eval-consistency-visual", "anthropic")["model"] == "claude-haiku-4-5"
    assert route_for("eval-heuristic", "api")["model"] == "gpt-6-sol"
    assert route_for("eval-usability", "api")["model"] == "gpt-6-sol"
    assert route_for("eval-fix", "api")["reasoning_effort"] == "high"
    assert route_for("eval-fix", "api", study=True)["model"] == "gpt-6-sol"
    assert route_for("eval-fix", "api")["model"] == "gpt-6-sol"
    assert route_for("eval-journey", "anthropic")["provider"] == "anthropic-compatible"
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
