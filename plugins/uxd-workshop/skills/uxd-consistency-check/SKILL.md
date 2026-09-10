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

Run from this directory or use absolute paths:

```bash
python3 scripts/analyze.py --src=/path/to/prototype
python3 scripts/analyze.py --src=/path/to/prototype \
  --guideline=icon-style-consistency --verbose
python3 scripts/analyze.py --src=/path/to/prototype \
  --changed --base-ref=main
python3 scripts/analyze.py --src=/path/to/prototype \
  --changed --base-ref=main --json-file=/path/to/consistency-report.json
```

Use `--changed` only when the source path is a Git worktree. The checker scopes
numbered findings to added and modified lines, preventing legacy findings in a
touched file from overwhelming an MR review.

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

Use `scripts/visual_analyze.py` when a visual pass has screenshots or a running
prototype. Visual findings supplement source checks; they do not replace them.

## Outputs

Direct runs write Markdown and HTML reports to `reports/` by default. Evaluation
callers write artifacts in the consumer project, normally:

```text
.artifacts/{ID}/eval/consistency-report.json
```

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
