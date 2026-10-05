# uxd-consistency-check

Product-independent review of guideline compliance and internal prototype
consistency. [SKILL.md](SKILL.md) contains the workflow and result contracts.

## Guideline sources

- Discover `.design/product/design-guidelines/` in the required `--workspace`.
- Supplement it with repeatable `--guidelines` local files, directories, reference
  workspaces, or raw Markdown URLs.
- Keep provenance; ask about conflicting rules rather than silently overriding them.
- Without formal guidelines, review comparable pages/components and label product
  guideline compliance **Not evaluated**.

RHOAI-specific rules belong in its prototype repository's `.design` directory;
they are no longer shipped as universal checker defaults.

## Direct tools

```bash
python3 scripts/guideline_sources.py --workspace /path/to/prototype
python3 scripts/analyze.py --workspace /path/to/prototype --json-output
python3 scripts/analyze.py --workspace /path/to/prototype \
  --guidelines /path/to/reference-workspace --trust-guideline-commands --json-output
```

The analyzer is model-free and stdlib-only. It does not perform peer review or
claim a pass when no automated checks ran. The host assistant performs the
internal/guideline reviews and validates them with `scripts/validate_ai_review.py`.
`scripts/visual_analyze.py` optionally captures neutral DOM/style/screenshot evidence;
it requires Playwright for URL capture but does not impose a product theme.

URL sources must return raw text/Markdown. Stage authenticated or non-text
sources with the configured host reader. See [project context](references/project-context.md).

## Eval and local development

The committed `eval/eval.yaml` and `eval/cases/` exercise the portable skill.
Standalone `tests/` and `eval/tests/` are optional local developer suites and are
ignored rather than distributed with the skill. Existing local copies remain
usable. Scratch prototypes and reports belong under the repository's ignored `tmp/`.
