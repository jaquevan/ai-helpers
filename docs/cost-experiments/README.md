# Cost experiments

Day-by-day token and cost reduction experiments for `uxd-prototype-evaluate`.

## Process

1. One hypothesis per day — single variable only
2. CLI path is authoritative for `llm_cost_usd`
3. Record machine ledger row + human daily log
4. Compare quality vs `golden-baseline.md` before keeping a change

## Phases

| Phase | Doc | Checkpoint |
|-------|-----|------------|
| 0 | [phase0-infra-checklist.md](phase0-infra-checklist.md) | CP0 |
| 1 | [phase1-instrumentation-report.md](phase1-instrumentation-report.md) | CP1 |
| 2 | [golden-baseline.md](golden-baseline.md) | CP2 |
| 3 | [phase3-run-mode-matrix.md](phase3-run-mode-matrix.md) | CP3 |
| 4 | [model-tier-recommendations.md](model-tier-recommendations.md) | CP4 |
| 5 | [WEEKLY-SUMMARY.md](WEEKLY-SUMMARY.md) | CP5 |

## Commands

```bash
export PATH="$PWD/.local/node/bin:$PATH"

# Local Langfuse (Docker required — see docker/langfuse/README.md)
make langfuse-local-up
eval "$(make langfuse-local-env)"
make langfuse-smoke
make run-phase1-verify KEY=RHAISTRAT-1492

# Cluster (after local validation)
eval "$(make langfuse-env)"
eval "$(make mlflow-poc7)"
make mlflow-resume   # if MLflow was in standby
```

# Golden baseline (no-fix)
make mlflow-pipeline KEY=RHAISTRAT-1492 URL=http://localhost:9000 \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" EXPERIMENT=golden-a-opus

# Run-mode matrix cell F-NF
make mlflow-pipeline KEY=RHAISTRAT-1492 URL=http://localhost:9000 \
  ITERATE_FLAGS="--fresh --no-fix" EXPERIMENT=matrix-f-nf

# Model compare (Sonnet + Haiku)
make mlflow-compare KEY=RHAISTRAT-1492 URL=http://localhost:9000 \
  MODELS="claude-sonnet-5 claude-haiku-4-5" LANGFUSE=1
```

## Ledger

Per run: `.artifacts/<KEY>/eval/cost-ledger.jsonl`

Schema: [ledger-schema.json](ledger-schema.json)

## Daily log template

Copy [TEMPLATE-daily.md](TEMPLATE-daily.md) to `YYYY-MM-DD.md`.

## Quality gate

- ≥40% `llm_cost_usd` reduction vs golden
- No new AC failures
- ≤1 usability-point drop
- Sign-off: you + Andy for any exception
