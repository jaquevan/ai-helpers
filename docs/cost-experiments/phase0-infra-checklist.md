# Phase 0 — Infrastructure checklist (CP0)

**Date:** 2026-09-02  
**Cluster:** UXDPOC7 ROSA (`ux-eval` namespace)

## Resource verification

| Component | Required | Status |
|-----------|----------|--------|
| Langfuse web + worker | Yes | **Local first** (`make langfuse-local-up`); cluster pending capacity |
| PostgreSQL (in-cluster) | Yes | Via Helm |
| ClickHouse (in-cluster) | Yes | Via Helm |
| Redis/Valkey (in-cluster) | Yes | Via Helm |
| Blob storage / MinIO (in-cluster) | Yes | Via Helm |
| 30-day retention | Yes | `LANGFUSE_DATA_RETENTION_DAYS=30` in Helm values |

## Local Langfuse (test before cluster deploy)

```bash
# Requires Docker Desktop or OrbStack
make langfuse-local-up
eval "$(make langfuse-local-env)"
make langfuse-smoke
make run-phase1-verify KEY=RHAISTRAT-1492
```

See `docker/langfuse/README.md`. Free cluster capacity first:

```bash
eval "$(make cluster-env)"
make mlflow-standby    # scales MLflow+Postgres to 0 on node 82
```

Restore MLflow when scoring: `make mlflow-resume`

## Deployment (cluster)

```bash
oc login https://api.uxdpoc7.9hji.p3.openshiftapps.com:443
bash scripts/deploy-langfuse-ux-eval.sh
```

Route: `https://langfuse-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com`

## MLflow (parallel)

| Check | Status |
|-------|--------|
| `make mlflow-smoke KEY=RHAISTRAT-1492` | **Blocked** — MLflow route 503 |
| `bash scripts/fix-mlflow-ux-eval.sh` | Run after `oc login` |

## CP0 checklist

- [ ] Langfuse health endpoint returns 200 — **local:** `make langfuse-local-up`; cluster blocked until disk-pressure cleared
- [ ] One smoke trace visible in Langfuse UI — run `eval "$(make langfuse-local-env)" && make langfuse-smoke`
- [x] `make mlflow-smoke` — **RESTORED 2026-09-02** (cluster reachable; scorer failures are artifact quality, not infra)
- [x] Cluster resource sheet recorded
- [ ] Provider model names captured from CLI smoke run — pending `claude --print` run

### MLflow fix applied (2026-09-02)

**Root cause:** Pods evicted for `ephemeral-storage` on disk-pressure nodes; replacements Pending on node 82 (99% CPU). MLflow then **OOMKilled** at 2Gi memory limit.

**Fix:** Deleted 100+ stale `ux-eval` pods; pinned postgres+mlflow to node `ip-10-0-1-82`; CPU requests 25m/40m; memory limit **4Gi**.

**Result:** `https://mlflow-ux-eval.../health` → HTTP 200. Re-run: `bash scripts/fix-mlflow-ux-eval.sh`

### Cluster findings (ongoing)

- Nodes 146/180: `disk-pressure` taint — blocks new pods + Langfuse deploy
- Node 82: 99% CPU allocated — MLflow pinned here with minimal requests
- Autoscaler at max node group size
- Langfuse deploy deferred until disk cleared + `helm` installed

## Local instrumentation (ready before cluster)

| Item | Status |
|------|--------|
| `scripts/langfuse_trace.py` | **Done** |
| `scripts/log-cost-ledger.js` | **Done** |
| `scripts/deploy-langfuse-ux-eval.sh` | **Done** |
| `scripts/fix-mlflow-ux-eval.sh` | **Done** |
| `make langfuse-env` | **Done** |
| `make langfuse-smoke` | **Done** (dry-run OK) |
| `make ledger-smoke` | **Done** |

## Next

Phase 1: `make run-phase1-verify KEY=RHAISTRAT-1492`
