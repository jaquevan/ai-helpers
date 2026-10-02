---
id: status-label-colors-icons
title: Status Label Colors and Icons
category: labels
automatable: true
automation_result: candidate
checkpoints: [local, mr, signoff]
severity: warning
---

# Status Label Colors and Icons

## Rule

Each standardized status must use its designated color and icon combination. Do not deviate from the approved palette.

## Standard Status Colors and Icons

### Success States (Green)

| Status | Color | Icon |
|--------|-------|------|
| Ready | green | CheckCircleIcon |
| Complete | green | CheckCircleIcon |
| Cached | green | WindowRestoreIcon |
| Skipped | green | AngleDoubleRightIcon |

### Warning States (Yellow)

| Status | Color | Icon |
|--------|-------|------|
| Inadmissible | yellow/orange | ExclamationTriangleIcon |
| Evicted | yellow/orange | ExclamationTriangleIcon |
| Preempted | yellow/orange | ExclamationTriangleIcon |
| Unavailable | yellow/orange | ExclamationTriangleIcon |

### Error States (Red)

| Status | Color | Icon |
|--------|-------|------|
| Failed | red | ExclamationCircleIcon |

### In-Progress States (Blue)

| Status | Color | Icon |
|--------|-------|------|
| Starting | blue | InProgressIcon |
| Running | blue | InProgressIcon |

### Pending States (Purple)

| Status | Color | Icon |
|--------|-------|------|
| Pending | purple | PendingIcon |
| New | purple | (none) |

### Neutral/Stopped States (Gray)

| Status | Color | Icon |
|--------|-------|------|
| Paused | gray | PauseCircleIcon |
| Stopping | gray | InProgressIcon |
| Stopped | gray | OffIcon |
| Canceling | gray | InProgressIcon |
| Canceled | gray | BanIcon |
| Deleting | gray | InProgressIcon |
| Queued | gray | ClockIcon |
| Admitted | gray | CheckIcon |
| Unknown | gray | QuestionCircleIcon (outline) |

## Rationale

Consistent color-icon pairings create a visual language that users can learn once and apply everywhere. When "Failed" is always red with an exclamation-circle icon, users instantly recognize error states without reading the text.

Deviating from these mappings forces users to relearn status meanings in different contexts, increasing cognitive load.

## Examples

### ✅ Correct: Standard color and icon

```tsx
<Label
  variant="outline"
  color="green"
  icon={<CheckCircleIcon />}
>
  Complete
</Label>

<Label
  variant="filled"
  color="red"
  icon={<ExclamationCircleIcon />}
  onClick={handleShowError}
>
  Failed
</Label>

<Label
  variant="filled"
  color="blue"
  icon={<InProgressIcon />}
>
  Running
</Label>
```

### ❌ Incorrect: Wrong color for status

```tsx
// Don't use blue for success states
<Label
  variant="outline"
  color="blue"
  icon={<CheckCircleIcon />}
>
  Complete
</Label>
```

### ❌ Incorrect: Wrong icon for status

```tsx
// Don't use CheckIcon for failed states
<Label
  variant="filled"
  color="red"
  icon={<CheckIcon />}
>
  Failed
</Label>
```

### ❌ Incorrect: Missing required icon

```tsx
// Running status should have InProgressIcon
<Label
  variant="filled"
  color="blue"
>
  Running
</Label>
```

## Automated Checks

**Find Failed status with wrong color or icon:**
```bash
# Failed should be red with ExclamationCircleIcon
grep -rn ">Failed<" --include="*.tsx" src/ | grep -v "color=\"red\"\|color='red'"
grep -rn ">Failed<" --include="*.tsx" src/ -B 3 | grep -v "ExclamationCircleIcon"
```

**Find Complete/Ready status with wrong color or icon:**
```bash
# Complete and Ready should be green with CheckCircleIcon
grep -rn ">Complete<\|>Ready<" --include="*.tsx" src/ | grep -v "color=\"green\"\|color='green'"
grep -rn ">Complete<\|>Ready<" --include="*.tsx" src/ -B 3 | grep -v "CheckCircleIcon"
```

**Find Running/Starting status with wrong color or icon:**
```bash
# Running and Starting should be blue with InProgressIcon
grep -rn ">Running<\|>Starting<" --include="*.tsx" src/ | grep -v "color=\"blue\"\|color='blue'"
grep -rn ">Running<\|>Starting<" --include="*.tsx" src/ -B 3 | grep -v "InProgressIcon"
```

**Find Pending status with wrong color or icon:**
```bash
# Pending should be purple with PendingIcon
grep -rn ">Pending<" --include="*.tsx" src/ | grep -v "color=\"purple\"\|color='purple'"
grep -rn ">Pending<" --include="*.tsx" src/ -B 3 | grep -v "PendingIcon"
```

**Exceptions (custom status components with correct mappings):**
```bash
# StatusLabel or custom components that handle color/icon internally
grep -rn "StatusLabel\|<Status" --include="*.tsx" src/ | grep "status="
```

## Manual Review Checklist

- [ ] All "Failed" labels are red with ExclamationCircleIcon
- [ ] All "Complete" and "Ready" labels are green with CheckCircleIcon
- [ ] All "Running" and "Starting" labels are blue with InProgressIcon
- [ ] All "Pending" labels are purple with PendingIcon
- [ ] All warning states (Inadmissible, Evicted, Preempted, Unavailable) are yellow with ExclamationTriangleIcon
- [ ] All neutral/stopped states use gray color
- [ ] Icons match the approved icon for each status
- [ ] No hardcoded hex colors are used (use PatternFly semantic color tokens)
