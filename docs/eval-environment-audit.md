# Eval environment audit

**Branch:** `feat/evaluator-cost-investigation` (base: `andy/design-skill-improvements`)  
**Baseline key:** `RHAISTRAT-1492` (rhoai MR 170, commit `62feb4a`)  
**Audited:** 2026-09-01

## Cluster endpoints (UXDPOC7)

| Service | URL | Status |
|---------|-----|--------|
| OCP Console | https://console-openshift-console.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com/dashboards | Not browser-tested |
| RHOAI | https://rh-ai.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com | Not browser-tested |
| MLflow UI | https://mlflow-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com | **OK** (restored 2026-09-02) |
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
| MLflow cluster reachable | **OK** — restored via `scripts/fix-mlflow-ux-eval.sh` |
| Langfuse deploy | **Scripts ready** — `bash scripts/deploy-langfuse-ux-eval.sh` |
| `make langfuse-env` / `langfuse-smoke` | **Added** |
| Cost ledger | **Per-run** `.artifacts/<KEY>/eval/cost-ledger.jsonl` |
| Cost experiments docs | **`docs/cost-experiments/`** |

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

## Baseline eval run (2026-09-01)

**Mode:** `/eval-iterate RHAISTRAT-1492 http://localhost:9000 --no-fix --max-iterations=1`
**MLflow:** Skipped (cluster down)
**Report:** `.artifacts/RHAISTRAT-1492/eval/evaluation-report.html` (2.5 MB)

| Phase | Result |
|-------|--------|
| Phase A ACs | 1 PASS / 0 FAIL / 3 FLAGGED (`no_fix` exit) |
| Phase B usability | 18/21 (`data-scientist+junior`, `data-scientist+senior`) |

**FLAGGED (human review):** AC-1, AC-2, AC-4 require pipeline-log/backend verification outside UI prototype scope. AC-3 PASS (eval metric dropdown).

**Degraded:** consistency checker not bootstrapped; Pages publish skipped (`GITLAB_PAGES_REPO` unset).

**Phase 1 next:** `make mlflow-compare KEY=RHAISTRAT-1492 URL=http://localhost:9000` once MLflow pods are healthy.


```bash
export PATH="/Users/ejaquez/Desktop/ai-helpers/.local/node/bin:$PATH"
eval "$(make mlflow-poc7)"

# After eval artifacts exist:
make mlflow-smoke KEY=RHAISTRAT-1492
make mlflow-compare KEY=RHAISTRAT-1492 URL=http://localhost:9000 MODELS="claude-sonnet-4-6 claude-sonnet-5"
```
