# Langfuse consistency optimization notes

## 2026-09-10 — RHOAIUX-3239 iteration

Priority trace: `eval-iterate/RHOAIUX-3239`, trace id
`371b21836399887abce3f96cac94ba47`.

### Observed

- Local Langfuse contained one trace with 26 observations representing roughly
  seven logical phases.
- Phase boundary events and final summary observations duplicated several
  phases. `uxd-consistency-check/end` appeared three times.
- Phase events reported `invocation: cursor` during a Codex run because the
  helper hardcoded the host.
- The final root span measured about 2 ms because it was created after pipeline
  completion. The trace timeline spans the real work, but root-span latency is
  not a valid pipeline-duration metric.
- The Codex subscription run exposed no provider token or cost usage, so it
  cannot prove visual-consistency cost.
- The shared remote Langfuse health endpoint returned HTTP 503. Findings above
  come from the local instance.

### Improved in this branch

- Invocation is detected from `AI_HELPERS_PLATFORM` or host session variables.
- `eval-consistency-source` and `uxd-consistency-check` are explicitly zero-LLM
  phases and receive no allocated model cost.
- Changed-file category detection moved into `analyze.py`; the evaluator no
  longer spends model context pre-reading the full guideline corpus.
- RHOAIUX-3239 source-check runtime changed from 8.84 seconds / 23 guidelines
  to 6.81 seconds / 18 applicable guidelines: 23% faster on this fixture.
- Visual checks default to at most three deduplicated representative screens
  and record screenshots, guideline count, and input bytes.
- `visual_analyze.py --dom-only` avoids generating a duplicate screenshot when
  the journey already captured one.
- Consistency JSON now passes a stricter 14-check contract covering source,
  version, field enums/types, review-candidate safety, and summary group math.
- Standard evaluator orchestration no longer emits live start/end events in
  addition to final phase observations. New pipeline traces contain one row per
  logical phase; the optional boundary helper remains for standalone runs.

Verification traces:

- Pre-filter artifact: `24ed46989d913f05808c6b91c0a30e39`
- Optimized artifact: `1c9d7e87d53f0b30f2a8e9c04993bb28`
- OpenAI authentication failure: `16496146ce37a384d61ec73bf2744c9b`
- Step 8 paid harness audit: `b239b140ca5cec33e23270423cea090a`

Each contains exactly three observations: root, `eval-consistency-source`, and
`uxd-consistency-check`. The original trace contains 26 observations.

The approved Step 8 direct-API harness audit authenticated and ran for 91.8
seconds, but it stopped before consistency evaluation because Jira was not
available inside the one-tool API agent. It used 273,023 input tokens (240,410
cached), 2,248 output tokens, and an estimated $0.573022. Across 15 turns it
searched global directories, loaded a stale Claude plugin cache, and attempted
credential discovery. No credential value entered the stored trace, but the
behavior was unsafe and wasteful.

Step 9 hardens the benchmark path:

- The host fetches Jira through Atlassian MCP before model execution and stages
  validated JSON inside `tmp/benchmarks/<KEY>/`.
- `--preflight-only` validates Jira, workspace, benchmark, and exact local skill
  paths without checking an API key or invoking a provider.
- The prompt pins the evaluator skill containing the runner. Global Claude and
  Cursor plugin caches are forbidden.
- The shell tool receives no OpenAI, Langfuse, or Atlassian secrets. Keychain,
  credential-file, environment-dump, home-directory, parent-traversal, and
  outside-root commands are rejected.
- Filesystem scope is the prototype workspace, exact local evaluator skill, and
  gitignored benchmark directory. Tool output is capped at 8,000 characters;
  model execution is capped at 12 turns.
- Langfuse opens the root span and generation before execution, records redacted
  input/output plus completed/blocked/failed status, then synchronously flushes
  and shuts down after the real duration is measured.

Deterministic telemetry verification trace:
`b5a1df8281595958f30f162ce6b58b86`. The local Langfuse UI shows 0.20 seconds
for both root and generation, zero cost, populated input/output, `completed`
status, and `duration_ms: 200`. No model or provider API was invoked.

## 2026-09-10 — Step 10 controlled benchmark

Trace: `1de6d33eb2f9c0ce4a0598da0a60d3d0`.

The MCP preflight and local-path guard passed. The model stayed inside the local
AI Helpers skill and benchmark roots; it did not inspect a global plugin cache,
home directory, credential file, or Keychain. Langfuse correctly records the
run as `ERROR`, with populated input/output and 39.27-second root/generation
latency.

