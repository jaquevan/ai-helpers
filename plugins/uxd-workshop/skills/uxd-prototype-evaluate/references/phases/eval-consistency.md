# eval-consistency

Runs PatternFly design consistency checks against the prototype using the local sibling `${EVALUATOR_SKILL_DIR}/../uxd-consistency-check/` skill. It never clones a checker, reads a project `.context/` checker, or requires network access.

**Resolve `CONSISTENCY_DIR` before any skip or check:**

```bash
RESOLUTION="$(bash "${EVALUATOR_SKILL_DIR}/scripts/bootstrap-consistency-checker.sh")"
printf '%s\n' "$RESOLUTION"
CONSISTENCY_DIR="$(printf '%s\n' "$RESOLUTION" | sed -n 's/^CONSISTENCY_DIR=//p')"
```

If `CONSISTENCY_DIR` is empty, stop and report an incomplete plugin install. Do not substitute a project-local copy or a network fallback.

## Execution Modes

eval-consistency runs in two modes, invoked separately by the orchestrator:

- **`--mode=source`** (Phase A setup): Runs deterministic source-code checks against changed files. The analyzer pre-filters guideline categories locally; do not spend model tokens pre-reading the corpus. Produces initial `consistency-report.json` and appends to `refinement-suggestions.json`. Called before eval-classify.
- **`--mode=visual`** (post-journey): Runs AI-powered visual checks against journey screenshots. Appends visual findings to the existing `consistency-report.json`. Called after eval-journey captures screenshots.
- **`--mode=both`** (legacy): Runs source then visual sequentially. Use when both inputs are available.

When called without `--mode`, defaults to `both` (legacy behavior).

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `${CONSISTENCY_DIR}/guidelines/` | Local bundled PatternFly guideline markdown files | Yes |
| `.artifacts/<KEY>/eval/journey-log.json` | Screenshots for visual-mode checks | For visual mode |
| `.artifacts/<KEY>/eval/screenshots/` | Journey screenshots | For visual mode |
| `--workspace` | Path to prototype source | For source mode |
| `--mode` | `source`, `visual`, or `both` | No (default: both) |

## Outputs

| File | Description |
|------|-------------|
| `.artifacts/<KEY>/eval/consistency-report.json` | Full consistency report (source + visual findings) |
| `.artifacts/<KEY>/eval/refinement-suggestions.json` | Appended with consistency suggestions |

## Procedure

### Step 1: Source Code Mode (when `--workspace` available)

**Mode gate:** Runs with `--mode=source` or `--mode=both`. Skip when `--mode=visual`.

#### 1a: Run the local analyzer

The evaluator entrypoint resolves the bundled analyzer, discovers changed and
untracked files, detects applicable categories, writes the evaluator contract,
and validates it. Do not read the full guideline corpus, repeat category
detection in agent context, or reconstruct these commands with a model.

```bash
python3 "${EVALUATOR_SKILL_DIR}/scripts/run_evaluator.py" \
  --key=<KEY> --workspace=<workspace> \
  --jira-context="${JIRA_CONTEXT_FILE}" \
  --benchmark-dir="${BENCHMARK_DIR}"
```

If validation fails, stop. Do not synthesize or repair JSON manually.

#### 1b: Consume findings

Use the JSON as written. For high-confidence findings entering the fix queue,
read only the matching guideline's `## Rule` and recommendation. Do not load
guideline prose for low-confidence review candidates.

#### 1c: Summary contract

```
total_guidelines_checked = number of guidelines where the rule was applicable to at least one file
violations = count of severity:error findings
warnings = count of severity:warning findings
passes = total_guidelines_checked - violations - warnings
```

### Step 2: Visual Mode (when screenshots exist)

**Mode gate:** Runs with `--mode=visual` or `--mode=both`. Skip when `--mode=source`.

**When `--mode=visual`:** Read the existing `consistency-report.json` (from the prior source-mode pass) and append visual findings to it. Do not overwrite source-mode results.

Cross-reference captured screenshots against PatternFly guidelines for visual violations (icon style, layout patterns, empty states, CTA placement) that source-mode cannot detect.

Visual analysis is bounded because it is the only model-assisted consistency
step:

1. Deduplicate screenshot paths by content hash.
2. Select at most three representative screens by default: primary, most
   interactive, and alternate/error state.
3. Check only visual rules not already resolved by deterministic source checks.
4. Load only each applicable guideline's `## Rule` and manual checklist.
5. Record screenshot count, applicable guideline count, and input byte count in
   `visual_mode.input_metrics` for Langfuse comparison.

**Structured extraction (preferred):** If `${CONSISTENCY_DIR}/scripts/visual_analyze.py` exists, use it to extract DOM structure with bounding boxes from key pages. This gives the LLM structured visual input instead of raw PNGs:

```bash
cd "${CONSISTENCY_DIR}"
python3 scripts/visual_analyze.py <one-ambiguous-page-url> \
  --dom-only --output-dir=<eval-artifacts>/visual-extraction
```

Use DOM extraction only when an existing screenshot is ambiguous. `--dom-only`
avoids capturing a duplicate PNG. Feed the compact JSON plus the existing
journey screenshot to the model.

**Fallback:** If visual_analyze.py is not available, analyze the raw journey screenshots directly.

1. Collect unique screenshots from `journey-log.json` (`journeys[].steps[].screenshot`).
2. Select the bounded representative set above.
3. Each finding records: `screenshot`, `journey`, `step`, `guideline_id`, `guideline_title`, `category`, `severity`, `verdict` (`VIOLATION`), `description`, `suggestion`.
4. **Deduplicate:** If the same violation appears on multiple screenshots, collapse to one finding with a `seen_on` array.

### Step 3: Write consistency-report.json

**Write behavior by mode:**
- `--mode=source`: Create a new `consistency-report.json` with `source_mode` populated and `visual_mode.ran = false`.
- `--mode=visual`: Read existing `consistency-report.json`, update `visual_mode` section, recompute `summary` to include both source + visual findings.
- `--mode=both`: Write complete file with both sections.

```json
{
  "source": "uxd-consistency-check",
  "checked_at": "<ISO timestamp>",
  "guidelines_version": "<contents of ${CONSISTENCY_DIR}/VERSION, or git short hash if .git exists>",
  "degraded": false,
  "source_mode": {
    "ran": true,
    "violations": []
  },
  "visual_mode": {
    "ran": true,
    "screenshots_checked": 3,
    "input_metrics": {
      "screenshots_considered": 12,
      "screenshots_analyzed": 3,
      "guidelines_analyzed": 4,
      "input_bytes": 123456
    },
    "findings": []
  },
  "summary": {
    "total_guidelines_checked": 8,
    "violations": 3,
    "warnings": 1,
    "passes": 4
  }
}
```

Set `"ran": false` for any mode that could not execute (no workspace = no source mode; no screenshots = no visual mode).

### Step 4: Append to refinement-suggestions.json

For each high-confidence violation, add a consistency suggestion entry.
Low-confidence `review_candidate` findings stay in the report and must not enter
the automatic fix queue.

```json
{
  "type": "consistency",
  "guideline_id": "<id>",
  "severity": "<error|warning>",
  "file": "<path>",
  "line": "<number>",
  "current": "<what's there now>",
  "fix": "<what it should be>",
  "pf_doc_url": "<url>",
  "source": "<source_mode|visual_mode>"
}
```

Only include violations from MR delta files. Consistency fixes are applied FIRST by eval-fix (deterministic, high confidence).
