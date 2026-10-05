# eval-consistency

Use the sibling generic `uxd-consistency-check` skill. The checker tools ship in
the plugin; product guidelines come from the consumer workspace and explicit
`--guidelines` supplements, not a bundled PatternFly/RHOAI corpus.

## Resolve the checker

```bash
RESOLUTION="$(bash "${EVALUATOR_SKILL_DIR}/scripts/bootstrap-consistency-checker.sh")"
CONSISTENCY_DIR="$(printf '%s\n' "$RESOLUTION" | sed -n 's/^CONSISTENCY_DIR=//p')"
```

An absent checker is an incomplete install. Missing product guidelines is a
different state and must not prevent internal peer review.

## Source mode (before classification)

Require a prototype workspace for source checks and peer comparisons. Use the
actual source checkout in hybrid mode, while writing outputs to the pinned
consumer `ARTIFACTS_DIR` rather than the nested source checkout.

```bash
python3 "${EVALUATOR_SKILL_DIR}/scripts/run_evaluator.py" \
  --key "$KEY" --workspace "$SOURCE_DIR" \
  --jira-context "$JIRA_CONTEXT_FILE" --artifacts-dir "$ARTIFACTS_DIR" \
  "${GUIDELINE_ARGS[@]}"
```

`GUIDELINE_ARGS` contains the user-supplied repeatable `--guidelines` values.
Include `--trust-guideline-commands` only after approving local rule commands.
Without it, the source report records the corpus and marks automated guideline
compliance as not evaluated; the assistant still reviews the Markdown policies.
Do not re-run source mode inside the model phase or invent source counts.

Read the sibling `SKILL.md` and always perform its internal peer-comparison
procedure against the edited source scope. Validate the grounded output with
`validate_ai_review.py --workspace "$SOURCE_DIR" --mode internal` and write
`internal-consistency-review.json` to `ARTIFACTS_DIR`. Peer-only differences
remain FLAGGED human-review candidates; do not add them to the automatic fix queue.

For supplied policies, perform the sibling guideline-review procedure, keep its
validated source findings in `consistency-source-ai.json`, and record every
source. With no policies, label guideline compliance **Not evaluated**. With no
peers, label internal review **Insufficient comparable examples**. Do not borrow
RHOAI or any other product's rules without an explicit source selection.

## Visual mode (after journey capture)

Review supplied journey screenshots/DOM against the selected guidelines and
comparable workspace screens. Use `visual_analyze.py` when neutral DOM/style
measurements are useful; it does not enforce a product theme.

Read only relevant source rules and representative evidence. Validate guideline
findings with `validate_ai_review.py --mode visual`, supplying the same workspace,
guideline sources, actual model, and inspected screenshot paths. Write
`consistency-visual-ai.json`. Preserve source results rather than overwriting them.

Only merge validated, guideline-backed visual findings into the report's
`visual_mode.findings`, and set `visual_mode.ran` only when actual visual evidence
was inspected. Missing screenshots means visual compliance is not evaluated,
not a pass. A source-only or screenshot-only input cannot prove unavailable DOM facts.

## Report and handoff

Keep separate results for executed automated checks, model-reviewed guideline
compliance, and internal consistency. The report reads the validated AI review
files alongside `consistency-report.json`. Do not promote peer conventions to
policy violations, automatically fix peer-only candidates, or claim that zero
automated findings means all design rules passed.

For a remote-only evaluation without source access, explicitly record that
source peer review was not evaluated. Browser evidence can still support the
visual review within its documented limits.
