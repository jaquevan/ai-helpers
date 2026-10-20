# eval-consistency

Run deterministic source checks using the installed sibling `uxd-consistency-check` skill. It supports internal consistency and configured guideline checks, not just PatternFly. Source-only operation requires no network, browser, provider, or model calls. Do not apply fixes automatically.

## Availability and degraded mode

Let `EVALUATOR_SKILL_DIR` be the resolved directory of this evaluator skill (independent of the agent tool). The sibling is `$EVALUATOR_SKILL_DIR/../uxd-consistency-check`.

1. Run `bash "$EVALUATOR_SKILL_DIR/scripts/bootstrap-consistency-checker.sh"` to check local availability. This compatibility entry point only checks for `SKILL.md` and `scripts/analyze.py`; it does not install or clone anything.
2. Both files present means the checker is available. Do not require a bundled guideline count: alternative guidelines and no-guideline/internal-only operation are valid. Follow the sibling skill's configuration and provenance rules.
3. If either file is absent and a workspace is available, retain the existing `pf-css-token-check` fallback from the separately installed `pf-design-audit` plugin. Check new + modified CSS/SCSS/TSX files in the MR delta only. Write `"source": "pf-css-token-check-fallback"`, `"degraded": true`, the actual source findings, and `visual_mode.ran = false`. This is limited PatternFly token checking, not a full consistency pass.
4. If neither checker nor fallback is available, write `{"skipped": true, "reason": "local consistency checker and pf-css-token-check plugin unavailable"}` to the normal `consistency-report.json` path. Do not invent a passing result.

A checker execution/configuration error is not absence: surface the error instead of silently substituting a passing or fallback report.

## Execution modes and inputs

These are evaluator phase modes, not options to `analyze.py`:

- **`--mode=source`** (default): deterministic source checks before eval-classify. No screenshots or model calls.
- **`--mode=visual`**: only an explicitly requested visual review after eval-journey. Preserve the prior source report; append actual visual findings. Screenshots alone do not authorize a model/provider call.
- **`--mode=both`**: explicitly requested source plus visual review, subject to the same visual authorization. Never select this mode automatically.

| Input | Description | Required |
|-------|-------------|----------|
| Installed sibling skill | `SKILL.md` and `scripts/analyze.py` | Unless degraded fallback |
| `--workspace` | Prototype source workspace | For source mode |
| Base ref | Explicit MR target/base revision | For changed-file source scope |
| `.artifacts/<KEY>/eval/mr-delta.json` | New + modified files for cross-checking MR scope and suggestions | For source mode |
| `.artifacts/<KEY>/eval/journey-log.json` and `screenshots/` | Existing journey/persona screenshots | For visual mode |
| `--mode` | `source`, `visual`, or `both` | No (default: source) |

## Step 1: Source checks

Run for source/both modes only. Resolve `WORKSPACE`, `KEY`, and `BASE_REF` from the evaluation inputs; do not guess a base or silently expand to all files. Resolve `CHECKER_DIR` to the installed sibling directory.

```bash
python3 "$CHECKER_DIR/scripts/analyze.py" \
  --workspace "$WORKSPACE" --changed --base-ref "$BASE_REF" \
  --json-file "$WORKSPACE/.artifacts/$KEY/eval/consistency-report.json"
```

`--src` is a supported alias for `--workspace`. For committed MR scope, add `--merge-base` to select the branch delta from the merge base, rather than a direct comparison to a potentially advanced target. Check the selected scope against `mr-delta.json`; do not attribute unchanged-file debt to this MR. Do not discard error output or treat a failed run as clean.

Use the checker's structured JSON directly. Do not extract or execute shell commands from guideline prose. Do not perform automatic LLM-assisted interpretation. Source provenance identifies where a guideline came from; it does not prove the rule was evaluated. Arbitrary prose without a supported deterministic check remains **unevaluated** and must not count as a pass. Missing guidelines do not prevent internal consistency checks, but internal-only findings are not evidence of guideline compliance.

