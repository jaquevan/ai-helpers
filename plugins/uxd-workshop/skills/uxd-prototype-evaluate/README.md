# uxd-prototype-evaluate

Evaluate a running prototype against a Jira ticket's acceptance criteria, optionally fix failures, then run persona usability walkthroughs. Writes an HTML evidence report.

**Contract (inputs, outputs, flags, two-phase flow, artifact paths):** [SKILL.md](SKILL.md)

## Prerequisites

| Requirement | How to get it | Required? |
|-------------|---------------|-----------|
| Node.js >= 18 | `brew install node` or `nvm install 18` | Yes |
| Python 3 | `brew install python3` | Yes |
| Atlassian MCP | Configure in your IDE | Yes (for live Jira) |
| Playwright Chromium | `npm install` then `npx playwright install chromium` in the skill dir (marketplace install does not run `postinstall`) | Yes |

```bash
bash scripts/preflight-check.sh
```

```bash
cd plugins/uxd-workshop/skills/uxd-prototype-evaluate
npm install
npx playwright install chromium
```

Consistency guidelines and the analyzer ship in the sibling `../uxd-consistency-check/` skill. They are available locally with no git URL, project checkout, or network bootstrap. Usability-testing bootstraps on first pipeline run when a git URL is set:

```bash
export USABILITY_TESTING_REPO="git@example.com:org/usability-testing.git"
```

Product-specific remotes, Langfuse, and Pages URLs come from the `uxd-eval-config` plugin (internal marketplace). Personas: `plugins/uxd-workshop/knowledge/personas/`. Overlay details: `references/skill-overlays.md`.

## Model and telemetry configuration

The active experimental runner uses the direct OpenAI Responses API and
metadata-only Langfuse traces. Before model execution, the host assistant must
fetch Jira with the Atlassian MCP and stage a normalized JSON file with
`source: "atlassian-mcp"` under `tmp/benchmarks/<KEY>/jira-context.json`.
No shell, credential-file, or Keychain fallback is allowed.

First validate the local skill, workspace, and staged Jira data without making
an API request:

```bash
make langfuse-pipeline KEY=PROJ-298 URL=http://localhost:3000 \
  WORKSPACE=/path/to/prototype \
  JIRA_CONTEXT=tmp/benchmarks/PROJ-298/jira-context.json \
  PREFLIGHT_ONLY=1
```

Then run the bundled consistency checker and its 14-contract validator without
calling a model:

```bash
make langfuse-pipeline KEY=PROJ-298 URL=http://localhost:3000 \
  WORKSPACE=/path/to/prototype \
  JIRA_CONTEXT=tmp/benchmarks/PROJ-298/jira-context.json \
  DETERMINISTIC_ONLY=1
```

This writes `.artifacts/<KEY>/eval/consistency-report.json` in the prototype
workspace and `deterministic-source-result.json` in the gitignored benchmark
directory. It checks changed files against the detected Git base; set
`BASE_REF=<ref>` to override or `ALL_FILES=1` to check the whole workspace.

To inspect the three model-phase packets without calling a model, replace
`DETERMINISTIC_ONLY=1` with `PHASE_PLAN_ONLY=1`. The editable JSON packets are
written under `tmp/benchmarks/<KEY>/phase-packets/`.

Omit `DETERMINISTIC_ONLY=1` only for an explicitly approved paid run. The
bounded OpenAI runner currently supports no-fix evaluation runs:

```bash
make langfuse-pipeline KEY=PROJ-298 URL=http://localhost:3000 \
  WORKSPACE=/path/to/prototype \
  JIRA_CONTEXT=tmp/benchmarks/PROJ-298/jira-context.json \
  ITERATE_FLAGS="--no-fix --max-iterations=1"
```

