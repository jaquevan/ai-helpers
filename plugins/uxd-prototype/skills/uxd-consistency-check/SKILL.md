---
name: uxd-consistency-check
version: 0.2.0
description: >-
  Review edited prototype areas against workspace or supplied design guidelines
  and comparable components/pages. Use for source and visual consistency review
  across products, including workspaces without formal guidelines.
---

# Check Prototype Consistency

Review a prototype's **guideline compliance** and **internal consistency** as
separate dimensions. The checker ships tools, not product policy. It does not
assume PatternFly, RHOAI, Project Felt, a particular color, or a localhost port.

## Inputs

`$ARGUMENTS`

- **`--workspace <local-path>` (required):** the prototype to review. Ask if absent;
  never guess a project from the skill installation directory.
- **`--guidelines <file|directory|reference-workspace|raw-Markdown-URL>`:** optional,
  repeatable supplements to the workspace's guidelines. Relative paths resolve
  from the workspace. A reference workspace contributes guidelines only; its
  source code is not the prototype under review.
- **`--base-ref <ref>` / `--changed`:** edited-area scope; use Git merge-base for
  committed topic-branch review, and include untracked prototype files for local work.
- **`--url` or screenshots:** optional visual evidence. Source alone does not
  prove rendered appearance or behavior.
- **`--output-dir`:** consumer-owned report directory; never the installed skill.

## 1. Resolve guideline sources

Always load `.design/product/design-guidelines/` from the workspace when present,
then add explicit sources. Plain Markdown is valid for model-assisted review;
automation frontmatter is optional.

```bash
python3 "${CONSISTENCY_SKILL_DIR}/scripts/guideline_sources.py" \
  --workspace "$WORKSPACE" \
  --guidelines "/path/to/additional-guidelines"
```

Omit `--guidelines` when none was supplied. Record source locations and content
fingerprints. Identical duplicate rules are deduplicated; conflicting IDs stop
resolution and require the user to reconcile them. Do not silently override a
workspace rule, use an unrelated product, or substitute a default corpus.

URLs must return actual Markdown/text. For an authenticated GitLab/Drive page,
use the configured host reader to stage documents locally with their original
source URLs, then supply that path. A login page or repository-tree HTML is not
a guideline. If an explicitly supplied source cannot be read, explain the error
and ask for a readable source rather than quietly ignoring it.

**No guidelines:** still perform internal consistency review. Offer the user the
option to provide guidelines, select a named reference workspace, or use official
guidance for their chosen design system. These are opt-in additions, not blockers
for peer review. Label guideline compliance **Not evaluated** until a source is used.

## 2. Review internal consistency (always)

Inspect the edited areas and find comparable components/pages in the same
workspace. Prefer peers with the same user intent, interaction, state, and
component role; compare labels, interaction patterns, hierarchy, spacing, states,
and accessibility treatment. Use source excerpts and supplied browser evidence.

- Cite exact target and peer file/line evidence. Prefer at least two independent
  examples when available; a single peer supports only low-confidence candidates.
- Explain why the examples are comparable. Do not compare unrelated pages just
  to produce a result, and do not use the target itself as its evidence.
- A repeated pattern is a **convention, not proof of correctness**. Identify when
  an edited area is an improvement, intentional exception, or different context.
- Differences backed only by peers are **FLAGGED review candidates**, never
  authoritative violations or automatic fixes. Explain the tradeoff to the user.
- With no suitable examples, record **Insufficient comparable examples**. Do not
  invent a convention or claim an internal-consistency pass.

Write a non-deterministic review with this contract, including `comparisons: []`
when no comparable evidence is available:

```json
{
  "status": "completed",
  "mode": "internal",
  "model": "actual-provider/model",
  "non_deterministic": true,
  "comparisons": [{
    "target": {"file": "src/NewPage.tsx", "line_start": 8, "line_end": 8, "evidence": "exact excerpt"},
    "peers": [{"file": "src/SimilarPage.tsx", "line_start": 12, "line_end": 12, "evidence": "exact peer excerpt"}],
    "rationale": "These actions serve the same user intent and interaction state.",
    "conclusion": "review_candidate"
  }],
  "findings": [{"comparison_index": 0, "rationale": "Describe the meaningful difference.", "suggestion": "Describe the options for human review."}]
}
```

Conclusions: `consistent`, `review_candidate`, or `intentional_improvement`.
Validate before reporting:

```bash
python3 "${CONSISTENCY_SKILL_DIR}/scripts/validate_ai_review.py" \
  --workspace "$WORKSPACE" --mode internal --model "$MODEL" \
  --input "$OUTPUT_DIR/internal-review.raw.json" \
  --output "$OUTPUT_DIR/internal-consistency-review.json"
```

Pass the same explicit `--guidelines` arguments to each tool when supplied.

## 3. Review supplied guideline compliance

Read the relevant rules from the resolved sources, not a bundled product corpus.
Check the edited scope against those rules and document approved exceptions.
For source findings, cite exact excerpts, file paths and line ranges. For visual
findings, cite supplied screenshot paths and relevant rule IDs. Keep source and
visual findings separate and declare the actual model used.

Use `validate_ai_review.py --mode source|visual` with the same workspace and
guideline sources. Source findings require `guideline_id`, `file`, `line_start`,
`line_end`, `evidence`, `rationale`, `suggestion`, and `confidence`. Visual findings
require `guideline_id`, `screenshot`, `rationale`, `suggestion`, and `confidence`;
pass every inspected image via `--screenshot`. Both reviews require `status`,
`mode`, `model`, `non_deterministic: true`, and a `findings` array.

Do not change the prototype during a check unless separately requested.

## 4. Optional deterministic checks

The analyzer can run local guidelines' `automatable: true` check commands.
Read those commands first and use `--trust-guideline-commands` only for approved
local checks. URL-supplied documents remain manual review inputs; downloading a
guideline does not authorize its shell commands. A rule without automation
metadata still participates in the model-assisted review.

```bash
python3 "${CONSISTENCY_SKILL_DIR}/scripts/analyze.py" \
  --workspace "$WORKSPACE" --changed --base-ref "$BASE_REF" \
  --trust-guideline-commands --json-file "$OUTPUT_DIR/consistency-report.json"
```

Omit `--changed` for a non-Git or whole-workspace review. `--src` remains an alias
for `--workspace`. The JSON separates executed checks from missing/manual rules;
zero findings is not a complete compliance or internal-consistency pass.

## Outputs

Write in the consumer project, normally `.artifacts/<KEY>/eval/`:

- `consistency-report.json`: local source-check results, guideline sources and fingerprints.
- `internal-consistency-review.json`: grounded peer comparisons and review candidates.
- `consistency-source-ai.json` / `consistency-visual-ai.json`: optional validated guideline reviews.

Summarize each dimension separately, state coverage and source provenance, and
offer concrete next actions. Missing guidelines means **Guideline compliance:
Not evaluated**; it does not stop **Internal consistency** from being reviewed.

Source ownership and precedence: [references/project-context.md](references/project-context.md).
