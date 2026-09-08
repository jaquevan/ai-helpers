#!/usr/bin/env bash
# Bring MLflow + Postgres back after standby. Applies low-footprint patches from fix-mlflow-ux-eval.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Scaling MLflow stack to 1"
bash "$SCRIPT_DIR/fix-mlflow-ux-eval.sh"
