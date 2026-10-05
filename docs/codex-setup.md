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
cp -R plugins/uxd-prototype/skills/uxd-consistency-check ~/.agents/skills/
```

For a project-local installation, replace `~/.agents/skills/` in those commands with `.agents/skills/` in the project. The consistency checker is used by the prototype create/evaluate workflow. See the [Codex skills guide](https://developers.openai.com/codex/skills/) for supported skill locations.

Some optional skill configuration and reference files contain `YOUR_*` example values. Replace those only in your local copy when configuring the matching integration; do not commit credentials. The four core prototype `SKILL.md` files do not require replacing generic input examples such as `{ID}` or `<URL>`.

Marketplace installation is planned, not available today; manual copying is the current route. Repeat the copy commands from an updated checkout to update the installed skill files, after reviewing any local customizations.

## 3. Verify skills are available

In Codex CLI or the IDE extension, use `/skills` to inspect available skills or type `$` to select one (for example, `$uxd-prototype-create`). In the ChatGPT desktop app, open **Skills** in the sidebar. Codex detects local skill changes automatically; restart if an update does not appear.

Invocation differs by assistant: Claude Code and Cursor commonly use plugin-qualified slash commands such as `/uxd-prototype:uxd-prototype-create`; Codex CLI and the IDE extension use `/skills` or `$skill-name` instead.

## 4. Connect required services

- **Jira:** configure an authenticated Atlassian MCP for direct issue lookup. If MCP is unavailable, provide the ticket details yourself or configure the REST fallback with `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN` in your local environment. Never put tokens in a prompt, skill file, or repository.
- **Figma:** connect an approved Figma MCP when the workflow needs to inspect design files directly, or provide an accessible Figma URL and any required screenshots/assets.
- **Publishing:** connect only the GitHub, GitLab, or Vercel account needed for your chosen destination. See [publish setup](../plugins/uxd-prototype/skills/uxd-prototype-publish/README.md#setup).

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

## Tips for managing costs

- Use `--no-iterate` for a quick evaluation pass without the Phase A fix loop, and `--no-report` when a full report is not needed. These are optional safeguards, not required setup steps; see the [evaluator flags](../plugins/uxd-prototype/skills/uxd-prototype-evaluate/SKILL.md#flags).
- A full create + evaluate + publish workflow is estimated at **about $6** as a planning figure. Actual cost varies with scope, iterations, provider, and model. Review any estimate and obtain required approval before paid work.
- A dedicated cost guide is planned; it will be linked here once `docs/cost-guide.md` is available.
- Keep the **$300/month per-associate budget** in mind and ask the AI Budget Help Slack bot about access or budget policy.
