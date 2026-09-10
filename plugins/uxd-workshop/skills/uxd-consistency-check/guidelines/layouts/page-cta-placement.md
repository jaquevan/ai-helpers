---
id: page-cta-placement
title: Page-Level CTA Placement
category: layout
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Page-Level CTA Placement

## Rule

Primary call-to-action (CTA) buttons (e.g., "Create project", "Add connection") must be placed according to their scope and the page structure:

### With Toolbar (Table/List Pages)

**Place CTA inside the toolbar's filter group**, as the last item after search/filters:

```tsx
<ToolbarGroup variant="filter-group">
  [Filter dropdown] → [Search input] → [Primary CTA]
</ToolbarGroup>
<ToolbarItem variant="pagination" align={{ default: 'alignEnd' }}>
  [Pagination]
</ToolbarItem>
```

### Without Toolbar

**Place CTA at top right** in the page header section (using Flex layout):

```tsx
<PageSection>
  <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }}>
    <FlexItem>
      [Page title and description]
    </FlexItem>
    <FlexItem>
      [Primary CTA]
    </FlexItem>
  </Flex>
</PageSection>
```

### With Tabs

**Placement depends on CTA scope:**

- **CTA applies to ALL tabs**: Place at top right, above the tab navigation
- **CTA is tab-specific**: Place beneath each individual tab (either in toolbar if present, or top right of tab content)

## Rationale

Consistent CTA placement helps users quickly locate primary actions. Placing CTAs inside the toolbar's filter group logically groups all table controls together. Top-right placement (without toolbar) follows the F-pattern reading flow, making actions easily discoverable.

## Examples

### ✅ Correct: CTA in Filter Group (With Toolbar)

```tsx
<Toolbar id="connections-toolbar">
  <ToolbarContent>
    <ToolbarGroup variant="filter-group">
      <ToolbarItem>
        <Dropdown>
          {/* Filter dropdown */}
        </Dropdown>
      </ToolbarItem>
      <ToolbarItem>
        <SearchInput 
          placeholder="Filter by name"
          value={filterValue}
          onChange={handleChange}
        />
      </ToolbarItem>
      <ToolbarItem>
        <Button variant="primary" onClick={handleAdd}>
          Add connection
        </Button>
      </ToolbarItem>
    </ToolbarGroup>
    <ToolbarGroup align={{ default: 'alignEnd' }}>
      <ToolbarItem variant="pagination">
        <Pagination {...paginationProps} />
      </ToolbarItem>
    </ToolbarGroup>
  </ToolbarContent>
</Toolbar>
```

### ✅ Correct: CTA Top Right (No Toolbar)

```tsx
<PageSection>
  <Flex 
    justifyContent={{ default: 'justifyContentSpaceBetween' }}
    alignItems={{ default: 'alignItemsCenter' }}
  >
    <FlexItem>
      <Title headingLevel="h1">Projects</Title>
      <Text>View your existing projects or create new projects.</Text>
    </FlexItem>
    <FlexItem>
      <Button variant="primary" onClick={handleCreate}>
        Create project
      </Button>
    </FlexItem>
  </Flex>
</PageSection>
```

### ❌ Incorrect: CTA Outside Filter Group

```tsx
// Don't do this - CTA should be INSIDE the filter group
<ToolbarGroup variant="filter-group">
  <ToolbarItem>
    <SearchInput />
  </ToolbarItem>
</ToolbarGroup>
<ToolbarItem>
  <Button variant="primary">Create</Button>
</ToolbarItem>
<ToolbarItem variant="pagination">
  <Pagination />
</ToolbarItem>
```

## Current Violations

**CTA outside filter group (should be inside):**
- `src/app/Settings/APIKeys/APIKeys.tsx` - "Create API key" is separate ToolbarItem
- `src/app/Projects/Projects.tsx` - "Create project" is separate ToolbarItem

**Correct implementation:**
- `src/app/Connections/Connections.tsx` - "Add connection" is inside filter group ✓

## Automated Checks

**Check for CTAs outside filter groups:**
```bash
# Find primary buttons (review each for correct toolbar/flex placement)
grep -rn "variant=\"primary\"" --include="*.tsx" src/

# Find ToolbarGroups with filter-group variant (CTA should be inside these)
grep -rn "variant=\"filter-group\"" --include="*.tsx" src/
```

**Pattern to detect:**
- Primary buttons in toolbars should be within `<ToolbarGroup variant="filter-group">`
- Primary buttons should come after search/filter elements in the group
- CTAs outside toolbars should be in a Flex layout with `justifyContentSpaceBetween`

## Manual Review Checklist

- [ ] Page-level CTAs in toolbars are inside `ToolbarGroup variant="filter-group"`
- [ ] CTA appears as the last item in the filter group (after search/filters)
- [ ] Pages without toolbars have CTAs at top right in page header
- [ ] Tab-specific CTAs appear beneath each tab
- [ ] Cross-tab CTAs appear above tab navigation at top right
- [ ] CTA placement matches the scope of the action
