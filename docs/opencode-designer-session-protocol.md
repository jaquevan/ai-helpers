# OpenCode Designer Session Protocol (Langfuse observability)

Internal. For UXD designers running consented OpenCode sessions against the
`uxd-prototype-evaluate`, `uxd-prototype-create`, and `uxd-consistency-check`
skills with Langfuse tracing enabled by `trace-in-langfuse`.

This flow is for internal technical evaluation only. The launcher displays a
data notice and requires the user to type `TRACE` before starting OpenCode.
The plugin captures full raw session content: user and assistant text,
provider-exposed reasoning, tool arguments, and tool outputs (which may include
file contents). Do not use it with HR, customer, personal, or confidential
data. The Python evaluator's sanitized artifact policy does not sanitize these
separate OpenCode session events. Trace consent does not approve paid evaluator
phases.

Goal: a full opted-in designer session is **identifiable, timed, and
cost-tracked** in Langfuse. Ordinary sessions remain unexported.

## Primary vs. secondary observability unit

- **PRIMARY (this protocol):** a full consented UX designer session in OpenCode.
  Everything the designer does in the conversation — user turns, assistant
  generations, tool calls, tool failures, retries, tokens, cost — is traced by
   the local launcher-only plugin automatically. Creator and consistency runs
   do not invoke a paid pipeline.
- **EVALUATOR PIPELINE:** the existing Python direct-API
  pipeline (`scripts/langfuse-trace-pipeline.py` and the per-phase bounded
  runners) remains for isolated phase benchmarks and cost-regression
  experiments. In a consented evaluator run it is attached below the invoking
  evaluator tool span.
  It runs once and retains its existing estimate, reservation, and cap gates.

## How tracing works

Credentials live in owner-only, per-component files under
`~/.config/opencode/langfuse/`. The launcher injects a component's credentials
only into its fresh OpenCode process and loads the local plugin overlay.

Verified behaviors of the installed plugin:

- **One trace per consented run.** The plugin creates one root for the fresh
  OpenCode session and closes it at `session.idle`. User turns, generations,
  exposed reasoning, tool I/O, and the direct evaluator pipeline are children
  of that trace.
- Root metadata includes:
  - `component` and `run_id` — the component and launcher-generated run id.
  - `consent`, `trace_scope`, and `telemetry` — the typed consent and full-raw
    capture scope.
  - `evaluator_paid_approval` — whether the evaluator launcher invocation
    carried the separate `--approve-estimate` flag.
- `user_id` comes from `LANGFUSE_USER_ID` (defaulting to `anonymous`) and
  `environment` from `LANGFUSE_ENVIRONMENT` (defaulting to
  `development`). OpenCode `session.id` is attached to tool spans. Use the
  root's component and run id as the reliable run identity.
- There is no separate `invocation` tag. OpenCode observations use the
  `opencode-langfuse-local-fork` instrumentation scope; evaluator pipeline
  observations use the Python Langfuse tracer and attach below the invoking
  tool span.
- Observation types the plugin emits (verified names):
  - `opencode.turn` (agent root, one per user turn) — carries the user message
    as its **input**.
  - `opencode.message.user` (event) — the user message, one per turn.
  - `opencode.generation` (generation) — one per assistant model call.
  - `opencode.message.text` and `opencode.message.reasoning` events — content
    emitted by OpenCode when those message parts are available.
  - tool spans (named after the tool, e.g. `bash`, `edit`, `webfetch`) — one per
    tool call, with the tool args as input and the result as output.

The local plugin does not currently create dedicated retry, compaction, or
failed-generation observations, and it does not explicitly set error status on
tool spans. Do not treat the presence of those observations or error markers as
guaranteed.

### What is captured on each `opencode.generation` (verified via the v4 API)

| Field | Source | Notes |
|---|---|---|
| Model name | `model` | e.g. `Qwen3.8-27B`, `gpt-6-sol` |
| Provider | `metadata` | OpenCode provider and model identifiers, plus billing source and `model_invoked` |
| Token usage | `usageDetails` | `input`, `output`, `reasoning`, `cache_read`, `cache_write`, `total` — from the provider-reported step.ended tokens |
| Per-call cost | `costDetails.total`, `inputCost`/`outputCost`/`totalCost` | Computed by Opencode from its **price card**. See cost limitation below. |
| Generation duration | `latency` (ms), `startTime`/`endTime` | Wall-clock per model call |
| Time to first token | `timeToFirstToken` | **Currently `null`** in this install — Opencode does not surface TTFT to the plugin here. |
| Input / output | turn input, message events, generation output | User text is on the turn; available assistant text/reasoning is emitted as message events. Generation output contains message ID and finish metadata. |
| Reasoning | `usageDetails.reasoning` (token count) + reasoning text when present | See reasoning limitation below. |

