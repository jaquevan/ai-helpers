# Caching and routing

## Local X-Ray cache

Cache only a complete schema-valid canonical five-file set. The cache key is
the SHA-256 of the ordered JSON object containing `intent_key`, `build_key`, and
`evaluator_key`. Store entries outside the live five-file directory with a
checksum manifest. Validate checksums and canonical schemas before every
restore; a corrupt or partial entry is an invalid miss, never a best-effort hit.

Use `scripts/xray-cache.js` from deterministic orchestration code. Phase A
entries accelerate local assembly. Full entries restore the completed result
and bypass journey, visual, and usability model calls. Restores validate in a
staging directory before atomically replacing only the five canonical files.

Cache misses never reuse partial model output. Changes to criteria/personas
invalidate `intent_key`; source, DOM, or crop changes invalidate `build_key`;
schema/routing changes invalidate `evaluator_key`.

## Prompt-prefix cache

For model phases, keep this order:

1. static role and phase procedure;
2. static persona or PatternFly guideline definitions;
3. strict response schema; and
4. dynamic ticket state, current DOM, cropped images, and journey history.

Do not add timestamps, absolute paths, run IDs, or screenshot data to the static
developer prefix. Record its SHA-256 and byte length plus dynamic input bytes
and provider-reported cached input tokens. Provider cache use is an optimization;
the local compound-key cache controls whole-phase reuse.

## Model routes

`config/phase-routing.json` is authoritative:

- extract, classify, source consistency, and report: local;
- journey and visual consistency: economical tier (`gpt-5.6-luna` or Haiku);
- usability: balanced tier (`gpt-5.6-terra` or Sonnet);
- code fixes: highest reasoning tier (`gpt-5.6-sol` or Opus).

OpenAI is the default. Anthropic-compatible routing is explicit and optional.
Never route deterministic work to a model merely because a global override was
provided.
