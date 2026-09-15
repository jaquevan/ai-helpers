# Visual consistency API phase

Judge the supplied rendered component/region crops against the bundled
reference rules. A viewport image may appear only as an explicit fallback.

- Treat the supplied rule text as authoritative.
- Report only visible evidence. Do not infer source implementation.
- Use `VIOLATION`/`error` only for a clear mismatch.
- Use `FLAGGED`/`warning` when a designer must confirm context.
- Keep findings specific, actionable, and linked to supplied screenshot paths.
- Do not repeat an existing source finding unless the screenshot adds a distinct visual problem.
