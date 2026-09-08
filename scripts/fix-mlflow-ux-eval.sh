#!/usr/bin/env bash
# Restore MLflow + Postgres in ux-eval namespace.
# Root cause (2026-09-02): disk-pressure evictions on 2/3 nodes; node 82 at 99% CPU.
set -euo pipefail
NAMESPACE="${MLFLOW_NAMESPACE:-ux-eval}"
HEALTHY_NODE="${MLFLOW_NODE:-ip-10-0-1-82.us-east-2.compute.internal}"

echo "==> Clean stale pods in $NAMESPACE"
oc delete pods -n "$NAMESPACE" --field-selector=status.phase=Failed --grace-period=0 --force 2>/dev/null || true
oc delete pods -n "$NAMESPACE" --field-selector=status.phase=Succeeded --grace-period=0 --force 2>/dev/null || true
for p in $(oc get pods -n "$NAMESPACE" --no-headers 2>/dev/null | awk '$3 ~ /Error|Unknown|Completed/ {print $1}'); do
  oc delete pod -n "$NAMESPACE" "$p" --grace-period=0 --force 2>/dev/null || true
done

echo "==> Patch Postgres (low CPU, pin to $HEALTHY_NODE)"
oc patch deployment postgres -n "$NAMESPACE" --type='json' -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/cpu","value":"25m"},
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"128Mi"}
]' 2>/dev/null || true
oc patch deployment postgres -n "$NAMESPACE" -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"$HEALTHY_NODE\"}}}}}" 2>/dev/null || true

echo "==> Patch MLflow (low CPU, 4Gi memory limit — 2Gi OOMKills on startup)"
oc patch deployment mlflow -n "$NAMESPACE" --type='json' -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/cpu","value":"40m"},
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"1Gi"},
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"4Gi"}
]' 2>/dev/null || true
oc patch deployment mlflow -n "$NAMESPACE" -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"$HEALTHY_NODE\"}}}}}" 2>/dev/null || true

echo "==> Wait for pods"
oc rollout status deployment/postgres -n "$NAMESPACE" --timeout=120s || true
oc rollout status deployment/mlflow -n "$NAMESPACE" --timeout=180s || true

echo "==> Status"
oc get pods -n "$NAMESPACE" -o wide
MLFLOW_URL="${MLFLOW_URL:-https://mlflow-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com}"
curl -sf "${MLFLOW_URL}/health" && echo " MLflow OK" || echo "MLflow still down — check: oc logs -n $NAMESPACE deployment/mlflow"
