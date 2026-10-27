# Offline product-guideline checker tests

From the repository root, using an approved temporary location:

```bash
TMPDIR=/path/to/approved/scratch python3 -S -m unittest discover \
  -s plugins/uxd-prototype/skills/uxd-consistency-check/tests -v
python3 scripts/lint-evals.py plugins/uxd-prototype/skills/uxd-consistency-check/eval/eval.yaml
make validate
```

Python 3.10+ and Git suffice. `-S` disables site packages; tests require no model,
network, browser or optional dependency. Isolated temporary consumer workspaces
receive analyzer artifacts only in their `.artifacts`. Do not generate docs.

## Coverage

- No implicit baseline (including a `patternfly` applicability label), implicit
  analyzer policy discovery, or standalone peer audit. Zero selected rules gives `not_evaluated`
  and zero passes, even with visibly differing repeated controls.
- Two neutral product namespaces preserve same-ID rules without precedence;
  exact qualified filters and applicability remain enforced. Same-namespace
  identical text merges provenance; different text fails.
- Removed component/token check IDs stay unsupported on explicit import and
  namespaced 1.1 / legacy raw-ID 1.0 replay, even after deleting original files.
- Historical baseline-kind provenance cannot execute a neutral check; its
  report compatibility group remains not evaluated and empty. Internal-only
  supplemental reviews are rejected.
- Explicit generic root-class/CSS policies still produce evidence-based findings.
  CSS policy has no filename or label exemptions, including PatternFly and
  prototype-bar assets. Root-class checks require HTML targets; extension case
  is normalized. `no-custom-css` also detects uppercase HTML style syntax and
  valid unquoted `rel=stylesheet` attributes.
- Illustrative MUI fixture is local product policy, **not official/verified MUI
  guidance** or evidence of adoption. No system compliance is inferred.
- Frozen replay without originals, explicit label mismatch rejection,
  provenance/content tampering rejection, source membership checks, exact
  UTF-8 BOM/CRLF preservation, and both manifest schema versions.
- Unsupported prose remains unevaluated despite `automatable: true`. Supplemental
  source review uses qualified selected IDs and exact excerpts, stays separate,
  and leaves deterministic report bytes untouched.
- URL refusal, invalid local source/ID/metadata handling, nested/duplicate
  frontmatter rejection, and applicability checks.

`schema_assertions.py` checks only the published schema vocabulary with stdlib
assertions and fails on unknown keywords. It is **not a general JSON Schema
validator**; consumers should use Draft 2020-12 validation. Fingerprints establish
integrity, not signatures or remote authenticity.

## Test-first scope-removal evidence

The updated neutral two-source composition test first failed because the PF
label still loaded two bundled rules. Removing label-based loading made it pass.
The retired-check import/replay regression next failed for both retired IDs;
removing their dispatch/regex paths made it pass. New no-policy peer,
baseline-kind replay and internal-supplement tests then failed for the expected
old behaviors; disabling those paths made all tests pass. The existing CSS
regression was expanded to both labels and both former filename exemptions as
characterization coverage after removal, not claimed as a separate observed RED.

## Caller migration

- Always select product documents explicitly. No `--design-system` value loads
  a baseline. No generic token engine replaces the removed token audit.
- Supported checks: `no-custom-css`, `required-html-class` only. All other check
  identifiers remain frozen but unevaluated, including old component/token IDs.
- New reports/filters/supplemental findings retain `namespace:original-id`.
  Manifest schema stays `1.1.0`; legacy `1.0.0` remains readable with its weaker
  original fingerprint and raw IDs. Report/supplemental schema stays `1.0.0`.
- `guideline_consistency.baseline` and `internal_consistency` remain inert,
  `not_evaluated`, with empty arrays. Legacy baseline documents remain provenance
  and unevaluated coverage, not active policy. Supplemental `--mode internal`
  is removed; source/visual review must cite selected applicable policy.
- `pf_doc_url` remains inert historical URL metadata only.
- Replay freezes guidelines, not source bytes, scope, filters or declared system
  version. Repeat source options and verify `inputs` hashes/revisions.
