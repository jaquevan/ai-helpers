#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVALUATOR_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECKER_DIR="$(cd "${EVALUATOR_DIR}/../uxd-consistency-check" && pwd)"
VALIDATOR="${EVALUATOR_DIR}/scripts/validate-consistency.js"
ARTIFACTS_DIR="$(mktemp -d -t uxd-consistency-contract.XXXXXX)"
trap 'rm -rf "${ARTIFACTS_DIR}"' EXIT

python3 "${CHECKER_DIR}/scripts/analyze.py" \
  --src="${CHECKER_DIR}/tests/fixtures/ground-truth" \
  --guideline=no-custom-css \
  --json-file="${ARTIFACTS_DIR}/consistency-report.json"

node "${VALIDATOR}" "${ARTIFACTS_DIR}" --json > /dev/null

node - "${ARTIFACTS_DIR}/consistency-report.json" <<'NODE'
const fs = require('fs');
const path = process.argv[2];
const report = JSON.parse(fs.readFileSync(path, 'utf8'));
report.source_mode.violations[0].review_candidate = true;
fs.writeFileSync(path, JSON.stringify(report));
NODE

if node "${VALIDATOR}" "${ARTIFACTS_DIR}" --json > /dev/null 2>&1; then
  echo "Validator accepted unsafe review-candidate semantics"
  exit 1
fi
