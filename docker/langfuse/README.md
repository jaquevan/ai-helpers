# Local Langfuse stack for uxd-prototype-evaluate instrumentation testing.

## Prerequisites

- Podman, Docker Desktop, or OrbStack on macOS
- ~4 GB free RAM for Postgres, ClickHouse, Redis, MinIO, Langfuse web/worker

**Podman (macOS):** the default VM is only 2GB — Langfuse needs more. One-time setup:

```bash
brew install podman podman-compose
podman machine init                    # first time only
podman machine set --memory 8192 --cpus 4
podman machine start
```

ClickHouse native port is mapped to **19000** (not 9000) so it does not conflict with the prototype dev server on `:9000`.

## Quick start

```bash
# One-time Podman setup (8GB RAM required — default 2GB OOMs Langfuse)
brew install podman podman-compose
podman machine init                    # skip if already created
podman machine set --memory 8192 --cpus 4
podman machine start

# Repo + Langfuse stack
cd ~/Desktop/ai-helpers
make langfuse-deps                     # Python SDK in .venv
make langfuse-local-up                 # http://localhost:3100 (first pull ~3 min)

eval "$(make langfuse-local-env)"
make langfuse-smoke
make run-phase1-verify KEY=RHAISTRAT-1492
```

Stop:

```bash
make langfuse-local-down
```

## UI login

Defaults from `env.example` (copied to `.env` on first up; `.env` is gitignored):

- URL: http://localhost:3100
- Email: `admin@local.dev`
- Password: `langfuse-local-dev`

SDK keys are pre-seeded via `LANGFUSE_INIT_*` in `.env`:

- `pk-lf-local-uxd-eval` / `sk-lf-local-uxd-eval-secret`

## Cluster note

Before deploying Langfuse on UXDPOC7, put MLflow in standby to free node 82:

```bash
source scripts/cluster-setup-env.sh   # or: eval "$(make cluster-env)"
bash scripts/mlflow-standby.sh
# deploy when ready: bash scripts/deploy-langfuse-ux-eval.sh
# restore MLflow: bash scripts/mlflow-resume.sh
```
