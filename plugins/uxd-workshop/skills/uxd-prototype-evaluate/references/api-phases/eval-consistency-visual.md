# Visual consistency API phase

Judge rendered screenshots against the bundled reference rules.

- Treat the supplied rule text as authoritative.
- Report only visible evidence. Do not infer source implementation.
- Use `VIOLATION`/`error` only for a clear mismatch.
- Use `FLAGGED`/`warning` when a designer must confirm context.
- Keep findings specific, actionable, and linked to supplied screenshot paths.
- Do not repeat an existing source finding unless the screenshot adds a distinct visual problem.
