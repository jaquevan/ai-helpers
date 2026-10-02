---
id: patternfly-component-usage
title: PatternFly Component Usage
category: foundations
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# PatternFly Component Usage

## Rule

Prototype interfaces must use PatternFly components or official PatternFly
classes for interactive controls and structural UI. Do not substitute raw
controls or another component library when PatternFly provides the pattern.

## Automated Checks

**Find raw controls in React source:**

```bash
# React prototypes must use PatternFly control components
grep -rnE "<(button|input|select|textarea|table|nav|form)([[:space:]>])" --include="*.jsx" --include="*.tsx" src/
```

**Find raw controls in standalone HTML without PatternFly classes:**

```bash
# Standalone HTML controls require an official PatternFly component class
grep -rnE "<(button|input|select|textarea|table|nav|form)([[:space:]>])" --include="*.html" --include="*.htm" src/ | grep -vE "class=[\"'][^\"']*pf-v[0-9]+-"
```

**Find known third-party component-library imports:**

```bash
# Do not replace PatternFly with another UI component library
grep -rnE "from[[:space:]]+['\"](@mui|@chakra-ui|antd|react-bootstrap)(/[^'\"]*)?['\"]" --include="*.js" --include="*.jsx" --include="*.ts" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] Interactive controls use PatternFly React components or official classes.
- [ ] Tables, navigation, and forms use the corresponding PatternFly patterns.
- [ ] No competing component library replaces an available PatternFly component.
- [ ] Any genuine PatternFly gap is documented before an exception is introduced.
