# Changelog

## Unreleased

- `uxd-research-heuristic-eval`: **promoted from experimental → stable**
  (`status: stable`). Promotion gate met — the colocated eval harness passes
  11/11 judges at `pass_rate 1.0` on `main`, and the skill was validated against a
  real product surface in both Mode A and Mode B.
- `uxd-research-heuristic-eval`: the specialist-lenses clarifying question now
  goes through the interactive `AskUserQuestion` mechanism (like the framework
  question) instead of free-text prose, and is explicitly non-blocking —
  defaulting to "None" and continuing when unanswered. Previously, prose
  questioning stalled non-interactive/agent callers indefinitely, so the
  evaluation never ran (surfaced by the eval's `avoids_design_recommendations`
  judge failing on the `no-recommendations` case).
- `uxd-research-heuristic-eval`: the Step 4 researcher **review-format**
  question (spreadsheet vs. chat) now routes through `AskUserQuestion` as a
  hard-stop gate, matching the design brief's stated intent
  (`references/human-vs-agent-operation.md`). Previously it was delegated to a
  reference doc and asked as free-text prose, so it was surfaced
  nondeterministically — the skill sometimes presented findings inline without
  offering the format choice, failing the `gates_on_researcher_review` judge on
  the `researcher-gate` case. Since this question only arises in Mode A (a human
  is present; Mode B always carries `--review`), hard-stop-and-wait is safe.
- `uxd-research-heuristic-eval`: ambiguous/incomplete interface input is now
  handled explicitly instead of as an open prose ask — Mode A asks and waits;
  Mode B stops with a clear error (like a missing `--framework`) rather than
  hanging on a question no agent caller can answer. The skill never proceeds on
  incomplete input.
- `uxd-research-heuristic-eval`: browser-inspection screenshots are now saved to
  the resolved project directory (the `--project` dir, or the current working
  directory — the same location as the report) using an absolute path. Previously
  the step gave a bare relative filename, which the Playwright MCP resolved against
  its own working root (`~/`), writing the screenshots outside the project and
  orphaning them from the report that references them.
- `uxd-research-heuristic-eval`: the Step 4 researcher **spreadsheet review** path
  now falls back to a local CSV (written to the project directory, same columns,
  legends as comment rows) when the Google Workspace MCP is unavailable, instead of
  dead-ending. The MCP was never a declared precondition and the path had no
  fallback, so a Mode A operator choosing "spreadsheet" without it could not
  proceed.
- `uxd-research-heuristic-eval`: the report traceability line now populates
  `[version]` from the plugin's git ref (short commit SHA, or a tag) instead of a
  `plugin.json` `version` field. The `uxd-research` manifest intentionally has no
  `version` field (repo convention — Claude Code falls back to the commit SHA), so
  the previous instruction could not be satisfied deterministically; emits
  `unversioned` if no git ref resolves.

## 1.1.0

- Added `patternfly` meta-plugin — one install gets all PatternFly skills
- Bumped all plugin versions to fix stale cache bug
- Moved `pf-assist` routing agent to the `patternfly` plugin
- Delisted empty plugins (`pf-a11y`, `pf-code-review`) from marketplace
- Cleaned up plugin manifests — removed unused custom fields
