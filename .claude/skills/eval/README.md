# Eval tooling (local dev)

Scripts here mirror the paths used by `/eval-iterate` and the Langfuse pipeline guide.
They symlink to the canonical copies in `plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/`.

## Setup

```bash
eval "$(make langfuse-env)"
make langfuse-smoke
make langfuse-verify
```

## Compare cheaper models (Phase 1)

```bash
eval "$(make langfuse-env)"
uv run python3 plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/langfuse-compare-models.py \
  --key RHAISTRAT-1492 \
  --url http://127.0.0.1:3000 \
  --skills eval-extract eval-classify eval-consistency eval-report \
  --models gpt-5.6-luna gpt-5.6-terra gpt-5.6-sol
```

## Orchestrator

Use `/eval-iterate RHAISTRAT-1492 <URL> --workspace=<rhoai-path>` in Cursor.
The active pipeline uses direct OpenAI API calls and metadata-only Langfuse
traces. Set `EVAL_PROVIDER=anthropic` when preserving a Claude CLI workflow.
Legacy MLflow scripts remain available for research comparison only.
