#!/usr/bin/env bash
# Run one designer-style evaluator session with Langfuse tracking enabled.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Missing ${PYTHON}. Run: make langfuse-deps" >&2
  exit 2
fi

if [[ "$#" -lt 3 ]]; then
  echo "Usage: $0 <JIRA_KEY> <PROTOTYPE_URL> <WORKSPACE> [extra pipeline flags]" >&2
  exit 2
fi

KEY="$1"
URL="$2"
WORKSPACE="$3"
shift 3
BENCHMARK_DIR="${REPO_ROOT}/tmp/personal-runs/${KEY}"
JIRA_CONTEXT="${BENCHMARK_DIR}/jira-context.json"

if [[ ! -f "${JIRA_CONTEXT}" ]]; then
  echo "Missing ${JIRA_CONTEXT}; stage Jira context before running." >&2
  exit 2
fi

exec "${REPO_ROOT}/scripts/eval-run.sh" "${PYTHON}" "${SCRIPT_DIR}/langfuse-trace-pipeline.py" \
  --personal-run \
  --key "${KEY}" \
  --url "${URL}" \
  --workspace "${WORKSPACE}" \
  --jira-context "${JIRA_CONTEXT}" \
  --benchmark-dir "${BENCHMARK_DIR}" \
  --env-file "${REPO_ROOT}/.env.local" \
  --trace-sanitized-artifacts \
  --iterate-flags="--max-iterations=1" \
  "$@"
