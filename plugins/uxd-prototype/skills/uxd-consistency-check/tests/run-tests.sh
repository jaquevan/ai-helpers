#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Discovery includes the Project Felt source-ground-truth and visual DOM suites.
python3 -m unittest discover -s "$SCRIPT_DIR" -p 'test_*.py' -v
