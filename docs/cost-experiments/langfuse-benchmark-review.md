# Langfuse benchmark — review guide

**Project:** `uxd-eval-local` on local Langfuse  
**UI:** http://localhost:3000/project/uxd-eval-local/traces  
**Login:** `admin@local.dev` / `langfuse-local-dev`

## What the benchmark runs

Phase 3 **run-mode matrix** (4 cells, Opus only) — each cell is a full `/uxd-prototype-evaluate` run with dual-write to Langfuse + cost ledger:

| Cell | Flags | `run_mode` | `fix_mode` |
|------|-------|------------|------------|
| `matrix-f-nf` | `--fresh --no-fix` | fresh | no_fix |
| `matrix-f-it` | `--fresh --max-iterations=1` | fresh | iterate |
| `matrix-i-nf` | `--no-fix` | incremental | no_fix |
| `matrix-i-it` | `--max-iterations=1` | incremental | iterate |

```bash
make langfuse-benchmark URL=http://localhost:9000
```

Artifacts:

- `.artifacts/RHAISTRAT-1492/eval/langfuse-benchmark-summary.json`
- `.artifacts/RHAISTRAT-1492/eval/langfuse-benchmark.log`
- `.artifacts/RHAISTRAT-1492/eval/cost-ledger.jsonl` (one row per cell)

## What to review in the UI

1. **Traces** — filter by name `eval-iterate/RHAISTRAT-1492`
2. **Metadata** on each root span: `run_mode`, `fix_mode`, `experiment`, `prototype_key`
3. **Generations** — `generation/claude-opus-4-6` cost/token children
4. **Scores** — `ac_pass_rate` where present
5. **Compare** F-NF vs I-NF (fresh vs incremental cost) and F-IT vs I-IT (iterate path)

## Golden baseline traces (already logged)

| Run | eval_run_id | llm_cost_usd | Langfuse trace |
|-----|-------------|--------------|----------------|
| golden-a-opus-nofix | eval-RHAISTRAT-1492-20260902-141517-8ff85c | 0.51 | [open](http://localhost:3000/project/uxd-eval-local/traces/8d072237120b96b54cd2752d261292e1) |
| golden-b-opus-iterate | eval-RHAISTRAT-1492-20260902-141626-2b4cb0 | 0.47 | [open](http://localhost:3000/project/uxd-eval-local/traces/0fa00bf116e762b7b6448402bff38d15) |

## Langfuse Cursor plugin — how to use it here

You installed the official **Langfuse** Cursor plugin. It adds the `langfuse` skill and `langfuse-cli` access.

### In Cursor chat

Ask the agent to use the Langfuse skill, for example:

- *"List recent traces for uxd-eval-local and summarize cost by run_mode"*
- *"Run error analysis on traces where ac_pass_rate < 1"*
- *"Fetch metrics for today's benchmark runs"*

The skill uses `npx langfuse-cli` against your `LANGFUSE_HOST` / keys.

### CLI (same keys as eval pipeline)

```bash
cd ~/Desktop/ai-helpers
eval "$(make langfuse-local-env)"

# List recent observations
npx langfuse-cli api observations list --limit 10 --json

# Trace detail
npx langfuse-cli api traces get --trace-id <id> --json
```

### Cursor vs CLI instrumentation

| Path | Langfuse data | Cost authority |
|------|---------------|----------------|
| `make mlflow-pipeline` / benchmark | Full trace + generations + ledger | CLI (`llm_cost_usd`) |
| Cursor `/eval-iterate` | Phase spans via `langfuse_trace.py phase` | Subscription (no per-token $) |

Use **CLI benchmark traces** for cost dashboards; use **Cursor plugin** for exploratory analysis, scores, and annotation queues on those traces.

## Sign-off checklist

- [ ] All 4 matrix traces visible with correct `run_mode` / `fix_mode`
- [ ] Ledger rows match Langfuse trace URLs
- [ ] Fresh vs incremental cost hypothesis noted in `phase3-run-mode-matrix.md`
- [ ] Ready for Phase 4 model experiments