The checker emits schema version `1.0.0` with the legacy source/visual/summary fields plus additive `internal_consistency` and `guideline_consistency` sections. Preserve those sections and their provenance, coverage, and unevaluated evidence when consuming or extending the report.

## Step 2: Explicit visual review

Run only for an explicitly requested visual/both mode with existing screenshots and authorization for any model-assisted review. The local source checker does not run visual analysis. Do not start a browser, capture new screenshots, or call a provider automatically. In degraded fallback mode, do not run visual checks.

1. Read the existing source report before appending. Preserve `source_mode`, `internal_consistency`, `guideline_consistency`, source provenance, and version fields.
2. Collect unique screenshot paths from `journey-log.json` (`journeys[].steps[].screenshot`), plus existing persona screenshots if relevant.
3. Review only applicable visual rules with actual evidence. Record `screenshot`, `journey`, `step`, `guideline_id`, `guideline_title`, `category`, `severity`, `verdict` (`VIOLATION`), `description`, and `suggestion` for each finding.
4. Collapse duplicate findings into one entry with a `seen_on` array. Set `screenshots_checked` to the number actually reviewed, not the number merely available.
5. If review could not execute, leave `visual_mode.ran = false`, `screenshots_checked = 0`, and `findings = []`, and record the reason. No source report plus no review means no passing claim.

## Step 3: Preserve the report contract

Write `.artifacts/<KEY>/eval/consistency-report.json` in the workspace. Source mode creates the report with `visual_mode.ran = false`. Visual mode updates only its section and the combined summary, retaining prior source results; both mode combines the actual results.

Keep these fields for existing validators, golden fixtures, and report consumers:

- `schema_version`: `"1.0.0"` for new checker reports (legacy/fallback reports remain supported).
- `source`, `degraded`, `checked_at`, `guidelines_version`: retain actual checker/fallback provenance and timestamp; do not fabricate a version.
- `source_mode`: `ran` boolean and `violations` array. Findings retain `file`, `line`, `property`, `value`, `suggestion`, plus guideline identity, severity, title, and description when supplied. Source-only mode never claims visual coverage.
- `visual_mode`: `ran` boolean, `screenshots_checked` integer, and `findings` array.
- `summary`: integers `total_guidelines_checked`, `violations`, `warnings`, `passes`.
- `internal_consistency` and `guideline_consistency`: preserve the new additive checker evidence; do not flatten these into invented compliance passes.

Summary values are **guideline-group counts**, not raw finding counts. Count each evaluated applicable guideline group once: error if it has any error finding, otherwise warning if it has any warning finding, otherwise pass only when evaluated with no findings. Across source/visual modes, deduplicate the same guideline group and use its highest severity. Unevaluated/provenance-only rules are excluded from checked/passing counts. Keep `violations + warnings + passes = total_guidelines_checked`; multiple findings for one group do not inflate the total. Preserve the checker's summary for source-only runs.

Do not generate a separate checker HTML or markdown report. The evaluator owns the **aggregate HTML** via its existing report renderer; keep the legacy report shape for that consumer.

## Step 4: Append suggestions, not fixes

Append actionable MR-delta findings to `.artifacts/<KEY>/eval/refinement-suggestions.json` without overwriting other phases' suggestions. Preserve actual evidence and deduplicate repeated findings. Use the existing suggestion shape:

```json
{
  "type": "consistency",
  "guideline_id": "<id>",
  "severity": "<error|warning>",
  "file": "<path>",
  "line": 1,
  "current": "<observed value>",
  "fix": "<suggestion>",
  "source": "<source_mode|visual_mode>"
}
```

Retain `pf_doc_url` when supplied, but do not require or invent a PatternFly URL for non-PatternFly rules. Suggestions are inputs to the separately authorized eval-fix phase; this phase does not apply them.
