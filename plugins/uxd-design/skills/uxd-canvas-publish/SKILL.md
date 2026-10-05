---
name: uxd-canvas-publish
version: 0.1.0
disable-model-invocation: true
description: >-
  Publish an exported canvas to a git repository, GitHub Pages, GitLab Pages,
  or Vercel. Use when sharing a finished static copy for review or updating a
  hosted preview. Creating or updating a Miro board is uxd-canvas-create.
---

# Publish Canvas

Share a completed canvas export on an external host. This skill does not build
the viewer or rewrite assets — run `uxd-canvas-export` first.

Family: `uxd-canvas-create` → `uxd-canvas-export` → **publish**.

## Not a Miro write

This skill publishes the static export only. Creating or updating a Miro board is `uxd-canvas-create`. A board URL is not a `--target`. If the user wants the board changed, stop and use that skill.

## Requirements

- A completed export from `uxd-canvas-export`.
- Authorization for the chosen host immediately before any push or deploy.

## Inputs and output

| Input | Source | Required |
|---|---|---|
| Export directory | `.artifacts/{ID}/export/` or `--source` | **Yes** |
| `export-manifest.json` | inside the export directory | Recommended |
| HTML and/or `canvas.json` | from the export | At least one |

If the export is missing, **stop** and tell the user to run `uxd-canvas-export` first. Do not invent a bundle in this skill.

Published result is a GitLab/GitHub merge request, GitHub Pages URL, GitLab Pages URL, or Vercel URL.

## Flags

$ARGUMENTS

Parse as: `<export-path-or-ID> [--target repo|github|gitlab|vercel] [--source <dir>] [--dry-run]`.

| Flag | Default | Meaning |
|---|---|---|
| `--source` | `.artifacts/{ID}/export/` | Export directory to publish |
| `--target` | asked if omitted | Where to publish. A git URL means open an MR/PR against that repo (implies `repo`) |
| `--dry-run` | off | Validate and describe external actions without pushing or deploying |

There is no `--target local`. Local HTML or JSON output is `uxd-canvas-export`.

## Conversational guidance

If the user says "share", "publish", "deploy", or "I'm done" without a target, ask:

> The canvas export is ready to share. Where should it go?
>
> - **Create a merge request** — push to a repo so the team can review.
> - **Publish to GitHub Pages** — deploy a static copy with a shareable URL.
> - **Deploy to GitLab Pages** — deploy a static copy (self-hosted or gitlab.com).
> - **Deploy to Vercel** — deploy a static copy with a preview URL.

## Publish

1. Resolve the export directory. Prefer `--source`, then `.artifacts/{ID}/export/`.
2. Confirm `export-manifest.json` when present. Require `index.html` for HTML hosts, or `canvas.json` when the export is JSON-only. If neither exists, stop.
3. Review canvas text, URLs, issue records, reactions, images, and inlined assets for confidential or personal data. Public targets require an explicit audience-safe review.
4. Honor `--dry-run`. Obtain any required authorization immediately before creating repositories, pushing, opening merge requests, or deploying.
5. Publish only the export directory (and required host configuration). Preserve existing CI unless the host requires a clean Pages/static template.

### Target: repo

Add the export to the selected repository and open a reviewable branch or merge request using that repository's conventions.

### Target: github

Publish the export with GitHub Pages. Use an existing repository when supplied; get confirmation before creating a public repository.

### Target: gitlab

Publish the export with GitLab Pages, respecting the instance's existing CI conventions.

### Target: vercel

Deploy the export as a static project using an existing project when supplied.

## Completion check

- The published URL or merge request points at the export, not the source `canvas/` directory.
- HTML hosts serve `index.html` with no application-server dependency.
- JSON-only exports are not deployed to Pages/Vercel unless the user explicitly asked to host `canvas.json`.
- No unintended internal data, credentials, inaccessible URLs, or local absolute paths are included.
- The final response identifies the target, URL, and any audience warning.
