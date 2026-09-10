---
id: table-toolbar-layout
title: Table Toolbar Layout
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Table Toolbar Layout

## Rule

Table toolbars must follow the standard RHOAI layout pattern. Elements are arranged left-to-right in a specific order, with pagination right-aligned. Active filters appear in a second row below the toolbar using filter chips or label groups with a "Clear all filters" link.

### Standard Toolbar Layout

```
[FilterIcon field selector] [Search input] [Primary Button] [Secondary Button] [Kebab ⋮] ... [Pagination →]
```

### With Active Filters (second row)

```
[FilterIcon field selector] [Search input] [Primary Button] [Secondary Button] [Kebab ⋮] ... [Pagination →]
[Field: value ×]  Clear all filters
```

### With Multiple Filter Groups (second row using label groups)

```
[FilterIcon field selector] [Search input] [Primary Button] [Secondary Button] [Kebab ⋮] ... [Pagination →]
[Label group: Label × Label × Label ×]  [Label group: Label × Label × Label ×]  Clear filters
```

### Toolbar Variants

| Variant | Description |
|---------|-------------|
| **Default** | Field selector + search + action buttons + kebab + pagination |
| **Help link action** | Field selector + search + help link (e.g., "Need another project?") + pagination — no action buttons |
| **Single filter chip** | Default + second row with one filter chip and "Clear all filters" link |
| **Multiple filter chips** | Default + second row with multiple field:value chips and "Clear all filters" link |
| **Label groups** | Default + second row with label groups instead of individual chips, plus "Clear filters" link |

### Element Rules

1. **Field selector** (leftmost): Uses FilterIcon — dropdown to choose which field to filter by
2. **Search input**: Text input paired with the field selector
3. **Action buttons**: Primary CTA first, then secondary. Placed after search in the filter group
4. **Kebab menu** (⋮): Overflow actions when there are too many buttons
5. **Pagination**: Always right-aligned using `align={{ default: 'alignEnd' }}`
6. **Filter chips** (second row): Show active filters with dismiss (×) buttons
7. **Clear filters link**: Always appears after filter chips/label groups

## Rationale

A consistent toolbar layout lets users build muscle memory for locating filters, actions, and pagination. Left-to-right ordering (filter → search → actions → pagination) follows the natural reading flow and groups related controls together. Showing active filters in a second row keeps the main toolbar clean while providing clear feedback about applied filters.

## Examples

### ✅ Correct: Standard toolbar layout

```tsx
<Toolbar id="table-toolbar">
  <ToolbarContent>
    <ToolbarGroup variant="filter-group">
      <ToolbarItem>
        <Dropdown
          toggle={(toggleRef) => (
            <MenuToggle ref={toggleRef} icon={<FilterIcon />}>
              {selectedFilter}
            </MenuToggle>
          )}
        >
          <DropdownList>
            <DropdownItem key="name">Name</DropdownItem>
            <DropdownItem key="owner">Owner</DropdownItem>
          </DropdownList>
        </Dropdown>
      </ToolbarItem>
      <ToolbarItem>
        <SearchInput
          placeholder={`Filter by ${selectedFilter}`}
          value={filterValue}
          onChange={handleFilterChange}
        />
      </ToolbarItem>
      <ToolbarItem>
        <Button variant="primary">Create project</Button>
      </ToolbarItem>
    </ToolbarGroup>
    <ToolbarItem variant="pagination" align={{ default: 'alignEnd' }}>
      <Pagination {...paginationProps} />
    </ToolbarItem>
  </ToolbarContent>
</Toolbar>
```

### ✅ Correct: Toolbar with active filter chips

