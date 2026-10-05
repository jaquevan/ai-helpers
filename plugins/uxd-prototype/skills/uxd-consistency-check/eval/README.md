# Consistency checker skill eval

This colocated agent-eval-harness suite covers six cases:

- Custom CSS: report all four grounded locations as blocking errors.
- Clean PatternFly HTML: accept the official stylesheet without false positives.
- Pagination search matches: retain low-confidence, non-blocking candidates.
- Native React control: identify the missing PatternFly component treatment.
- Missing visual evidence: request a URL/screenshots without inventing a visual pass.
- Missing guidelines: perform grounded internal peer review without a product-policy pass.

Source cases copy `prototype/` into an isolated consumer workspace and request
`artifacts/consistency-report.json`. Judges compare the analyzer's exact
locations, guideline IDs, classification, and guideline-level summary against
`annotations.yaml`; they also reject fabricated visual evidence. These are
agent workflow checks. The policies inside each fixture workspace are explicit
test inputs, not a bundled product corpus or default rules for other teams.

## Local judge calibration

Standalone developer suites under `tests/` and `eval/tests/` are ignored and not
distributed. If those local suites are available, use a Python environment with
`eval/requirements.txt` installed and run them from this skill directory:

```bash
python3 -m unittest discover -s eval/tests -p 'test_*.py' -v
bash tests/run-tests.sh
```

Calibration runs the real analyzer on the source cases and checks that the
judges reject missing reports, incorrect locations, promoted candidates, and
unsupported visual claims. It does not run a model or establish agent pass rates.

## Agent run

With agent-eval-harness installed, run from the repository root:

```text
/agent-eval-harness:eval-run --config plugins/uxd-prototype/skills/uxd-consistency-check/eval/eval.yaml --no-llm-judges
```

The runner/model follow the repository's Claude-based Skill Evals CI workflow;
the checker itself remains tool-agnostic. CI requires `ANTHROPIC_API_KEY` to
execute agent cases. A skipped run without that key is not evidence of passing
evals. No live MCP, browser, publishing, or telemetry access is needed.
