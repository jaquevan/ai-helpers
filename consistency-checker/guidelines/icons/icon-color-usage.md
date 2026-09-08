---
id: icon-color-usage
title: Icon Color Usage
category: icons
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Icon Color Usage

## Rule

Icon colors must follow the RHOAI section/lifecycle color system. Never hardcode hex color values for icons — use the CSS custom properties defined in the design system.

### Color Principles

1. **Icon color on white background**: Use the `--ai-*--IconColor` CSS variable for the icon's fill/stroke when displayed on a white/light background.
2. **Black icon on colored background**: When an icon sits inside a filled circle (e.g., `HeaderIcon`), the icon itself should be black and the background uses `--ai-*--BackgroundColor`.
3. **Exception for labels**: UI icons and PF icons in colored labels may use the label's color for the icon — this is the one case where colored small icons are allowed.

### Color Variable System

Colors are mapped by section type (lifecycle stage):

| Section | Icon Color Variable | Background Color Variable |
|---------|-------------------|--------------------------|
| Set up | `--ai-set-up--IconColor` | `--ai-set-up--BackgroundColor` |
| Organize | `--ai-organize--IconColor` | `--ai-organize--BackgroundColor` |
| Training | `--ai-training--IconColor` | `--ai-training--BackgroundColor` |
| Serving | `--ai-serving--IconColor` | `--ai-serving--BackgroundColor` |
| General | `--ai-general--IconColor` | `--ai-general--BackgroundColor` |

And by object type (resource):

| Resource | Variables |
|----------|-----------|
| Project | `--ai-project--IconColor`, `--ai-project--BackgroundColor` |
| Notebook | `--ai-notebook--IconColor`, `--ai-notebook--BackgroundColor` |
| Pipeline | `--ai-pipeline--IconColor`, `--ai-pipeline--BackgroundColor` |
| Cluster Storage | `--ai-cluster-storage--IconColor`, `--ai-cluster-storage--BackgroundColor` |
| Model Server | `--ai-model-server--IconColor`, `--ai-model-server--BackgroundColor` |
| Data Connection | `--ai-data-connection--IconColor`, `--ai-data-connection--BackgroundColor` |
| User | `--ai-user--IconColor`, `--ai-user--BackgroundColor` |
| Group | `--ai-group--IconColor`, `--ai-group--BackgroundColor` |

### Accessibility

For good color contrast:
- Icon color (from variables) should only be used on white/light backgrounds.
- On colored backgrounds (the circle fill), use black for the icon to maintain contrast.

## Rationale

The CSS variable system ensures colors stay consistent across the product and can be themed or updated centrally. Hardcoded hex values create maintenance burden and risk inconsistency when the color palette is updated.

## Examples

### ✅ Correct: Using design system utilities for icon colors

```tsx
import { typedIconColor, typedBackgroundColor } from '#~/concepts/design/utils';

// HeaderIcon handles this internally
<HeaderIcon type={ProjectObjectType.project} sectionType={SectionType.organize} />

// Or when building custom icon displays:
const iconColor = typedIconColor(ProjectObjectType.pipeline);
const bgColor = typedBackgroundColor(ProjectObjectType.pipeline);

<div style={{ backgroundColor: bgColor, borderRadius: '50%', width: 40, height: 40 }}>
  <PipelineIcon style={{ color: 'black', width: 32, height: 32 }} />
</div>
```

### ✅ Correct: Using CSS variables directly

```scss
.my-icon-container {
  background-color: var(--ai-pipeline--BackgroundColor);

  .icon {
    color: black; // Black icon on colored background
  }
}
```

### ❌ Incorrect: Hardcoded hex colors for icons

```tsx
// Don't hardcode colors
<ProjectIcon style={{ color: '#F4B678' }} />

<div style={{ backgroundColor: '#FCE8D2', borderRadius: '50%' }}>
  <ProjectIcon style={{ color: '#000' }} />
</div>
```

### ❌ Incorrect: Colored icon on colored background

```tsx
// Don't use a colored icon on a colored background — contrast issue
<div style={{ backgroundColor: 'var(--ai-project--BackgroundColor)' }}>
  <ProjectIcon style={{ color: 'var(--ai-project--IconColor)' }} />
</div>
```

## Automated Checks

**Find hardcoded hex colors applied to icon elements:**
```bash
# Find hex colors in style props near Icon components
grep -rn "Icon.*style=.*#[0-9a-fA-F]\{3,6\}" --include="*.tsx" src/
```

**Find inline color props on icon components that aren't using CSS vars:**
```bash
# Find fill or color with hex values on icon-related elements
grep -rn "color:\s*['\"]#\|fill:\s*['\"]#" --include="*.tsx" --include="*.scss" src/ | grep -i "icon"
```

**Verify typedIconColor and typedBackgroundColor are used (not bypassed):**
```bash
# Find HeaderIcon-like patterns that hardcode colors instead of using utils
grep -rn "borderRadius.*50%\|border-radius.*50%" --include="*.tsx" src/ | grep -i "background.*#"
```

**Exceptions (correct hardcoded colors):**
```bash
# Empty state gray (#8A8D90) is the standard color for empty state icons
grep -rn "#8A8D90\|8A8D90" --include="*.tsx" src/ | grep -i "icon\|empty"

# Label icons using label colors (PatternFly Label component manages colors)
grep -rn "<Label.*icon=" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] All icon colors come from CSS variables (`--ai-*--IconColor` / `--ai-*--BackgroundColor`)
- [ ] Icons on white backgrounds use section/object icon color
- [ ] Icons on colored circle backgrounds are black
- [ ] No hardcoded hex colors for icon fills (exception: `#8A8D90` for empty state gray)
- [ ] Label icons may use the label's color — this is the allowed exception
- [ ] `typedIconColor()` and `typedBackgroundColor()` are used for dynamic icon coloring
