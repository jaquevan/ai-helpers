#!/usr/bin/env python3
"""Synthetic regressions; these are not the missing historical ledger."""
import importlib.util
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "scripts/reconcile-ledger.py"
spec = importlib.util.spec_from_file_location("ledger_reconciliation", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def observation(name, parent, status, cost, attempt=None):
    return {"id": f"{parent}-{name}", "name": name, "parentObservationId": parent,
            "metadata": {"eval_run_id": "fixture-run", "status": status,
                         "estimated_cost_usd": cost, "attempt_id": attempt}}


def main():
    rows = [{"eval_run_id": "fixture-run", "totals": {"llm_cost_usd": 0},
             "phases": [{"phase": "eval-consistency-visual", "model": "fixture-model",
                         "status": "failed", "llm_cost_usd": None}]}]
    remote = [observation("eval-journey", "early-attempt", "completed", 0.035321),
              observation("eval-journey", "later-attempt", "completed", 0.0337485),
              observation("eval-consistency-visual", "later-attempt", "completed", 0.0735414)]
    result = module.reconcile(rows, remote, "fixture-run")
    assert result["rows"][0]["phases"][0]["result"] == "ambiguous_attempt"
    assert result["rows"][0]["warnings"]
    assert result["repeated_phase_names"] == ["eval-journey"]

    rows[0]["phases"][0].update(attempt_id="attempt-1", known_usage_cost_usd=0.01)
    remote.append(observation("eval-consistency-visual", "early-attempt", "failed", 0.01, "attempt-1"))
    result = module.reconcile(rows, remote, "fixture-run")
    phase = result["rows"][0]["phases"][0]
    assert phase["result"] == "matched"
    assert len(phase["candidates"]) == 1
    remote[-1]["metadata"]["status"] = "completed"
    result = module.reconcile(rows, remote, "fixture-run")
    assert result["rows"][0]["phases"][0]["result"] == "mismatch"
    assert result["rows"][0]["phases"][0]["differences"] == ["status"]
    assert module.reconcile(rows, remote, "unrelated-run")["ledger_rows"] == 0
    unknown = observation("eval-journey", "unknown", "failed", None)
    unknown["costDetails"] = {"total": 99}
    assert module.observation_summary(unknown)["known_cost_usd"] is None
    print("PASS: attempt-aware ledger reconciliation")


if __name__ == "__main__":
    main()
