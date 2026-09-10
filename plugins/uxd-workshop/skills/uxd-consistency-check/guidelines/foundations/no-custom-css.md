---
id: no-custom-css
title: No Custom CSS in Prototypes
category: foundations
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# No Custom CSS in Prototypes

## Rule

Prototype UI must use PatternFly components, classes, tokens, and official
PatternFly styles. Do not add inline styles, `<style>` blocks, authored CSS or
SCSS files, or non-PatternFly stylesheet links.

Use PatternFly layout, spacing, color, and component APIs instead. When no
PatternFly option exists, record the exception in the prototype's design
context before introducing styling.

## Automated Checks

**Find inline and embedded styles in standalone HTML:**

```bash
# Inline style attributes are custom CSS
grep -rnE "style[[:space:]]*=" --include="*.html" --include="*.htm" src/

# Embedded CSS is custom CSS
grep -rnE "<style([[:space:]>])" --include="*.html" --include="*.htm" src/

# Stylesheet links must be official PatternFly assets
grep -rn "rel=\"stylesheet\"" --include="*.html" --include="*.htm" src/ | grep -vi "patternfly"
```

**Find authored stylesheets and JSX styles:**

```bash
# Authored CSS and SCSS files are custom CSS
find src -type f \( -name "*.css" -o -name "*.scss" \) -print

# JSX/TSX style props are custom CSS
grep -rn "style={{" --include="*.jsx" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] Prototype loads official PatternFly styles only.
- [ ] No inline `style` attributes or JSX style props exist.
- [ ] No `<style>` blocks or authored CSS/SCSS files exist.
- [ ] Any documented exception links to design context and a future PatternFly replacement.
