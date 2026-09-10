# Project consistency context

Bundled guidelines are portable defaults shared by prototype creation and
evaluation. Product decisions belong in the consumer repository:

```text
.design/product/design-guidelines/consistency/
├── README.md
├── decisions/
└── exceptions/
```

- `README.md` indexes the current product conventions and their owners.
- `decisions/` records agreed component, content, and interaction choices.
- `exceptions/` records approved departures, their scope, and a replacement or
  review date.

Read this directory before interpreting checker candidates. Project context may
explain a low-confidence finding; it does not silently disable a bundled rule.
An exception must identify the guideline, affected prototype scope, owner, and
reason.

## RHAI UX default

RHAI UX prototypes use PatternFly components, classes, tokens, and official
styles without custom CSS. This is a product decision, not a universal rule for
every team. A future RHAI overlay can enforce it independently while other
products document allowed exceptions.

## Rule ownership

| Content | Location | Used for |
|---|---|---|
| Portable automated rules | bundled `guidelines/` | deterministic create/evaluate checks |
| Product conventions | `.design/.../consistency/decisions/` | human and AI interpretation |
| Approved deviations | `.design/.../consistency/exceptions/` | scoped review context |
| Editable experiments | ignored `tmp/consistency-checker-lab/` | local rule development only |

Promote a repeated, product-independent decision into a bundled guideline only
after its examples and expected findings are tested in committed fixtures.