The run reached the hard 12-turn cap while repeatedly reading skill procedures
and searching for an executable evaluator entrypoint. It never began source or
visual consistency evaluation and created no evaluation artifacts. This exposes
an architectural issue: a prose skill is not a deterministic pipeline runner.

Recovered from the local response log:

| Metric | Step 8 | Step 10 | Change |
|---|---:|---:|---:|
| Runtime | 91.8s | 39.3s | -57.2% |
| Input tokens | 273,023 | 107,594 | -60.6% |
| Cached input tokens | 240,410 | 89,070 | -63.0% |
| Output tokens | 2,248 | 1,904 | -15.3% |
| Turns | 15 | 12 | -20.0% |
| Estimated cost | $0.573022 | $0.238036 | -58.5% |

The trace currently shows zero usage/cost because `run_agent` raises when the
turn cap is reached and discards its accumulated result. A subsequent phase
must return a structured partial result, then replace model-led orchestration
with a deterministic evaluator entrypoint before another paid run.

## 2026-09-10 — Step 11 deterministic evaluator

`run_evaluator.py` now executes the local sibling checker directly, writes the
source report, and requires all 14 schema/contract checks to pass before any
model can run. The direct runner consumes that report and starts with the next
phase instead of asking a model to discover the evaluator implementation.

The RHOAIUX-3239 prototype completed deterministic source evaluation in 7.42
seconds with no provider request: 18 applicable guidelines, 5 warning groups,
13 passes, and 16 low-confidence review candidates. All paths and line numbers
were verified after fixing a grep-context parser defect exposed by JSX object
syntax. Checker tests now include that regression.

When the direct agent reaches its turn cap, it now returns a failed structured
result with accumulated token usage and estimated cost instead of throwing the
measurements away. This corrects the zero-usage failure seen in Step 10.

### Still to optimize

1. Replace the remaining full-skill model loop with explicit phase-bound calls
   that receive only the Jira fields and artifacts needed for that phase.
2. Run another paid benchmark only after deterministic tests prove the bounded
   phase orchestration cannot return to skill discovery.
3. Restore shared Langfuse health before comparing team-wide traces.

Do not claim visual cost is optimal until item 1 has measured provider usage.

## 2026-09-10 — Step 12 bounded phase orchestration

The direct OpenAI no-fix path no longer sends one agent through the complete
skill. It runs six explicit phases—extract, classify, journey, visual
consistency, usability, and report—with one inlined phase procedure and only
declared artifact paths. Each phase has a two-turn limit and the complete run
retains the 12-turn ceiling.

The controller checks required inputs before each provider call and runs the
phase's existing validators before advancing. Exact token, cache, duration, and
cost measurements are retained per phase for Langfuse instead of estimating a
split from total runtime. Human-readable phase packets and raw provider
responses are stored only in `tmp/benchmarks/<KEY>/`.

Deterministic simulation proves all six phases can be dispatched under the
shared ceiling and that execution stops before the next phase when the budget
is exhausted. No paid provider request was made for this step.

## 2026-09-10 — Step 13 bounded OpenAI benchmark

Trace: `4ec53f5bd0fe44ec85f2f084a27e7681`.

The source checker completed first with no model: 18 applicable guidelines,
5 warning groups, 13 passes, 16 low-confidence review candidates, and no custom
CSS findings. Its 14-check contract remained valid. Visual consistency did not
run because the first model phase failed.

The isolated `eval-extract` worker used `gpt-5.6-luna`, reached its two-turn
limit, and stopped before writing `extract-state.json`. It still searched the
workspace and local AI Helpers tree for an executable extractor despite having
the phase procedure inlined. The controller correctly blocked every downstream
phase and retained the measurements: 7.7 model seconds, 12,707 input tokens,
4,746 cached input tokens, 309 output tokens, 57 reasoning tokens, and
$0.0029122 estimated cost. End-to-end command time including the deterministic
checker was 15.2 seconds.

The earlier Anthropic-oriented RHOAIUX-3239 trace
`371b21836399887abce3f96cac94ba47` contains 26 observations spanning 17m24s,
including 14 consistency events and three duplicate checker-end events. It
records no model identity, provider usage, or cost, so a valid token/cost
comparison is impossible. Its configured Sonnet/Opus routing is intent, not
proof of the models actually invoked.

This benchmark shows phase isolation limits financial exposure, but inlining
prose does not make extraction executable. Before another paid run, Jira
extraction must become a deterministic local transformation of the staged MCP
JSON. Per-phase Langfuse observations also need live start/end timing; the
current child generation is emitted after completion and appears as zero
duration even though its metadata contains the measured 7.7 seconds.

