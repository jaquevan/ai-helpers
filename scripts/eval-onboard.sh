#!/usr/bin/env bash
# A safe, guided first-run check for the prototype evaluator.
# It never prints secrets, creates traces, opens a browser, fetches Jira, or calls a model.
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODE="auto"
PASS=0
FAIL=0
ACTION=0

usage() {
  cat <<'EOF'
Usage: scripts/eval-onboard.sh [--interactive|--check]

  --interactive  Show the guided terminal flow, even when input is redirected.
  --check        Run one non-interactive readiness check (suitable for CI).
EOF
}

for argument in "$@"; do
  case "${argument}" in
    --interactive) MODE="interactive" ;;
    --check) MODE="check" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: ${argument}" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${MODE}" == "interactive" ]] || { [[ "${MODE}" == "auto" ]] && [[ -t 0 && -t 1 ]]; }; then
  INTERACTIVE=1
else
  INTERACTIVE=0
fi

pass() {
  PASS=$((PASS + 1))
  echo "[PASS] $1"
}

fail() {
  FAIL=$((FAIL + 1))
  echo "[BLOCKED] $1"
}

action() {
  ACTION=$((ACTION + 1))
  echo "[ACTION] $1"
}

info() {
  echo "[INFO] $1"
}

run_checks() {
  PASS=0
  FAIL=0
  ACTION=0

  # Shared env is optional: designers can also export variables directly in their shell.
  if EVAL_ENV_QUIET=1 source "${SCRIPT_DIR}/eval-env.sh"; then
    pass "Shared evaluation environment loaded"
  else
    info "No .env.local found. Create one in the primary worktree, or export the variables in your shell instead."
  fi

  # OpenAI key is the only hard requirement — it is what pays for the model calls.
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    pass "OPENAI_API_KEY is configured"
  else
    action "Get an OpenAI key: create one at https://platform.openai.com/api-keys, store it in your password manager, then add OPENAI_API_KEY=sk-... to .env.local in the primary worktree. Never paste the key into chat or a tracked file."
  fi

  # Langfuse tracing is OPTIONAL — only for cost benchmarking. The pipeline runs fine without it.
  if [[ -n "${LANGFUSE_HOST:-}" && -n "${LANGFUSE_PUBLIC_KEY:-}" && -n "${LANGFUSE_SECRET_KEY:-}" ]]; then
    langfuse_check="$("${PYTHON_BIN}" "${ROOT}/plugins/uxd-prototype/skills/uxd-prototype-evaluate/scripts/verify-langfuse.py" --read-only 2>&1)"
    if [[ "$?" -eq 0 ]]; then
      pass "Langfuse tracing enabled and reachable"
    else
      info "Langfuse keys present but not reachable. Tracing is optional — evaluation still runs without it. To enable later, fix the keys; to disable, unset LANGFUSE_* or set LANGFUSE_ENABLED=0."
    fi
  else
    info "Langfuse tracing off (optional — only needed for cost benchmarking). Evaluation runs fine without it."
  fi

  # Report the provider/model that will be used by default.
  default_provider="$(grep -A2 '^  api:' "${ROOT}/plugins/uxd-prototype/skills/uxd-prototype-evaluate/config/model-defaults.yaml" 2>/dev/null | grep -m1 'provider:' | awk '{print $2}')"
  info "Default provider/model routing: ${default_provider:-openai} (override with --model or EVAL_PLATFORM; per-phase models in config/model-defaults.yaml)"

  if node -e "require('@playwright/test')" >/dev/null 2>&1; then
    pass "Playwright package is available"
    if node -e "const { chromium } = require('@playwright/test'); process.exit(require('fs').existsSync(chromium.executablePath()) ? 0 : 1)" >/dev/null 2>&1; then
      pass "Playwright Chromium is installed"
    else
      action "Install Chromium once: cd ${ROOT}/plugins/uxd-prototype/skills/uxd-prototype-evaluate && npm install && npx playwright install chromium"
    fi
  else
    action "Install evaluator dependencies once: cd ${ROOT}/plugins/uxd-prototype/skills/uxd-prototype-evaluate && npm install"
  fi

  if command -v codex >/dev/null 2>&1 && codex mcp get Atlassian >/dev/null 2>&1; then
    pass "Atlassian MCP is configured; Codex validates authorization when it stages Jira"
  else
    action "Add and authenticate Atlassian MCP once: codex mcp add Atlassian --url https://mcp.atlassian.com/v2/mcp && codex mcp login Atlassian"
  fi

  echo "Results: ${PASS} pass, ${FAIL} blocked, ${ACTION} action"
}

