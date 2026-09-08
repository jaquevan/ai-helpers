#!/usr/bin/env bash
# Phase 4: Direct OpenAI model experiments + documented Cursor Grok runs
set -euo pipefail
KEY="${1:-RHAISTRAT-1492}"
URL="${2:-http://localhost:9000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"

echo "==> 4A: OpenAI per-skill compare (Luna + Terra + Sol)"
make langfuse-compare KEY="$KEY" URL="$URL" \
  MODELS="gpt-5.6-luna gpt-5.6-terra gpt-5.6-sol" \
  SKILLS="eval-extract eval-classify eval-journey eval-usability" || true

echo "==> 4B: Cursor Grok runs (manual — set model in Cursor, then /eval-iterate)"
echo "    - cursor-grok-4.5-high: fresh --no-fix"
echo "    - cursor-grok-4.6-xhigh: fresh --no-fix and fresh iterate"
echo "==> Record in docs/cost-experiments/model-tier-recommendations.md"
