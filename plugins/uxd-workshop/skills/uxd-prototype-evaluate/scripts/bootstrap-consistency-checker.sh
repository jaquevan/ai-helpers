#!/bin/bash
# Resolve design consistency guidelines.
#
# Primary: skill-bundled ${SKILL_DIR}/consistency-checker/ (no network).
# Optional override: CONSISTENCY_CHECKER_REPO or overlay
#   context_repos.consistency_checker sparse-clones into
#   ${UXD_PROJECT_ROOT}/.context/consistency-checker/ (fork pin).
#
# Prints CONSISTENCY_DIR= and CONSISTENCY_AVAILABLE= for callers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLED_DIR="${SKILL_DIR}/consistency-checker"

PROJECT_ROOT="${UXD_PROJECT_ROOT:-}"
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(node -e "console.log(require('${SCRIPT_DIR}/resolve-root').resolveProjectRoot())" 2>/dev/null || pwd)"
fi
CONTEXT_DIR="${PROJECT_ROOT}/.context/consistency-checker"

OVERLAY_REPO="$(node "${SCRIPT_DIR}/overlay-get.js" context_repos.consistency_checker 2>/dev/null || true)"
CHECKER_REPO="${CONSISTENCY_CHECKER_REPO:-${OVERLAY_REPO:-}}"

has_guidelines() {
  local dir="$1"
  [ -d "${dir}/guidelines" ] && [ "$(find "${dir}/guidelines" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]
}

clone_override() {
  echo "Bootstrapping consistency-checker override into ${CONTEXT_DIR}..."
  mkdir -p "$CONTEXT_DIR"
  if [ ! -d "$CONTEXT_DIR/.git" ]; then
    git clone --depth 1 --filter=blob:none --no-checkout "$CHECKER_REPO" "$CONTEXT_DIR" || {
      echo "ERROR: Could not clone consistency-checker from ${CHECKER_REPO}."
      return 1
    }
  fi
  cd "$CONTEXT_DIR"
  git sparse-checkout init --cone || true
  git sparse-checkout set guidelines scripts requirements.txt requirements-visual.txt VERSION || true
  git checkout || true
  if ! has_guidelines "$CONTEXT_DIR"; then
    echo "ERROR: consistency-checker override cloned but guidelines/ is empty"
    return 1
  fi
}

if [ -n "$CHECKER_REPO" ]; then
  clone_override || true
fi

if has_guidelines "$CONTEXT_DIR"; then
  CONSISTENCY_DIR="$CONTEXT_DIR"
  SOURCE="override"
elif has_guidelines "$BUNDLED_DIR"; then
  CONSISTENCY_DIR="$BUNDLED_DIR"
  SOURCE="bundled"
else
  echo "CONSISTENCY_DIR="
  echo "CONSISTENCY_AVAILABLE=false"
  echo "Skipping: no bundled guidelines at ${BUNDLED_DIR}/guidelines/ and no clone at ${CONTEXT_DIR}."
  echo "  Optional fork pin: set CONSISTENCY_CHECKER_REPO or overlay context_repos.consistency_checker."
  exit 0
fi

echo "CONSISTENCY_DIR=${CONSISTENCY_DIR}"
echo "CONSISTENCY_AVAILABLE=true"
echo "Consistency-checker ready (${SOURCE}): ${CONSISTENCY_DIR}"
echo "  Guidelines: ${CONSISTENCY_DIR}/guidelines/"
echo "  Scripts:    ${CONSISTENCY_DIR}/scripts/"
