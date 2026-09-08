#!/usr/bin/env bash
# Scale MLflow + Postgres to 0 in ux-eval to free node capacity for Langfuse deploy.
# Resume with: bash scripts/mlflow-resume.sh
set -euo pipefail
NAMESPACE="${MLFLOW_NAMESPACE:-ux-eval}"

echo "==> Scaling MLflow stack to 0 in $NAMESPACE (standby)"
oc scale deployment/mlflow deployment/postgres -n "$NAMESPACE" --replicas=0
oc wait --for=delete pod -l app=mlflow -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
oc wait --for=delete pod -l app=postgres -n "$NAMESPACE" --timeout=120s 2>/dev/null || true

echo "==> Remaining pods in $NAMESPACE"
oc get pods -n "$NAMESPACE" -o wide 2>/dev/null || true
echo ""
echo "MLflow route will 503 until you run: bash scripts/mlflow-resume.sh"
