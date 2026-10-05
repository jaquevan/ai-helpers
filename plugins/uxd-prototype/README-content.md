## Workflow and documentation

Use **create → evaluate → publish**, with **export** whenever you need captures or implementation-ready output.

| Skill | Role | Documentation |
|-------|------|---------------|
| `/uxd-prototype:uxd-prototype-create` | Create or refine a prototype | [Skill guide](skills/uxd-prototype-create/SKILL.md) · [Scenario planning](skills/uxd-prototype-create/references/scenario-brainstorm.md) · [Pipeline mode](skills/uxd-prototype-create/references/pipeline-mode.md) |
| `/uxd-prototype:uxd-prototype-evaluate` | Acceptance criteria, focused fixes, persona walkthroughs, and evidence reports | [Skill guide](skills/uxd-prototype-evaluate/SKILL.md) · [Orchestration](skills/uxd-prototype-evaluate/references/orchestration.md) |
| `/uxd-prototype:uxd-prototype-export` | HTML, React, PatternFly specs, and Prototype Bar installation | [Skill guide](skills/uxd-prototype-export/SKILL.md) · [Journey schema](skills/uxd-prototype-export/references/journeys-schema.md) · [Scenario schema](skills/uxd-prototype-export/references/scenarios-schema.md) |
| `/uxd-prototype:uxd-prototype-publish` | Publish for review or deployment | [Skill guide](skills/uxd-prototype-publish/SKILL.md) |

**After evaluation:** publish when acceptance criteria pass and usability is acceptable. Review FLAGGED items; refine and re-evaluate major failures.

**Create onboarding:** the skill asks about the source, workspace/standalone choice, and design decisions before building. It asks about decision depth when relevant, then presents a **Prototype Plan** for confirmation.

## Set up the skills in Codex

Native marketplace support is planned. In the ChatGPT desktop app, import an
existing Claude Code or Cursor setup when offered, then verify the skills are
available. Otherwise copy complete skill folders from an updated repository:

```bash
mkdir -p ~/.agents/skills
cp -R plugins/uxd-prototype/skills/uxd-prototype-create ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-evaluate ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-export ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-publish ~/.agents/skills/
```

Repeat the copy to update installed skills, reviewing local customizations first.
See the [create setup](skills/uxd-prototype-create/README.md#setup),
[evaluator setup](skills/uxd-prototype-evaluate/README.md#setup),
[export setup](skills/uxd-prototype-export/README.md#setup), and
[publish setup](skills/uxd-prototype-publish/README.md#setup).

## Prerequisites

- **Create:** the current assistant; workspace mode also needs Git and the project's build tools.
- **Evaluate:** Node.js ≥ 18, Python 3, and Playwright Chromium. Install with `npm install` and `npx playwright install chromium` in the skill directory.
- **Export:** Node.js ≥ 18; Chromium for browser captures.
- **Publish:** Git and authentication for the selected GitHub/GitLab/Vercel destination.
- Live Jira lookup requires an authenticated Atlassian MCP. Copying files does not transfer MCP connections or credentials.

## Cost Savings & Best Practices

- **Review Jira RFE/STRAT criteria first:** use specific, testable outcomes. Vague or subjective criteria and full meeting-note dumps can create unnecessary evaluation loops. Gemini Pro can help structure notes before evaluation.
- **Iterate small:** use focused changes and optional `--max-iterations=1` or `--no-iterate` controls instead of large repeated runs.
- **Choose models by total task cost:** start with GPT-6 Luna at low/medium effort for easy-to-check work, GPT-6.1 Sol at medium effort for bounded judgment, and GPT-6.1 Sol at high effort for planning or multi-step work. Reserve Astra for budgeted, very complex tasks.
- **Keep context focused:** one goal per chat, targeted files/sections, and only the authenticated MCP services needed for that goal.
- **Plan and checkpoint:** agree on scope and stopping conditions, review progress, and summarize context for a fresh handoff when needed.
- **Use included tooling where appropriate:** Gemini/Workspace and Rovo/Atlassian can cover research and summarization before a metered agentic run.

See the [full cost-saving guide](../../docs/prototype-cost-best-practices.md) for
criteria examples, model/effort starting points, context and MCP screenshots,
plan-mode guidance, and the included-versus-metered tooling comparison. For
setup help, visit **RHAI UXD AI Office Hours** or **`#forum-rhai-uxd-ai-enablement`**.
