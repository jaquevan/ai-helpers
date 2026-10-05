# Setting Up Codex with ai-helpers Skills

Codex marketplace integration for ai-helpers is planned, but manual skill-folder installation is the path available today. See [UXDOPS-3080](https://issues.redhat.com/browse/UXDOPS-3080) for marketplace progress.

## Prerequisites

- Node.js ≥ 18 and Python 3 for the prototype workflow.
- Playwright Chromium for prototype evaluation and browser-based export. Install it during setup in the evaluator/export skill folders below.
- Approved AI access: request it through the **AI Budget Help** Slack bot before running model-backed workflows.
- Budget context: up to **$300/month per associate**. This is the available monthly budget, not a target to spend.

## 1. Install and authenticate Codex

Install Codex using the [official Codex installation guide](https://developers.openai.com/codex/cli/), then sign in using the supported method for your organization.

**ChatGPT sign-in is not API-key billing.** ChatGPT account access and API-key authentication are separate billing paths; do not assume a ChatGPT sign-in authorizes API usage or that API usage is included in your ChatGPT plan. Follow your team's approved access and billing setup.

## 2. Install skills manually

From the ai-helpers repository root, copy complete skill folders—not only `SKILL.md`—so scripts, references, configuration, and templates are available. Install globally for your user:

```bash
mkdir -p ~/.agents/skills
cp -R plugins/uxd-prototype/skills/uxd-prototype-create ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-evaluate ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-export ~/.agents/skills/
cp -R plugins/uxd-prototype/skills/uxd-prototype-publish ~/.agents/skills/
```

For a project-local installation, replace `~/.agents/skills/` with `.agents/skills/`.
See the [Codex skills guide](https://developers.openai.com/codex/skills/) for supported locations.

Some optional skill configuration and reference files contain `YOUR_*` example values. Replace those only in your local copy when configuring the matching integration; do not commit credentials. The four core prototype `SKILL.md` files do not require replacing generic input examples such as `{ID}` or `<URL>`.

Marketplace installation is planned, not available today; manual copying is the current route. Repeat the copy commands from an updated checkout to update the installed skill files, after reviewing any local customizations.

## 3. Verify skills are available

In Codex CLI or the IDE extension, use `/skills` to inspect available skills or type `$` to select one (for example, `$uxd-prototype-create`). In the ChatGPT desktop app, open **Skills** in the sidebar. Codex detects local skill changes automatically; restart if an update does not appear.

Invocation differs by assistant: Claude Code and Cursor commonly use plugin-qualified slash commands such as `/uxd-prototype:uxd-prototype-create`; Codex CLI and the IDE extension use `/skills` or `$skill-name` instead.

## 4. Connect required services

- **Jira:** configure an authenticated Atlassian MCP for direct issue lookup. If MCP is unavailable, provide the ticket details yourself or configure the REST fallback with `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN` in your local environment. Never put tokens in a prompt, skill file, or repository.
- **Figma:** connect an approved Figma MCP when the workflow needs to inspect design files directly, or provide an accessible Figma URL and any required screenshots/assets.
- **Publishing:** connect only the GitHub, GitLab, or Vercel account needed for your chosen destination. See [publish setup](../plugins/uxd-prototype/skills/uxd-prototype-publish/README.md#setup).

Before a run, turn off MCP servers unrelated to the goal and verify that the
required ones are authenticated. See the [MCP controls example](prototype-cost-best-practices.md#provide-targeted-context-and-tools).

For Chai Bot's UXD persona MCP setup, see [Chai Bot (UXD Persona)](../README.md#chai-bot-uxd-persona). VPN is required.

## 5. Run your first prototype

Select `$uxd-prototype-create` and try:

```text
Create a prototype for Jira issue UXDOPS-1234. Start with a standalone HTML prototype.
```

The skill asks about the source, workspace choice, and design-decision handling before it builds. It asks a fourth question about decision depth only when relevant, then presents a plan for confirmation.

- **Workspace** is the codebase to build in (or `standalone` for a self-contained prototype).
- **Target** is only where a later merge/pull request will land; it is not the workspace to clone or build in.

For live Jira lookup, connect Atlassian MCP first. Without it, provide the issue details in your prompt or configure the Jira REST fallback.

## 6. Migrating from Cursor or Claude Code

Use your existing migration prompt to inventory the current setup, then verify the result against this guide. Copying complete skill folders transfers skill instructions and bundled scripts, references, templates, and configuration. It does **not** transfer MCP connections, credentials, editor permissions, local settings, or other assistant-specific integrations; configure those separately in Codex. Review customized skill files before copying so local changes are not overwritten.

## Cost savings and model choice

- Review Jira acceptance criteria before evaluation; use clear, observable outcomes instead of broad goals or full meeting transcripts.
- Use focused changes and optional `--max-iterations=1` / `--no-iterate` controls. Use `--no-report` when a full report is not needed; see the [evaluator flags](../plugins/uxd-prototype/skills/uxd-prototype-evaluate/SKILL.md#flags).
- Choose the latest approved OpenAI model appropriate to the task. A more capable model can be cheaper overall when it finishes in fewer turns; effort and context size also affect cost.
- If GPT-6/6.1 options are missing, update Codex or restart the harness. Ask **RHAI UXD AI Office Hours** or **`#forum-rhai-uxd-ai-enablement`** for help.
- Watch the usage indicator near Codex's model selector; hover for context details. Keep one goal per chat and use plan checkpoints for broad work.
- Follow the current team budget and access policy; ask the **AI Budget Help** Slack bot when unsure.

See [Cost Savings & Best Practices](prototype-cost-best-practices.md) for the
model/effort recommendations, screenshots, criteria examples, and tool comparison.
