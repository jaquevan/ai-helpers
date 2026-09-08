---
id: nav-item-structure
title: Navigation Item Structure
category: navigation
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Navigation Item Structure

## Rule

The left navigation must include the specified top-level items in the correct order, with the correct sub-menu hierarchy as defined in the RHOAI 3.4 design specification.

### Canonical Top-Level Items (in order)

1. Home
2. Projects
3. AI hub
4. Gen AI studio
5. Develop & train
6. Observe & monitor
7. Learning resources
8. Applications
9. Settings

### Required Sub-Menu Hierarchy

| Parent | Children |
|--------|----------|
| AI hub | Models, MCP servers |
| AI hub > Models | Catalog, Registry, Deployments |
| AI hub > MCP servers | MCP catalog, Deployments |
| Gen AI studio | AI asset endpoints, Playground, Prompt management, API keys |
| Develop & train | Feature store, Pipelines, Evaluations, Experiments, Training jobs |
| Develop & train > Feature store | Overview, Entities, Datasets, Data sources, Features, Feature views, Feature services |
| Develop & train > Pipelines | Pipeline definitions, Runs, Artifacts, Executions |
| Observe & monitor | Dashboard, Workload metrics |
| Applications | Enabled, Explore |
| Settings | Cluster settings, Environment setup, Model resources and operations, MCP resources, User management, Subscriptions, Policies |
| Settings > Cluster settings | General settings, Storage class |
| Settings > Environment setup | Workbench images, Hardware profiles, Connection types, Workbench templates |
| Settings > Model resources and operations | Serving runtimes, Model registry settings |
| Settings > MCP resources | MCP catalog settings |

## Rationale

The navigation structure defines the product's information architecture. Deviating from the approved structure — adding unlisted items, removing items, or reordering them — confuses users who have built spatial memory of where features live. All structural changes must go through the design review process.

## Examples

### ✅ Correct: Navigation items match the spec

```tsx
<Nav aria-label="Navigation">
  <NavList>
    <NavItem itemId="home">Home</NavItem>
    <NavItem itemId="projects">Projects</NavItem>
    <NavExpandable title="AI hub" groupId="ai-hub">
      <NavExpandable title="Models" groupId="ai-hub-models">
        <NavItem itemId="model-catalog">Catalog</NavItem>
        <NavItem itemId="model-registry">Registry</NavItem>
        <NavItem itemId="model-deployments">Deployments</NavItem>
      </NavExpandable>
      <NavExpandable title="MCP servers" groupId="ai-hub-mcp">
        <NavItem itemId="mcp-catalog">MCP catalog</NavItem>
        <NavItem itemId="mcp-deployments">Deployments</NavItem>
      </NavExpandable>
    </NavExpandable>
    {/* ... remaining items in order */}
  </NavList>
</Nav>
```

### ❌ Incorrect: Items out of order

```tsx
<Nav aria-label="Navigation">
  <NavList>
    <NavItem itemId="home">Home</NavItem>
    <NavItem itemId="settings">Settings</NavItem>  {/* Wrong position */}
    <NavItem itemId="projects">Projects</NavItem>
    {/* Settings should be last */}
  </NavList>
</Nav>
```

### ❌ Incorrect: Unlisted nav item added without spec update

```tsx
<NavList>
  <NavItem itemId="home">Home</NavItem>
  <NavItem itemId="projects">Projects</NavItem>
  <NavItem itemId="dashboard">My Dashboard</NavItem>  {/* Not in spec */}
</NavList>
```

## Automated Checks

**Find navigation item definitions:**
```bash
# Locate nav item labels in sidebar/navigation components
grep -rn "NavItem\|NavExpandable\|title=" --include="*.tsx" src/ | grep -i "nav\|sidebar\|menu"
```

**Find nav item ordering configuration:**
```bash
# Look for navigation route/config arrays that define item order
grep -rn "navItems\|navigationItems\|sidebarItems\|menuItems" --include="*.tsx" --include="*.ts" src/
```

**Check for nav labels matching the canonical list:**
```bash
# Find all NavItem text content (review for spec compliance)
grep -rn "<NavItem" --include="*.tsx" src/ | grep -oP '>\K[^<]+(?=</NavItem>)'
```

**Check for NavExpandable titles matching the canonical list:**
```bash
# Find all expandable section titles
grep -rn "NavExpandable" --include="*.tsx" src/ | grep -oP 'title="[^"]*"'
```

## Manual Review Checklist

- [ ] All 9 top-level items are present in the correct order
- [ ] No unlisted items appear in the navigation
- [ ] Sub-menu hierarchy matches the specification tables above
- [ ] Item labels match exactly (case-sensitive)
- [ ] No items have been removed without a corresponding spec update
- [ ] New items added through the design review process are reflected in both spec and code
