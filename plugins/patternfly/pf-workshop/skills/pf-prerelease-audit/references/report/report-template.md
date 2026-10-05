<!--
Markdown report template for the pf-prerelease-audit skill.
Fill placeholders from the data model in ./schema.md. Delete any section
with no data for this run rather than leaving it as "N/A" filler — see
schema.md's "Category vs. skill capability" note.
-->
# PatternFly Prerelease Compatibility Report — {{REPO}}

**Date:** {{DATE}}
**Branch:** `{{BRANCH}}`
**Tester:** {{TESTER}}

<!-- Replace with exactly one verdict line, mapped from schema.md's verdict value. -->
{{VERDICT_LINE}}

## Versions Tested

| Package | Before | After (prerelease) | Notes |
|---|---|---|---|
| `@patternfly/{{pkg}}` | `{{before}}` | `{{after}}` | {{note or blank}} |

**Not consumed by {{REPO_SHORT}}** (present on the prerelease manifest but not a dependency here): {{list, or omit section}}

## Summary

| Check | Baseline | Prerelease | Result |
|---|---|---|---|
| {{check name}} | {{pass/fail/skip + detail}} | {{pass/fail/skip + detail}} | {{No regression / Fixed in prerelease / New regression}} |

<!-- Drop the Baseline column entirely for skills that don't run a baseline pass. -->

## Installation Notes

<!-- Always state what was tried, including failed attempts — don't only document the happy path. -->
- **{{workaround}}** — cause: {{cause}}. Outcome: {{worked / fell back to X because Y / not needed}}.

## Findings

<!-- Replace with category subsections only when findings exist or that category was checked;
     omit this entire Findings section if there are no applicable categories.
     Say "None observed" only for a category the audit actually checked; omit unsupported
     categories. Supported labels include TypeScript API break, Import path break, CSS/SCSS
     break, Runtime failure, Bundle-size change, Peer dependency warning, and Build tooling
     artifact. For `bundle-size-change`, use the heading "Bundle-size change" and include the
     measured change and verdict. Include it only when bundle size was measured. -->
{{FINDINGS_SECTIONS}}

## Fixes Applied

<!-- Omit this section entirely if no source changes were needed. -->
- **{{file}}** — {{description}}

## Pre-existing Observations

<!-- Warnings/failures present in both baseline and prerelease (or, for skills without a
     baseline, present on main independent of this bump). Call these out so they aren't
     mistaken for new regressions. -->
- {{observation}}

## Recommendations

**For PF team:**
- {{recommendation}}

**For {{REPO_SHORT}} team:**
- {{recommendation}}

## Test Environment

- Node: {{node version}}
- Package manager: {{npm/yarn}} {{version}}
- OS: {{os}}
- Bundler: {{bundler, if applicable}}
