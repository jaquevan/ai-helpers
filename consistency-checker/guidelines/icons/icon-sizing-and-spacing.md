---
id: icon-sizing-and-spacing
title: Standard Icon Sizing and Spacing
category: icons
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Standard Icon Sizing and Spacing

## Rule

Standard icons must follow specific size and spacing rules depending on their context:

| Context | Icon Size | Background | Spacing to Label |
|---------|-----------|------------|-----------------|
| Page/card headers | 32px | 40px filled circle | 8px |
| Selectable cards | 40px | None (plain, on white) | 4px |
| Empty states | 54px | None (plain) | PF default |
| UI icons in selectors | 24px | None | 8px |
| UI icons in tables | 24px | None | 4px |
| UI icons in labels | 16px | None | PF label default |

### Standard Icon Sizing Details

- **Page/card headers**: Icon is 32px, colored black. Placed inside a 40px filled circle background. The background circle color comes from the section/lifecycle color system. Keep 8px spacing between the filled background edge and the label text.
- **Selectable cards**: Icon is 40px, colored per the color values mapping (no filled background). Keep 4px spacing between the icon and the label.
- **Empty states**: Icon is 54px (same as PF icons for empty states). Icon color is gray (`#8A8D90`, same as PF empty state color).

### PatternFly Icon Sizes (Reference)

- Small: 12px
- Medium: 16px
- Large: 24px
- XL (empty states): 54px

## Rationale

Consistent icon sizing creates visual rhythm across the product. The 32px icon inside a 40px circle creates a standardized "header icon" pattern recognizable throughout RHOAI. Spacing rules ensure labels don't crowd icons and maintain readability.

## Examples

### ✅ Correct: HeaderIcon with default 40px size and 4px padding

```tsx
import HeaderIcon from '#~/concepts/design/HeaderIcon';
import { ProjectObjectType, SectionType } from '#~/concepts/design/utils';

// Default: size=40, padding=4 → 32px icon inside 40px circle
<HeaderIcon type={ProjectObjectType.project} sectionType={SectionType.organize} />
```

### ✅ Correct: Selectable card with 40px plain icon and 4px gap

```tsx
import { SingleModelIcon } from '#~/images/icons';

<Flex alignItems={{ default: 'alignItemsCenter' }} spaceItems={{ default: 'spaceItemsSm' }}>
  <FlexItem>
    <SingleModelIcon style={{ width: 40, height: 40 }} />
  </FlexItem>
  <FlexItem>Single-model serving platform</FlexItem>
</Flex>
```

### ✅ Correct: Empty state icon at 54px in gray

```tsx
<img
  src={projectEmptyStateImg}
  alt=""
  style={{ width: 54, height: 54, color: '#8A8D90' }}
/>
```

### ❌ Incorrect: HeaderIcon with non-standard size

```tsx
// Don't override the default sizing
<HeaderIcon type={ProjectObjectType.project} size={60} padding={10} />
```

### ❌ Incorrect: Standard icon rendered at 24px

```tsx
import { PipelineIcon } from '#~/images/icons';

// PipelineIcon is a Standard icon (width: 36) — don't shrink to 24px
<PipelineIcon style={{ width: 24, height: 24 }} />
```

## Automated Checks

**Find HeaderIcon usage with non-standard size props:**
```bash
# HeaderIcon with explicit size that isn't 40
grep -rn "HeaderIcon" --include="*.tsx" src/ | grep "size=" | grep -v "size={40}" | grep -v "size=.40"
```

**Find HeaderIcon usage with non-standard padding:**
```bash
# HeaderIcon with explicit padding that isn't 4
grep -rn "HeaderIcon" --include="*.tsx" src/ | grep "padding=" | grep -v "padding={4}" | grep -v "padding=.4"
```

**Find Standard icons (from images/icons/) rendered at sizes under 32px:**
```bash
# Look for inline width/height under 32 on custom icon components
grep -rn "Icon.*style=.*width:\s*[0-9]\+\|Icon.*width=.[0-9]\+" --include="*.tsx" src/ | grep -E "width[=:]\s*[0-9]{1,2}[^0-9]" | grep -v "width.*3[2-9]\|width.*[4-9][0-9]\|width.*[1-9][0-9]{2}"
```

**Find empty state icons not using 54px:**
```bash
# Empty state images with non-standard sizes
grep -rn "empty-state" --include="*.tsx" src/ | grep -i "width\|height\|size" | grep -v "54"
```

## Manual Review Checklist

- [ ] All page headers use the 32px icon + 40px circle pattern via `HeaderIcon`
- [ ] Selectable cards use 40px plain icons with 4px label spacing
- [ ] Empty states use 54px icons in gray (`#8A8D90`)
- [ ] No Standard icons are shrunk below 32px
- [ ] No UI/PF icons are stretched above 24px (except PF XL empty state at 54px)
- [ ] Spacing between icons and labels matches the spec (8px for headers, 4px for cards/tables)
