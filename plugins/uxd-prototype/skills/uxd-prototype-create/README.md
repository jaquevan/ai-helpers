# uxd-prototype-create

Create or refine a UX prototype from a Jira ticket, Figma design, feature description, or idea—standalone or in an existing codebase.

**Contract (inputs, outputs, flags, steps):** [SKILL.md](SKILL.md)

## Prerequisites

| Requirement | When it is needed |
|-------------|-------------------|
| Node.js ≥ 18 and npm | Running a Node-based prototype dev server or the optional measured creator runner |
| Python 3 | Bundled metadata and workspace scripts |
| Git | Building in an existing workspace or using a git source/target |
| Atlassian MCP | Live Jira lookup; otherwise provide the ticket details or configure the documented Jira REST fallback |

Standalone HTML generation does not require build tools. A workspace may have its own additional requirements.

## Quick start

```text
/uxd-prototype:uxd-prototype-create Prototype PROJ-298
/uxd-prototype:uxd-prototype-create Create a prototype from this Figma design: https://figma.com/design/...
/uxd-prototype:uxd-prototype-create Build on the existing project at /path/to/project
```

`--workspace` is the codebase to build in; `--target` only controls where a later MR/PR lands.

> **What to expect:** Before creating or changing files, the skill asks about the source, whether to use an existing workspace or standalone HTML, and how to handle design decisions. It asks a fourth question about decision depth only when relevant, then shows a Prototype Plan for confirmation.

## Setup

For an existing Node-based workspace, install that project's dependencies and start its documented dev server:

```bash
cd /path/to/workspace
npm install
npm run dev
```

Use the workspace's documented start command if it is not `npm run dev`. The standalone HTML path does not need `npm install`. For live Jira lookup, configure an authenticated Atlassian MCP in your assistant; the REST fallback requires `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN`.

For a measured creator phase, use the bounded runner described in [pipeline mode](references/pipeline-mode.md): request an estimate first, then explicitly approve paid execution. The creator runner uses a separate $15 cap and is optional; it is not needed for the normal conversational workflow.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/resolve_workspace.py` | Prepare a workspace clone and resolve branch/upstream details |
| `scripts/fetch_jira.py` | Optional Jira REST fallback when MCP is unavailable |
| `scripts/frontmatter.py` | Read and update prototype artifact metadata |
| `scripts/pipeline_mode.py` | Run the create/evaluate/publish pipeline orchestration |
| `scripts/creator-phase-runner.py` | Run one bounded, measured creator phase after estimate approval |
| `tests/run-tests.sh` | Run creator bridge and bounded-phase tests |

## Related

- **uxd-prototype-evaluate** — validate acceptance criteria and run persona usability walkthroughs
- **uxd-prototype-export** — capture pages or journey steps; install the Prototype Bar
- **uxd-prototype-publish** — submit an MR or publish a sanitized prototype