Jira extraction, AC classification, and baseline screenshot/DOM capture are
deterministic local steps. The runner then invokes three isolated model phases:
journey, visual consistency, and usability. Journey uses one tool-free Responses
API request with strict `text.format.type: json_schema` Structured Outputs and
portable image inputs resolved from relative paths in `prototype-evidence.json`.
Visual consistency and usability retain two-turn limits. Existing phase
validators must pass before the next phase starts. The report is
schema-validated and rendered by bundled local scripts. Model work uses at most
5 turns under the shared 12-turn ceiling.
Inspectable packets and provider responses stay under the gitignored benchmark
directory. The runner never discovers global marketplace caches.

`OPENAI_BASE_URL` may be either an API base URL (for example,
`https://api.openai.com/v1`) or the full Responses endpoint. Verify Langfuse
credentials and connectivity before a real run with:

```bash
eval "$(make langfuse-local-env)" # or: eval "$(make langfuse-env)"
make langfuse-verify
```

Platform/model selection uses `AI_HELPERS_PLATFORM=codex|cursor|anthropic`.
OpenAI is the default; set `EVAL_PROVIDER=anthropic` to preserve the Claude
workflow. If the host cannot be detected, ask the designer which platform they
are using before selecting a phase model. MLflow files remain in the repository
for research comparison only and are not used by active targets.

## Quick start

```
/uxd-prototype-evaluate PROJ-298 http://localhost:3000 --workspace=/path/to/prototype
/uxd-prototype-evaluate review PROJ-298
```

## Optional Google Sheet sync

Set `tracking.sheet_id` in `config/product-overlay.yaml` (or `EVAL_SHEET_ID`). Leave empty to disable. Requires `gcloud auth login --enable-gdrive-access`.

## Validators

| Script | Purpose |
|--------|---------|
| `scripts/extract_jira_context.py` | Deterministic staged-Jira extraction and MR delta |
| `scripts/run-classification.js` | Deterministic T1-T4 AC classification and CSV initialization |
| `scripts/run-report.js` | Schema validation, HTML rendering, and rendering validation |
| `scripts/validate-phase-b-output.js` | Phase B persona output schemas and score contracts |
| `scripts/validate-artifact-schemas.js` | Schema validation for pipeline artifacts |
| `scripts/validate-report-rendering.js` | Report rendering quality checks |

## Claude Code permissions

The eval pipeline shells out to bundled Node/bash scripts and Playwright. To auto-approve them, add to the project's `.claude/settings.json` (or `~/.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "Bash(node:*validate-artifact-schemas*)",
      "Bash(node:*validate-phase-b-output*)",
      "Bash(node:*validate-report-rendering*)",
      "Bash(node:*render-report*)",
      "Bash(node:*render-mini-report*)",
      "Bash(node:*classify-ac-tier*)",
      "Bash(node:*compute-patience-drain*)",
      "Bash(node:*generate-journey-script*)",
      "Bash(node:*validate-verdicts*)",
      "Bash(node:*hydrate-persona-results*)",
      "Bash(node:*resolve-root*)",
      "Bash(node:*append-iteration-log*)",
      "Bash(node:*build-leaderboard*)",
      "Bash(node:*generate-dashboard*)",
      "Bash(node:*log-run*)",
      "Bash(bash:*pipeline-setup*)",
      "Bash(bash:*publish-report*)",
      "Bash(bash:*bootstrap-usability-testing*)",
      "Bash(bash:*bootstrap-consistency-checker*)",
      "Bash(npx:playwright*)",
      "Bash(npm:install*)",
      "Bash(python3:*eval_state*)"
    ]
  }
}
```

Contributors in this repo get these via `.claude/settings.json` (accepted once via the workspace trust dialog).

## Phase procedures

Orchestration: `SKILL.md` and `references/orchestration.md`. Per-phase files live in `references/phases/`. Ignore `references/draft-phase-a-cli-workflow.md` — not implemented.

## Related

- `uxd-prototype-create` — builds the prototype; refine from eval findings
- `uxd-prototype-export` — Prototype Bar Eval tab and `export-helper.mjs`
- `uxd-prototype-publish` — blocked by AC FAIL unless `--force`
