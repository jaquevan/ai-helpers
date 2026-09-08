#!/usr/bin/env bash
# Deploy Langfuse on UXDPOC7 (ux-eval namespace) via Helm.
# Prerequisites: oc login, helm 3, cluster capacity for Postgres+ClickHouse+Redis+MinIO.
set -euo pipefail

NAMESPACE="${LANGFUSE_NAMESPACE:-ux-eval}"
RELEASE="${LANGFUSE_RELEASE:-langfuse}"
ROUTE_HOST="${LANGFUSE_ROUTE_HOST:-langfuse-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com}"
RETENTION_DAYS="${LANGFUSE_RETENTION_DAYS:-30}"

echo "==> Namespace: $NAMESPACE"
oc get namespace "$NAMESPACE" >/dev/null 2>&1 || oc create namespace "$NAMESPACE"

echo "==> Add Langfuse Helm repo"
helm repo add langfuse https://langfuse.github.io/langfuse-k8s 2>/dev/null || true
helm repo update

VALUES_FILE="${TMPDIR:-/tmp}/langfuse-ux-eval-values.yaml"
cat > "$VALUES_FILE" <<EOF
langfuse:
  additionalEnv:
    - name: LANGFUSE_DATA_RETENTION_DAYS
      value: "${RETENTION_DAYS}"
ingress:
  enabled: true
  hosts:
    - host: ${ROUTE_HOST}
      paths:
        - path: /
          pathType: Prefix
postgresql:
  enabled: true
clickhouse:
  enabled: true
redis:
  enabled: true
s3:
  enabled: true
  bucket: langfuse
EOF

echo "==> Helm install/upgrade (full in-cluster stack)"
helm upgrade --install "$RELEASE" langfuse/langfuse \
  --namespace "$NAMESPACE" \
  --values "$VALUES_FILE" \
  --wait --timeout 20m

echo "==> Create OpenShift route if not managed by chart"
oc expose svc "${RELEASE}-web" -n "$NAMESPACE" \
  --name=langfuse-ux-eval \
  --hostname="$ROUTE_HOST" 2>/dev/null || true

echo "==> Wait for pods"
oc wait --for=condition=ready pod -l app.kubernetes.io/instance="$RELEASE" \
  -n "$NAMESPACE" --timeout=600s || true

echo "==> Health check"
curl -sf "https://${ROUTE_HOST}/api/public/health" && echo " OK" || echo "Health check failed — verify route and pods"

echo ""
echo "Next steps:"
echo "  1. Open https://${ROUTE_HOST} and create project + API keys"
echo "  2. export LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... LANGFUSE_HOST=https://${ROUTE_HOST}"
echo "  3. make langfuse-smoke"
