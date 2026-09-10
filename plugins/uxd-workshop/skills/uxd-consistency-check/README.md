# uxd-consistency-check

Local PatternFly consistency checker for UX prototypes.

## Contents

- `guidelines/` — bundled markdown rules grouped by design category.
- `scripts/analyze.py` — deterministic source analyzer.
- `scripts/visual_analyze.py` — optional visual/DOM extraction helper.
- `tests/` — committed analyzer fixtures and tests.
- `VERSION` — guideline corpus version.

## Direct use

```bash
cd /path/to/ai-helpers/plugins/uxd-workshop/skills/uxd-consistency-check
python3 scripts/analyze.py --src=/path/to/prototype --verbose
```

Run one rule or category while developing a guideline:

```bash
python3 scripts/analyze.py --src=/path/to/prototype \
  --guideline=icon-style-consistency
python3 scripts/analyze.py --src=/path/to/prototype \
  --category=icons
```

## Local ground truth

Start with the committed HTML prototype before testing against create or
evaluate workflows:

```bash
bash tests/run-tests.sh
python3 scripts/analyze.py \
  --src=tests/fixtures/ground-truth \
  --guideline=no-custom-css \
  --report-dir=tmp/ground-truth-report
```

`ground-truth/src/index.html` intentionally contains inline CSS, a `<style>`
block, and a non-PatternFly stylesheet link. `ground-truth/src/custom.css`
contains authored CSS. The expected result is four warnings from
`no-custom-css`.

## Project documentation

Consumer prototype repositories should use:

```text
.design/product/design-guidelines/consistency/
```

Use that location for local context, source provenance, and design decisions.
The bundled rules here remain the portable default used by create/evaluate
workflows. See `references/project-context.md` for the directory contract,
precedence, and the current RHAI no-custom-CSS convention.

## Test development

Committed fixtures are under `tests/fixtures/`. Scratch prototypes and reports
can be edited under the ignored repository path:

```text
tmp/consistency-checker-lab/
```

Run committed tests with:

```bash
bash tests/run-tests.sh
```
