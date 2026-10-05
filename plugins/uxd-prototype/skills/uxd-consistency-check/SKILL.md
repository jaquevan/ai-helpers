---
name: uxd-consistency-check
version: 0.1.0
description: >-
  Check UX prototypes against bundled PatternFly consistency guidelines and
  produce actionable source and visual findings. Use when auditing prototype
  source, validating PatternFly conventions, or reviewing consistency before
  usability evaluation.
---

# UXD Consistency Check

Run deterministic PatternFly consistency checks against an existing prototype.
The skill owns its guideline corpus and scripts; callers must resolve them
relative to this skill directory rather than a consumer project's root.

## Source checks

Treat authored custom CSS and unapproved component substitutions as blocking
errors. React prototypes must use PatternFly components for interactive
controls. Static HTML must use the matching `pf-vN-*` classes. Native controls
without PatternFly treatment and imports from other UI component libraries are
violations; ambiguous search-only matches remain non-blocking review
candidates.

The `project-felt-adoption` guideline checks app entry HTML for the
`pf-v6-theme-felt` root class, checks for Felt background assets, and flags
explicit default PatternFly background assets mixed into Felt. Use it for
Red Hat portfolio prototypes:

```bash
python3 scripts/analyze.py --src=/path/to/prototype \
  --guideline=project-felt-adoption --json-output
```

### Supplemental non-deterministic source review

When requested, add a model-assisted review after the deterministic analyzer.
It supplements the source result and must never replace, reclassify, or silently
deduplicate deterministic findings. Review only the scoped MR files and the
applicable bundled rules' `## Rule` and `## Manual Review Checklist` sections.
Focus on semantic or contextual issues a pattern matcher cannot determine.
Do not edit prototype source.

Write the model response as JSON with this contract, then validate it before
including it in the run report:

```json
{
  "status": "completed",
  "mode": "source",
  "model": "openai/gpt-6-luna",
  "non_deterministic": true,
  "findings": [
    {
      "guideline_id": "patternfly-component-usage",
      "file": "src/path/to/file.tsx",
      "line_start": 12,
      "line_end": 14,
      "evidence": "exact source excerpt from those lines",
      "rationale": "Why the excerpt conflicts with the rule in context.",
      "suggestion": "A concrete PatternFly-aligned correction.",
      "confidence": "high"
    }
  ]
}
```

Use `findings: []` when no issues are supported by source evidence. Findings
must cite exact file/line evidence; the validator resolves title/category and
severity from the bundled corpus, rejects unknown guideline IDs and ungrounded
quotes, and downgrades uncertain/candidate findings to warnings. Save this
supplement separately from `source_mode.violations`, for example as
`consistency-source-ai.json`; do not include deterministic counts as if they
were model judgments.

Run from this directory or use absolute paths:

```bash
python3 scripts/analyze.py --src=/path/to/prototype
python3 scripts/analyze.py --src=/path/to/prototype \
  --guideline=icon-style-consistency --verbose
python3 scripts/analyze.py --src=/path/to/prototype \
  --changed --base-ref=main
python3 scripts/analyze.py --src=/path/to/prototype \
  --changed --base-ref=main --json-file=/path/to/consistency-report.json
python3 scripts/analyze.py --src=/path/to/git-worktree \
  --changed --merge-base --base-ref=main
```

Use `--changed` only when the source path is a Git worktree. The checker scopes
numbered findings to added and modified lines, preventing legacy findings in a
touched file from overwhelming an MR review. Use `--tracked-only` for MR
worktrees that contain unrelated local scratch files; `--merge-base` checks
committed changes on the topic branch rather than local worktree edits. Normal
prototype worktrees still include untracked prototype files by default.

### Start here: local ground truth

Run the committed ground-truth fixture before using the checker in another
skill:

```bash
bash tests/run-tests.sh
python3 scripts/analyze.py \
  --src=tests/fixtures/ground-truth \
  --guideline=no-custom-css \
  --report-dir=tmp/ground-truth-report
```

The fixture intentionally contains four custom-CSS violations. A nonzero
analyzer exit means violations were found; the test suite verifies they are the
expected findings.

## Visual checks

Use `scripts/visual_analyze.py` to capture DOM evidence from a running
prototype, and capture screenshots for the actual visual judgment. When a
non-deterministic visual review is requested, use the selected vision-capable
model to inspect a bounded set of representative screenshots against relevant
bundled rules. Keep visual findings separate from the deterministic source
report and validate them with `scripts/validate_ai_review.py --mode visual`.
Visual findings supplement source checks; they do not replace them.

URL-based visual extraction also reports deterministic Project Felt DOM checks
for the root theme class, pill-shaped visible controls, and a Red Hat red
primary-control background. Use `--require-project-felt` to fail the command if
these checks fail. Screenshot-only extraction has no DOM measurements and
reports the checks as unavailable.

Use this JSON contract for the visual model response. `screenshot` and each
`seen_on` value must exactly match a screenshot path supplied to the validator:

```json
{
  "status": "completed",
  "mode": "visual",
  "model": "openai/gpt-6-luna",
  "non_deterministic": true,
  "findings": [
    {
      "guideline_id": "icon-style-consistency",
      "screenshot": "screenshots/primary.png",
      "seen_on": ["screenshots/primary.png"],
      "rationale": "The repeated action uses inconsistent icon styles.",
      "suggestion": "Use one PatternFly icon style for this action.",
      "confidence": "high"
    }
  ]
}
```

Validate and trace a review from within the active consistency session:

```bash
python3 scripts/validate_ai_review.py \
  --mode=source --input=<raw-source-review.json> \
  --output=<consistency-source-ai.json> --source-root=<prototype-worktree> \
  --model=openai/gpt-6-luna --ticket=<JIRA_KEY> \
  --prototype-url=<live-url> --trace-phase

python3 scripts/validate_ai_review.py \
  --mode=visual --input=<raw-visual-review.json> \
  --output=<consistency-visual-ai.json> --source-root=<prototype-worktree> \
  --model=openai/gpt-6-luna --ticket=<JIRA_KEY> \
  --prototype-url=<live-url> --screenshot=screenshots/primary.png --trace-phase
```

## Outputs

Direct runs write Markdown and HTML reports to `reports/` by default. Evaluation
callers write artifacts in the consumer project, normally:

```text
.artifacts/{ID}/eval/consistency-report.json
```

The evaluator may also project that same source result into a schema-validated
five-file canonical shadow bundle. The analyzer still runs once, and the legacy
report remains authoritative until the migration promotes canonical output.

Do not write evaluation artifacts into this installed skill directory.

## Guidelines

Guidelines live in `guidelines/` and use frontmatter with `id`, `title`,
`category`, `automatable`, `checkpoints`, and `severity`. Set
`automation_result: candidate` when a command only finds code requiring human
judgment; these results stay low-confidence `FLAGGED` warnings. Add or revise
rules there first; keep project-specific rationale and historical decisions in
the consumer project's `.design/product/design-guidelines/consistency/` directory.
Structure and precedence: [references/project-context.md](references/project-context.md).

## Tests

Run the committed analyzer fixtures:

```bash
bash tests/run-tests.sh
```

Editable local experiments live in the ignored `tmp/consistency-checker-lab/`
directory at the repository root. They are not part of the published skill.
