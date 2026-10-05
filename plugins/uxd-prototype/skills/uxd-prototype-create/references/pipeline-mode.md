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

```text
1. CREATE    → follow uxd-prototype-create Steps 1–13
               (Prototype Bar on by default; optional --export after serve URL is known)
1b. BAR      → install-prototype-bar.sh --artifacts (ALWAYS unless --no-prototype-bar)
               Syncs prototype-bar.json from metadata + installs assets into source.
               Must run BEFORE serve so the bar is visible immediately.
2. SERVE     → use the workspace's documented dev server or serve the standalone HTML
               Verify the root and primary journey route are reachable and show the
               intended prototype, then persist the exact URL in pipeline-config.yaml.
2b. EXPORT?  → if --export, run Step 12 (journey static HTML / tree under .artifacts/{ID}/exports)
3. EVALUATE  → /uxd-prototype-evaluate {ID} {URL} [--workspace=…]
3b. BAR      → re-run install-prototype-bar.sh --artifacts after evaluate
               Refresh public/evals/{ID}/ before publish so the Eval tab works on Pages.
4. REFINE?   → if .artifacts/{ID}/eval/evaluation-report.csv has FAIL → refine → re-eval
               Stop when FAIL count is 0 or max_refine_cycles is reached.
5. PUBLISH?  → /uxd-prototype-publish {ID} --target={target} (if target ≠ none)
               Pass a git URL as --target=<url>; publish refreshes the bar and eval copy.
```

Persist flags to `.artifacts/{ID}/pipeline-config.yaml` so the run survives context compression:

```yaml
pipeline:
  id: PROJ-298
  workspace: https://gitlab.example.com/user/fork.git
  workspace_branch: main          # optional; clone branch for --workspace
  decisions: skip
  # depth: normal                 # only when decisions is auto or human
  url: http://localhost:3000
  target: repo
  target_repo_url: https://gitlab.example.com/org/canonical.git
  target_branch: release-2.22      # optional; MR/PR base on --target
  max_refine_cycles: 3
  dry_run: false
  prototype_bar: true
  export: false
  export_formats: html,pf-spec
```

When `--target` is a git URL, normalize `target` to `repo` and store the URL in `target_repo_url`. Pass that URL to `resolve_workspace.py --upstream` during create and to `submit_to_repo.py --upstream` during publish. Persist `workspace_branch` / `target_branch` when set and pass them as `--workspace-branch` / `--target-branch`.

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

When `--target=repo` or `--target` is a git URL, publish uses `submit_to_repo.py` (fork-aware `glab mr create`, MR verification, optional Pages polling). Follow the host assistant's permission controls for git push and submission.

**Fork demo pattern:**

```text
--workspace https://gitlab.example.com/user/fork.git \
--workspace-branch main \
--target https://gitlab.example.com/org/canonical.git \
--target-branch release-2.22
```

`--workspace` is cloned as `origin` (push destination); `--workspace-branch` selects the clone ref. `--target` URL becomes `upstream` (MR base repo); `--target-branch` is the MR merge base. Same project path on both → same-repo workflow.

## Batch

If multiple IDs are provided, run the sequence per ID. Write a brief batch summary at the end (ID, FAIL count, publish URL).