prompt_future_run() {
  local profile model report max_iter reset_ws fresh
  echo
  echo "Setup is ready. Pick a future run profile; this does not start an evaluation."
  echo "  1) Review only — report what fails, no code changes"
  echo "  2) Approved model evaluation — fix loop + your final approval (recommended)"
  read -r -p "Choose 1 or 2 [2]: " profile
  profile="${profile:-2}"

  echo "Model budget for that future run:"
  echo "  1) gpt-6-luna — lower-cost exploration"
  echo "  2) gpt-6-sol — complex coding and agentic work"
  echo "  3) Phase-routed defaults (recommended)"
  read -r -p "Choose 1, 2, or 3 [3]: " model
  model="${model:-3}"

  echo "Report output:"
  echo "  1) Full HTML report with screenshots + evidence (recommended)"
  echo "  2) Compact chat summary only (cheaper, no HTML)"
  read -r -p "Choose 1 or 2 [1]: " report
  report="${report:-1}"

  local flags=()
  if [[ "${profile}" == "2" ]]; then
    echo "Max fix-loop iterations (each iteration costs model tokens):"
    echo "  1) 1 — single pass, no re-loop"
    echo "  2) 2 — one retry"
    echo "  3) 3 — default"
    echo "  4) 5 — aggressive (costs more)"
    read -r -p "Choose 1-4 [3]: " max_iter
    case "${max_iter:-3}" in
      1) max_iter=1 ;; 2) max_iter=2 ;; 3) max_iter=3 ;; 4) max_iter=5 ;; *) max_iter=3 ;;
    esac
    flags+=("--max-iterations=${max_iter}")
  else
    flags+=("--no-fix" "--max-iterations=1")
  fi

  echo "Reset workspace to origin HEAD before each run?"
  read -r -p "y or n [n]: " reset_ws
  [[ "${reset_ws}" == "y" || "${reset_ws}" == "Y" ]] && flags+=("--reset")

  echo "Rebuild eval artifacts from scratch (ignore prior runs)?"
  read -r -p "y or n [n]: " fresh
  [[ "${fresh}" == "y" || "${fresh}" == "Y" ]] && flags+=("--fresh")

  if [[ "${report}" == "2" ]]; then
    flags+=("--no-report")
  fi

  echo
  echo "────────────────────────────────────────────"
  echo " Your eval plan:"
  case "${profile}" in
    1) echo "   Profile:  review only (no code changes)" ;;
    *) echo "   Profile:  model evaluation (fix loop + approval gate)" ;;
  esac
  case "${model}" in
    1) echo "   Model:    gpt-6-luna" ;;
    2) echo "   Model:    gpt-6-sol" ;;
    *) echo "   Model:    phase-routed defaults" ;;
  esac
  [[ "${report}" == "2" ]] && echo "   Report:   compact chat summary" || echo "   Report:   full HTML report"
  [[ ${#flags[@]} -gt 0 ]] && echo "   Flags:    ${flags[*]}"
  echo
  echo " Run it with:"
  echo "   /uxd-prototype-evaluate <KEY> <URL> ${flags[*]}"
  echo
  echo " Remember to pass --workspace=<path> to enable the fix loop."
  echo " The agent fetches Jira automatically from <KEY>."
  echo " You'll get one confirmation before any paid model calls start."
  echo "────────────────────────────────────────────"
}

if [[ "${INTERACTIVE}" -eq 1 ]]; then
  echo "Prototype evaluator setup — about 2 minutes"
  echo "This checks configuration only. Keep keys in .env.local; never paste them into this terminal or chat."
  read -r -p "Press Enter to start, or type q to exit: " start_answer
  [[ "${start_answer}" == "q" || "${start_answer}" == "Q" ]] && exit 0
fi

while true; do
  run_checks
  if [[ "${FAIL}" -eq 0 ]]; then
    [[ "${INTERACTIVE}" -eq 1 ]] && prompt_future_run
    exit 0
  fi

  if [[ "${INTERACTIVE}" -ne 1 ]]; then
    exit 1
  fi

  echo
  read -r -p "Fix the blocked item privately, then press Enter to recheck (or type q to stop): " retry_answer
  [[ "${retry_answer}" == "q" || "${retry_answer}" == "Q" ]] && exit 1
done
