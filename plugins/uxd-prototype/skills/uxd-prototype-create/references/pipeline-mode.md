# Pipeline Mode (Speedrun)

End-to-end orchestration: create → evaluate → optional refine → publish.

## When to use

User asks for a full pipeline, "speedrun", "create and evaluate and publish", or passes `--pipeline` / `--speedrun`.

## Onboarding extras (pipeline only)

After normal create questions, also ask:

1. **Publish target** — `repo` (MR/PR), `github` (GitHub Pages), `gitlab`, `vercel`, `none` (stop after eval), **or a git URL** (open an MR/PR against that repo; implies `repo`)
2. **Prototype URL for evaluate** — required once the app can be served (workspace: usual `npm start` URL; standalone: serve the HTML folder)
3. **Auto-refine?** — yes/no (default yes, max 3 cycles)

## Sequence

```
1. CREATE    → follow uxd-prototype-create Steps 1–13
               (Prototype Bar on by default; optional --export after serve URL is known)
1b. BAR      → install-prototype-bar.sh --artifacts (ALWAYS unless --no-prototype-bar)
               Syncs prototype-bar.json from metadata + installs assets into source.
               Must run BEFORE serve so the bar is visible immediately.
2. SERVE     → ensure prototype is reachable at {URL}
2b. EXPORT?  → if --export, run Step 12 (journey static HTML / tree under .artifacts/{ID}/exports)
3. EVALUATE  → /uxd-prototype-evaluate {ID} {URL} [--workspace=…]
3b. BAR (refresh) → re-run install-prototype-bar.sh --artifacts after evaluate.
               This re-syncs the config AND copies the eval report into
               public/evals/{ID}/ so the Eval tab works on Pages.
               (Happens automatically — Step 3 in the unified script detects the report.)
               MUST run before publish so public/evals/ exists on disk.
4. REFINE?   → if .artifacts/{ID}/eval/evaluation-report.csv has FAIL → refine (this skill) → re-eval
               skip when FAIL count is 0
5. PUBLISH?  → /uxd-prototype-publish {ID} --target={target}  (if target ≠ none)
               When target was a git URL, pass --target=<url> (or --target=repo with
               upstream already set / submit_to_repo.py --upstream <url>)
               Publish Step 2a re-copies eval + refreshes the bar; repo submit
               auto-stages public/evals/{ID}/ even if omitted from changeset.md.
```

Persist flags to `.artifacts/{ID}/pipeline-config.yaml` so the run survives context compression:

```yaml
pipeline:
  id: PROJ-298
  workspace: https://gitlab.example.com/user/fork.git
  workspace_branch: main          # optional; clone branch for --workspace
  decisions: skip
  # depth: normal          # only when decisions is auto or human
  url: http://localhost:3000
  target: repo
  target_repo_url: https://gitlab.example.com/org/canonical.git
  target_branch: release-2.22     # optional; MR/PR base on --target
  max_refine_cycles: 3
  dry_run: false
  prototype_bar: true
  export: false
  export_formats: html,pf-spec
```

When `--target` is a git URL, normalize `target` to `repo` and store the URL in `target_repo_url`. Pass that URL to `resolve_workspace.py --upstream` during create and to `submit_to_repo.py --upstream` during publish. Persist `workspace_branch` / `target_branch` when set and pass them as `--workspace-branch` / `--target-branch`.

## Deterministic local serve and evaluator handoff

After create Steps 1–11 complete, start the local-only bridge before invoking
the evaluator. It writes only allowlisted metadata to
`.artifacts/{ID}/creator-phase-events.jsonl`, appends an `observability` block
to `pipeline-config.yaml`, and never calls a model or reserves a budget. When
`--env-file` is supplied, it runs a read-only Langfuse health/auth preflight and
exports the same allowlisted create-serve metadata; it never sends prototype
source or rendered content.

Record each completed deterministic creator phase with the same program run ID.
Only deterministic phases are accepted; this command cannot be used to imply a
paid creator phase ran.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" \
  --key "{ID}" --program-run-id "{PROGRAM_RUN_ID}" \
  --record-phase create-intake
```

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" \
  --key "{ID}" \
  --workspace standalone \
  --journey-route "/" \
  --expected-text "{prototype title}" \
  --env-file "/path/to/.env.creator"
```

For workspace mode, pass the completed workspace instead. The bridge runs the
workspace package manager install and `build` script, then serves an
`index.html` from `dist`, `build`, `out`, or `public`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" \
  --key "{ID}" --workspace ".artifacts/{ID}/code" \
  --journey-route "/{primary-route}" --expected-text "{prototype title}"
```

It allocates a localhost port atomically, persists the exact URL, PID, and log
path, and requires HTTP 200 for both the root and selected journey route. It
rejects login/authentication pages and pages that do not contain the expected
identity text. Stop a retained local server after evaluation with:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" --key "{ID}" --stop
```

To trace an already-running real prototype, pass the same Jira, GitLab, and
prototype URLs used by the evaluator. This mode does not rebuild or start a
second server. It verifies the checkout origin, exact revision, live HTTP
response, and non-login page identity before exporting create-serve metadata.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" \
  --key "{ID}" --workspace "/path/to/git-checkout" \
  --prototype-url "http://127.0.0.1:8080/" \
  --jira-url "https://jira.example.com/browse/{ID}" \
  --gitlab-url "https://gitlab.example.com/group/project.git" \
  --source-revision "{FULL_GIT_SHA}" \
  --env-file "/path/to/.env.creator" --benchmark-name "real-{ID}"
