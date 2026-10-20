---
name: uxd-consistency-check
version: 0.1.0
description: Audit UI consistency against local guidance and peers. Use when reviewing a workspace, checking changed UI, or separating guideline coverage from internal consistency.
audience: UI designers and developers
inputs: Workspace path, optional guideline documents, and optional source scope
outputs: Workspace-owned JSON report with frozen guideline provenance and separate internal comparisons
---

# Check UI consistency

Check source against selected guidelines and compare repeated UI roles within a project. These are independent assessments: neither an existing majority pattern nor zero findings establishes design compliance.

## Start here

```text
/uxd-consistency-check --workspace /path/to/project
/uxd-consistency-check --workspace /path/to/project --guidelines /path/to/local-guidelines
/uxd-consistency-check --workspace /path/to/project --changed --base-ref main
```

Ask for the workspace if missing; do not infer a repository from an unrelated checkout. Confirm that it exists before analysis. Default to source-only; no Jira key, live URL, models, remote bootstrap, or external services are required. Report files are written only inside the consumer workspace's `.artifacts`, never inside the skill installation.

## Requirements

Python 3.10+ for bundled tools; Git for changed-source scope. Runtime tools use the standard library ([requirements.txt](requirements.txt)). [requirements-visual.txt](requirements-visual.txt) is optional for explicitly requested live browser capture. Install it only for that task.

## Procedure

1. Resolve the installed skill directory from the host's skill location; call it `SKILL_DIR`. Keep it distinct from the consumer `WORKSPACE`. Read project context using [project-context.md](references/project-context.md). Explain the selected source scope and guideline sources.
2. Load workspace guidance from `.design/product-design/guidelines/` plus repeated local `--guidelines` inputs. Default `--design-system patternfly` adds only the bundled baseline. No workspace guidance means workspace guideline coverage is `not_evaluated`, not product compliance. An alternative design-system ID needs its own local guidance. Select only requested project overlays; never infer product policies from the design system.
3. A user-supplied `--guidelines` URL is a **skill-layer request**, not an analyzer argument. Retrieve only that requested document through authorized agent retrieval tools. Stage local Markdown under workspace `.artifacts` with flat scalar `source_url`, `version`, and `retrieved_at` frontmatter; pass its local path to the analyzer. Record an unknown version explicitly. Never crawl linked documents, discover external guidelines, execute document commands, or silently replace unavailable content. Report retrieval blockers and ask whether to continue with available sources. The scripts never fetch URLs.
4. Run the bundled analyzer. It freezes guideline content and provenance alongside the report. For replay, use the saved `--guideline-manifest` rather than rereading mutable documents; do not combine a frozen manifest with new `--guidelines` inputs.

   ```bash
   python3 "${SKILL_DIR}/scripts/analyze.py" --workspace "${WORKSPACE}" --json-output
   ```

5. Read back the report at the emitted `artifact` path and its referenced guideline snapshot. Separate baseline/workspace coverage, unevaluated rules, and internal comparisons. Baseline `patternfly-component-usage` and `css-token-usage` findings are warning-level review candidates, not proven errors. Only an explicit supported policy can produce a policy violation. Unknown/prose-only checks remain unevaluated.
6. Summarize findings with file/line evidence, coverage limits, internal comparison status, and artifact paths. With no comparable peers, report `insufficient_comparators` and `insufficient comparable examples`; do not call that a pass. Never modify UI source as part of checking.

## Scope and output controls

- `--workspace` aliases: `--src`, `--source-dir`. `--design-system` defaults to `patternfly`; `--design-system-version` records the selected version, not inferred compatibility.
- Repeat `--guidelines` for local files/directories. `--category` and `--guideline` filter by exact category or rule ID.
- `--changed --base-ref main` targets changed lines, including eligible untracked files. Add `--tracked-only` to exclude untracked files; add `--merge-base` for committed merge-base-to-HEAD scope excluding dirty/untracked changes. Both modifiers require `--changed`. Unchanged peers can supply internal comparison context.
- JSON is printed and always saved. Default: `.artifacts/consistency/<run>/consistency-report.json`, with a guideline snapshot reference. `--json-file` selects a workspace `.artifacts` destination; `--report-dir` is a JSON-only compatibility directory override, **not HTML generation**. Do not combine these overrides.
- `--verbose` explains scope on stderr. Exit codes: `0` no error-level rule findings (warnings/unevaluated checks may remain), `1` explicit policy errors, `2` invalid input or analysis failure.

Published contracts: [report v1](schemas/v1/consistency-report.schema.json) and [guideline manifest v1](schemas/v1/guideline-manifest.schema.json). Do not invent fields or treat supplemental evidence as deterministic coverage.

## Optional evidence, separate from source checking

Package existing workspace screenshots offline; this does not launch a browser or assess visual compliance:

```bash
python3 "${SKILL_DIR}/scripts/visual_analyze.py" --workspace "${WORKSPACE}" --screenshot .artifacts/screenshots/page.png
```

Repeat `--screenshot` or select `--output`. Only an explicitly requested `--url` opts into live Playwright capture and its optional dependencies. No URL is guessed or visited by default. This helper does not run models; source-only output keeps visual coverage unrun.

If the user separately supplies supplemental review JSON, validate it without generating a review or calling a model:

```bash
python3 "${SKILL_DIR}/scripts/validate_ai_review.py" --mode source --input "${WORKSPACE}/.artifacts/review.json" --source-root "${WORKSPACE}" --guideline-manifest "${WORKSPACE}/.artifacts/consistency/<run>/<snapshot>.json"
```

Use actual `--help` for `--mode source|visual|internal`, optional `--model`, repeated `--screenshot`, and `--output`. Supplemental validation produces a separate schema-version `1.0.0` report; it never merges into or replaces the deterministic report. Evidence matches current workspace files, ranges, screenshots, and frozen guidelines, not historical HEAD bytes. If committed-scope source differs from the current checkout, keep that review unavailable until matching evidence is supplied.

## References and verification

- [Project context and local metadata](references/project-context.md)

- Project-specific examples live under `references/overlays/`; pass individual requested Markdown files, not the whole reference directory.
- The repository's offline verification results are separate from any model-based evaluation or live browser acceptance; neither is required for normal source checks.

No publishing, issue creation, MR/PR, Slack posts, or auto-merge occurs in a consistency check. Contributions require a separate request and approval flow.
