---
id: table-filter-icons
title: Table Filter Dropdown Icons
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Table Filter Dropdown Icons

## Rule

Use the `FilterIcon` **only for field selectors** (dropdowns that let users choose which field to filter by). Do **not** use the FilterIcon for category/value filters (dropdowns that select specific values or categories).

### Use FilterIcon For:
- **Field selectors**: Dropdowns that choose which column/field to filter (e.g., "Name", "Status", "Type")
- Typically paired with a search input in a compound filter component

### Do NOT Use FilterIcon For:
- **Category filters**: Dropdowns that select predefined categories (e.g., "All projects" vs "A.I. projects")
- **Value filters**: Dropdowns that select specific filter values (e.g., selecting a status from "Active", "Expired", "Disabled")
- **Sort selectors**: Dropdowns for sorting options (e.g., "Name", "Created")

## Rationale

The FilterIcon semantically represents the action of choosing what to filter by, not the filter value itself. Field selectors let users pick which attribute to filter on, while category and value filters apply specific filters. Reserving the FilterIcon for field selectors creates clear visual distinction between choosing a filter criterion vs. choosing a filter value.

## Examples

### ✅ Correct: FilterIcon on Field Selector

```tsx
import { FilterIcon } from '@patternfly/react-icons';

// Field selector dropdown - shows WHICH field to filter by
<ToolbarItem>
  <Dropdown
    toggle={(toggleRef) => (
      <MenuToggle
        ref={toggleRef}
        icon={<FilterIcon />}
        onClick={handleToggle}
        isExpanded={isOpen}
      >
        Name
      </MenuToggle>
    )}
  >
    <DropdownList>
      <DropdownItem key="name">Name</DropdownItem>
      <DropdownItem key="type">Type</DropdownItem>
      <DropdownItem key="owner">Owner</DropdownItem>
    </DropdownList>
  </Dropdown>
</ToolbarItem>

// Paired with search input for the selected field
<ToolbarItem>
  <SearchInput
    placeholder="Filter by name"
    value={filterValue}
    onChange={handleChange}
  />
</ToolbarItem>
```

### ✅ Correct: No Icon on Category/Value Filters

```tsx
// Category filter - selects a category (no icon)
<ToolbarItem>
  <Select
    toggle={(toggleRef) => (
      <MenuToggle
        ref={toggleRef}
        onClick={handleToggle}
        isExpanded={isOpen}
      >
        {selectedCategory}
      </MenuToggle>
    )}
  >
    <SelectList>
      <SelectOption value="All projects">All projects</SelectOption>
      <SelectOption value="A.I. projects">A.I. projects</SelectOption>
    </SelectList>
  </Select>
</ToolbarItem>

// Status filter - selects specific status values (no icon)
<ToolbarItem>
  <Select
    toggle={(toggleRef) => (
      <MenuToggle
        ref={toggleRef}
        onClick={handleToggle}
        isExpanded={isOpen}
      >
        Status
        {badge}
      </MenuToggle>
    )}
  >
    <SelectList>
      <SelectOption value="Active" hasCheckbox>Active</SelectOption>
      <SelectOption value="Expired" hasCheckbox>Expired</SelectOption>
      <SelectOption value="Disabled" hasCheckbox>Disabled</SelectOption>
    </SelectList>
  </Select>
</ToolbarItem>
```

### ❌ Incorrect: FilterIcon on Category/Value Filter

```tsx
// Don't add FilterIcon to category filters
<MenuToggle
  icon={<FilterIcon />}  // ❌ Wrong - this is a category filter
  onClick={handleToggle}
>
  A.I. projects
</MenuToggle>

// Don't add FilterIcon to value filters
<MenuToggle
  icon={<FilterIcon />}  // ❌ Wrong - this is a value filter
  onClick={handleToggle}
>
  Status
</MenuToggle>
```

## Visual Pattern

**Typical toolbar layout:**

```
[Field Selector with FilterIcon] → [Search Input] → [Category Filter, no icon] → [Create CTA]
```

Example:
```
[🔍 Name ▼] → [Search: "Filter by name..."] → [A.I. projects ▼] → [Create project]
```

## Current Violations

**Correct implementations:**
- `src/app/Connections/Connections.tsx` - Field selector has FilterIcon ✓
- `src/app/Settings/Subscriptions/Subscriptions.tsx` - Field selector has FilterIcon ✓
- `src/app/Projects/Projects.tsx` - Category filter has NO icon ✓
- `src/app/Settings/APIKeys/APIKeys.tsx` - Status value filter has NO icon ✓

No violations found - current implementation follows the pattern correctly.

## Automated Checks

**Verify field selectors have FilterIcon:**
```bash
# Find dropdowns with FilterIcon (should be field selectors only)
grep -rn "icon={<FilterIcon" --include="*.tsx" src/

# Find all FilterIcon usage (review context to confirm field-selector usage)
grep -rn "FilterIcon" --include="*.tsx" src/
```

**Verify category/value filters don't have FilterIcon:**
```bash
# Find MenuToggle lines — review these to confirm FilterIcon is absent on category/value filters
grep -rn "MenuToggle" --include="*.tsx" src/ | grep -v "FilterIcon"
```

## Manual Review Checklist

- [ ] Field selectors (choose which field to filter) have FilterIcon
- [ ] Field selectors are paired with SearchInput or similar input component
- [ ] Category filters (predefined categories) have NO icon
- [ ] Value filters (select specific values) have NO icon
- [ ] Sort selectors have NO icon
- [ ] FilterIcon is only used for "which field to filter by" dropdowns
