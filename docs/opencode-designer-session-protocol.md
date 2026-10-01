# Designer session protocol — fork-owned Langfuse runtime

Source: `jaquevan/ai-helpers:beau-testing`. Designer setup lives in the companion `uxd-langfuse-tracing` README. Upstream MLflow instructions do not describe this runtime.

## Entry and consent

Run `bash scripts/trace-in-langfuse <component> ...` from a **plain interactive terminal**, never from an assistant's shell tool or existing OpenCode session. The launcher verifies the selected project's credentials, describes full-session text capture and scoped workspace access, and requires exact `TRACE` at its prompt. It starts a fresh OpenCode 1.18.31 process with `run --command designer-<name>` and the header as arguments. Ordinary sessions do not load the tracing overlay.

Capture includes user/assistant text, available provider-exposed reasoning and tool I/O with best-effort credential redaction. Opaque encrypted content and base64 attachments are omitted. This is not an anonymization guarantee for session text or file paths. Use only approved project content. Do not read, print or upload credential files or dump the environment.

OpenCode model usage may cost money. `TRACE` is separate from paid evaluator approval. The first evaluator invocation is estimate-only; a separately approved invocation reuses the identical inputs/context and consumes its saved estimate once. Preserve cap, reservation and settlement rules. Never automatically retry paid work.

## Header

```text
[UXD-SESSION]
component=<creator|consistency|evaluator>
run_kind=<manual-smoke|manual-designer-test|manual-regression>
ticket=<JIRA_KEY|none>
workspace=<existing absolute directory>
prototype_url=<http(s) URL|none>
scenario=<one-line task with source/design links if relevant>
```

`ticket=none` means no Jira lookup. Creator/consistency use the supplied feature brief. Evaluator `none` is restricted to manual-smoke with a served URL and explicitly stated acceptance criteria. Stage `{ "source": "synthetic-smoke", "ticket": { "key": "none", "summary": "Synthetic smoke", "description": "...", "acceptance_criteria": ["..."] } }`; these are synthetic requirements, never authenticated Jira evidence.

For a creator/consistency refinement with `--context-file ... --offline-atlassian`, read the prepared local snapshot even when the ticket is a real Jira key. The launcher/plugin disables Atlassian/Jira/Confluence-named MCP servers for this child session. Do not use shell scripts or HTTP to bypass that policy. No Jira create/edit/comment/transition/attachment/link/watch actions are permitted. Snapshot provenance and proposed UI checks are distinct; prefer newer dated scope updates over superseded description text. The snapshot hash is part of the input fingerprint and the safe receipt records its path/hash.

The default smoke workspace is `$AI_HELPERS_REPO/tmp/<name>`. External workspaces get a scoped run-only external-directory allow rule. Existing explicit denies are not overridden. Remaining tool/MCP policies still apply. If input or permission is missing, stop with `outcome_status: blocked` and a focused question in final text. A noninteractive run cannot answer a question/permission dialog.

The launcher pins OpenCode's session directory to the fork root using `run --dir <ai-helpers-root>` and sets the child `PWD` to that same path. Setting only a subprocess working directory is insufficient: OpenCode 1.18.31 can otherwise select the caller's inherited `PWD`, making the fork protocol look external even when the prototype workspace is allowed.

Keep newly written logs and scratch outputs in the workspace. `UXD_TRACE_ARTIFACT_DIR` identifies `.artifacts/<ticket>/runs/<run_id>` there; create it if needed, put server output in `server.log`, and poll the served URL with a bounded readiness wait. Do not write a log to `/tmp` and then trigger an external-directory prompt while reading it. If a task stops after edits, preserve those edits and report verification still pending. Independent follow-up checks must be labeled as outside the original trace; do not rewrite the historical outcome.

Creator and consistency are conversational sessions; do not invoke direct pipelines unless a separately authorized measured creator workflow explicitly requires one. Evaluator uses the launcher-supplied interpreter and `node scripts/trace-eval-run.mjs` exactly once. A missing trace bridge is a blocker. Estimate-only does not produce a paid evaluation report. Respect an explicitly requested `--no-report`; do not infer it from a stale skill revision.

## Identity and trace location

Read the named variables individually, e.g. `printf '%s\n' "$UXD_TRACE_RUN_ID"` and `printf '%s\n' "$UXD_TRACE_RECEIPT"`. Never use `env`/`printenv` without a specific safe name.

- `UXD_TRACE_RUN_ID`: available from the start of the session.
- Root name: `<component>/<run_id>`; historical evaluator names began `evaluation/`.
- Receipt: `tmp/traced-sessions/<run_id>/receipt.json` in the fork.
- The plugin writes the actual OTel `trace_id` and `trace_url` into that receipt at initialization, and prints the URL to stderr. A tool can read this safe receipt during the session.
- Hosted URL: `<LANGFUSE_BASE_URL>/project/<LANGFUSE_PROJECT_ID>/traces/<32-character-trace-id>`.
- User identity: stable `sha256:<16 hex>` pseudonym shared by session, pipeline and ledger. Never substitute the raw username.

The launcher run ID is not the OTel trace ID. A printed link does not prove ingestion. Receipt `export_status=flush_completed` means the SDK flush finished; a separate read-only API/UI check verifies remote ingestion.