### What is captured on tool spans (verified)

Tool name, args (input), result title + output, and span timing. The current
local plugin does not set a dedicated failure status or emit a separate
`tool_failures` counter; tool errors may only be visible in the captured output.

## The first-message header (required)

The launcher starts a fresh OpenCode session and prepends this header to the
skill invocation. Do not start a traced run mid-conversation or use
`--continue`; the launcher does not accept an existing session. The header
makes the trace searchable and identifiable:

```
[UXD-SESSION]
component=<creator|evaluator|consistency>
run_kind=<manual-smoke|manual-designer-test|manual-regression>
ticket=<JIRA_KEY>
workspace=<absolute workspace path>
prototype_url=<URL|none>
scenario=<free-text purpose>
```

Field rules:
- `component` — one of `creator`, `evaluator`, `consistency`.
- `run_kind` — one of `manual-smoke`, `manual-designer-test`, `manual-regression`.
- `ticket` — the Jira key (e.g. `RHAISTRAT-1745`), or `none`.
- `workspace` — absolute path to the working directory (e.g.
  `/Users/ejaquez/Desktop/rhoai`).
- `prototype_url` — the served prototype URL, or `none`.
- `scenario` — one line of free text describing the purpose.

This header is included in the first traced turn, so it is searchable in
Langfuse and acts as the human-readable identity for the session. The stable
machine identity is the trace root's component and launcher-generated `run_id`.

## Naming / search convention (stable)

The launcher-generated trace root is named `evaluation/<run_id>` for evaluator
runs and `<component>/<run_id>` for creator and consistency runs. Root metadata
also records `component` and `run_id`. The session header identifies the
ticket, run kind, workspace, URL, and scenario in the first turn.

Finding a session in Langfuse v4 (this deployment is v4 `events_only`):

- **By trace name:** search for the component prefix and launcher-generated
  run id, such as `evaluation/evaluator-20260925-120000-abcdef`.
- **By metadata:** filter on root metadata `component` and `run_id`.
- **By session id:** tool spans carry the OpenCode `session.id`; Langfuse may
  expose this as `session_id`. Use it as a convenience when present, while the
  root name and `run_id` remain the reliable run identity.

Open the single trace root for that launcher invocation to see its turns,
generations, tool spans, and evaluator pipeline children.

## What is captured and what is not

Captured automatically (no action needed):
- Every user turn and every assistant generation, in order.
- Every tool call with its args and result, plus per-tool elapsed time.
- Model-level retries and failed steps.
- Per-generation model, provider, agent, mode, finish, and token usage.
- Per-generation cost (subject to the price-card limitation below).
- Provider-exposed reasoning (token count, and reasoning text when the provider
  sends it).

Not captured / must be added by hand:
- **Hidden or encrypted chain-of-thought.** OpenAI (and some other providers)
  may return reasoning that is encrypted, redacted, or withheld. The plugin
  only records what the provider actually emits as a reasoning part. When the
  provider withholds it, there is no reasoning text to capture. Do not claim
  private CoT is recorded.
- **A per-session total as a single field.** Totals are sums across the
  session's per-turn traces (see interpretation below).
- **A decision log.** The plugin records *what* happened, not *why* you made a
  design decision. Add a concise decision log in the final message of the
  session (the commands below require this) so it is captured as the last
  assistant generation.
- **Artifact content.** Local artifacts (reports, screenshots, exported HTML)
  are written to the workspace and are **not** uploaded to Langfuse. Record
  their paths in the session's final message / scorecard.

## Reasoning limitation (state this honestly)

The plugin captures **provider-exposed** reasoning only:
- The `reasoning` **token count** is recorded whenever the provider reports it
  in its usage block.
- Reasoning **text** is recorded only when the provider emits a reasoning
  message part in clear text.
- OpenAI may return reasoning as an encrypted or withheld blob; in that case
  neither the text nor an interpretation is available, and the token count may
  still be present.

Because of this, the reliable "why" for a designer session comes from the
assistant-visible rationale in the generation output, the tool trace, and the
explicit decision log written at the end of the session — not from hidden CoT.

## Interpreting timing and cost

- **Per-generation time:** the `latency` on each `opencode.generation`.
- **Per-tool time:** the `latency` on each tool span. Sum tool latencies for
  total tool time.
- **Total session time:** the span from the root's start to end (equivalently,
  the wall-clock time of the OpenCode session).
- **Total session tokens:** sum `usageDetails` (`input`, `output`, `reasoning`,
  `cache_read`, `cache_write`) over every `opencode.generation` in the trace.
  (Input tokens are re-sent per turn, so input totals are large by design.)
