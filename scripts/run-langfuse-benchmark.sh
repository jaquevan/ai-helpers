#!/usr/bin/env bash
# Langfuse benchmark: Phase 3 run-mode matrix with dual-write to local Langfuse.
set -euo pipefail
URL="${1:-http://localhost:9000}"
KEY="${KEY:-RHAISTRAT-1492}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"
export AGENT_EVAL_HARNESS_PATH="${AGENT_EVAL_HARNESS_PATH:-$ROOT/workspace/agent-eval-harness}"

if [ -z "${LANGFUSE_PUBLIC_KEY:-}" ]; then
  eval "$(make langfuse-local-env)"
fi
export LANGFUSE_ENABLED=1

ARTIFACTS="$ROOT/.artifacts/$KEY/eval"
mkdir -p "$ARTIFACTS"
LOG="$ARTIFACTS/langfuse-benchmark.log"
SUMMARY="$ARTIFACTS/langfuse-benchmark-summary.json"

echo "==> Langfuse benchmark — host: ${LANGFUSE_HOST:-unset} | URL: $URL | key: $KEY" | tee "$LOG"

cells=(
  "--fresh --no-fix|matrix-f-nf"
  "--fresh --max-iterations=1|matrix-f-it"
  "--no-fix|matrix-i-nf"
  "--max-iterations=1|matrix-i-it"
)

for cell in "${cells[@]}"; do
  flags="${cell%%|*}"
  label="${cell##*|}"
  echo "" | tee -a "$LOG"
  echo "==> Cell $label: $flags" | tee -a "$LOG"
  if make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
    ITERATE_FLAGS="$flags" EXPERIMENT="$label" 2>&1 | tee -a "$LOG"; then
    echo "OK: $label" >> "$LOG"
  else
    echo "WARN: $label failed (see log)" | tee -a "$LOG"
  fi
done

python3 - "$ARTIFACTS/cost-ledger.jsonl" "$SUMMARY" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ledger_path, summary_path = sys.argv[1], sys.argv[2]
labels = ["matrix-f-nf", "matrix-f-it", "matrix-i-nf", "matrix-i-it"]
cells = []
if Path(ledger_path).exists():
    for line in Path(ledger_path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("experiment") in labels:
            cells.append(row)

import os
host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
summary = {
    "benchmark": "langfuse-run-mode-matrix",
    "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "langfuse_host": host,
    "langfuse_traces_ui": f"{host}/project/uxd-eval-local/traces" if host else "",
    "cells_found": len(cells),
    "cells": cells,
}
Path(summary_path).write_text(json.dumps(summary, indent=2) + "\n")
print(f"Wrote {summary_path} ({len(cells)} matrix rows)")
PY

echo "" | tee -a "$LOG"
echo "==> Review traces: ${LANGFUSE_HOST}/project/uxd-eval-local/traces" | tee -a "$LOG"
echo "==> Summary JSON: $SUMMARY" | tee -a "$LOG"
