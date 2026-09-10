#!/usr/bin/env bash
# Proves that the evaluator resolves the local sibling checker and that the
# checker JSON is accepted by the evaluator's existing report validator.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVALUATOR_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BOOTSTRAP="${EVALUATOR_DIR}/scripts/bootstrap-consistency-checker.sh"
EXPECTED_DIR="$(cd "${EVALUATOR_DIR}/../uxd-consistency-check" && pwd)"

RESOLUTION="$(bash "${BOOTSTRAP}")"
ACTUAL_DIR="$(printf '%s\n' "${RESOLUTION}" | sed -n 's/^CONSISTENCY_DIR=//p')"

if [ "${ACTUAL_DIR}" != "${EXPECTED_DIR}" ] || ! printf '%s\n' "${RESOLUTION}" | grep -qx 'CONSISTENCY_AVAILABLE=true'; then
  echo "Expected local sibling consistency skill resolution"
  exit 1
fi

if rg -q '\.context|git clone|CONSISTENCY_CHECKER_REPO|overlay-get|UXD_PROJECT_ROOT' "${BOOTSTRAP}"; then
  echo "Bootstrap must not use a project context, clone, override, or network resolver"
  exit 1
fi

ARTIFACTS_DIR="$(mktemp -d -t uxd-consistency-eval.XXXXXX)"
trap 'rm -rf "${ARTIFACTS_DIR}"' EXIT

python3 "${ACTUAL_DIR}/scripts/analyze.py" \
  --src "${ACTUAL_DIR}/tests/fixtures/ground-truth" \
  --guideline no-custom-css \
  --json-output > "${ARTIFACTS_DIR}/consistency-report.json"
node "${EVALUATOR_DIR}/scripts/validate-consistency.js" "${ARTIFACTS_DIR}" --json > /dev/null