```

The generated evaluator handoff remains deliberately inert:

```yaml
evaluator:
  preflight: pending
  estimate: pending
  approval_required: true
  model_invoked: false
```

Run evaluator preflight and estimate against the persisted URL only after the
creator identity gate passes. Paid evaluator phases still require that
evaluator's explicit estimate approval. Paid creator work uses the separate
bounded runner and never shares the evaluator's `$25.00`
`openai-budget-ledger.json`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pipeline_mode.py" \
  --key "{ID}" --benchmark-dir "{BENCHMARK_DIR}" --estimate-only
```

This zero-spend command reports the total configured creator estimate and
per-phase token ceilings. The estimate uses the pinned OpenAI price card; it is
not an invoice. Paid phase execution is a separate command and requires its own
estimate review and approval:

```bash
RUNNER="${CLAUDE_SKILL_DIR}/scripts/creator-phase-runner.py"
python3 "$RUNNER" --key "{ID}" --phase create-plan \
  --workspace "/absolute/path/to/project" \
  --prompt-file "/absolute/path/to/project/.artifacts/{ID}/creator-task.md" \
  --env-file "/absolute/path/to/.env.creator" \
  --run-id "{PROGRAM_RUN_ID}" --comparison-id "creator-{ID}-{REVISION}" \
  --estimate-only

# Review the estimate output. Reuse the exact run ID, phase, prompt file,
# model, comparison ID, and benchmark directory for the approved call.
python3 "$RUNNER" --key "{ID}" --phase create-plan \
  --workspace "/absolute/path/to/project" \
  --prompt-file "/absolute/path/to/project/.artifacts/{ID}/creator-task.md" \
  --env-file "/absolute/path/to/.env.creator" \
  --run-id "{PROGRAM_RUN_ID}" --comparison-id "creator-{ID}-{REVISION}" \
  --approve-estimate
```

Run `create-generate` and `create-refine` the same way, reusing the same run ID
and creator benchmark directory for a full creation workflow. Each phase has a
separate approval record and reservation. Reservations use
`openai-budget-ledger-creator.json`, the `$15.00` cap, and `create-*` phase IDs.

Creator phases have no fixed tool-round ceiling. They continue until the
required outputs are present, valid, and refreshed during that phase, or a
cumulative input-token, output-token, or reserved-cost bound stops the phase.
Per-turn output limits still apply; each later request is reduced to the
remaining total output-token allowance. The runner records tool-call/failure counts, error categories,
completion-gate outcome, and bound stops in the phase JSONL and Langfuse
metadata. A token/cost bound can stop the phase before its artifacts are
complete; that failed paid attempt must not be retried with the same run ID.
Every Responses API function call receives a matching tool output, including
policy-denied and timed-out calls, so the conversation can recover instead of
failing on an unresolved call. Explicit HTTP errors settle usage from completed
turns; transport interruptions without a provider response retain the
reservation as usage-unknown.

Use one stable `--run-id` across all approved creator phases. Like evaluator
runs, creator traces use the shared `LivePipelineTrace` implementation and a
deterministic trace ID from that run ID. Each separately approved CLI phase
opens a `creation` root and `creator-phases` grouping span in that same trace;
ordered phase observations (`create-plan`, `create-generate`, `create-refine`)
are tagged as `creator-paid`. They appear together in the `prototype-create`
Langfuse project and share the same comparison ID. Each paid phase also adds a
`creator-artifact-manifest` audit span with output file URIs, byte sizes, SHA-256
hashes, task-input hashes, phase usage, tool diagnostics, and ledger summary.
The manifest is content-free (`sanitized_artifact_output`); prototype source is
kept local. To backfill a completed workspace into an existing deterministic
run trace without another model call:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/record_creator_artifact_manifest.py" \
  --key "{ID}" --workspace "/absolute/path/to/project" \
  --run-id "{PROGRAM_RUN_ID}" --comparison-id "{COMPARISON_ID}"
```

The runner settles from provider-reported usage and stops after the first
failed phase; do not retry a paid phase in the same experiment.

The default phase routes are `gpt-6-sol`; the optional creator quality judge is
`gpt-6-luna`. The separate skill eval config also uses these GPT-6 defaults.

## Defaults

| Flag | Default |
|------|---------|
| `--decisions` | `skip` |
| `--depth` | `normal` (ignored when `--decisions=skip`) |
| `--target` | `none` |
| `--max-refine-cycles` | `3` |
| `--headless` | off |
| `--prototype-bar` | on |
| `--export` | off |

## Evaluate contract

- Evaluate needs a **live URL** — do not claim "quick rubric" scoring.
- Pass for continuing to publish without `--force`: zero FAIL in `.artifacts/{ID}/eval/evaluation-report.csv`.
- FLAGGED criteria: surface to the user; do not auto-block publish unless the user wants a clean report.

## Repo submit notes

When `--target=repo` or `--target` is a git URL, publish uses `submit_to_repo.py` (fork-aware `glab mr create`, MR verification, optional Pages polling). Run git push / submit scripts with elevated permissions (`required_permissions: ["all"]` in Cursor).

**Fork demo pattern:**

```
--workspace https://gitlab.example.com/user/fork.git \
--workspace-branch main \
--target https://gitlab.example.com/org/canonical.git \
--target-branch release-2.22
```

`--workspace` is cloned as `origin` (push destination); `--workspace-branch` selects the clone ref. `--target` URL becomes `upstream` (MR base repo); `--target-branch` is the MR merge base. Same project path on both → same-repo workflow.

## Batch

If multiple IDs are provided, run the sequence per ID. Write a brief batch summary table at the end (ID, FAIL count, publish URL).
