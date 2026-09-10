---
id: nav-dark-mode-tokens
title: Navigation Dark Mode Token Usage
category: navigation
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Navigation Dark Mode Token Usage

## Rule

Navigation components must use PatternFly CSS custom properties (design tokens) for all color values — backgrounds, text, borders, and icon fills. Hardcoded hex, RGB, or named color values break dark mode support.

The RHOAI 3.4 design specification defines both light and dark theme variants for the navigation. Both must render correctly using the same source code, with theming handled entirely through CSS custom properties.

### Required Token Categories

| Purpose | Token Pattern | Example |
|---------|--------------|---------|
| Nav background | `--pf-v6-c-nav--BackgroundColor` | Navigation container background |
| Nav item text | `--pf-v6-c-nav__link--Color` | Item label text color |
| Active item background | `--pf-v6-c-nav__link--m-current--BackgroundColor` | Selected item highlight |
| Hover background | `--pf-v6-c-nav__link--hover--BackgroundColor` | Hover state background |
| Section divider | `--pf-v6-c-nav__section--BorderColor` | Dividers between sections |
| Icon fill | `--pf-v6-c-nav__link--Color` or inherited | Nav icon color |

### Forbidden Patterns

- Inline `style={{ color: '#...' }}` on nav elements
- Inline `style={{ backgroundColor: '...' }}` on nav elements
- CSS with hardcoded `color:`, `background:`, or `border-color:` values in nav-related stylesheets
- Direct use of PatternFly color palette variables (e.g., `--pf-v6-global--Color--100`) — use component-level tokens instead

## Rationale

PatternFly's theming system swaps CSS custom property values when toggling between light and dark mode. If navigation components use hardcoded colors, those values won't change with the theme — resulting in illegible text (dark text on dark background), invisible icons, or clashing highlight colors in dark mode.

## Examples

### ✅ Correct: Using PatternFly component tokens

```tsx
<Nav aria-label="Navigation" className="pf-m-dark">
  <NavList>
    <NavItem isActive={isActive}>
      Dashboard
    </NavItem>
  </NavList>
</Nav>
```

```css
/* If custom styles are needed, use CSS custom properties */
.custom-nav-section {
  border-bottom: 1px solid var(--pf-v6-c-nav__section--BorderBottomColor);
}
```

### ✅ Correct: Icon inheriting color from parent

```tsx
<NavItem isActive={pathname === '/home'}>
  <HomeNavIcon />
  Home
</NavItem>
```

```css
/* Icon color inherits from nav link token */
.nav-icon svg {
  fill: currentColor;
}
```

### ❌ Incorrect: Hardcoded hex color on nav item

```tsx
<NavItem
  style={{ color: '#151515' }}
  isActive={isActive}
>
  Dashboard
</NavItem>
```

### ❌ Incorrect: Hardcoded background in CSS

```css
.custom-sidebar .pf-v6-c-nav__link {
  background-color: #ffffff;  /* Breaks dark mode */
}

.custom-sidebar .pf-v6-c-nav__link.pf-m-current {
  background-color: #f0f0f0;  /* Breaks dark mode */
}
```

### ❌ Incorrect: Hardcoded icon fill color

```tsx
<HomeNavIcon style={{ fill: '#6a6e73' }} />
```

### ❌ Incorrect: RGB color values

```css
.sidebar-nav {
  background: rgb(255, 255, 255);  /* Breaks dark mode */
  color: rgb(21, 21, 21);          /* Breaks dark mode */
}
```

## Automated Checks

**Find hardcoded hex colors in nav-related TSX files:**
```bash
# Look for inline hex color values in navigation components
grep -rn "style={{" --include="*.tsx" src/ | grep -i "nav\|sidebar" | grep "#[0-9a-fA-F]"
```

**Find hardcoded colors in nav-related CSS/SCSS:**
```bash
# Look for hardcoded color values in nav stylesheets
grep -rn "color:\s*#\|background.*:\s*#\|border.*color:\s*#" --include="*.css" --include="*.scss" src/ | grep -i "nav\|sidebar"
```

**Find RGB/RGBA values in nav context:**
```bash
# Look for rgb/rgba values in navigation styling
grep -rn "rgb\(.*\)\|rgba\(.*\)" --include="*.css" --include="*.scss" --include="*.tsx" src/ | grep -i "nav\|sidebar"
```

**Find inline style props on Nav components:**
```bash
# NavItem or NavExpandable with inline style overrides
grep -rn "Nav.*style={{" --include="*.tsx" src/
```

**Exceptions (PatternFly token overrides that are theme-safe):**
```bash
# CSS custom property usage (correct pattern)
grep -rn "var(--pf" --include="*.css" --include="*.scss" src/ | grep -i "nav\|sidebar"
```

## Manual Review Checklist

- [ ] No hardcoded hex color values (`#...`) in nav component files
- [ ] No hardcoded `rgb()` or `rgba()` values in nav styling
- [ ] No inline `style={{ color: }}` or `style={{ backgroundColor: }}` on nav elements
- [ ] All custom nav CSS uses `var(--pf-v6-...)` tokens
- [ ] Nav icon SVGs use `fill: currentColor` (inherits from text color token)
- [ ] Navigation renders correctly in both light and dark themes
- [ ] PatternFly's `pf-m-dark` variant class is used for dark sidebar (not custom overrides)
