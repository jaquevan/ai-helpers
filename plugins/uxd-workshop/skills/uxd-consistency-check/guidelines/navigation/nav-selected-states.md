---
id: nav-selected-states
title: Navigation Selected States
category: navigation
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Navigation Selected States

## Rule

Navigation selection must follow the RHOAI design specification for visual treatment:

1. **Selected items** display a distinct background highlight (handled by PatternFly's `isActive` prop)
2. **Only one item** can be visually active at a time
3. **Parent sections remain expanded** when a child item is selected — navigating between children must not collapse the parent
4. **Expandable parents show a selected state** when they themselves are the active route (distinct from having a selected child)

### State Definitions

| State | Visual Treatment |
|-------|-----------------|
| Default | No background highlight, normal weight text |
| Selected (leaf) | Light background highlight on the item |
| Expanded (parent) | Chevron rotated down, children visible, no highlight on parent |
| Expanded + parent selected | Parent has background highlight, children visible |
| Expanded + child selected | Child has background highlight, parent expanded but no parent highlight |

## Rationale

Consistent selection states help users maintain orientation within the navigation hierarchy. When a child item is selected, the parent must stay expanded so users can see the full context of where they are. Using PatternFly's built-in `isActive` and `isExpanded` props ensures the selection styling matches the design system rather than introducing custom visual treatments.

## Examples

### ✅ Correct: Using PatternFly isActive for selection

```tsx
<NavExpandable
  title="Observe & monitor"
  groupId="observe-monitor"
  isActive={pathname.startsWith('/observe')}
  isExpanded={expandedSections.includes('observe-monitor')}
>
  <NavItem
    itemId="dashboard"
    isActive={pathname === '/observe/dashboard'}
  >
    Dashboard
  </NavItem>
  <NavItem
    itemId="workload-metrics"
    isActive={pathname === '/observe/workload-metrics'}
  >
    Workload metrics
  </NavItem>
</NavExpandable>
```

### ✅ Correct: Parent stays expanded when navigating between children

```tsx
const [expandedSections, setExpandedSections] = React.useState<string[]>([]);

const onNavSelect = (_event: React.FormEvent, result: { itemId: string; groupId: string }) => {
  // Navigation occurs but expanded state is preserved
  navigate(result.itemId);
};

const onNavExpand = (_event: React.FormEvent, result: { groupId: string; isExpanded: boolean }) => {
  setExpandedSections(prev =>
    result.isExpanded
      ? [...prev, result.groupId]
      : prev.filter(id => id !== result.groupId)
  );
};
```

### ❌ Incorrect: Custom background color instead of isActive

```tsx
<NavItem
  itemId="dashboard"
  style={{
    backgroundColor: pathname === '/dashboard' ? '#f0f0f0' : 'transparent'
  }}
>
  Dashboard
</NavItem>
```

### ❌ Incorrect: Collapsing parent on child navigation

```tsx
const onNavSelect = (_event, result) => {
  setExpandedSections([]);  // Collapses all sections on any navigation
  navigate(result.itemId);
};
```

### ❌ Incorrect: Multiple items marked active simultaneously

```tsx
<NavItem isActive={true}>Dashboard</NavItem>
<NavItem isActive={true}>Workload metrics</NavItem>
```

## Automated Checks

**Find custom background styling on nav items:**
```bash
# Look for inline styles or className overrides on nav items
grep -rn "NavItem" --include="*.tsx" src/ | grep "style=\|backgroundColor\|background-color"
```

**Find isActive usage on nav components:**
```bash
# Verify isActive is used (not custom selected logic)
grep -rn "isActive" --include="*.tsx" src/ | grep -i "nav"
```

**Check for expanded state being reset on navigation:**
```bash
# Look for patterns that collapse all sections on select
grep -rn "setExpanded\|onNavSelect\|onSelect" --include="*.tsx" src/ | grep -i "nav"
```

**Find hardcoded active/selected classes on nav elements:**
```bash
# Custom CSS classes for nav selection instead of PatternFly props
grep -rn "pf-m-current\|active-nav\|selected-nav\|nav-active" --include="*.tsx" --include="*.css" --include="*.scss" src/
```

## Manual Review Checklist

- [ ] All nav items use `isActive` prop for selection state (no custom styling)
- [ ] Only one nav item is `isActive` at any time
- [ ] Expanding a parent section does not affect selection state
- [ ] Selecting a child does not collapse the parent
- [ ] Navigating between siblings within a section keeps the parent expanded
- [ ] Parent `NavExpandable` shows `isActive` only when its own route is active (not a child route)
- [ ] No hardcoded background colors or custom CSS classes for selected state
