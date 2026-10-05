#!/bin/bash
# Resolve the repository-local consistency skill in the UXD prototype plugin.
# No project checkout, bootstrap clone, or network access is required.
# Prints CONSISTENCY_DIR= and CONSISTENCY_AVAILABLE= for callers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONSISTENCY_DIR="${SKILL_DIR}/../uxd-consistency-check"

has_checker() {
  local dir="$1"
  [ -f "${dir}/scripts/analyze.py" ] && [ -f "${dir}/scripts/guideline_sources.py" ]
}

if has_checker "$CONSISTENCY_DIR"; then
  CONSISTENCY_DIR="$(cd "$CONSISTENCY_DIR" && pwd)"
else
  echo "CONSISTENCY_DIR="
  echo "CONSISTENCY_AVAILABLE=false"
  echo "Missing uxd-consistency-check scripts at ${CONSISTENCY_DIR}/scripts/."
  exit 0
fi

echo "CONSISTENCY_DIR=${CONSISTENCY_DIR}"
echo "CONSISTENCY_AVAILABLE=true"
echo "Consistency checker ready: ${CONSISTENCY_DIR}"
echo "  Guidelines: supplied workspace .design/product/design-guidelines plus explicit supplements"
echo "  Scripts:    ${CONSISTENCY_DIR}/scripts/"
