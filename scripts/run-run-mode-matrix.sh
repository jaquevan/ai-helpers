#!/usr/bin/env bash
# Phase 3: Run-mode matrix (4 cells) on RHAISTRAT-1492 — Opus only
set -euo pipefail
URL="${1:-http://localhost:9000}"
KEY="RHAISTRAT-1492"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"

cells=(
  "--fresh --no-fix|matrix-f-nf"
  "--fresh --max-iterations=1|matrix-f-it"
  "--no-fix|matrix-i-nf"
  "--max-iterations=1|matrix-i-it"
)

for cell in "${cells[@]}"; do
  flags="${cell%%|*}"
  label="${cell##*|}"
  echo "==> Cell $label: $flags"
  make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
    ITERATE_FLAGS="$flags" EXPERIMENT="$label" || echo "WARN: $label failed"
done

echo "==> Record matrix in docs/cost-experiments/phase3-run-mode-matrix.md"
