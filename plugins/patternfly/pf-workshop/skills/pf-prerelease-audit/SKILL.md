---
name: pf-prerelease-audit
description: Audit a consumer project against PatternFly prerelease packages, compare validation results, classify compatibility findings, and produce a report. Use when evaluating a PatternFly release candidate in any consuming repository.
version: 0.1.0
disable-model-invocation: true
---

# PatternFly Prerelease Audit

Run a structured compatibility audit of a consumer repository against selected PatternFly prerelease versions. The audit method and report format are reusable; repository-specific commands and architecture belong to the consumer project's own instructions or to a product playbook supplied by the user.

## Operating boundary

1. Confirm the current working directory is the intended consumer repository root.
2. Read the repository's project instructions and relevant package-manager, build, and CI configuration before planning changes.
3. If the user supplied a product playbook, treat it as additional repository-specific guidance. If they refer to a playbook stored elsewhere, ask them to paste the relevant product tab unless that content is available in the current context.
4. Follow local instructions for exact package locations, install workarounds, validation commands, environment access, and cleanup. Local project instructions take precedence when they are newer or conflict with a playbook.
5. If there is no local guidance, inspect the repository and present the discovered package files and proposed validation commands for confirmation before modifying the project. Do not invent repository-specific paths or commands.

This skill defines only the common audit process, PatternFly prerelease handling, finding classification, and report format. It does not own or maintain any consumer's runbook.

## Safety and change control

- Inspect `git status` before starting. If there are unrelated user changes, preserve them and ask how to proceed before making overlapping edits.
- Confirm the target versions and the list of consumer package files with the user before changing dependency declarations.
- Do not delete project files, reset or stash user work, commit, push, or open a pull request unless the user explicitly requests that action.
- Keep any test-only dependency changes and source fixes scoped to the audit branch. Follow the consumer's instructions for restoring temporary changes after the audit.
- Never put credentials in commands, reports, or project files. Use the project's interactive authentication flow for environment access.

## Phase 1: Resolve and confirm versions

If the user supplied target versions, use those. Otherwise:

1. Discover the `@patternfly/*` packages actually declared by the consumer project, including relevant workspaces, and detect the package manager from its lockfiles.
2. For each consumed package, query the npm `prerelease` dist-tag. Verify the returned version is a release-candidate/prerelease version; package version lines can advance independently.
3. If a tag is missing or does not identify an appropriate candidate, report that package as unresolved rather than substituting a stable release or an unrelated prerelease.
4. Show the user the package/version map and any packages present in their requested map but not consumed by this repo. Ask for confirmation before continuing.

Do not add PatternFly packages that the consumer does not already use. Keep prerelease versions exact (no `^` or `~`) unless the consumer's instructions explain a required project-specific mechanism.

## Phase 2: Establish the baseline

Follow the consumer's own instructions to choose or create an audit branch, install the current dependencies, and run its relevant validation commands before applying prerelease changes. Capture the exact commands, exit statuses, and concise result summaries.

Use the same validation commands for baseline and prerelease runs wherever feasible. If baseline validation is not available, record why and do not imply that a failure is newly introduced without evidence.

## Phase 3: Apply the prerelease and validate

1. Update only the consumed PatternFly package declarations identified in Phase 1, using the consumer's documented rules for workspaces, overrides, resolutions, and lockfiles.
2. Install dependencies using the package manager and any workaround documented by the consumer. Record failed attempts and the successful resolution; do not hide install warnings or conflicts.
3. Run the repository's documented build, type-check, lint, unit/integration, and visual checks as applicable. Follow local guidance on the order and scope of commands, especially in monorepos where a root command may not cover every consumer package.
4. Record each check's result and coverage. Mark checks that could not be run as skipped with a reason.
5. Compare each prerelease result with its baseline. Fix or update tests only when the user has authorized source changes and the change is attributable to the prerelease.

Do not equate a successful root-level command with full coverage unless the consumer's instructions or CI configuration show which packages it exercises.

## Phase 4: Classify findings

Report changes introduced by the prerelease separately from pre-existing failures and tooling artifacts. Use the categories defined in `references/report/schema.md` when applicable:

- TypeScript API break
- Import path break
- CSS/SCSS break
- Runtime or test failure
- Bundle-size change, only if measured
- Peer-dependency warning
- Build-tooling artifact, when investigation shows the symptom is not a PatternFly regression

Do not report an accepted, intentional test or snapshot update as a regression. Do not claim a category was checked if the audit did not run a check capable of detecting it. Escalate uncertain or unverified causes as needing investigation.

## Phase 5: Produce the compatibility report

Use the shared data model in `references/report/schema.md` and render the Markdown and self-contained HTML templates in:

- `references/report/report-template.md`
- `references/report/report-template.html`

Include only sections supported by the checks actually performed. Record package versions, baseline and prerelease outcomes, installation workarounds, findings, pre-existing observations, fixes, recommendations, and test environment. Include skipped checks and their reasons; never silently omit known coverage gaps.

Render exactly one verdict line/block from the schema verdict. For findings, include only categories with findings or checks that were actually performed; use "None observed" only for a checked category. Map `bundle-size-change` to a "Bundle-size change" section with measured details and a verdict, and include it only when bundle size was measured. Omit optional sections and visual-diff details/images when their data is absent; include an image only with its visual-diff finding. In HTML, escape all generated values for their context, including text in headings, attributes, code, and preformatted diffs (`&amp;`, `&lt;`, `&gt;`, `&quot;`, `&#x27;`). Keep markup to the template's fixed structure and fixed verdict/category mappings; never insert project-derived content as HTML. Before creating a snapshot data URI, strictly validate base64 and verify the decoded bytes have the PNG signature; escape the alt text. See the rendering contract in `references/report/schema.md`.

Write the completed reports into the consumer repository using the local playbook's naming/location convention, or ask the user where to save them if none is documented. Keep the reports on the audit branch unless the user requests another destination.

## Final summary

Tell the user:

- Which PatternFly packages and versions were tested.
- Which validation commands ran, their results, and any skipped coverage.
- Which findings are new, pre-existing, accepted, or still uncertain.
- Any source or dependency changes made, and where the Markdown and HTML reports were written.
- Any cleanup or follow-up required by the consumer's local instructions.
