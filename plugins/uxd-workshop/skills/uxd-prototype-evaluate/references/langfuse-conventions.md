# Langfuse conventions — uxd-prototype-evaluate

## Correlation ID

Use `eval_run_id` everywhere:

```
eval-{KEY}-{YYYYMMDD-HHMMSS}-{6hex}
```

Set in `eval-state.yaml` at pipeline start. Same value for:

- Langfuse `trace_id`
- `.artifacts/<KEY>/eval/cost-ledger.jsonl` rows

## Trace naming

| Level | Name pattern |
|-------|----------------|
| Root trace | `eval-iterate/{KEY}` |
| Phase observation | `eval-extract`, `eval-journey`, … |
| Deterministic checker | `uxd-consistency-check` |
| Artifact event | `render-report.js`, `playwright-run` |
| Generation | model name under phase span |

## Metadata (required)

| Field | Example |
|-------|---------|
| `prototype_key` | `RHAISTRAT-1492` |
| `eval_run_id` | `eval-RHAISTRAT-1492-20260902-143022-a1b2c3` |
| `run_mode` | `fresh` \| `incremental` |
| `fix_mode` | `no_fix` \| `iterate` |
| `model_tier` | `premium` \| `standard` \| `budget` \| `cursor_grok` |
| `invocation` | `api` \| `anthropic` \| `cli` \| `codex` \| `cursor` |
| `privacy_mode` | `metadata_only` |
| `depth_tier` | `quick` \| `standard` \| `deep` |

The consistency-check event stores counts only: guideline version, guideline
count, warning/violation groups, match count, and affected-file count. This lets
developers compare detector behavior and designers compare before/after review
impact without uploading prototype source or case-study text.

Tags: `team:uxd`, `pipeline:prototype-evaluator`

## Privacy rules (enforced in langfuse_trace.py)

- **userId:** SHA-256 hash of designer username (16 hex chars)
- **Jira / source:** path + byte count only
- **Screenshots:** filename + dimensions + hash; never upload image bytes
- **Report HTML:** `output_bytes` only
- **Text summaries:** max 500 chars, redact keys and emails
- **Retention:** 30 days

## Cost fields

| Field | Meaning |
|-------|---------|
| `llm_cost_usd` | Provider-reported model usage |
| `observability_cost_usd` | Langfuse infra allocation per run |

`render-report.js` always logs `llm_cost_usd: 0` with `duration_ms` and `output_bytes`.

## CLI vs Cursor

- **Direct API:** authoritative provider token usage and estimated API cost
- **Anthropic CLI/Cursor:** provider-reported or coarse phase events, depending on host support

## Phase boundary helper (orchestrator)

The optional helper emits start/end events because its calls run in separate
shell processes; it does not leave an observation open between calls.
It detects the host from `AI_HELPERS_PLATFORM` and known host session variables.
Use `--invocation` only when the host cannot be detected.

Do not call this helper during the standard evaluator pipeline. That pipeline
records timestamps in `eval-state.yaml`, then creates one observation per
logical phase in the final logger. Mixing both paths duplicates observations.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/langfuse_trace.py phase \
  --artifacts-dir "${ARTIFACTS_DIR}" --phase eval-journey --action start
# ... execute phase ...
python3 ${CLAUDE_SKILL_DIR}/scripts/langfuse_trace.py phase \
  --artifacts-dir "${ARTIFACTS_DIR}" --phase eval-journey --action end --duration-ms 45000
```

For a standalone checker run without a final pipeline logger, emit
`uxd-consistency-check` start/end events.
The completed evaluator trace also adds this event automatically whenever a
valid `consistency-report.json` exists.

## Ledger path

Per run only: `.artifacts/<KEY>/eval/cost-ledger.jsonl`

Optional index: `.artifacts/eval/cost-ledger-index.jsonl` (pointers only)

## Dashboard queries

- Cost by `metadata.phase`
- Cost by `metadata.run_mode` and `metadata.fix_mode`
- Cost by `metadata.model_tier`
- Quality scores: `ac_pass_rate`, `usability_score`, `quality_per_dollar`

Current trace findings and optimization backlog:
[langfuse-optimization-notes.md](langfuse-optimization-notes.md).

## Makefile targets

```bash
eval "$(make langfuse-env)"
make langfuse-smoke
make langfuse-pipeline KEY=RHAISTRAT-1492 URL=http://localhost:9000 \
  WORKSPACE=/path/to/prototype \
  JIRA_CONTEXT=tmp/benchmarks/RHAISTRAT-1492/jira-context.json \
  PREFLIGHT_ONLY=1 ITERATE_FLAGS="--fresh --no-fix"
```

The direct runner opens its root span and generation before model execution,
ends them afterward, then calls `flush()` and `shutdown()`. Root/generation
input, output, status, and latency therefore reflect the actual run rather than
a post-run summary span.
