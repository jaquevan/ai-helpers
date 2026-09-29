#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/test_pipeline_mode.py"
python3 "$SCRIPT_DIR/test_creator_phase_runner.py"
