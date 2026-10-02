<!-- Auto-generated — do not edit manually. -->

# UXD Prototype Plugin

Create UX prototypes from Jira tickets, Figma designs, or feature descriptions.

## Workflow and documentation

The prototype workflow is **create → evaluate → publish**, with **export** available whenever you need captures or implementation-ready output. The standalone consistency checker runs alongside create/evaluate and can also be used directly.

| Skill | Role | Documentation |
|-------|------|---------------|
| `/uxd-prototype:uxd-prototype-create` | Create or refine a prototype from a Jira ticket, Figma design, feature description, or idea | [Skill guide](skills/uxd-prototype-create/SKILL.md) · [Scenario planning](skills/uxd-prototype-create/references/scenario-brainstorm.md) · [Pipeline mode](skills/uxd-prototype-create/references/pipeline-mode.md) |
| `/uxd-prototype:uxd-prototype-evaluate` | Check acceptance criteria, apply focused fixes, run persona walkthroughs, and produce an evidence report | [Skill guide](skills/uxd-prototype-evaluate/SKILL.md) · [Orchestration](skills/uxd-prototype-evaluate/references/orchestration.md) · [Consistency phase](skills/uxd-prototype-evaluate/references/phases/eval-consistency.md) |
| `/uxd-prototype:uxd-prototype-export` | Export pages and journey steps as HTML, React, or PatternFly specs; install the Prototype Bar | [Skill guide](skills/uxd-prototype-export/SKILL.md) · [Journey schema](skills/uxd-prototype-export/references/journeys-schema.md) · [Scenario schema](skills/uxd-prototype-export/references/scenarios-schema.md) |
| `/uxd-prototype:uxd-prototype-publish` | Publish a prototype for review or deployment through a supported hosting or git destination | [Skill guide](skills/uxd-prototype-publish/SKILL.md) |
| `/uxd-prototype:uxd-consistency-check` | Review a prototype for PatternFly consistency and visual design concerns | [Skill guide](skills/uxd-consistency-check/SKILL.md) · [Project context](skills/uxd-consistency-check/references/project-context.md) · [Guidelines](skills/uxd-consistency-check/guidelines/) · [Project Felt guideline](skills/uxd-consistency-check/guidelines/project-felt-adoption.md) |

**After evaluation:** publish when acceptance criteria pass and usability is acceptable. Review FLAGGED items before publishing. For major failures or low usability, use the findings to refine the prototype and evaluate again.

**Create onboarding:** before generating anything, the skill asks what to prototype, whether to use an existing codebase or standalone HTML, and how to handle design decisions. It asks about decision depth only when relevant, then presents a **Prototype Plan** for confirmation. Nothing is built, cloned, or published until you confirm.

## Set up the skills in Codex

Native Codex marketplace support for ai-helpers is planned, but is **not available yet**. You can try importing your existing setup through the ChatGPT desktop app, or copy the full skill directories manually.

### ChatGPT desktop app

1. Install or update the ChatGPT desktop app and sign in.
2. Open Codex and, when offered, import your existing Claude Code or Cursor setup.
3. Check that the skills are available. If the import does not include them, use the manual copy method below.

### Manual file-system copy

From the ai-helpers repository root, copy the complete skill folders (not only `SKILL.md`) so scripts, references, configuration, and other resources are included:

```bash
mkdir -p ~/.agents/skills
cp -R plugins/uxd-prototype/skills/uxd-prototype-create ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-evaluate ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-export ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-publish ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-consistency-check ~/.agents/skills/
```

Re-copy the folders from the repository to update them. Copy the related skills together for the full create/evaluate/export workflow.

## Prerequisites

| Skill | Required setup |
|-------|----------------|
| `uxd-prototype-create` | `Harness only` means the chat interface (e.g., Codex or Claude) you're already using; standalone creation needs no extra software. Workspace mode needs `git`. |
| `uxd-prototype-evaluate` | **Node.js ≥ 18, Python 3, and Playwright Chromium.** Copying/installing the skill files does not install dependencies or Chromium. From the evaluator skill directory, run `npm install` and `npx playwright install chromium` before the first evaluation. |
| `uxd-prototype-export` | Node.js ≥ 18. |
| `uxd-prototype-publish` | `git` and authentication for the chosen destination (GitLab, GitHub, or Vercel). |

Live Jira integration for create/evaluate requires an authenticated Atlassian MCP.

## Best Practices & Cost Management

- **Models are pre-configured:** you don't need to choose one. With the default OpenAI routing, GPT-6 Sol handles complex creation and refinement, while GPT-6 Luna handles lighter supporting and judging tasks—balancing quality and cost.
- **Write clear acceptance criteria:** state expected behavior and important edge cases up front. Ambiguity leaves the skill guessing, causing unnecessary iterations that can quickly burn through token budgets.
- **Keep iterations small:** make focused, step-by-step changes and rerun only what you need. Optional safeguards—not required coding steps—include `--max-iterations=1` to cap the Phase A fix loop at one iteration, or `--no-iterate` to skip the fix loop and run a single Phase A pass. Avoid large re-runs to stay within your budget.

For information on the cost of running each skill, tips, setup, and other recommendations, see the [uxd-prototype skills cost report](https://docs.google.com/document/d/1pLT1_tMHozWsPI-C2jLNLd5xSSUteldoDWzU5x4VZNA/edit?tab=t.0).
