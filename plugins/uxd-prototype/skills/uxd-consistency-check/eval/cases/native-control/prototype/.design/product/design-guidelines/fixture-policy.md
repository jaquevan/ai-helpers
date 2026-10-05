---
id: patternfly-component-usage
title: Example fixture component policy
category: components
automatable: true
severity: error
---

## Rule

This fixture requires component-library buttons, rather than native button tags.
It is an explicit fixture policy, not a universal product constraint.

## Automated Checks

```bash
grep -rn '<button' --include='*.tsx' src/
```
