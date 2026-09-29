#!/usr/bin/env bash
# Run one evaluation command with the shared worktree environment loaded.
set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "Usage: scripts/eval-run.sh <command> [args...]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_ENV_QUIET=1 source "${SCRIPT_DIR}/eval-env.sh"
exec "$@"
