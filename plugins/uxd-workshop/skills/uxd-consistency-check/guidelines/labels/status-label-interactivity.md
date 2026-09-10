---
id: status-label-interactivity
title: Status Label Interactivity
category: labels
automatable: true
checkpoints: [local, mr, signoff]
severity: warning
---

# Status Label Interactivity

## Rule

Status labels must clearly distinguish between interactive and non-interactive states using PatternFly label variants:

- **Interactive status labels** (clickable, reveal details) → Use `variant="filled"` (solid background)
- **Non-interactive status labels** (static, informational) → Use `variant="outline"` (outlined border)

Interactive labels should have click handlers (onClick, component props like `isClickable`) and use pointer cursor. Non-interactive labels should have no click handlers and use default cursor.

## Rationale

Visual affordance eliminates "click-searching" behavior where users cannot distinguish between static information and interactive elements. The solid background mimics a button-like appearance, providing a clear cue for interaction, while the outlined style signals secondary, static indicators.

This reduces cognitive load and increases user confidence by ensuring consistent interaction patterns across the platform.

## Visual Pattern

| Feature | Interactive | Non-Interactive |
|---------|-------------|-----------------|
| **Style** | PatternFly filled (solid) label | PatternFly unfilled (outlined) label |
| **Visual Weight** | High | Low |
| **Cursor** | Pointer/Hand | Default Arrow |
| **Hover State** | Yes | No |
| **Click Behavior** | Opens popover or modal with details | None (static) |

## Choosing Interactive vs Non-Interactive

The RHOAI status component provides both interactive (filled) and non-interactive (outlined) variants for **all 22 statuses**. The variant is a context-driven decision, not a status-specific one. Choose based on whether the label has actionable detail to reveal.

**Use filled (interactive) when** the status label opens a popover, modal, or detail panel — e.g., showing error logs, progress events, or eviction reasons.

**Use outlined (non-interactive) when** the status is purely informational with no drill-down.

### Typical Patterns

In practice, some statuses are more commonly interactive than others:

| Commonly Interactive (filled) | Why |
|-------------------------------|-----|
| Failed | Users need to see error details |
| Running | Users may want to view live logs |
| Starting | Users may want to see initialization events |
| Stopping | Users may want to see shutdown logs |
| Evicted | Users need the eviction reason |
| Preempted | Users need preemption details |
| Inadmissible | Users need admission error details |

| Commonly Non-Interactive (outlined) | Why |
|-------------------------------------|-----|
| Ready, Complete, Cached, Skipped | Terminal success — no further action |
| Stopped, Canceled, Paused | Intentional state — details are usually elsewhere |
| Queued, Admitted, Unknown | Waiting/unknown — typically no actionable detail to reveal |

**These are defaults, not rules.** The same status (e.g., "Running") may be interactive in one context (showing live logs in a workbench table) and non-interactive in another (a summary card). Always match the variant to the actual interactivity of the label in its specific context.

## Status + Descriptor Pattern

When a status label needs to show additional context (e.g., the latest Kubernetes state or a sub-status message), use the **Status + descriptor** compound pattern: the status label above, with a descriptor text line below.

### Descriptor Text Color Rules

The descriptor text color must match the severity of the parent status:

| Parent Status Severity | Descriptor Text Color | Example |
|------------------------|----------------------|---------|
| Error (Failed) | Red text (`--pf-v6-global--danger-color--status`) | "Assign pod" |
| Warning (Starting with non-critical alert) | Yellow/orange text (`--pf-v6-global--warning-color--status`) | "Oauth proxy container started" |
| Normal transitional (Starting, Queued) | Default secondary text color (`--pf-v6-global--Color--200`) | "Pulling container image" |

### Examples

#### ✅ Correct: Status with descriptor (normal)

```tsx
<div>
  <Label variant="filled" color="blue" icon={<InProgressIcon />}>
    Starting
  </Label>
  <span className="pf-v6-u-color-200 pf-v6-u-font-size-sm">
    Pulling container image
  </span>
</div>
```

