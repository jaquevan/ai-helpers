# Interactive recorder adapter

The interactive router preserves the installed upstream 0.4.0 recorder's
formatting, history, token buckets, generation costs, error handling and event
handlers. It does not reuse the one-shot fork's close-on-idle lifecycle.

`build-interactive-recorder.mjs` verifies the exact upstream bundle SHA-256 and
generates an adapter under ignored `generated/`. The upstream MIT license is
copied alongside it. Reviewable changes are limited to:

1. Inject a private tracer instead of getting a global tracer.
2. Inject flush/shutdown callbacks instead of creating/registering a global
   provider and reading process-global credentials.
3. Inject this runtime through the plugin factory.
4. Retain user/generation dedup IDs across idle cleanup.
5. Inject a private async-local context facade for the recorder's five parent
   scopes; do not register or replace OpenCode's global context manager.

No `eval` or dynamic source evaluation is used. The generated file is an ordinary
ES module loaded at startup. A different upstream build fails the hash check;
upgrading requires review and revalidation. `npm ci` and `npm run build:interactive`
are prerequisites for installing the loader.

The router requires an exact TRACE consent prefix in the first user message of
an unused conversation. Before that, it does not pass session-bound chat/tool/event hooks to the
recorder, buffer spans, or export to the generic project. Consent in a resumed
conversation is rejected.

After consent, the router decorates completed span copies with routing/provenance
metadata and redacts known credentials before handing them to one selected project
processor. It preserves the original I/O representation, usage and explicit cost
values. An upstream zero cost remains zero with an explicit unvalidated-zero
provenance label; absent/nonfinite costs remain unknown. No server repricing is
performed.
