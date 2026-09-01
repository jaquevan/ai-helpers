# Eval MLflow tooling (local dev)

Scripts here mirror the paths used by `/eval-iterate` and the MLflow pipeline guide.
They symlink to the canonical copies in `plugins/uxd-workshop/skills/uxd-prototype-evaluate/scripts/`.

## Setup

```bash
eval "$(make mlflow-poc7)"
make mlflow-smoke KEY=RHAISTRAT-1492
```

## Compare cheaper models (Phase 1)

```bash
eval "$(make mlflow-poc7)"
uv run python3 .claude/skills/eval/scripts/mlflow-compare-models.py \
  --key RHAISTRAT-1492 \
  --url http://127.0.0.1:3000 \
  --skills eval-extract eval-classify eval-consistency eval-report \
  --models claude-sonnet-4-6 claude-sonnet-5
```

## Orchestrator

Use `/eval-iterate RHAISTRAT-1492 <URL> --workspace=<rhoai-path>` in Cursor.
Troubleshooting: `/eval-optimize-mlflow` ([eval-optimize-mlflow](https://github.com/jaquevan/eval-optimize-mlflow)).