- Aggregate summary counts are guideline groups, not finding arrays. Exit zero
  with no evaluated rules is not a pass.

## Indexed selection, acquisition and staging coverage

- `test_guideline_resolver.py`: conventional/overridden and legacy candidates,
  absent/ambiguous indexes, exact sidecar fields, topics-only metadata reads,
  sidecar-free product README links, malformed/missing links, and traversal/symlink
  rejection. README candidate discovery reads only the selected index; selected
  rules are not opened until proposal. Discovery never calls providers; index
  `approved` is not user consent.
- `test_guideline_selection.py`: genuine instruction/confirmation evidence binding,
  draft exceptions, unchanged local reuse, changed source/hash/authority/scope
  reapproval, stale selection rejection before acquisition planning/authorization
  after locator/authority/status/index changes, separate model authorization,
  selected README source freezing with authored or exact path-derived identity,
  exact Figma branch/node calls and
  screenshots, Docs/web full-document fallback consent, unavailable access/local
  export, exact repository SHA/file routing, immutable originals/staged bytes,
  manual-only incompatible evidence, mapped local adapters, scoped analyzer argv
  and frozen replay. Capability/event fixtures are explicitly synthetic **test
  inputs**, not real provider responses or access evidence.
- `test_selection_documentation.py`: executes the reference's literal CLI proposal
  request against a temporary consumer; validates the inert template and rejects
  adoption with unknown product identity. Executes the new strict eval judge on
  all seven selection fixtures and adversarial mutations: missing/extra/wrong-type
  fields, wrong source/branch/node identities, invented pass/PF mode, absent event
  traces, duplicate keys and forbidden tool dispatch. A partial contract cannot
  pass. These are offline judge regressions, not a host/model eval run.

## LLM evidence and fix handoffs

`test_audit_regressions.py` reproduces the W1-code/section, W2 arrow-before-style,
W3 padded-range, W4 fabricated-ref, W5 applicability, and original-CRLF-byte hash
counterexamples. Negative tests are paired with scoped positives, exact/repeated
excerpt locations, local verified blob provenance, 1.0/1.1 manifest replay,
metadata-derived applicability, explicit whole-document selection, and incomplete
JSX coverage. All fixtures are synthetic and offline; Git writes occur only in
disposable test consumers. No implementation checkout is staged or committed.

- `test_llm_review_contract.py` uses fixture responses only (no live model). It
  exercises README selection → immutable selected-rule snapshot → rechecked MR
  delta → exact guideline/code citations → frozen replay → validated report and
  non-applied fix handoff. Wrong quotes/paths/hashes, stale source/scope, missing
  rules, invalid schemas, and changed-line violations are rejected. High-impact
  or low-confidence judgments require an independent verifier; disagreement stays
  explicit and unresolved.
- `test_consistency_integration.py` verifies rendered local rule/code links and
  append/deduplication of fix proposals while preserving other phases and citation
  provenance. Suggestions remain unapplied pending separate approval.

The [selection reference](../references/selection-workflow.md) documents the exact
API/CLI seam: index → proposal → genuine approval receipt → optional authorized
acquisition → immutable staging → scoped `analyzer_args` → frozen replay/evaluator
reuse. Preserve `analysis_workspace`; narrow-root reports/manifests belong to
that root's `.artifacts`, not the entire consumer. Receipts remain consumer-root
artifacts. Remote currentness can remain unknown even when frozen-ready.

Colocated evals include older guidance-only migration checks and new **strict
structured** selection decisions: abstention despite index/PF hints, exact frame
IDs, unresolved Figma scope, genuine approval vs content assertion, unavailable
connector/local export, full-document section fallback, and product-only PF prose.
New strict cases require a complete exact JSON decision and a recorded tool-event
list with no dispatch beyond the requested checker skill load. They never imply
provider execution; actual bounded-call/receipt assertions live in runtime tests.
Local lint and fixture-judge success are not live host/model eval results. Remote
source authority, actual product adoption, model judgment quality, live browser
acceptance and full CSS/JavaScript semantics remain outside offline claims.
