---
id: table-column-headers
title: Table Column Headers
category: tables
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Table Column Headers

## Rule

Table column headings must never be truncated. Display the full header text, allowing it to wrap to multiple rows for long labels. RHOAI uses a custom column header component instead of the default PatternFly header cell, which has a fixed size that causes awkward wrapping even for relatively short headers.

### Column Header States

| State | Appearance |
|-------|-----------|
| Default | Black text, sort icon (neutral), optional help icon |
| Hover | Text darkens, sort icon becomes visible/prominent |
| Sorted Ascending | Blue text, up arrow icon |
| Sorted Descending | Blue text, down arrow icon |
| Empty | No text, minimal height |

Both **Default** and **Compact** size variants exist. Compact headers have reduced vertical padding.

### Header Content Rules

- Display the **full column name** — do not truncate or ellipsis
- If the header text is long, allow it to **wrap to multiple lines**
- Sort icons appear inline after the header text
- Optional help icons (OutlinedQuestionCircleIcon) appear after the sort icon

## Rationale

Truncated column headers force users to hover or guess what data a column contains. Since headers are read once to orient the user and referenced repeatedly during data scanning, full visibility is critical. The RHOAI custom header component ensures text displays naturally without the fixed-width wrapping issues of the default PatternFly component.

## Examples

### ✅ Correct: Full header text displayed

```tsx
<Thead>
  <Tr>
    <Th sort={getSortParams(0)}>Name</Th>
    <Th sort={getSortParams(1)}>Registered deployments</Th>
    <Th sort={getSortParams(2)}>Last modified</Th>
    <Th
      info={{
        popover: "Owner who created this resource",
        ariaLabel: "Owner info"
      }}
    >
      Owner
    </Th>
  </Tr>
</Thead>
```

### ❌ Incorrect: Truncated header with ellipsis

```tsx
<Th style={{ maxWidth: '100px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
  Registered deployments
</Th>
```

### ❌ Incorrect: Abbreviated header text

```tsx
<Th>Reg. deploy.</Th>
```

## Automated Checks

**Find column headers with truncation styling:**
```bash
# Look for text truncation on Th elements
grep -rn "textOverflow\|text-overflow\|truncat" --include="*.tsx" src/ | grep -i "Th\|header\|thead"
```

**Find Th elements with maxWidth constraints:**
```bash
# Th elements with fixed widths that may cause truncation
grep -rn "maxWidth\|max-width" --include="*.tsx" src/ | grep -i "Th\|header\|thead"
```

**Find abbreviated header text patterns:**
```bash
# Short Th content that might be abbreviations (review manually)
grep -rn "<Th" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] All column headers display full text (no truncation or ellipsis)
- [ ] Long headers wrap to multiple lines rather than being cut off
- [ ] Sort icons appear inline after header text
- [ ] Help icons (if used) appear after sort icons
- [ ] No abbreviated column names used instead of full text
- [ ] Compact table headers have reduced padding but still show full text
- [ ] Custom RHOAI header component is used where available
