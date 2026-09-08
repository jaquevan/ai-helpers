---
id: table-pagination
title: Table Pagination
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Table Pagination

## Rule

Tables with pagination must follow this placement and variant pattern:

**Placement:**
- **Top**: Right-aligned in the toolbar, above the table content
- **Bottom**: Right-aligned at the end of the table (after the `</Table>` component)

**Variant:**
- **Full pagination** (default): Use for most tables with toolbars. Shows page range dropdown, first/previous/page input/next/last navigation
- **Compact pagination**: Use only when the top toolbar has limited space or contains many items that make it look overcrowded. Shows page range dropdown and previous/next arrows only

## Rationale

Consistent pagination placement helps users quickly locate table navigation controls. Top pagination allows users to control the view before scrolling, while bottom pagination provides access after reviewing table contents. Right-alignment keeps pagination controls visually separated from table actions and filters.

## When to Use Pagination

**Use pagination when:**
- Tables have more than 20 rows (configurable threshold)
- Data sets are large and performance benefits from limiting rendered rows

**Do NOT use pagination for:**
- Small tables with < 10 rows total
- Lookup tables or reference data with minimal entries

## Implementation Pattern

### Standard Pattern (Top + Bottom)

```tsx
<Toolbar id="table-toolbar">
  <ToolbarContent>
    {/* Filters and actions on the left */}
    <ToolbarItem>
      <SearchInput ... />
    </ToolbarItem>
    <ToolbarItem>
      <Button variant="primary">Create</Button>
    </ToolbarItem>
    
    {/* Pagination on the right */}
    <ToolbarItem variant="pagination" align={{ default: 'alignEnd' }}>
      <Pagination
        itemCount={filteredItems.length}
        perPage={perPage}
        page={page}
        onSetPage={(_event, newPage) => setPage(newPage)}
        onPerPageSelect={(_event, newPerPage) => {
          setPerPage(newPerPage);
          setPage(1);
        }}
        perPageOptions={[
          { title: '10', value: 10 },
          { title: '20', value: 20 },
          { title: '50', value: 50 },
        ]}
        id="table-pagination-top"
      />
    </ToolbarItem>
  </ToolbarContent>
</Toolbar>

<Table aria-label="Table with pagination">
  {/* Table content */}
</Table>

<Pagination
  itemCount={filteredItems.length}
  perPage={perPage}
  page={page}
  onSetPage={(_event, newPage) => setPage(newPage)}
  onPerPageSelect={(_event, newPerPage) => {
    setPerPage(newPerPage);
    setPage(1);
  }}
  perPageOptions={[
    { title: '10', value: 10 },
    { title: '20', value: 20 },
    { title: '50', value: 50 },
  ]}
  variant="bottom"
  id="table-pagination-bottom"
/>
```

### Compact Variant (Overcrowded Toolbar)

Use `isCompact` prop when toolbar has many items:

```tsx
<ToolbarItem variant="pagination" align={{ default: 'alignEnd' }}>
  <Pagination
    isCompact
    itemCount={filteredItems.length}
    perPage={perPage}
    page={page}
    onSetPage={(_event, newPage) => setPage(newPage)}
    onPerPageSelect={(_event, newPerPage) => {
      setPerPage(newPerPage);
      setPage(1);
    }}
    id="table-pagination-top"
  />
</ToolbarItem>
```

## Current Violations

**Missing bottom pagination:**
- `src/app/Projects/Projects.tsx` - Only has top pagination

**Incorrect alignment or placement:**
- (To be identified during review)

**Inconsistent per-page options:**
- Various files use different values (5, 10, 20, 50, 100)
- **Standard**: Use `[10, 20, 50]` unless there's a specific need

## Automated Checks

**Check for pagination placement:**
```bash
# Find tables with pagination
grep -rn "Pagination" --include="*.tsx" src/ -l

# Check if bottom pagination exists
grep -rn "variant=\"bottom\"" --include="*.tsx" src/

# Check for compact pagination
grep -rn "isCompact" --include="*.tsx" src/ | grep -i "Pagination"
```

**Pattern to detect:**
- Tables with top pagination should also have bottom pagination
- Top pagination should be in `ToolbarItem` with `variant="pagination"` and `align={{ default: 'alignEnd' }}`
- Bottom pagination should have `variant="bottom"`

## Manual Review Checklist

- [ ] Tables with >20 rows have pagination both top and bottom
- [ ] Top pagination is right-aligned in toolbar
- [ ] Bottom pagination is right-aligned after table
- [ ] Full pagination is used unless toolbar is overcrowded
- [ ] Compact pagination only used when toolbar space is limited
- [ ] Per-page options are consistent: [10, 20, 50]
- [ ] Page state resets to 1 when filters change
- [ ] Both top and bottom pagination share the same state and props
