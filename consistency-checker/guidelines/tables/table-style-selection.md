---
id: table-style-selection
title: Table Style and Row Patterns
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Table Style and Row Patterns

## Rule

Choose the correct table style (default or compact) and row pattern (basic, expandable, or compound expandable) based on data density and content type.

### Table Styles

| Style | Row Height | Use When |
|-------|-----------|----------|
| **Default** | Standard padding | Most tables — provides comfortable reading space for cells with descriptions, labels, or status indicators |
| **Compact** | Reduced padding | Tables with high data density where vertical space is limited and cells contain only simple text values |

### Row Patterns

| Pattern | Description | Use When |
|---------|------------|----------|
| **Basic rows** | Standard non-expandable table rows | Most table data that doesn't need drill-down |
| **Expandable rows** | Rows with a toggle (chevron) on the left that reveals a detail section below | A row has related detail that doesn't fit in columns (e.g., full descriptions, nested tables, logs) |
| **Compact expandable rows** | Expandable rows with compact styling | Same as expandable but in data-dense contexts |
| **Compound expandable** | Individual cells are expandable — clicking a specific cell column expands content related to that column | A row has multiple expandable dimensions (e.g., clicking a "Status" cell shows status detail, clicking "Models" shows model detail) |

### Compound Expandable Behavior

In compound expandable tables:
- The expanded section appears below the row and spans the full table width
- Only one cell per row can be expanded at a time
- The expanded cell gets a highlighted/selected state
- The expansion area can contain nested tables, status details, or other structured content

## Rationale

Default row height gives cells enough breathing room for descriptions, labels, icons, and multi-line content. Compact style saves vertical space but should only be used when cells contain simple values. Expandable rows keep the main table scannable by hiding detail behind a toggle, while compound expandable rows let users drill into specific columns without expanding everything.

## Examples

### ✅ Correct: Default style for tables with rich cell content

```tsx
<Table aria-label="Projects" variant="default">
  <Thead>
    <Tr>
      <Th>Name</Th>
      <Th>Description</Th>
      <Th>Status</Th>
      <Th>Created</Th>
    </Tr>
  </Thead>
  <Tbody>
    {projects.map(project => (
      <Tr key={project.id}>
        <Td>
          <a href={project.url}>{project.name}</a>
          <div className="description">{project.description}</div>
        </Td>
        <Td><Label color="green">Active</Label></Td>
        <Td>{project.created}</Td>
      </Tr>
    ))}
  </Tbody>
</Table>
```

### ✅ Correct: Compact style for simple data-dense tables

```tsx
<Table aria-label="API Keys" isCompact>
  <Thead>
    <Tr>
      <Th>Name</Th>
      <Th>Key ID</Th>
      <Th>Created</Th>
      <Th>Expires</Th>
    </Tr>
  </Thead>
  <Tbody>
    {keys.map(key => (
      <Tr key={key.id}>
        <Td>{key.name}</Td>
        <Td>{key.keyId}</Td>
        <Td>{key.created}</Td>
        <Td>{key.expires}</Td>
      </Tr>
    ))}
  </Tbody>
</Table>
```

### ✅ Correct: Expandable row for detail drill-down

```tsx
<Tbody isExpanded={isRowExpanded(row.id)}>
  <Tr>
    <Td
      expand={{
        rowIndex: idx,
        isExpanded: isRowExpanded(row.id),
        onToggle: () => toggleRow(row.id)
      }}
    />
    <Td>{row.name}</Td>
    <Td>{row.status}</Td>
  </Tr>
  <Tr isExpanded={isRowExpanded(row.id)}>
    <Td colSpan={3}>
      <ExpandableRowContent>
        {/* Detail content: nested table, description, etc. */}
      </ExpandableRowContent>
    </Td>
  </Tr>
</Tbody>
```

### ❌ Incorrect: Compact style for table with descriptions and labels

```tsx
<Table isCompact>
  <Tbody>
    <Tr>
      <Td>
        <a href={url}>{name}</a>
        <div>{description}</div>  {/* Cramped in compact rows */}
        <Label>Active</Label>     {/* Labels need default row height */}
      </Td>
    </Tr>
  </Tbody>
</Table>
```

## Automated Checks

**Find tables using compact style:**
```bash
# Review whether compact tables contain rich cell content
grep -rn "isCompact" --include="*.tsx" src/ | grep -i "table"
```

**Find expandable row patterns:**
```bash
# Find expandable row usage
grep -rn "ExpandableRowContent\|isExpanded\|expand={{" --include="*.tsx" src/
```

**Find compound expandable usage:**
```bash
# Find compound expandable table patterns
grep -rn "compoundExpand\|CompoundExpandable" --include="*.tsx" src/
```

**Find tables with descriptions to verify they use default style:**
```bash
# Tables with description-like content (should not be compact)
grep -l "description\|Description" --include="*.tsx" src/ | xargs grep -l "isCompact"
```

## Manual Review Checklist

- [ ] Tables with descriptions, labels, or multi-line content use default (non-compact) style
- [ ] Compact tables contain only simple text values (names, dates, IDs)
- [ ] Expandable rows are used when detail doesn't fit in columns
- [ ] Compound expandable is used when rows have multiple expandable dimensions
- [ ] Only one cell is expanded at a time in compound expandable tables
- [ ] Expanded sections span full table width
- [ ] Expand toggles (chevrons) are on the left side of expandable rows
- [ ] Compact expandable rows are only used in data-dense contexts
