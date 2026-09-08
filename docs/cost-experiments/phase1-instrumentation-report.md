# Phase 1 — Instrumentation report (CP1)

## Verification commands

```bash
export PATH="$PWD/.local/node/bin:$PATH"
eval "$(make langfuse-env)"
# export LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=...

make langfuse-smoke
make ledger-smoke KEY=RHAISTRAT-1492
make langfuse-pipeline KEY=RHAISTRAT-1492 URL=http://localhost:9000 \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" EXPERIMENT=phase1-verify
```

## CP1 checklist

- [ ] Per-run ledger: `.artifacts/RHAISTRAT-1492/eval/cost-ledger.jsonl`
- [ ] Ledger row has `run_mode`, `fix_mode`, `model_tier`, `invocation`, `llm_cost_usd`, `observability_cost_usd`
- [ ] Langfuse `llm_cost_usd` within 1% of stream-json (when keys set)
- [ ] Phase observations reconcile to trace total
- [ ] `render-report.js` → `render-metrics.json` with `llm_cost_usd: 0`
- [ ] Privacy audit: no screenshots/raw Jira in trace
- [ ] Cursor phase events via `langfuse_trace.py phase`

## Smoke run results

| Check | Result | Notes |
|-------|--------|-------|
| `make langfuse-smoke` | PASS | Dry-run without LANGFUSE keys |
| `make ledger-smoke` | PASS | Row appended to cost-ledger.jsonl |
| `render-report.js` metrics | PASS | `render-metrics.json` with duration_ms + output_bytes |
| `make test-subskills` | PASS | 3/3 |
| CLI pipeline trace | Pending | Requires `claude` IAM + cluster optional |

## Reconciliation

| Source | llm_cost_usd |
|--------|--------------|
| stream-json | |
| Langfuse trace | |
| cost-ledger.jsonl | |
