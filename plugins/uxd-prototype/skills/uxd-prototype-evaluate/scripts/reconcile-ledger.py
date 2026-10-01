#!/usr/bin/env python3
"""Read-only, attempt-aware comparison of a JSONL ledger and exported observations.

No API calls, invoice reconstruction, ledger rewrites, or replay of model work.
Legacy run IDs are not enough to prove that two records belong to one attempt.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def observation_summary(observation):
    metadata = observation.get("metadata") or {}
    if "known_usage_cost_usd" in metadata:
        cost = metadata["known_usage_cost_usd"]
    elif "estimated_cost_usd" in metadata:
        cost = metadata["estimated_cost_usd"]
    elif metadata.get("billing_source") in {"provider_usage_price_card_estimate", "opencode-model-price-card"}:
        cost = (observation.get("costDetails") or observation.get("cost") or {}).get("total")
    else:
        cost = None
    return {
        "id": observation.get("id"), "phase": observation.get("name"),
        "attempt_id": metadata.get("attempt_id"), "status": metadata.get("status"),
        "usage_known": metadata.get("usage_known"), "known_cost_usd": cost,
        "parent_id": observation.get("parentObservationId", observation.get("parent_id")),
        "start_time": observation.get("startTime", observation.get("start_time")),
        "end_time": observation.get("endTime", observation.get("end_time")),
    }


def reconcile(ledger, observations, run_id):
    rows = [(index + 1, row) for index, row in enumerate(ledger) if row.get("eval_run_id") == run_id]
    observed = [observation_summary(o) for o in observations
                if run_id in {(o.get("metadata") or {}).get("eval_run_id"),
                              (o.get("metadata") or {}).get("run_id")}]
    phase_names = {phase.get("phase") for _, row in rows for phase in row.get("phases", [])}
    # Exact phase names distinguish phase containers from request-level child
    # generations, which may legitimately be numerous within one attempt.
    counts = Counter(o["phase"] for o in observed if o["phase"] in phase_names or str(o["phase"]).startswith("eval-"))
    repeated = sorted(name for name, count in counts.items() if count > 1)
    results = []
    for line, row in rows:
        warnings = []
        unknown = [p.get("phase") for p in row.get("phases", [])
                   if p.get("usage_known") is False or
                   (p.get("model") and p.get("llm_cost_usd", p.get("cost_usd")) is None)]
        if (row.get("totals") or {}).get("llm_cost_usd") == 0 and unknown:
            warnings.append("zero_total_with_unknown_phase_cost; zero is not proof of zero spend")
        phases = []
        for phase in row.get("phases", []):
            attempt = phase.get("attempt_id")
            candidates = [o for o in observed if o["phase"] == phase.get("phase")]
            if attempt:
                candidates = [o for o in candidates if o["attempt_id"] == attempt]
            comparison = {"phase": phase.get("phase"), "attempt_id": attempt,
                          "ledger_status": phase.get("status"), "candidates": candidates}
            if not candidates:
                comparison["result"] = "no_matching_observation"
            elif len(candidates) != 1 or (not attempt and (repeated or len(rows) > 1)):
                comparison["result"] = "ambiguous_attempt"
            else:
                candidate = candidates[0]
                differences = []
                for field in ("status", "usage_known"):
                    if phase.get(field) is not None and candidate.get(field) is not None and phase[field] != candidate[field]:
                        differences.append(field)
                known = phase.get("known_usage_cost_usd", phase.get("llm_cost_usd", phase.get("cost_usd")))
                remote = candidate["known_cost_usd"]
                if numeric(known) and numeric(remote) and abs(known - remote) > 1e-8:
                    differences.append("known_cost_usd")
                comparison["differences"] = differences
                comparison["result"] = ("mismatch" if differences else "matched") if attempt else "unverified_candidate"
            phases.append(comparison)
        results.append({"ledger_line": line, "date": row.get("date"), "totals": row.get("totals"),
                        "warnings": warnings, "phases": phases})
    return {
        "eval_run_id": run_id, "ledger_rows": len(rows), "repeated_phase_names": repeated,
        "rows": results,
        "note": "Costs are recorded estimates. Ambiguous legacy attempts require their original usage journals or per-invocation artifacts; no historical records were modified.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    ledger = [json.loads(line) for line in args.ledger.read_text().splitlines() if line.strip()]
    document = json.loads(args.observations.read_text())
    observations = document if isinstance(document, list) else document.get("observations", document.get("data"))
    if not isinstance(observations, list):
        parser.error("Observation export must contain a data or observations array.")
    print(json.dumps(reconcile(ledger, observations, args.run_id), indent=2))


if __name__ == "__main__":
    main()
