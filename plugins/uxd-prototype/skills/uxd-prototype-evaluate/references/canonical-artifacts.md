# Canonical evaluation artifacts

## Status

Version 1 is the primary OpenAI runtime and HTML report contract. Existing
legacy artifacts remain adapter-supported until external consumers migrate.

## Canonical v1 files

Each evaluation run uses these five authoritative JSON files in its `eval/` directory:

| File | Owns |
|---|---|
| `brief.json` | Immutable intent: criteria, tasks, personas, and scoped source context. |
| `evaluation.json` | AC verdicts, journey results, usability scores, consistency findings, and derived totals. |
| `evidence.json` | Bounded DOM facts plus portable full-page, region, and component evidence records. |
| `actions.json` | Proposed/applied fixes and explicit human handoffs. It cannot trigger publication. |
| `state.json` | Lifecycle, phase measurements, and compound cache identity. |

Schemas are in `schemas/v1/`. Run `node scripts/validate-canonical-artifacts.js <eval-dir> --json` before a canonical artifact is consumed or cached.

Source consistency can emit a pre-classification shadow bundle with
`brief.intent.stage: consistency-source`. In that stage, acceptance criteria,
tasks, personas, journeys, and usability results are intentionally empty. The
bundle records only source consistency findings, deterministic identity, and
zero-model telemetry under:

```text
.artifacts/<KEY>/eval/shadow/consistency-source/<run-id>/
```

## CSV retirement decision

`evaluation-report.csv` is retired as a canonical evaluation artifact. Its past roles—AC verdict transport, usability rows, display baseline, and publish gate—are typed data in `evaluation.json`.

Until legacy consumers move, a dedicated compatibility adapter may create a CSV projection from the five canonical documents. The adapter is one-way, temporary, and cannot import or overwrite canonical values. The default OpenAI model path neither reads nor writes CSV after deterministic classification. Anthropic-compatible execution may retain it temporarily during migration.

CSV may return later only as an explicit designer-requested export; it is not a pipeline requirement.

## Temporary legacy adapter

The adapter is disabled by default and writes only to an explicit shadow or
compatibility directory. It validates all five canonical files before writing,
refuses a destination named `eval`, and fails on existing files unless
`--replace` is used with an adapter-only directory.

```bash
node scripts/materialize-legacy-eval-artifacts.js \
  --canonical-dir <canonical-eval-directory> \
  --output-dir <separate-compatibility-directory> \
  --targets csv,summary,consistency,extract,evidence,journey,actions,state \
  --json
```

Targets materialize the current legacy CSV, summary, consistency, extract,
evidence, journey, fix/action, iteration, and YAML state shapes. The command is
local and deterministic: it reports `model_invoked: false`, performs no publish
or provider operation, and never reads legacy files back into canonical JSON.

Do not request or generate `persona-results.json` through the adapter. It is a
temporary bounded-provider transport and is merged into `evaluation.json` and
`evidence.json` before report rendering.

## Runtime order

1. Local source consistency, Jira extraction, classification, and targeted
   capture assemble and validate the canonical five.
2. An exact full-cache hit restores the validated final five and bypasses every
   model phase.
3. On a miss, bounded model phases return strict JSON; a deterministic merger
   updates all five atomically and stores the complete cache entry.
4. The HTML report reads canonical JSON directly. Compatibility projections are
   generated only for a named downstream consumer.

## Strict-output rules

- Output only schema-valid JSON; do not add unrecognized properties.
- Use stable cross-file IDs, never inferred filenames.
- Store concise visible outcomes only. `reasoning`, `thought`, `chain_of_thought`, `analysis`, `transcript`, and `think_aloud` fields are prohibited.
- Use `evaluation.consistency.findings[]` as the only canonical finding collection. Any legacy `violations` list is a derived compatibility projection.
- Keep filesystem paths relative and portable. Evidence references use IDs; screenshot paths live only in `evidence.json`.
- For component and region evidence, `crop` stores the unpadded Playwright
  element box in viewport CSS pixels. Apply `padding` and clamp to the source
  viewport; `image.width` and `image.height` must exactly match that clamped
  rectangle. Capture at device scale factor 1.
- Model phases prefer bounded crop paths. A viewport/full-page image is a
  fallback only when page-level context is required or no valid crop exists.
- `actions.json` records a proposed publish handoff with `requires_user_invocation: true`; it never performs a publish/deploy/Jira operation.
- Compatibility files are disposable projections. Never use them to repair or update canonical JSON.

## Boundaries

This contract does not replace creation/publish-owned files such as
`metadata.json`, `workspace-analysis.json`, `changeset.md`, `scenarios.json`,
`journeys.json`, or `prototype-bar.json`.

ODH test-plan integration is out of scope.
