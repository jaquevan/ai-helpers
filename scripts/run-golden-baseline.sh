#!/usr/bin/env bash
# Phase 2: Golden Opus baseline — 2 modes × 3 MRs (CLI authoritative)
set -euo pipefail
KEY="${1:-}"
URL="${2:-http://localhost:9000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"

MRS=(RHAISTRAT-1492 RHAISTRAT-1527 RHAISTRAT-133)
if [ -n "$KEY" ]; then MRS=("$KEY"); fi

run_one() {
  local key="$1" flags="$2" label="$3"
  echo "==> $label: $key ($flags)"
  make langfuse-pipeline KEY="$key" URL="$URL" MODEL=gpt-5.6-sol \
    ITERATE_FLAGS="$flags" EXPERIMENT="$label" || echo "WARN: $label failed for $key"
}

for key in "${MRS[@]}"; do
  run_one "$key" "--fresh --no-fix --max-iterations=1" "golden-a-opus-nofix"
  run_one "$key" "--fresh --max-iterations=1" "golden-b-opus-iterate"
done

echo "==> Record results in docs/cost-experiments/golden-baseline.md"
echo "==> Obtain sign-off from you + Andy before Phase 3"