#### ✅ Correct: Status with descriptor (warning — yellow text)

```tsx
<div>
  <Label variant="filled" color="blue" icon={<InProgressIcon />}>
    Starting
  </Label>
  <span style={{ color: 'var(--pf-v6-global--warning-color--status)' }}
        className="pf-v6-u-font-size-sm">
    Oauth proxy container started
  </span>
</div>
```

#### ✅ Correct: Status with descriptor (error — red text)

```tsx
<div>
  <Label variant="filled" color="red" icon={<ExclamationCircleIcon />}>
    Failed
  </Label>
  <span style={{ color: 'var(--pf-v6-global--danger-color--status)' }}
        className="pf-v6-u-font-size-sm">
    Assign pod
  </span>
</div>
```

#### ❌ Incorrect: Descriptor color doesn't match status severity

```tsx
<div>
  <Label variant="filled" color="red" icon={<ExclamationCircleIcon />}>
    Failed
  </Label>
  <span className="pf-v6-u-color-200">  {/* Should be red, not gray */}
    Assign pod
  </span>
</div>
```

## Examples

### ✅ Correct: Interactive status with filled variant

```tsx
<Label
  variant="filled"
  color="red"
  icon={<ExclamationCircleIcon />}
  onClick={handleShowErrorDetails}
  style={{ cursor: 'pointer' }}
>
  Failed
</Label>
```

### ✅ Correct: Non-interactive status with outline variant

```tsx
<Label
  variant="outline"
  color="green"
  icon={<CheckCircleIcon />}
>
  Complete
</Label>
```

### ❌ Incorrect: Interactive status with outline variant

```tsx
// Don't use outline for clickable status
<Label
  variant="outline"
  color="red"
  onClick={handleShowErrorDetails}
>
  Failed
</Label>
```

### ❌ Incorrect: Non-interactive status with filled variant

```tsx
// Don't use filled for static status
<Label
  variant="filled"
  color="green"
>
  Complete
</Label>
```

### ❌ Incorrect: Filled label without click handler

```tsx
// Filled variant signals interactivity but has no onClick
<Label
  variant="filled"
  color="blue"
>
  Running
</Label>
```

## Automated Checks

**Find filled labels without click handlers (missing interactivity):**
```bash
# Find Label components with variant="filled" that lack onClick or isClickable
grep -rn "variant=\"filled\"" --include="*.tsx" src/ | grep -v "onClick\|isClickable\|component="
```

**Find labels with click handlers but outline variant (wrong affordance):**
```bash
# Find Label components with onClick but variant="outline"
grep -rn "variant=\"outline\"" --include="*.tsx" src/ | grep "onClick"
```

**Exceptions (correct usage of filled without explicit onClick):**
```bash
# Label components that accept click props via component prop or wrapper
grep -rn "variant=\"filled\"" --include="*.tsx" src/ | grep "component=\|isClickable=\{true\}"
```

**Find status descriptors with hardcoded colors (should use tokens):**
```bash
# Descriptor text near status labels using hardcoded colors instead of CSS variables
grep -rn "color:" --include="*.tsx" src/ | grep -i "status\|descriptor\|latest.state" | grep -v "var(--pf"
```

## Manual Review Checklist

- [ ] All clickable status labels use `variant="filled"`
- [ ] All static informational labels use `variant="outline"`
- [ ] Filled labels have visible cursor change (pointer) on hover
- [ ] Filled labels open popovers/modals with relevant details
- [ ] Outline labels have no hover state or click behavior
- [ ] The variant choice matches actual interactivity in context (not assumed from status name)
- [ ] Status + descriptor patterns use correct descriptor text color (red for Failed, yellow for warnings, gray for normal)
- [ ] Descriptor text uses PatternFly CSS tokens, not hardcoded colors
- [ ] Color and icon combinations follow the standard palette (green=success, red=danger, yellow=warning, blue=in-progress, gray=neutral)
