# Eval environment audit

**Branch:** `feat/evaluator-cost-investigation` (base: `andy/design-skill-improvements`)  
**Baseline key:** `RHAISTRAT-1492` (rhoai MR 170, commit `62feb4a`)  
**Audited:** 2026-09-01

## Cluster endpoints (UXDPOC7)

| Service | URL | Status |
|---------|-----|--------|
| OCP Console | https://console-openshift-console.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com/dashboards | Not browser-tested |
| RHOAI | https://rh-ai.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com | Not browser-tested |
| MLflow UI | https://mlflow-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com | **503** (health endpoint; may need in-cluster access or route fix) |
| OCP API | `https://api.uxdpoc7.9hji.p3.openshiftapps.com:443` | **OK** — `oc login` successful |

```bash
export PATH="$PWD/.local/node/bin:$PATH"
eval "$(make mlflow-poc7)"
oc login https://api.uxdpoc7.9hji.p3.openshiftapps.com:443 --username cluster-admin
```

## Local tooling (installed this session)

| Tool | Version | Path |
|------|---------|------|
| Node.js | v20.18.0 | `ai-helpers/.local/node/bin/` (gitignored) |
| npm | 10.8.2 | same |
| oc | stable client | `ai-helpers/.local/node/bin/oc` |
| Python mlflow | 3.15.2 | system pip3 |
| Playwright Chromium | 1.62.x | eval skill `node_modules` |

Add to shell profile for persistence:

```bash
export PATH="/Users/ejaquez/Desktop/ai-helpers/.local/node/bin:$PATH"
```

## Preflight (`scripts/preflight-check.sh`)

| Check | Result | Notes |
|-------|--------|-------|
| Node.js >= 18 | **PASS** | v20.18.0 via `.local/node` |
| Python 3 | **PASS** | 3.14.7 |
| Atlassian MCP | **PASS** (Cursor) | `RHAISTRAT-1492` fetched via MCP in agent session |
| Consistency checker repo | **WARN** | `CONSISTENCY_CHECKER_REPO` not set |
| Playwright | **PASS** | Chromium installed |
| `.artifacts/` write | **PASS** | |
| `oc` CLI | **PASS** | Logged into UXDPOC7 |

## MLflow / tracing config

| Item | Status |
|------|--------|
| `make mlflow-poc7` | **Added** — root Makefile |
| `make mlflow-smoke`, `mlflow-compare`, `mlflow-pipeline` | **Added** |
| `.claude/settings.json` | **Configured** |
| `.claude/skills/eval/scripts/` | **Symlinked** to plugin MLflow scripts |
| `make test-subskills` | **3/3 passed** |
| MLflow cluster reachable | **Blocked** — HTTP 503; `oc get pods -n ux-eval` shows no healthy MLflow pods (`Endpoints: <none>` on route). Platform fix required before tracing. |

## rhoai workspace (MR 170)

| Item | Status |
|------|--------|
| Clone | **Done** — `workspace/rhoai-https/` (HTTPS shallow + checkout `62feb4a`) |
| `npm install` | **Done** |
| Dev server | **Running** — http://localhost:9000 (webpack `start:dev`) |
| Artifacts | `workspace/rhoai-https/.artifacts/RHAISTRAT-1492/` (metadata.json created) |

```bash
export PATH="/Users/ejaquez/Desktop/ai-helpers/.local/node/bin:$PATH"
cd workspace/rhoai-https
npm run start:dev   # port 9000
```

## Depth tiers → `/eval-iterate` flags

| Tier | Flags | Use |
|------|-------|-----|
| `quick` | `--no-fix --no-iterate --no-report` | Spot-check |
| `standard` | `--max-iterations=1` | Designer default |
| `deep` | (none) | Full pipeline |

## Remaining blockers for full baseline eval

1. **MLflow 503** — cluster login works but tracking URI returns 503; check `oc get pods -A | grep mlflow` and route TLS
2. **CONSISTENCY_CHECKER_REPO** — optional but recommended for non-degraded consistency
3. **Full `/eval-iterate`** — run in Cursor against running prototype:

```
/eval-iterate RHAISTRAT-1492 http://localhost:9000 --workspace=/Users/ejaquez/Desktop/ai-helpers/workspace/rhoai-https
```

## Next commands

```bash
export PATH="/Users/ejaquez/Desktop/ai-helpers/.local/node/bin:$PATH"
eval "$(make mlflow-poc7)"

# After eval artifacts exist:
make mlflow-smoke KEY=RHAISTRAT-1492
make mlflow-compare KEY=RHAISTRAT-1492 URL=http://localhost:9000 MODELS="claude-sonnet-4-6 claude-sonnet-5"
```
