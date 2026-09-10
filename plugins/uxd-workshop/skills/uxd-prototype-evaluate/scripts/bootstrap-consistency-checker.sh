#!/bin/bash
# Resolve the locally bundled sibling consistency skill.
# No project checkout, bootstrap clone, or network access is required.
# Prints CONSISTENCY_DIR= and CONSISTENCY_AVAILABLE= for callers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONSISTENCY_DIR="${SKILL_DIR}/../uxd-consistency-check"

has_guidelines() {
  local dir="$1"
  [ -d "${dir}/guidelines" ] && [ "$(find "${dir}/guidelines" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]
}

if has_guidelines "$CONSISTENCY_DIR"; then
  CONSISTENCY_DIR="$(cd "$CONSISTENCY_DIR" && pwd)"
else
  echo "CONSISTENCY_DIR="
  echo "CONSISTENCY_AVAILABLE=false"
  echo "Missing sibling uxd-consistency-check skill at ${CONSISTENCY_DIR}/guidelines/."
  exit 0
fi

echo "CONSISTENCY_DIR=${CONSISTENCY_DIR}"
echo "CONSISTENCY_AVAILABLE=true"
echo "Consistency checker ready: ${CONSISTENCY_DIR}"
echo "  Guidelines: ${CONSISTENCY_DIR}/guidelines/"
echo "  Scripts:    ${CONSISTENCY_DIR}/scripts/"
