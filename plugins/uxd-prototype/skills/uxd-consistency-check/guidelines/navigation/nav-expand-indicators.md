---
id: nav-expand-indicators
title: Navigation Expand/Collapse Indicators
category: navigation
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Navigation Expand/Collapse Indicators

## Rule

Expandable navigation items (those with sub-items) must display a chevron indicator: chevron-right when collapsed and chevron-down when expanded. Leaf items (no children) must not display any expand/collapse indicator.

### Leaf Items (no chevron)

- Home
- Projects
- Learning resources

### Expandable Items (chevron required)

- AI hub
- Gen AI studio
- Develop & train
- Observe & monitor
- Applications
- Settings

PatternFly's `NavExpandable` component handles the chevron automatically. Using `NavItem` for sections that have children, or `NavExpandable` for leaf items, violates this guideline.

## Rationale

Chevron indicators communicate affordance — they tell users which items can be expanded to reveal sub-navigation. Showing a chevron on a leaf item misleads users into expecting sub-items. Omitting a chevron on an expandable item hides available navigation, forcing users to discover sub-menus by accident.

## Examples

### ✅ Correct: Leaf item uses NavItem (no chevron)

```tsx
<NavItem itemId="home" isActive={pathname === '/'}>
  Home
</NavItem>
<NavItem itemId="projects" isActive={pathname === '/projects'}>
  Projects
</NavItem>
<NavItem itemId="learning-resources" isActive={pathname === '/resources'}>
  Learning resources
</NavItem>
```

### ✅ Correct: Expandable item uses NavExpandable (chevron auto-rendered)

```tsx
<NavExpandable
  title="Observe & monitor"
  groupId="observe-monitor"
  isActive={pathname.startsWith('/observe')}
  isExpanded={expandedSections.includes('observe-monitor')}
>
  <NavItem itemId="dashboard">Dashboard</NavItem>
  <NavItem itemId="workload-metrics">Workload metrics</NavItem>
</NavExpandable>
```

### ❌ Incorrect: Expandable section rendered as NavItem (no chevron shown)

```tsx
<NavItem itemId="settings" onClick={toggleSettings}>
  Settings
</NavItem>
{showSettings && (
  <div className="sub-nav">
    <NavItem>Cluster settings</NavItem>
    <NavItem>Environment setup</NavItem>
  </div>
)}
```

### ❌ Incorrect: Leaf item wrapped in NavExpandable (misleading chevron)

```tsx
<NavExpandable title="Home" groupId="home">
  {/* No children — this shouldn't be expandable */}
</NavExpandable>
```

## Automated Checks

**Find items using NavExpandable (should match the expandable list above):**
```bash
# All NavExpandable usages — verify titles match expected expandable items
grep -rn "NavExpandable" --include="*.tsx" src/ | grep "title="
```

**Find leaf-like NavItem usages in sidebar components:**
```bash
# NavItem usages in navigation context — verify these are actual leaf items
grep -rn "<NavItem" --include="*.tsx" src/ | grep -i "nav\|sidebar"
```

**Check for custom expand/collapse that bypasses PatternFly Nav:**
```bash
# Look for manual chevron icon usage in navigation context
grep -rn "AngleRightIcon\|AngleDownIcon\|ChevronRightIcon\|ChevronDownIcon" --include="*.tsx" src/ | grep -i "nav\|sidebar\|menu"
```

**Check for empty NavExpandable (no children):**
```bash
# Find NavExpandable with no NavItem children (potential empty expandables)
grep -rn "NavExpandable" --include="*.tsx" src/ | grep -v "NavItem"
```

## Manual Review Checklist

- [ ] Home, Projects, and Learning resources use `NavItem` (no chevron)
- [ ] AI hub, Gen AI studio, Develop & train, Observe & monitor, Applications, and Settings use `NavExpandable`
- [ ] No empty `NavExpandable` components (all have at least one child)
- [ ] No custom chevron icons added manually to nav items
- [ ] Expand/collapse behavior toggles chevron direction (right ↔ down)
- [ ] PatternFly `NavExpandable` component is used rather than custom expand logic
