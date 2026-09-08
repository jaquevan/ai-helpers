# Phase 3 — Run-mode matrix (CP3)

**MR:** RHAISTRAT-1492 | **Model:** Opus only (no model changes)

```bash
make run-run-mode-matrix URL=http://localhost:9000
```

## Matrix results

| Cell | Flags | eval_run_id | llm_cost_usd | input_tokens | AC P/F/FL | Usability | Langfuse trace |
|------|-------|-------------|--------------|--------------|-----------|-----------|----------------|
| F-NF | `--fresh --no-fix` | eval-…-142004-2ea33d | **0.42** | 2590 | 1/0/3 | pending | [trace](http://localhost:3000/project/uxd-eval-local/traces/70513a93855ccec21babaa819c88fca2) |
| F-IT | `--fresh --max-iterations=1` | eval-…-142113-1a12ea | **0.29** | 2645 | 1/0/3 | pending | [trace](http://localhost:3000/project/uxd-eval-local/traces/ddcbc16609fc732343a1409bc0bd9a51) |
| I-NF | `--no-fix` | eval-…-142226-8729b8 | **0.43** | 2832 | 1/0/3 | pending | [trace](http://localhost:3000/project/uxd-eval-local/traces/8df15db0294182bb4b2ef721505d8912) |
| I-IT | `--max-iterations=1` | eval-…-142658-947efd | **1.76** | 12246 | 1/0/3 | pending | [trace](http://localhost:3000/project/uxd-eval-local/traces/3a77a87850d82a48d99f2ae42ba498b5) |

**Total benchmark cost:** ~$2.90 | **Summary:** `.artifacts/RHAISTRAT-1492/eval/langfuse-benchmark-summary.json`

## Hypothesis verification

| Hypothesis | Result |
|------------|--------|
| Fresh > incremental cost | **Not confirmed** — F-NF ($0.42) ≈ I-NF ($0.43); incremental iterate (I-IT $1.76) dominated by fix loop |
| Iterate ≥ no-fix when FAILs present | **Confirmed** — I-IT ($1.76) >> I-NF ($0.43) |
| Incremental no-fix cheapest for re-check | **Not confirmed** — F-IT ($0.29) was cheapest overall |

## CP3 checklist

- [x] All 4 cells run with ledger + Langfuse trace
- [x] `run_mode` / `fix_mode` correct in every row
- [ ] F-NF and F-IT started from empty eval dir
- [ ] No-fix cells: no fix-log / workspace edits
- [ ] Daily logs in `docs/cost-experiments/YYYY-MM-DD.md`
