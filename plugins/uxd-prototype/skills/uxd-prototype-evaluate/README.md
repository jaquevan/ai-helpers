# uxd-prototype-evaluate

Evaluate a running prototype against a Jira ticket's acceptance criteria, optionally fix failures, then run persona usability walkthroughs and produce an HTML evidence report.

**Contract (inputs, outputs, flags, two-phase flow, artifact paths):** [SKILL.md](SKILL.md)

## Prerequisites

| Requirement | How to get it | Required? |
|-------------|---------------|-----------|
| Node.js ≥ 18 | `brew install node` or `nvm install 18` | Yes |
| Python 3 | `brew install python3` | Yes |
| Atlassian MCP | Configure in your assistant | For live Jira lookup |
| Playwright Chromium | Install with the commands below | Yes for browser evaluation |

Run the preflight check from this skill directory:

```bash
bash scripts/preflight-check.sh
```

## Quick start

```text
/uxd-prototype:uxd-prototype-evaluate PROJ-298 http://localhost:3000 --workspace=/path/to/prototype
/uxd-prototype:uxd-prototype-evaluate review PROJ-298
```

The first example evaluates a reachable prototype and enables the workspace fix loop; `review` opens the existing report without rerunning the pipeline.

## Setup

From the repository root, install the evaluator dependencies and Chromium before the first browser evaluation:

```bash
cd plugins/uxd-prototype/skills/uxd-prototype-evaluate
npm install
npx playwright install chromium
```

Marketplace/manual skill-file installation does not install Node dependencies or Chromium. Optional context repositories bootstrap on first pipeline run when configured:

```bash
export USABILITY_TESTING_REPO="git@example.com:org/usability-testing.git"
export CONSISTENCY_CHECKER_REPO="git@example.com:org/consistency-checker.git"
```

Optional Google Sheet sync: set `tracking.sheet_id` in `config/product-overlay.yaml` or `EVAL_SHEET_ID`; leave it unset to disable. Google Drive access requires `gcloud auth login --enable-gdrive-access`.

Claude Code users may optionally auto-approve the evaluator's bundled commands by adding this project-level allowlist to `.claude/settings.json` (or `~/.claude/settings.json`). Contributors in this repository can accept the workspace trust prompt. Other assistants manage command approval through their own permission controls.

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

Phase orchestration is documented in [SKILL.md](SKILL.md) and [references/orchestration.md](references/orchestration.md). Per-phase procedures are in `references/phases/`; `references/draft-phase-a-cli-workflow.md` is not implemented.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/preflight-check.sh` | Check evaluator prerequisites |
| `scripts/validate-phase-b-output.js` | Validate Phase B persona output schemas and scores |
| `scripts/validate-artifact-schemas.js` | Validate pipeline artifact schemas |
| `scripts/validate-report-rendering.js` | Check rendered report quality |
| `scripts/pipeline-setup.sh` | Prepare pipeline artifact directories and runtime state |
| `scripts/publish-report.sh` | Publish the generated report when configured |

Product-specific remotes and Pages URLs come from the internal `uxd-eval-config` plugin. Persona files are under `plugins/uxd-prototype/knowledge/personas/`; see `references/skill-overlays.md` for overlays.

## Related

- **uxd-prototype-create** — creates the prototype and artifacts; refine from evaluation findings
- **uxd-prototype-export** — provides the Prototype Bar Eval tab and local report helper
- **uxd-prototype-publish** — blocks publishing on AC FAIL unless `--force` is explicitly used
