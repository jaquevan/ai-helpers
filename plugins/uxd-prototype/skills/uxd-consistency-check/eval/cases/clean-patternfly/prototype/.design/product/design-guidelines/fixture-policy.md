---
id: no-custom-css
title: Example fixture styling policy
category: foundations
automatable: true
severity: error
---

## Rule

This fixture forbids authored CSS, inline styles, and non-PatternFly stylesheet
links. It is test input, not a rule imposed on other products.

## Automated Checks

```bash
grep -rnE "style[[:space:]]*=" --include="*.html" src/
grep -rnE "<style([[:space:]>])" --include="*.html" src/
grep -rn 'rel="stylesheet"' --include="*.html" src/ | grep -vi patternfly
find src -type f -name '*.css' -print
```