- **Total session cost:** sum `costDetails.total` over every
  `opencode.generation` in the trace.

### Cost limitation (important)

Per-call cost is computed by Opencode from its **price card**, not from a
provider invoice. Consequences:
- For the **LiteMaaS / Qwen** custom provider, no price is configured, so
  `costDetails.total` is **0** — cost is effectively **unavailable** for those
  calls (they are not free, just unpriced in Opencode). Treat Qwen cost as
  `unavailable`, not `$0`.
- The **Qwen quality judge** is a separate Langfuse-side **LLM-as-a-Judge**, not
  a traced pipeline model. Its cost is read out-of-band from the Scores API and
  is **not** part of a session's traced `total_cost` — report it as
  `unavailable (judge-only, not traced)`. Do not fold a Qwen judge observation
  into the generation `costDetails` sum above.
- For price-carded models (e.g. OpenAI models), cost is a **price-card
  estimate**, not an invoice figure. Reconcile against provider billing
  separately before quoting an "invoice" number.
- `inputPrice`/`outputPrice` are `null` in this install; only the summed
  `costDetails.total` is populated when a price exists.
- `timeToFirstToken` is `null` — do not report TTFT.

## Session scorecard template

Fill this in at the end of each session (post it as the final message so it is
traced, and keep a copy in the workspace).

```
[UXD-SCORECARD]
ticket:            <JIRA_KEY>
component:         <creator|evaluator|consistency>
run_kind:          <manual-smoke|manual-designer-test|manual-regression>
langfuse_run_id:   <component-run-id from the trace root>
trace_url:         <trace root URL>
model:             <e.g. Qwen3.8-27B>
total_time:        <mm:ss wall clock for the session>
total_cost:        <sum of generation costDetails, or "unavailable (LiteMaaS)">; Qwen judge cost is separate and out-of-band — not in this total
assistant_turns:   <count of opencode.turn observations>
tool_calls:        <count of tool spans>
tool_failures:     <inspect tool outputs; no explicit error status is guaranteed>
total_tokens:      <input/output/reasoning summed>
report_artifact:   <absolute path to report / exported artifact, or none>
outcome:           <one line: what the session produced / decided>
friction_notes:    <1–3 lines: what slowed you down, what was confusing>
decision_log:      <concise: decisions made + why>
```

## First evaluator test

A fixed, repeatable smoke test to confirm the consented loop (launcher → traced
evaluation → pipeline → artifacts → scorecard) before doing real work.

- **Ticket:** RHAISTRAT-1745
- **Workspace:** `/Users/ejaquez/Desktop/rhoai`
- **URL:** `http://127.0.0.1:8080`
- **Component:** `evaluator`
- **Scenario:** evaluate existing prototype as a UX designer

Run the launcher from the repository. It first verifies the component project,
then displays the full-session data notice and asks you to type `TRACE`. The
first evaluator invocation stages Jira context, runs estimate-only, displays
the estimate, and stops before paid evaluator phases. The OpenCode planning
turn may still cost money through the configured OpenCode model.

Command:

```
bash scripts/trace-in-langfuse evaluator --ticket RHAISTRAT-1745 --workspace /Users/ejaquez/Desktop/rhoai --prototype-url http://127.0.0.1:8080 --scenario "evaluate existing prototype as a UX designer"
```

Do not use `--continue` or a session ID. The launcher refuses to attach tracing
to an existing conversation.

Review the estimate. If you approve the paid evaluator phases, launch a second
fresh traced session with the same ticket, workspace, URL, and scenario, adding
`--approve-estimate`:

```
bash scripts/trace-in-langfuse evaluator --ticket RHAISTRAT-1745 --workspace /Users/ejaquez/Desktop/rhoai --prototype-url http://127.0.0.1:8080 --scenario "evaluate existing prototype as a UX designer" --approve-estimate
```

This flag records explicit approval and tells the evaluator skill to reuse the
staged Jira context and run the bounded paid pipeline once. It does not replace
the pipeline's preflight, reservation, or cap checks. If the run inputs change,
repeat estimate-only and review the new estimate first.

After the session, confirm one `evaluation/<run_id>` root contains the session,
evaluator tool span, pipeline child, phase observations, final status, tokens,
duration, and separate OpenCode/direct-pipeline cost fields.

## Security

- Langfuse/OpenAI keys live only in owner-only per-component files under
  `~/.config/opencode/langfuse/` or launcher-injected environment variables. Never
  print, commit, copy, or move them into repo files, docs, commands, tests, or
  chat output.
- All local `.env*` files remain gitignored.
