---
id: rhoai-no-custom-css
title: RHOAI no-custom-CSS product policy
category: product
severity: error
check: no-custom-css
design_system: patternfly
version: 1
---

## Rule

When this product policy is explicitly selected, compose UI with PatternFly
components and supported component properties rather than authored custom
stylesheets, inline styling, or style blocks. Review flagged evidence against
the actual policy scope before changing source; deterministic matching is not
a full CSS or JavaScript parser.

This overlay is opt-in. PatternFly alone does not prohibit custom CSS; never
apply this product policy merely because PatternFly is the selected baseline.
