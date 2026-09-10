---
id: cta-button-icons
title: CTA Button Icons
category: components
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# CTA Button Icons

## Rule

Primary "Create" action buttons should **not** include icons. Use text-only labels like "Create project", "Create policy", or "Create API key".

Reserve plus icons (`PlusIcon`, `PlusCircleIcon`) for inline or secondary "add" actions within forms, modals, or tables.

## Rationale

Consistent button styling helps users quickly identify primary actions. Icons on primary CTAs add visual noise without improving clarity—the text label is sufficient. Plus icons are better suited for smaller, inline add actions where space is constrained or the action is repetitive.

## When to Use Icons

**Do NOT use icons for:**
- Page-level primary "Create" buttons
- Modal primary "Create" buttons
- Main action buttons in toolbars

**DO use icons for:**
- Inline "add" actions within forms (e.g., "Add row", "Add filter")
- Secondary actions (e.g., icon-only buttons in table rows)
- Repeatable add actions in lists or configuration panels

## Examples

### ✅ Correct

**Primary Create button (no icon):**
```tsx
<Button variant="primary" onClick={handleCreate}>
  Create project
</Button>
```

**Inline add action (with icon):**
```tsx
<Button 
  variant="secondary" 
  icon={<PlusCircleIcon />}
  onClick={handleAddRow}
>
  Add row
</Button>
```

### ❌ Incorrect

**Primary Create button with icon:**
```tsx
// Don't do this
<Button 
  variant="primary" 
  icon={<PlusIcon />}
  onClick={handleCreate}
>
  Create policy
</Button>
```

## Current Violations

The following files currently violate this guideline:
- `src/app/Settings/Policies/Policies.tsx:` - "Create policy" button has `<PlusIcon />`
- `src/app/Settings/MCPResources/MCPResources.tsx:` - "Add source" button has `<PlusCircleIcon />`

## Automated Checks

**Search for files with primary buttons that might have plus icons:**
```bash
# Find files containing both primary buttons and plus icons, then show the icon lines
grep -l "variant=\"primary\"" --include="*.tsx" -r src/ | xargs grep -Hn "icon={<Plus"
```

**Exceptions (correct plus icon usage):**
```bash
# Secondary/tertiary buttons with plus icons are allowed (inline add actions)
grep -l "variant=\"secondary\"\|variant=\"tertiary\"" --include="*.tsx" -r src/ | xargs grep -Hn "icon={<Plus"
```

**Pattern to detect:**
- `variant="primary"` + `icon={<PlusIcon` or `icon={<PlusCircleIcon`
- Button text contains "Create" or "Add" (for page-level actions)

**Note:** This check flags files that contain both primary buttons and plus icons. The exception filters out icons that are on secondary/tertiary buttons. Files with both primary buttons (without icons) and secondary buttons (with icons) will be correctly filtered.

## Manual Review Checklist

**Helper command - find primary Create/Add buttons to review for icon usage:**
```bash
# Find primary Create/Add buttons (review these manually for icon usage)
grep -rn "variant=\"primary\"" --include="*.tsx" src/ | grep -E "Create|Add"
```

- [ ] All primary "Create" buttons are text-only (no icons)
- [ ] Plus icons are only used for inline/secondary add actions
- [ ] Button labels are clear and descriptive without relying on icons
- [ ] Icon usage is consistent across similar action types
