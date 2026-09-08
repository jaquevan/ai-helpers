#!/usr/bin/env bash
# Foundation batch: fixtures → tiered subskill probes → 2 traced pipeline runs (CP-E2E-1).
set -euo pipefail

KEY="${KEY:-RHAISTRAT-1492}"
URL="${URL:-http://localhost:9000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"
export AGENT_EVAL_HARNESS_PATH="${AGENT_EVAL_HARNESS_PATH:-$ROOT/workspace/agent-eval-harness}"

ARTIFACTS="$ROOT/.artifacts/$KEY/eval"
LOG="$ARTIFACTS/foundation-batch.log"
SUMMARY="$ARTIFACTS/foundation-batch-summary.json"
mkdir -p "$ARTIFACTS"

if [ -z "${LANGFUSE_PUBLIC_KEY:-}" ]; then
  eval "$(make langfuse-local-env)"
fi
export LANGFUSE_ENABLED=1

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "==> Foundation batch — key=$KEY url=$URL langfuse=${LANGFUSE_HOST:-unset}"

log "Step 1/4: fixture subskill tests (no LLM cost)"
make test-subskills 2>&1 | tee -a "$LOG"

log "Step 2/4: tiered subskill probes (LANGFUSE=1)"
declare -a PROBES=(
  "eval-extract|gpt-5.6-luna gpt-5.6-terra"
  "eval-classify|gpt-5.6-luna gpt-5.6-terra"
  "eval-journey|gpt-5.6-terra gpt-5.6-sol"
  "eval-usability|gpt-5.6-terra gpt-5.6-sol"
  "eval-consistency|gpt-5.6-terra gpt-5.6-sol"
)

for probe in "${PROBES[@]}"; do
  skill="${probe%%|*}"
  models="${probe#*|}"
  log "  subskill probe: $skill models=[$models]"
  make langfuse-compare KEY="$KEY" URL="$URL" SKILLS="$skill" MODELS="$models" \
    LANGFUSE=1 EXPERIMENT="foundation-probe-$skill" 2>&1 | tee -a "$LOG" || \
    log "WARN: probe $skill failed (continuing)"
done

log "Step 3/4: pipeline golden-a-opus-nofix (per-phase Langfuse)"
make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" \
  EXPERIMENT="foundation-golden-a-opus-nofix" 2>&1 | tee -a "$LOG"

log "Step 4/4: pipeline matrix-f-nf (per-phase Langfuse)"
make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" \
  EXPERIMENT="foundation-matrix-f-nf" 2>&1 | tee -a "$LOG"

log "==> Foundation batch complete"
log "  Log: $LOG"
log "  Langfuse: ${LANGFUSE_HOST:-}/project/uxd-eval-local/traces"
log "  Ledger: $ARTIFACTS/cost-ledger.jsonl"

python3 - <<'PY' "$SUMMARY" "$LOG"
import json, re, sys
summary_path, log_path = sys.argv[1], sys.argv[2]
text = open(log_path).read()
costs = [float(x) for x in re.findall(r'\$([0-9]+\.[0-9]+)', text)]
payload = {
    "status": "complete",
    "cost_mentions_usd": costs[-10:] if costs else [],
    "log": log_path,
}
open(summary_path, "w").write(json.dumps(payload, indent=2))
print(json.dumps(payload, indent=2))
PY