## 2026-09-10 — Step 14 deterministic Jira extraction

`extract_jira_context.py` now transforms the validated Atlassian MCP snapshot
into `extract-state.json` and `mr-delta.json` without a model or network call.
For RHOAIUX-3239 it selected five acceptance criteria from linked Story
RHOAIUX-3240, matched the junior/senior ML engineer personas, created one
problem-based usability task, and classified two changed MR source files in 0.11
seconds. The model phase plan is reduced from six phases to five and reserves
the shared turn budget for work requiring judgment or browser interaction.

Langfuse model-phase observations now open before each provider call and close
after artifact validation. This gives them real timeline duration plus exact
model, token, cache, cost, turn, and validator metadata. Deterministic source
consistency and Jira extraction remain zero-cost events with measured duration.
No paid provider request was made for this step.

## 2026-09-10 — Step 15 portable deterministic classification and reporting

`run-classification.js` now assigns T1–T4 tiers and initializes the strict
10-column evaluation CSV without a model. `run-report.js` validates all input
schemas, renders the bundled HTML template, and validates the rendered output
without a model. Both scripts resolve helpers from their own skill directory
and pass from an unrelated working directory.

The RHOAIUX-3239 benchmark classifies all five Jira criteria as T4 because they
describe design exploration, feedback, engineering review, Figma delivery, and
competitive analysis rather than observable prototype behavior. This avoids
manufactured PASS/FAIL verdicts and gives the designer explicit review actions.

The direct OpenAI plan is reduced from five model phases and ten possible turns
to three model phases and six possible turns: journey, visual consistency, and
usability. Source consistency, Jira extraction, classification, schema checks,
and report rendering are local zero-token phases with individual Langfuse phase
metadata. No paid provider request was made for this step.

## 2026-09-10 — Step 16 three-phase OpenAI benchmark

Trace: `3fe342b2e0c6930a3a88e9179681b296`.

The deterministic gates completed first and remained valid: consistency 14/14
and classification 10/10. The first model phase, `eval-journey`, then consumed
two turns but did not write `journey-log.json`. Its strict output gate stopped
the pipeline before visual consistency, usability, or local report rendering.
The model copied Kueue-oriented example terms from the 503-line general journey
procedure and searched unrelated source instead of using the extracted
RHOAIUX-3239 criteria. This confirms the general interactive procedure is too
large and example-heavy for a two-turn direct-API worker.

Provider measurements were retained: 14,444 input tokens, of which 6,846 were
cache reads and 7,598 were uncached; 470 output tokens; 14,914 total tokens;
8.4 seconds model duration; and $0.034528 estimated cost. Langfuse flush
completed and the live phase shows a real 8.39-second duration with non-empty
input and output.

The trace also exposed two accounting defects. OpenAI `input_tokens` already
includes cached tokens, but the Langfuse mapping submitted that total plus a
separate cache-read count, displaying 21,290 prompt tokens. The pipeline-level
summary was also a generation carrying the same usage and cost as its child,
doubling the trace aggregate to $0.069056. The mapping now submits 7,598
uncached plus 6,846 cached tokens, and the pipeline summary is a zero-usage span.
Full redacted phase inputs/outputs now include character counts and SHA-256
fingerprints. Deterministic telemetry tests cover cache accounting, payload
completeness, real phase duration metadata, flush, and shutdown.

Do not treat this run as a successful quality comparison: it stopped at the
first model phase. Before another paid run, replace the full interactive journey
procedure with a compact direct-API contract or a structured-output phase runner
that can accept screenshots directly.

## 2026-09-10 — Step 17 structured journey implementation

`eval-journey` now uses one tool-free OpenAI Responses API request rather than a
shell-driven loop. The request uses strict `text.format.type: json_schema`
Structured Outputs, a compact journey-only procedure, and image inputs loaded
from relative paths in `prototype-evidence.json`. No marketplace or user-home
path is embedded in the implementation.

Before the request, `capture-prototype-evidence.js` captures a 1440×900 baseline
screenshot and compact visible headings/controls/body text. Screenshot paths
remain relative to the run's artifacts directory; the structured schema limits
all returned screenshot fields to those exact paths. The local writer validates
the schema again, checks AC IDs, persona data, step counts, and T1/T2 coverage,
then atomically writes `journey-log.json` and updates the acceptance-criteria
CSV. T3 remains deterministic and T4 is finalized as `FLAGGED` for human review.

Deterministic tests use a mocked Responses payload and a real local Playwright
capture. No paid provider request was made. The bounded model budget is now five
possible turns: one structured journey request plus two turns each for visual
consistency and usability.

