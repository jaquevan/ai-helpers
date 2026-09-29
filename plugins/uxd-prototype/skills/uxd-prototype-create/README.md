# uxd-prototype-create

Create a UX prototype from a Jira ticket, Figma file, feature description, or rough idea — standalone HTML or integrated into an existing codebase.

**Contract (inputs, outputs, flags, steps):** [SKILL.md](SKILL.md)

## Quick start

- "Prototype PROJ-298"
- "Create a prototype from this Figma design: https://figma.com/design/..."
- "Build on top of my existing repo at /path/to/project"
- "Run the full pipeline for PROJ-298 and open an MR"

`--workspace` is the codebase to build in. `--target` is only where the MR/PR lands.

Measured OpenAI phases use `config/model-routing.json` (`gpt-6-sol`, with
`gpt-6-luna` as the judge) and `scripts/creator-phase-runner.py`. Estimate each
phase first; paid execution requires explicit approval and uses the separate
creator `$15` ledger. See [pipeline mode](references/pipeline-mode.md) for the
estimate/approve commands.

Run creator bridge and bounded-phase tests with:

```bash
bash tests/run-tests.sh
```

## Related

- **uxd-prototype-export** — static HTML / component tree / PF spec; Prototype Bar
- **uxd-prototype-evaluate** — Playwright AC validation + persona usability
- **uxd-prototype-publish** — MR, GitHub/GitLab Pages, or Vercel
