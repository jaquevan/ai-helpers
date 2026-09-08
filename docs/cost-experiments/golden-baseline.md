# Golden baseline — Opus (CP2)

**Reviewers:** You + Andy (both sign-off required before Phase 3)

**Success threshold for later experiments:** ≥40% `llm_cost_usd` reduction, no new AC failures, ≤1 usability-point drop.

## Run spec

Per MR: Golden-A (`--fresh --no-fix --max-iterations=1`) + Golden-B (`--fresh --max-iterations=1` iterate)

```bash
make run-golden-baseline URL=http://localhost:9000
```

## RHAISTRAT-1492 (MR 170 — primary)

| Run | eval_run_id | llm_cost_usd | AC P/F/FL | Usability | Sign-off |
|-----|-------------|--------------|-----------|-----------|----------|
| Golden-A no-fix | eval-RHAISTRAT-1492-20260902-141517-8ff85c | 0.51 | 1/0/3 | pending | [ ] |
| Golden-B iterate | eval-RHAISTRAT-1492-20260902-141626-2b4cb0 | 0.47 | 1/0/3 | pending | [ ] |
| Cursor Opus | | n/a | | | [ ] |

## RHAISTRAT-1527 (MR 168)

| Run | eval_run_id | llm_cost_usd | AC P/F/FL | Usability | Sign-off |
|-----|-------------|--------------|-----------|-----------|----------|
| Golden-A | | | | | [ ] |
| Golden-B | | | | | [ ] |

## RHAISTRAT-133 (MR 169)

| Run | eval_run_id | llm_cost_usd | AC P/F/FL | Usability | Sign-off |
|-----|-------------|--------------|-----------|-----------|----------|
| Golden-A | | | | | [ ] |
| Golden-B | | | | | [ ] |

## Per-phase cost (Golden-A, RHAISTRAT-1492)

| Phase | llm_cost_usd | Model |
|-------|--------------|-------|
| eval-extract | | claude-sonnet-5 |
| eval-journey | | claude-opus-4-6 |
| eval-usability | | claude-opus-4-6 |
| render-report.js | 0 | (artifact only) |

## Sign-off

- [ ] Reviewer 1 (you): quality acceptable as reference baseline
- [ ] Reviewer 2 (Andy): quality acceptable as reference baseline
