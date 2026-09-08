---
id: icon-library-selection
title: Icon Library Selection by Size Context
category: icons
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Icon Library Selection by Size Context

## Rule

Use the correct icon library based on the size context where the icon appears:

| Library | Size Range | Use Cases |
|---------|-----------|-----------|
| PatternFly icons | 12px, 16px, 24px | Statuses, table icons, selectors, menus, empty states (XL 54px) |
| UI icons (Brand) | Up to 24px | Table icons, selectors, label icons, navigation — when PF doesn't have the icon |
| Standard icons (Brand) | 32px–100px | Page headers, informative cards, selectable cards, empty states |

### Key Rules

- **Never use UI icons at sizes > 24px.** UI icons have a larger stroke weight designed for small sizes; they look wrong when scaled up.
- **Never use Standard icons at sizes < 32px.** Standard icons have a finer stroke designed for large display; they become illegible at small sizes.
- **Prefer PF icons** for small sizes when available. Only reach for UI icons if PF doesn't have what you need or a UI icon better matches the corresponding Standard icon (e.g., Folder, Wrench).

## Rationale

The three icon libraries are designed for different optical sizes. UI icons have thicker strokes for legibility at small sizes. Standard icons have thinner, more decorative strokes suited to larger sizes. Using an icon at the wrong size creates visual inconsistency — thick strokes look heavy at large sizes, thin strokes become invisible at small sizes.

## Examples

### ✅ Correct: Standard icon in page header (32px+ context)

```tsx
import { ProjectIcon } from '#~/images/icons';

// ProjectIcon is defined with width: 36 — correct for HeaderIcon (40px container)
<HeaderIcon type={ProjectObjectType.project} sectionType={SectionType.organize} />
```

### ✅ Correct: UI icon / PF icon in navigation (14px context)

```tsx
// NavIcon renders at 14px — appropriate for UI/PF icons
<NavIcon componentRef={DevelopAndTrainNavIcon} />
```

### ✅ Correct: PF icon in a table or label (16px–24px context)

```tsx
import { OutlinedQuestionCircleIcon } from '@patternfly/react-icons';

<Button variant="plain" icon={<OutlinedQuestionCircleIcon />} />
```

### ❌ Incorrect: UI icon SVG used in a HeaderIcon (40px context)

```tsx
// Don't import a UI_icon SVG and render it at header size
import folderIcon from '#~/images/UI_icon-Red_Hat-Folder-RGB.svg';

// This SVG is designed for <= 24px, but HeaderIcon renders at 40px
<div style={{ width: 40, height: 40 }}>
  <img src={folderIcon} />
</div>
```

### ❌ Incorrect: Standard icon used in a label or table (16px context)

```tsx
// Don't use a Standard icon (designed for 32px+) at label size
import { ExperimentIcon } from '#~/images/icons';

<Label icon={<ExperimentIcon />}>Experiment</Label>  // Too detailed for 16px
```

## Automated Checks

**Find UI icon SVGs imported in files that also use HeaderIcon (suggests wrong library for large context):**
```bash
# Find files importing UI_icon SVGs alongside HeaderIcon usage
grep -rln "UI_icon-Red_Hat" --include="*.tsx" src/ | xargs grep -l "HeaderIcon" 2>/dev/null
```

**Find Standard icon TS imports used in Label or nav contexts:**
```bash
# Find files importing from images/icons/ that also render in Labels
grep -rln "from.*images/icons" --include="*.tsx" src/ | xargs grep -ln "<Label.*icon=" 2>/dev/null
```

**Verify createIcon definitions use expected widths (32 or 36 for Standard icons):**
```bash
# Find createIcon with width not in [32, 36] — may indicate wrong library
grep -A2 "createIcon" --include="*.ts" src/images/icons/ | grep "width:" | grep -v "width: 32" | grep -v "width: 36"
```

## Manual Review Checklist

- [ ] Page headers use Standard icons (from `images/icons/*.ts` or `Icon-Red_Hat-*.svg`)
- [ ] Navigation uses UI icons or PF icons at 14–24px
- [ ] Tables, selectors, and labels use PF or UI icons at 16–24px
- [ ] No UI icon SVGs (`UI_icon-Red_Hat-*`) are rendered at sizes > 24px
- [ ] No Standard icons are rendered at sizes < 32px