```tsx
<Toolbar id="table-toolbar">
  <ToolbarContent>
    <ToolbarGroup variant="filter-group">
      {/* Filter selector + search + buttons */}
    </ToolbarGroup>
    <ToolbarItem variant="pagination" align={{ default: 'alignEnd' }}>
      <Pagination {...paginationProps} />
    </ToolbarItem>
  </ToolbarContent>
  <ToolbarContent>
    <ToolbarItem>
      <ChipGroup categoryName="Name">
        <Chip onClick={() => removeFilter('name', value)}>{value}</Chip>
      </ChipGroup>
    </ToolbarItem>
    <ToolbarItem>
      <Button variant="link" onClick={handleClearAll}>
        Clear all filters
      </Button>
    </ToolbarItem>
  </ToolbarContent>
</Toolbar>
```

### ✅ Correct: Toolbar with label groups for multiple filters

```tsx
<Toolbar id="table-toolbar">
  <ToolbarContent>
    {/* Main toolbar row */}
  </ToolbarContent>
  <ToolbarContent>
    <ToolbarItem>
      <LabelGroup categoryName="Status">
        <Label onClose={() => removeFilter('status', 'Active')}>Active</Label>
        <Label onClose={() => removeFilter('status', 'Running')}>Running</Label>
      </LabelGroup>
    </ToolbarItem>
    <ToolbarItem>
      <LabelGroup categoryName="Type">
        <Label onClose={() => removeFilter('type', 'Pipeline')}>Pipeline</Label>
      </LabelGroup>
    </ToolbarItem>
    <ToolbarItem>
      <Button variant="link" onClick={handleClearAll}>
        Clear filters
      </Button>
    </ToolbarItem>
  </ToolbarContent>
</Toolbar>
```

### ❌ Incorrect: Pagination on the left

```tsx
<ToolbarContent>
  <ToolbarItem>
    <Pagination {...paginationProps} />  {/* Should be right-aligned */}
  </ToolbarItem>
  <ToolbarItem>
    <SearchInput />
  </ToolbarItem>
</ToolbarContent>
```

### ❌ Incorrect: Filter chips without "Clear all" link

```tsx
<ToolbarContent>
  <ChipGroup>
    <Chip>name-example</Chip>
  </ChipGroup>
  {/* Missing "Clear all filters" link */}
</ToolbarContent>
```

### ❌ Incorrect: Action buttons before search input

```tsx
<ToolbarGroup variant="filter-group">
  <ToolbarItem>
    <Button variant="primary">Create</Button>  {/* Should come after search */}
  </ToolbarItem>
  <ToolbarItem>
    <SearchInput />
  </ToolbarItem>
</ToolbarGroup>
```

## Automated Checks

**Find toolbar instances and verify structure:**
```bash
# Find all Toolbar components in table contexts
grep -rn "Toolbar" --include="*.tsx" src/ | grep -v "node_modules"
```

**Verify pagination is right-aligned:**
```bash
# Pagination should use alignEnd
grep -rn "Pagination" --include="*.tsx" src/ -B 2 | grep "align"
```

**Check for "Clear all filters" or "Clear filters" link:**
```bash
# Find filter chip usage and verify clear action exists
grep -l "ChipGroup\|LabelGroup" --include="*.tsx" src/ | xargs grep -l "Clear"
```

**Find filter chips without a clear action:**
```bash
# Files with ChipGroup but no clear button (potential violation)
grep -l "ChipGroup" --include="*.tsx" src/ | xargs grep -L "Clear"
```

**Verify FilterIcon is used on field selectors:**
```bash
# FilterIcon usage (should be on field selectors only)
grep -rn "FilterIcon" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] Toolbar elements follow left-to-right order: filter selector → search → buttons → kebab → pagination
- [ ] Pagination is right-aligned using `align={{ default: 'alignEnd' }}`
- [ ] Field selector uses FilterIcon (per table-filter-icons guideline)
- [ ] Primary button appears before secondary buttons
- [ ] Active filter chips appear in a second toolbar row
- [ ] "Clear all filters" or "Clear filters" link appears after filter chips/label groups
- [ ] Kebab menu is used for overflow actions when too many buttons exist
- [ ] Help link variant is used where appropriate (no action buttons, just a help link)
- [ ] Label groups are used instead of individual chips when filtering by multiple categories
