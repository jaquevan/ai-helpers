#!/bin/bash
# Compatibility entry point: discover the installed sibling checker only.
# No project context, remote repository, or guideline bundle is required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/uxd-consistency-check"

if [ -f "$CHECKER_DIR/SKILL.md" ] && [ -f "$CHECKER_DIR/scripts/analyze.py" ]; then
  echo "CONSISTENCY_AVAILABLE=true"
  echo "Consistency checker available: $CHECKER_DIR"
else
  echo "CONSISTENCY_AVAILABLE=false"
  echo "Consistency checker unavailable: $CHECKER_DIR (requires SKILL.md and scripts/analyze.py)"
  echo "Install or restore the sibling uxd-consistency-check beside this evaluator with SKILL.md and scripts/analyze.py, then rerun evaluation. Record checks as unavailable until restored; do not run a substitute audit."
fi
