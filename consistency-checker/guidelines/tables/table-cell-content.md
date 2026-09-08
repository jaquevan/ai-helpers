---
id: table-cell-content
title: Table Cell Content Patterns
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Table Cell Content Patterns

## Rule

Table cells must use the approved RHOAI content cell patterns. Descriptions within cells must be truncated when they exceed 2 rows. When a cell has no value, display a dash character (`-`), not empty space or "N/A".

### RHOAI Custom Cell Types

In addition to PatternFly's default cell components, RHOAI uses these custom cell designs:

| Cell Type | Contents | Use Case |
|-----------|----------|----------|
| Link + External + Help + Description | Linked resource name, external link icon, help icon, description text (truncated at 2 rows) | Primary resource cells with external documentation |
| Link + Help + User + Description | Linked resource name, help icon, username, description text (truncated at 2 rows) | Resource cells showing ownership |
| Link + Help | Linked text (truncated if too long), help icon | Simple linked resources with contextual help |
| Timestamp | Date/time string | Created, modified, or last-active columns |
| Resource + Label | Resource name with a PatternFly Label below it | Resources with status or category labels |
| No value | Dash character (`-`) | Cells where no data exists |
| Status with latest state (horizontal) | Status Label + latest state text on the same line | Compact status display |
| Status with latest state (vertical) | Status Label above, latest state text below | Status display when horizontal space is limited |

### Compound Expandable Status Cells

For cells showing resource counts with expandable detail (e.g., running/stopped counts in project tables):

| State | Resources | Appearance |
|-------|-----------|-----------|
| Default | Filled | Play icon + running count, stop icon + stopped count |
| Default | No resources | Play icon + 0, stop icon + 0 |
| Default | Only Running | Play icon + count, stop icon + 0 |
| Default | Only Stopped | Play icon + 0, stop icon + count |
| Selected | (any) | Blue highlight background on the cell |

## Description Truncation

Cell descriptions must be truncated at **2 rows maximum**. Use CSS line clamping:

```css
.cell-description {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
```

## Rationale

Consistent cell patterns make tables scannable. When descriptions overflow beyond 2 rows, they push other cells out of alignment and disrupt the visual grid. The dash character for empty values provides a clear signal that data is absent (as opposed to empty space which could be a rendering bug).

## Examples

### ✅ Correct: Description truncated at 2 rows

```tsx
<Td>
  <div>
    <a href={resourceUrl}>{resource.name}</a>
    <ExternalLinkAltIcon />
    <Popover bodyContent={resource.helpText}>
      <OutlinedQuestionCircleIcon />
    </Popover>
  </div>
  <div className="pf-v6-u-color-200" style={{
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden'
  }}>
    {resource.description}
  </div>
</Td>
```

### ✅ Correct: No value shown as dash

```tsx
<Td>{resource.owner || '-'}</Td>
```

### ✅ Correct: Resource + Label cell

```tsx
<Td>
  <div>{resource.name}</div>
  <Label color="blue" isCompact>{resource.category}</Label>
</Td>
```

### ✅ Correct: Status with latest state (horizontal)

```tsx
<Td>
  <Flex>
    <Label color="blue" icon={<InProgressIcon />} isCompact>
      Starting
    </Label>
    <FlexItem>
      <span className="pf-v6-u-color-200">Oauth proxy container started</span>
    </FlexItem>
  </Flex>
</Td>
```

### ❌ Incorrect: Unbounded description

```tsx
<Td>
  <a href={url}>{name}</a>
  <p>{description}</p>  {/* Can grow to any height */}
</Td>
```

### ❌ Incorrect: Empty cell with no indicator

```tsx
<Td>{resource.owner}</Td>  {/* Renders empty space if owner is undefined */}
```

### ❌ Incorrect: "N/A" instead of dash

```tsx
<Td>{resource.owner || 'N/A'}</Td>
```

## Automated Checks

**Find cells that may have unbounded descriptions:**
```bash
# Table cells with description-like content (review for truncation)
grep -rn "description" --include="*.tsx" src/ | grep -i "Td\|table\|cell"
```

**Find empty value handling in table cells:**
```bash
# Look for N/A or n/a in table context (should be dash)
grep -rn "N/A\|n/a\|N\/A" --include="*.tsx" src/ | grep -i "Td\|table\|cell"
```

**Find line-clamp usage (correct truncation pattern):**
```bash
# Verify line-clamp is used for description truncation
grep -rn "line-clamp\|lineClamp\|WebkitLineClamp" --include="*.tsx" --include="*.css" --include="*.scss" src/
```

**Find external link icons in table cells:**
```bash
# ExternalLinkAltIcon usage in table context
grep -rn "ExternalLinkAltIcon\|ExternalLinkSquareAltIcon" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] Cell descriptions are truncated at 2 rows maximum
- [ ] Empty cells display a dash (`-`), not blank space or "N/A"
- [ ] Link cells use the correct combination (link + external + help + description as needed)
- [ ] Timestamp cells display consistent date/time formatting
- [ ] Resource + Label cells show the label below the resource name
- [ ] Status cells with latest state use horizontal layout when space allows, vertical when constrained
- [ ] Compound expandable status cells show correct running/stopped icons and counts
- [ ] Help icons in cells use OutlinedQuestionCircleIcon (outlined, not filled)
