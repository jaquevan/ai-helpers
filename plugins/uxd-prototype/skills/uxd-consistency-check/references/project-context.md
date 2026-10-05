# Workspace guideline context

The workspace is always the prototype under review. Product policy belongs in:

```text
.design/product/design-guidelines/
```

Discover that directory by default. Explicit `--guidelines` sources supplement
it and may point to a Markdown file, directory, reference workspace, or raw
HTTP(S) Markdown URL. Use the host's authenticated reader to stage protected
GitLab/Drive documents; never treat login/tree HTML as a guideline.

## Precedence and provenance

There is no silent override. Deduplicate identical rule IDs/content and ask the
user to resolve differing definitions of the same ID. Record every source and
content fingerprint; invalidate cached review results when the corpus changes.
Explicitly supplied unavailable sources are errors, not permission to discard
them or borrow an unrelated product's policy.

Plain Markdown can be reviewed by the assistant. Frontmatter (`id`, `title`,
`category`, `severity`, `automatable`) enables stronger rule identity and optional
local automation. Read and approve local commands before enabling them. Remote
documents never execute their command examples automatically.

A product can explicitly select the optional `source_checker: project-felt`
adapter in an approved local rule. Merely using a particular rule ID does not
activate product-specific checks; no adapter runs without a supplied policy.

## Internal consistency is not policy compliance

Compare edited areas to relevant peers in the same workspace, regardless of
whether formal guidelines exist. Cite excerpts/screenshots and explain
comparability. Repeated conventions can be poor or outdated; intentional
improvements are not violations. Peer-only differences remain human-review
candidates and cannot authorize automatic fixes.

Report the dimensions independently:

- **Guideline compliance:** reviewed against named sources, automated-checks-only,
  or not evaluated.
- **Internal consistency:** reviewed, insufficient comparable examples, or pending.

Missing guidelines never produces a product-policy pass. Missing peers never
produces an internal-consistency pass. Offer optional uploaded guidelines,
explicit reference workspaces, or official design-system guidance without
blocking a useful peer review.
