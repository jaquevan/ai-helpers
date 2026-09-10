---
id: nav-submenu-depth
title: Navigation Submenu Nesting Depth
category: navigation
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Navigation Submenu Nesting Depth

## Rule

Navigation sub-menus must not exceed 3 levels of nesting. The maximum depth defined in the RHOAI 3.4 design specification is:

```
Level 1 (top-level) > Level 2 (section) > Level 3 (sub-item)
```

### Maximum Depth Examples from the Spec

| Level 1 | Level 2 | Level 3 |
|---------|---------|---------|
| Settings | Cluster settings | General settings |
| Settings | Cluster settings | Storage class |
| Settings | Environment setup | Workbench images |
| Settings | Environment setup | Hardware profiles |
| Settings | Model resources and operations | Serving runtimes |
| Develop & train | Feature store | Overview |
| Develop & train | Feature store | Entities |
| Develop & train | Pipelines | Pipeline definitions |
| Develop & train | Pipelines | Runs |
| AI hub | Models | Catalog |
| AI hub | Models | Registry |
| AI hub | MCP servers | MCP catalog |

### Items at Each Depth

- **Depth 1 (9 items)**: Home, Projects, AI hub, Gen AI studio, Develop & train, Observe & monitor, Learning resources, Applications, Settings
- **Depth 2**: Direct children of expandable top-level items (e.g., Models, MCP servers under AI hub)
- **Depth 3**: Leaf items under depth-2 expandable sections (e.g., Catalog under Models)

No level-4 nesting exists in the specification. If a proposed feature requires deeper nesting, the information architecture must be restructured.

## Rationale

Deep navigation hierarchies increase cognitive load and reduce discoverability. Users must remember which sections to expand through multiple levels to reach their target. Three levels is the maximum that still allows efficient navigation — beyond that, items should be relocated, promoted to a higher level, or accessed through alternative patterns (tabs, breadcrumbs, or direct links).

## Examples

### ✅ Correct: Three levels of nesting (maximum)

```tsx
<NavExpandable title="Settings" groupId="settings">
  <NavExpandable title="Cluster settings" groupId="cluster-settings">
    <NavItem itemId="general-settings">General settings</NavItem>
    <NavItem itemId="storage-class">Storage class</NavItem>
  </NavExpandable>
  <NavExpandable title="Environment setup" groupId="env-setup">
    <NavItem itemId="workbench-images">Workbench images</NavItem>
    <NavItem itemId="hardware-profiles">Hardware profiles</NavItem>
  </NavExpandable>
</NavExpandable>
```

### ✅ Correct: Two levels for simpler sections

```tsx
<NavExpandable title="Observe & monitor" groupId="observe-monitor">
  <NavItem itemId="dashboard">Dashboard</NavItem>
  <NavItem itemId="workload-metrics">Workload metrics</NavItem>
</NavExpandable>
```

### ❌ Incorrect: Four levels of nesting

```tsx
<NavExpandable title="Settings" groupId="settings">
  <NavExpandable title="Cluster settings" groupId="cluster">
    <NavExpandable title="General settings" groupId="general">
      <NavItem itemId="display-prefs">Display preferences</NavItem>
      <NavItem itemId="notifications">Notifications</NavItem>
    </NavExpandable>
  </NavExpandable>
</NavExpandable>
```

## Automated Checks

**Find triple-nested NavExpandable (depth 3 — allowed maximum):**
```bash
# Look for NavExpandable patterns to audit nesting depth
grep -rn "NavExpandable" --include="*.tsx" src/
```

**Find route configuration nesting depth:**
```bash
# Look for nested route/nav config objects (children of children of children)
grep -rn "children.*children.*children" --include="*.ts" --include="*.tsx" src/
```

**Find deeply nested nav structures in JSX:**
```bash
# Look for 4+ levels of NavExpandable nesting (violation)
grep -rn "NavExpandable" --include="*.tsx" src/ | grep -c "NavExpandable"
```

## Manual Review Checklist

- [ ] No navigation path requires more than 3 clicks to reach from the top level
- [ ] All depth-3 items are leaf nodes (NavItem, not NavExpandable)
- [ ] No NavExpandable is nested inside another NavExpandable that is itself inside a NavExpandable (4+ deep)
- [ ] New features requiring deep nesting have been restructured to fit within 3 levels
- [ ] Route configuration mirrors the nav depth limits
