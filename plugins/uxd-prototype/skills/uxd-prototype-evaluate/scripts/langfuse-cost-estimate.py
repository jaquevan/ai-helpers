#!/usr/bin/env python3
"""Pre-run cost estimate from Langfuse trace history (zero-spend).

Lola-eval pattern, no database: read prior `eval-iterate/<KEY>` traces from
the Langfuse public API, group them by run_mode x fix_mode x model_tier, and
estimate the next run in tiers:

  [calibrated] median of prior runs matching run_mode+fix_mode(+tier)
  [similar]    same run_mode+fix_mode, different tier
  [bound]      OPENAI_PHASE_BOUNDS x OPENAI_PRICING_PER_MTOK (pre-calibration prior)

Config file overrides (highest precedence first):
  flat_usd_per_run   bypasses everything; every phase row shows 0
  rates_per_mtok     recompute cost from observed/bound tokens at given rates
  token_budgets      replace token counts (rate or proportional rescale)
  multiplier / phase_multipliers  scale the final numbers

Reads traces/observations only — never writes, never spends model tokens.

Usage:
  eval "$(make langfuse-env)"
  python3 langfuse-cost-estimate.py --key RHAISTRAT-1492
  python3 langfuse-cost-estimate.py --key RHAISTRAT-1492 \
    --run-mode fresh --fix-mode no_fix --model-tier premium \
    --config config/cost-estimate.example.json
  python3 langfuse-cost-estimate.py --key RHAISTRAT-1492 --budget-usd 5.00
  python3 langfuse-cost-estimate.py --key RHAISTRAT-1492 --json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import langfuse_trace  # noqa: E402
from model_routing import route_for  # noqa: E402

PAID_PHASE_ORDER = ("eval-journey", "eval-fix", "eval-consistency-visual", "eval-heuristic", "eval-usability")
OPENAI_PHASE_MODELS = {phase: route_for(phase, "api")["model"] for phase in PAID_PHASE_ORDER}


def fail(message: str, code: int = 3) -> None:
    print(f"cost-estimate: {message}", file=sys.stderr)
    sys.exit(code)


def http_get(host: str, path: str, params: dict, timeout: int = 30) -> dict:
    url = f"{host.rstrip('/')}{path}?" + urllib.parse.urlencode(params)
    public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
    secret_key = os.environ["LANGFUSE_SECRET_KEY"]
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        body = error.read().decode()[:300]
        raise RuntimeError(f"Langfuse API {path} -> {error.code}: {body}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Langfuse API {path} unreachable: {error}") from error


def fetch_trace_history(host: str, prototype_key: str, since: datetime, max_runs: int) -> list[dict]:
    """Fetch eval-iterate traces + their paid observations for one prototype key."""
    trace_items = []
    page = 1
    while len(trace_items) < max_runs:
        payload = http_get(host, "/api/public/traces", {
            "name": f"eval-iterate/{prototype_key}",
            "fromTimestamp": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "limit": 100,
            "page": page,
        })
        trace_items.extend(payload.get("data") or [])
        meta = payload.get("meta") or {}
        if page >= int(meta.get("totalPages") or 1):
            break
        page += 1

    runs = []
    for trace in trace_items:
        trace_id = trace.get("id")
        if not trace_id:
            continue
        observations = http_get(host, "/api/public/observations", {"traceId": trace_id, "limit": 100}).get("data") or []
        paid = [o for o in observations
                if (o.get("type") or "").upper() == "GENERATION"
                and (o.get("costDetails") or {}).get("total")]
        if not paid:
            continue  # metadata-only / smoke traces carry no model cost
        runs.append({
            "trace_id": trace_id,
            "timestamp": trace.get("timestamp") or "",
            "metadata": trace.get("metadata") or {},
            "total_cost_usd": sum(float((o.get("costDetails") or {}).get("total") or 0) for o in paid),
            "phases": paid,
        })
    runs.sort(key=lambda r: r["timestamp"], reverse=True)
    return runs[:max_runs]


def load_fixture(path: Path) -> list[dict]:
    """Offline testing: same shape as fetch_trace_history, from a JSON file."""
    raw = json.loads(path.read_text())
    traces = raw.get("traces") if isinstance(raw, dict) else raw
    runs = []
    for i, trace in enumerate(traces or []):
        paid = [o for o in trace.get("observations") or []
                if (o.get("type") or "").upper() == "GENERATION"
                and (o.get("costDetails") or {}).get("total")]
        if not paid:
            continue
        runs.append({
            "trace_id": trace.get("id") or trace.get("trace_id") or f"fixture-{i}",
            "timestamp": trace.get("timestamp") or "",
            "metadata": trace.get("metadata") or {},
            "total_cost_usd": sum(float((o.get("costDetails") or {}).get("total") or 0) for o in paid),
            "phases": paid,
        })
    runs.sort(key=lambda r: r["timestamp"], reverse=True)
    return runs


def run_meta(run: dict) -> dict:
    meta = run["metadata"]
    return meta if isinstance(meta, dict) else {}


def exact_match(run: dict, run_mode: str, fix_mode: str, model_tier: str | None) -> bool:
    meta = run_meta(run)
    if meta.get("run_mode") != run_mode or meta.get("fix_mode") != fix_mode:
        return False
    return not model_tier or meta.get("model_tier") in (None, model_tier)


def phase_name(observation: dict) -> str | None:
    return observation.get("name") or (observation.get("metadata") or {}).get("phase")


def phase_usage(observation: dict) -> tuple[int, int]:
    usage = observation.get("usageDetails") or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    # Inclusive input tokens, matching cost-ledger.jsonl input_tokens semantics.
    return int(usage.get("input") or 0) + cache_read, int(usage.get("output") or 0)


def bound_cost(phase: str) -> tuple[float, int, int] | None:
    bounds = langfuse_trace.OPENAI_PHASE_BOUNDS.get(phase)
    model = OPENAI_PHASE_MODELS.get(phase)
    if not bounds or model not in langfuse_trace.OPENAI_PRICING_PER_MTOK:
        return None
    input_tokens, output_tokens = bounds
    return (langfuse_trace.estimated_cost(model, input_tokens, output_tokens),
            input_tokens, output_tokens)


def sample_phase(basis: list[dict], phase: str) -> list[dict]:
    samples = []
    for run in basis:
        for observation in run["phases"]:
            if phase_name(observation) != phase:
                continue
            in_tokens, out_tokens = phase_usage(observation)
            samples.append({
                "cost": float((observation.get("costDetails") or {}).get("total") or 0),
                "model": observation.get("model"),
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
            })
    return samples


def estimate_phases(basis: list[dict], phases: list[str], basis_tier: str, config: dict) -> tuple[list[dict], list[str]]:
    multiplier = float(config.get("multiplier") or 1.0)
    phase_multipliers = config.get("phase_multipliers") or {}
    token_budgets = config.get("token_budgets") or {}
    rates = config.get("rates_per_mtok") or {}
    flat = config.get("flat_usd_per_run")
    overrides_applied: list[str] = []

    rows = []
    for phase in phases:
        samples = sample_phase(basis, phase)
        bound = bound_cost(phase)
        models = [s["model"] for s in samples if s["model"]]
        model = models[0] if models else OPENAI_PHASE_MODELS.get(phase)
        if samples:
            est = statistics.median(s["cost"] for s in samples)
            in_tokens = int(statistics.median(s["in_tokens"] for s in samples))
            out_tokens = int(statistics.median(s["out_tokens"] for s in samples))
            tier, n = basis_tier, len(samples)
        else:
            est = bound[0] if bound else 0.0
            in_tokens = bound[1] if bound else None
            out_tokens = bound[2] if bound else None
            tier, n = "bound", 0

        row = {"phase": phase, "model": model, "est_cost_usd": round(est, 6),
               "input_tokens": in_tokens, "output_tokens": out_tokens, "tier": tier, "n": n}

        if flat is None:
            rate = rates.get(model or "")
            if rate and in_tokens is not None and out_tokens is not None:
                row["est_cost_usd"] = round(
                    (in_tokens * float(rate["input"]) + out_tokens * float(rate["output"])) / 1_000_000, 6)
                row["tier"] = "rate-override"
                overrides_applied.append(f"rate:{phase}")
            budget = token_budgets.get(phase)
            if budget:
                prev_in, prev_out = row["input_tokens"], row["output_tokens"]
                row["input_tokens"] = int(budget.get("input") or 0)
                row["output_tokens"] = int(budget.get("output") or 0)
                rate = rates.get(model or "")
                if rate:
                    row["est_cost_usd"] = round(
                        (row["input_tokens"] * float(rate["input"]) + row["output_tokens"] * float(rate["output"]))
                        / 1_000_000, 6)
                elif prev_in is not None and prev_out is not None and (prev_in + prev_out) > 0:
                    row["est_cost_usd"] = round(
                        row["est_cost_usd"] * (row["input_tokens"] + row["output_tokens"]) / (prev_in + prev_out), 6)
                row["tier"] = "budget"
                overrides_applied.append(f"budget:{phase}")
            scale = float(phase_multipliers.get(phase) or 1.0) * multiplier
            if scale != 1.0:
                row["est_cost_usd"] = round(row["est_cost_usd"] * scale, 6)
                overrides_applied.append(f"multiplier:{phase}" if phase in phase_multipliers else "multiplier")
        else:
            row.update({"est_cost_usd": 0.0, "tier": "flat", "n": 0})
        rows.append(row)
    return rows, overrides_applied


def render(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    config = result["config"]
    evidence = result["evidence"]
    print(f"Cost estimate — {result['prototype_key']}  (zero-spend, no model calls)")
    print(f"  config:   run_mode={config['run_mode']}  fix_mode={config['fix_mode']}  "
          f"tier={config['model_tier'] or 'any'}  iterations={config['iterations']}")
    print(f"  evidence: {evidence['exact_n']} exact / {evidence['similar_n']} similar prior runs, "
          f"{evidence['days']}d window ({evidence['source']})")
    if config.get("config_path"):
        suffix = f"  (overrides: {', '.join(config['overrides_applied'])})" if config["overrides_applied"] else ""
        print(f"  config:   {config['config_path']}{suffix}")
    print()
    print(f"  {'phase':<26} {'model':<18} {'est $':>8}  {'tokens in/out':>16}  evidence")
    for row in result["phases"]:
        tokens = f"{row['input_tokens']:,}/{row['output_tokens']:,}" if row["input_tokens"] is not None else "—"
        print(f"  {row['phase']:<26} {str(row['model'] or '—'):<18} {row['est_cost_usd']:>8.4f}  {tokens:>16}  "
              f"[{row['tier']} n={row['n']}]")
    print("  " + "─" * 78)
    total = result["total_per_run_usd"]
    print(f"  {'total per run':<26} {'':<18} {total:>8.4f}  {'':>16}  [{result['total_tier']}]")
    if config["iterations"] != 1:
        print(f"  total ({config['iterations']} iteration(s)): ${result['total_usd']:.4f}")
    cap = result["cap_usd"]
    if cap:
        print(f"  program cap ${cap:.2f} (OPENAI_CAP_USD): ${max(cap - total, 0.0):.2f} headroom per run")
    if result.get("budget_usd") is not None:
        ok = total <= result["budget_usd"]
        print(f"  budget check ${result['budget_usd']:.2f}: {'OK' if ok else 'EXCEEDED (exit 2)'}")
    print()
    print("  Designer gate: confirm this estimate before running, or cancel. "
          "[calibrated]=median of matching past runs · [similar]=other tier · [bound]=worst-case prior")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-run cost estimate from Langfuse trace history (zero-spend)")
    parser.add_argument("--key", required=True, help="Prototype key, e.g. RHAISTRAT-1492")
    parser.add_argument("--run-mode", choices=["fresh", "incremental"], default="fresh")
    parser.add_argument("--fix-mode", choices=["no_fix", "iterate"], default="no_fix")
    parser.add_argument("--model-tier", choices=["premium", "standard", "budget", "cursor_grok"])
    parser.add_argument("--iterations", type=int, default=1, help="Multiply the per-run estimate (fix loops)")
    parser.add_argument("--max-runs", type=int, default=50, help="Cap on prior runs pulled from Langfuse")
    parser.add_argument("--limit-days", type=int, default=90, help="History window in days")
    parser.add_argument("--config", help="JSON overrides: multiplier, phase_multipliers, token_budgets, rates_per_mtok, flat_usd_per_run")
    parser.add_argument("--budget-usd", type=float, help="Exit 2 when the estimate exceeds this budget")
    parser.add_argument("--offline-fixture", help="JSON file with traces+observations (testing, no Langfuse)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    config: dict = {"multiplier": 1.0, "phase_multipliers": {}, "token_budgets": {}, "rates_per_mtok": {}, "flat_usd_per_run": None}
    if args.config:
        config_path = Path(args.config).expanduser()
        try:
            loaded = json.loads(config_path.read_text())
            for field in ("multiplier", "phase_multipliers", "token_budgets", "rates_per_mtok", "flat_usd_per_run"):
                if field in loaded:
                    config[field] = loaded[field]
            config["config_path"] = str(config_path)
        except (OSError, json.JSONDecodeError) as error:
            fail(f"cannot read --config {config_path}: {error}")

    if args.offline_fixture:
        fixture_path = Path(args.offline_fixture).expanduser()
        try:
            runs = load_fixture(fixture_path)
        except (OSError, json.JSONDecodeError) as error:
            fail(f"cannot read --offline-fixture {fixture_path}: {error}")
        source = f"offline fixture {fixture_path.name}"
    else:
        host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
        if not host or not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
            fail("LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set. "
                 "Run: eval \"$(make langfuse-env)\"", 3)
        since = datetime.now(timezone.utc) - timedelta(days=args.limit_days)
        try:
            runs = fetch_trace_history(host, args.key, since, args.max_runs)
        except RuntimeError as error:
            fail(str(error))
        source = host

    exact = [r for r in runs if exact_match(r, args.run_mode, args.fix_mode, args.model_tier)]
    similar = [r for r in runs if run_meta(r).get("run_mode") == args.run_mode
               and run_meta(r).get("fix_mode") == args.fix_mode]

    if exact:
        basis, basis_tier = exact, "calibrated"
    elif similar:
        basis, basis_tier = similar, "similar"
    else:
        basis, basis_tier = [], "bound"

    observed = set()
    for run in basis:
        for observation in run["phases"]:
            name = phase_name(observation)
            if name in PAID_PHASE_ORDER:
                observed.add(name)
    if observed:
        phases = [p for p in PAID_PHASE_ORDER if p in observed]
    else:
        phases = [p for p in PAID_PHASE_ORDER if p != "eval-fix" or args.fix_mode == "iterate"]

    rows, overrides_applied = estimate_phases(basis, phases, basis_tier, config)
    flat = config.get("flat_usd_per_run")
    total = round(float(flat), 6) if flat is not None else round(sum(r["est_cost_usd"] for r in rows), 6)

    result = {
        "prototype_key": args.key,
        "config": {
            "run_mode": args.run_mode, "fix_mode": args.fix_mode, "model_tier": args.model_tier,
            "iterations": args.iterations, "config_path": config.get("config_path"),
            "overrides_applied": overrides_applied,
        },
        "evidence": {
            "exact_n": len(exact), "similar_n": len(similar), "days": args.limit_days,
            "source": source,
            "window_start": (datetime.now(timezone.utc) - timedelta(days=args.limit_days)).strftime("%Y-%m-%d"),
        },
        "phases": rows,
        "total_per_run_usd": total,
        "total_tier": "flat" if flat is not None else basis_tier,
        "total_usd": round(total * args.iterations, 6),
        "cap_usd": langfuse_trace.OPENAI_CAP_USD,
        "budget_usd": args.budget_usd,
    }
    render(result, args.json)
    if args.budget_usd is not None and total > args.budget_usd:
        sys.exit(2)


if __name__ == "__main__":
    main()
