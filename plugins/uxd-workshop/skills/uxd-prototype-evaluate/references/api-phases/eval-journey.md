# Structured journey evaluation

Inspect only the supplied prototype evidence, screenshot inputs, extracted Jira
context, and classified acceptance criteria. Do not search the filesystem, run
commands, retrieve Jira, or infer implementation details that are not visible.

Produce one journey for each supplied journey definition. Record only what the
screenshot and compact page evidence support. If interaction behavior cannot be
confirmed from the supplied evidence, use `FLAGGED` rather than inventing a
successful or failed interaction. Screenshot paths must be copied exactly from
the supplied relative path list.

Return criterion results only for T1 and T2 criteria. T3 backend criteria retain
their deterministic classification result. T4 design-process criteria are
finalized locally as `FLAGGED` because a prototype cannot prove design review,
engineering validation, research, or handoff deliverables.

The API response schema is authoritative. Return no prose outside that schema.
