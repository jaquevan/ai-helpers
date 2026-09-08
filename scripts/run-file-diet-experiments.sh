#!/usr/bin/env bash
# Phase 5: File diet and depth tier experiments
set -euo pipefail
KEY="${1:-RHAISTRAT-1492}"
URL="${2:-http://localhost:9000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"

echo "==> Day 1: incremental re-run after golden (file diet baseline)"
make langfuse-pipeline KEY="$KEY" URL="$URL" EXPERIMENT=file-diet-baseline \
  ITERATE_FLAGS="--no-fix" MODEL=gpt-5.6-sol || true

echo "==> Day 3: quick tier"
make langfuse-pipeline KEY="$KEY" URL="$URL" EXPERIMENT=tier-quick \
  ITERATE_FLAGS="--fresh --no-fix --no-iterate --no-report" MODEL=gpt-5.6-sol || true

echo "==> Day 4: standard max-iterations=1"
make langfuse-pipeline KEY="$KEY" URL="$URL" EXPERIMENT=tier-standard \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" MODEL=gpt-5.6-sol || true

echo "==> Update docs/cost-experiments/WEEKLY-SUMMARY.md and model-tier-recommendations.md"
