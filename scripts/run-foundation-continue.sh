#!/usr/bin/env bash
# Continue foundation per questionnaire: 1492 only, tiered probes, golden-a + skip matrix if done.
set -euo pipefail

KEY="${KEY:-RHAISTRAT-1492}"
URL="${URL:-http://localhost:9000}"
SKIP_MATRIX="${SKIP_MATRIX:-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.local/node/bin:$PATH"
export AGENT_EVAL_HARNESS_PATH="${AGENT_EVAL_HARNESS_PATH:-$ROOT/workspace/agent-eval-harness}"

ARTIFACTS="$ROOT/.artifacts/$KEY/eval"
LOG="$ARTIFACTS/foundation-continue.log"
mkdir -p "$ARTIFACTS"

if [ -z "${LANGFUSE_PUBLIC_KEY:-}" ]; then
  eval "$(make langfuse-local-env)"
fi
export LANGFUSE_ENABLED=1

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "==> Foundation continue — key=$KEY (questionnaire: 1492, tiered probes, golden+F-NF, CP-E2E-1)"

log "Step 1: fixture tests"
make test-subskills 2>&1 | tee -a "$LOG"

log "Step 2: tiered subskill probes (fixed eval/ artifact paths)"
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
  log "  probe: $skill [$models]"
  make langfuse-compare KEY="$KEY" URL="$URL" SKILLS="$skill" MODELS="$models" \
    LANGFUSE=1 2>&1 | tee -a "$LOG" || log "WARN: $skill probe failed"
done

log "Step 3: golden-a-opus-nofix (workspace from eval-state)"
make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
  ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" \
  EXPERIMENT="foundation-golden-a-opus-nofix" 2>&1 | tee -a "$LOG"

if [ "$SKIP_MATRIX" != "1" ]; then
  log "Step 4: matrix-f-nf"
  make langfuse-pipeline KEY="$KEY" URL="$URL" MODEL=gpt-5.6-sol \
    ITERATE_FLAGS="--fresh --no-fix --max-iterations=1" \
    EXPERIMENT="foundation-matrix-f-nf" 2>&1 | tee -a "$LOG"
else
  log "Step 4: skipped matrix-f-nf (SKIP_MATRIX=1 — use prior foundation-matrix-f-nf run)"
fi

log "==> Foundation continue complete — log: $LOG"
log "  Langfuse: ${LANGFUSE_HOST:-}/project/uxd-eval-local/traces"