## 2026-09-10 — Step 18 paid benchmark

Step 18 is a partial benchmark, not a successful end-to-end run. The structured
journey request completed in one call and passed API schema enforcement plus the
local journey/CSV gate. It used 6,202 input tokens, 957 output tokens, 286
reasoning tokens, 11 seconds of provider time, and an estimated $0.023888.

The shell-driven visual-consistency worker then reproduced the prior wandering
failure: five responses repeatedly inspected paths and artifacts without
running visual analysis. Its accumulated provider usage was 21,643 input tokens
(14,845 cached), 1,201 output tokens, 201 reasoning tokens, 18 seconds of model
service time, and an estimated $0.057698. `visual_mode.ran` remained false, so
usability and report rendering did not run.

Across the paid responses, Step 18 used 27,845 input tokens (14,845 cached),
2,158 output tokens, 487 reasoning tokens, 30,003 total tokens, 29 seconds of
provider service time, and an estimated $0.081586. Relative to Step 10, this is
74.1% fewer input tokens, 72.6% fewer total tokens, and 65.7% lower estimated
cost, but it is not a quality-complete comparison.

Langfuse trace `7f10936e436a630435c8c8a20d25e2b9` correctly records the structured
journey and the first two visual responses with non-empty inputs/outputs, live
11.159s and 9.251s latencies, exclusive cache accounting, and a zero-usage
pipeline summary span. Three diagnostic continuation responses were preserved
in the gitignored provider log but occurred outside that trace, so the trace is
not a complete accounting of all Step 18 usage.

The visual phase gate now requires `visual_mode.ran: true`; the previous generic
14-check consistency validator could pass a source-only report and is no longer
sufficient to advance this phase. A phase that writes fully valid outputs on its
last allowed turn may advance without spending another turn on a confirmation
message.
# Step 19 — Hybrid visual and live-persona architecture

- Visual consistency is one tool-free Responses API call with direct images and
  strict `text.format.type: json_schema` output.
- Guideline prose is reduced locally to Rule and Manual Review sections before
  model input.
- Usability remains live and interactive, but personas receive only five local
  browser functions. Filesystem, shell, search, Jira, and source are absent.
- Every browser action supplies fresh DOM and screenshot evidence; each
  persona-task must interact before its strict result is accepted.
- Validation in this step is local/mocked only; no provider rerun was made.

## 2026-09-10 — Step 20 hybrid paid benchmark

Trace: `0085ab4b4794434fa2cbc5bfab871235`.

The single approved run completed strict journey and visual-consistency phases,
then stopped during the first live persona. Journey passed its local artifact
gate in one call. Visual consistency passed all 14 report checks in one call
and reported two screenshot-grounded findings: an unapproved top-level “Home
page variations” navigation item and collapsed navigation sections using down
chevrons. The combined checker result was 23 guidelines, 1 violation group, 6
warning groups, and 16 passes.

The junior ML-engineer persona launched in a real browser, observed the rendered
Playground, clicked the MCP tab, and captured a second screenshot. Its next API
request failed because the runner combined `store: false` with
`previous_response_id`; the provider could not retrieve the unpersisted prior
response. No second paid run was attempted.

Raw provider logs show the complete paid usage: 28,961 input tokens, 1,068
output tokens, 30,029 total tokens, 468 reasoning tokens, zero cache reads, 15
seconds of provider service time, and $0.070738 estimated cost. Langfuse flushed
the trace with 26.55 seconds root latency and populated journey/visual inputs
and outputs, but records only 24,833 input tokens, 1,049 output tokens, and
$0.062254 because the failed Node wrapper did not return the first persona
request's usage to the Python controller. This is a partial benchmark, not an
end-to-end success.

Before another paid run, continue the usability conversation statelessly by
replaying response output items and tool results instead of using
`previous_response_id`, and preserve accumulated usage when any later turn
fails. Validate both changes with mocked multi-turn tests first.

## 2026-09-10 — Step 21 stateless usability recovery

The browser-only persona runner now keeps `store: false` and no longer sends
`previous_response_id`. Each continuation replays returned assistant items,
including their original `phase`, followed by local browser function results
and fresh screenshot evidence. Requests explicitly include encrypted reasoning
content for stateless replay.

If a later provider request fails, the Node runner emits its accumulated token
usage and turns as a structured failed result. The Python adapter preserves that
result for the pipeline and Langfuse instead of replacing it with zero usage.
Mocked multi-turn browser and adapter tests cover both contracts; no paid run
was made in this step.
