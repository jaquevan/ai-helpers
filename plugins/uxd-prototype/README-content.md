## Workflow and documentation

Use **create → evaluate → publish**, with **export** whenever you need captures or implementation-ready output.

| Skill | Role | Documentation |
|-------|------|---------------|
| `/uxd-prototype:uxd-prototype-create` | Create or refine a prototype | [Skill guide](skills/uxd-prototype-create/SKILL.md) · [Scenario planning](skills/uxd-prototype-create/references/scenario-brainstorm.md) · [Pipeline mode](skills/uxd-prototype-create/references/pipeline-mode.md) |
| `/uxd-prototype:uxd-prototype-evaluate` | Acceptance criteria, focused fixes, persona walkthroughs, and evidence reports | [Skill guide](skills/uxd-prototype-evaluate/SKILL.md) · [Orchestration](skills/uxd-prototype-evaluate/references/orchestration.md) |
| `/uxd-prototype:uxd-prototype-export` | HTML, React, PatternFly specs, and Prototype Bar installation | [Skill guide](skills/uxd-prototype-export/SKILL.md) · [Journey schema](skills/uxd-prototype-export/references/journeys-schema.md) · [Scenario schema](skills/uxd-prototype-export/references/scenarios-schema.md) |
| `/uxd-prototype:uxd-prototype-publish` | Publish for review or deployment | [Skill guide](skills/uxd-prototype-publish/SKILL.md) |

The companion functional change adds **`uxd-consistency-check`** for any product.
It supplements workspace guidelines with explicit local/URL sources and always
compares edited areas with relevant workspace peers. Without guidelines,
internal review still runs; guideline compliance is **Not evaluated**. Peer-only
findings are review candidates, not permission to automatically copy a convention.
See its [skill guide](https://github.com/jaquevan/ai-helpers/blob/627f4331e7cdc2ff035a51698818dac643bfbb69/plugins/uxd-prototype/skills/uxd-consistency-check/SKILL.md)
and [source contract](https://github.com/jaquevan/ai-helpers/blob/627f4331e7cdc2ff035a51698818dac643bfbb69/plugins/uxd-prototype/skills/uxd-consistency-check/references/project-context.md).
Install that version before using the new checker; this documentation change
does not itself add the skill.

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
# Available after installing the companion functional change:
if [ -d plugins/uxd-prototype/skills/uxd-consistency-check ]; then
  cp -R plugins/uxd-prototype/skills/uxd-consistency-check ~/.agents/skills/
fi
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
- **Consistency (companion change):** Python 3 and a required prototype workspace; Playwright is optional for DOM capture.
- Live Jira lookup requires an authenticated Atlassian MCP. Copying files does not transfer MCP connections or credentials.

## Best Practices & Cost Management

- Use the host assistant's configured model; per-phase settings are optional when supported. No particular provider or spend cap is imposed by the normal conversational workflow.
- Write clear acceptance criteria and keep iterations focused. `--max-iterations=1` or `--no-iterate` can reduce repeated work.
- Product guidelines live in the product's `.design/product/design-guidelines` directory. Explicit `--guidelines` sources supplement them; conflicts require resolution.
- Compare peers critically: an existing convention can be poor or outdated, and an intentional improvement is not a violation.

For cost examples and setup tips, see the [uxd-prototype skills cost report](https://docs.google.com/document/d/1pLT1_tMHozWsPI-C2jLNLd5xSSUteldoDWzU5x4VZNA/edit?tab=t.0). Actual costs depend on model and scope.