The launcher performs a read-only post-run API check and writes `remote-verification.json`. New receipts list expected session observation IDs; the check compares these, counts and explicitly sourced OpenCode cost subtotals. `verified` is scoped to those session records, not an invoice or a full pipeline audit. `partial` means records/counts/costs disagree; `unavailable` means the check could not complete. A task may be completed while remote ingestion is partial. Do not retry model work. Recheck with `node scripts/verify-langfuse-receipt.mjs <receipt-path>`, which writes a new timestamped local verification without changing historical data.

Langfuse v4 lists observations. Use **Is Root Observation = true** to browse one entry per invocation, then open its tree. All child observations must share the parent's trace ID; the Python bridge also suppresses an extra app-root marker. Unfiltered views intentionally show many rows. User/session attributes aid filtering, not automatic row collapsing. Estimate and approved invocations have separate trace IDs with a shared `input_fingerprint`.

## Trace content and accounting

The root contains turns, tools and generations. Each completed generation contains readable available conversation context and completed assistant parts, model, usage and cost provenance. It is not guaranteed to contain the exact provider wire prompt/system context. OpenCode message IDs deduplicate completion events; repeated text snapshots are consolidated. Available SDK message history is preferred, buffered parts are the labeled fallback.

Generation duration comes from OpenCode message timestamps, not the moment a completed message is exported. This is message elapsed time, not guaranteed pure provider latency. User turns, generations and tool calls are separate counts. Tools record failures and nonzero reported exits. Parent-session shutdown does not react to a child's idle event. Shutdown callers share the pending flush.

Only provider-exposed reasoning is observable. Hidden/encrypted CoT is not extracted or reconstructed. An explicit concise decision log is the reliable design rationale.

OpenCode's normalized input/output exclude cache/reasoning; the plugin exports disjoint numeric usage fields without adding the provider's overlapping total. Costs come from OpenCode's price card and the evaluator's provider-usage price card. They are estimates, not invoices. Unknown/unpriced values are never called free.

The root/receipt carries `known_session_cost_usd`, `unpriced_generations`, usage totals and coverage, plus a separate `direct_pipeline` result. The pipeline result is read from an atomic structured sidecar, not terminal scrollback. Pipeline observations and cost ledger rows use the same phase accounting shape: phase status, output tokens, known subtotal and usage completeness. A failed phase can have known nonzero spend. Unknown usage can leave the full total null while the known subtotal remains nonzero. Root summary metadata does not add another billable generation.

`session_status`, `task_outcome` and `export_status` are separate. The launcher returns nonzero for failed, blocked or unconfirmed outcomes and for missing/failed plugin export. It does not infer task completion from OpenCode exit code 0.

## Scorecard: report what is available now

End with a concise decision log, artifact/prototype paths and URLs, followed by this block. Write the same block into a workspace file named with the run ID so later runs do not overwrite it.

```text
[UXD-SCORECARD]
ticket: <key|none>
component: <creator|consistency|evaluator>
run_kind: <header value>
langfuse_run_id: <read UXD_TRACE_RUN_ID>
trace_name: <component>/<run_id>
trace_url: <read receipt.trace_url, or explicit receipt-read failure>
model: <actual session model if available>
report_artifact: <new absolute path(s), or none with reason>
prototype_url: <verified served URL, or none>
outcome_status: <completed|blocked|failed>
outcome: <what actually happened; estimate-only is not a completed paid evaluation>
friction_notes: <concrete issues>
decision_log: <concise decisions and reasons>
final_metrics: <receipt path; finalized after this message/session ends>
```

Do not guess final costs, durations or observation counts from terminal scrollback or report them as universally inaccessible. The run ID and receipt link are available during the session. Finalized metrics belong in the receipt after the last generation finishes and should be checked against remotely ingested observations.

## Artifacts

Report exact new artifact paths and verified URLs in final output. The root manifest also points to existing `.artifacts/<KEY>/eval/evaluation-report.html`, `journey-log.json`, `screenshots/`, `runs/`, ledger and `report-url.txt` when present. These inventory entries are labeled workspace-latest with unverified run ownership; do not attribute old reports to this run.

The manifest additionally consumes `report_artifact` and `prototype_url` from the final scorecard. This supports creator/consistency smoke artifacts whose key is not literally `none`. List absolute file paths separated by semicolons. Only existing paths contained in the workspace are inventoried, and these entries are labeled `session_reported`, not independently verified authorship. A newly discovered served URL is recorded even if the initial header used `prototype_url=none`.

`export-helper.mjs` serves local reports at `http://127.0.0.1:9417/evals/<KEY>/`. Local paths and localhost URLs only work on the owner's machine. A preexisting `report-url.txt` can provide a hosted link. Publishing through `publish-report.sh` commits/pushes to its configured destination and must be explicitly authorized separately. No artifact hosting or image upload is implied by `TRACE`. Inline image rendering on this deployment is pending live verification; links are the default.

## Verification

- `npm test --prefix .opencode-tracing`: offline hook, routing, consent-PTY and accounting behavior using mocks.
- `.venv/bin/python plugins/uxd-prototype/skills/uxd-prototype-evaluate/tests/test-tracing-contract.py`: ledger/observation parity, unknown usage, bridge, context and approval guards.
- Launcher `--dry-run`: no credentials/network; actual argv and expanded command body.
- `node scripts/inspect-langfuse-trace.mjs <component> --trace <id>`: paginated read-only v4 API check; returns metadata, usage, parenting and I/O presence, not raw session text.
- Each live test needs its own terminal `TRACE`; paid evaluator phases additionally need reviewed-estimate approval.

Keep credentials outside Git and generated receipts/configuration under ignored `tmp/`. Restart OpenCode after config/plugin/command changes; active sessions retain the old configuration.
