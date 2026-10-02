---
id: icon-style-consistency
title: Icon Style Consistency (Outlined vs Filled)
category: icons
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Icon Style Consistency (Outlined vs Filled)

## Rule

Use **outlined** icons for general UI elements and **filled** icons only for status/state indicators.

### Use Outlined Icons For:
- Navigation elements (folders, projects, files)
- Informational/help icons (question marks, lightbulbs)
- Decorative icons (stars, badges without status meaning)
- General actions (edit, view, settings - when not indicating state)
- Any icon that is part of the general UI chrome

### Use Filled Icons Only For:
- Status indicators (success, warning, error, info)
- State changes (in-progress, completed, failed)
- Alert/notification contexts
- Labels and badges that convey status

## Rationale

Consistent icon styling creates visual hierarchy. Outlined icons provide a lighter, more neutral appearance suitable for general UI elements. Filled icons naturally draw more attention and should be reserved for status indicators that require immediate user attention.

## Common Icons and Their Correct Style

| UI Element | ❌ Incorrect (Filled) | ✅ Correct (Outlined) |
|------------|----------------------|----------------------|
| Project/Folder | `FolderIcon` | `OutlinedFolderIcon` |
| Help/Info | `QuestionCircleIcon` | `OutlinedQuestionCircleIcon` |
| Ideas/Tips | `LightbulbIcon` | `OutlinedLightbulbIcon` |
| Favorites | `StarIcon` | `OutlinedStarIcon` |
| Calendar | `CalendarIcon` | `OutlinedCalendarAltIcon` |
| Clock/Time | `ClockIcon` | `OutlinedClockIcon` |

| Status/State | ✅ Correct (Filled) | ❌ Incorrect (Outlined) |
|--------------|---------------------|------------------------|
| Success | `CheckCircleIcon` | `OutlinedCheckCircleIcon` |
| Warning | `ExclamationTriangleIcon` | `OutlinedExclamationTriangleIcon` |
| Error | `ExclamationCircleIcon` | `OutlinedExclamationCircleIcon` |
| Info Alert | `InfoCircleIcon` | `OutlinedInfoCircleIcon` |

## Examples

### ✅ Correct: Outlined for UI Elements

```tsx
import { 
  OutlinedFolderIcon,
  OutlinedQuestionCircleIcon,
  OutlinedStarIcon 
} from '@patternfly/react-icons';

// Project selector
<MenuToggle icon={<OutlinedFolderIcon />}>
  Project X
</MenuToggle>

// Help popover trigger
<Button variant="plain" icon={<OutlinedQuestionCircleIcon />} />

// Favorite indicator (non-status)
<OutlinedStarIcon />
```

### ✅ Correct: Filled for Status/State

```tsx
import { 
  CheckCircleIcon,
  ExclamationTriangleIcon,
  InfoCircleIcon 
} from '@patternfly/react-icons';

// Success label
<Label color="green" icon={<CheckCircleIcon />}>
  Active
</Label>

// Warning alert
<Alert 
  variant="warning"
  title="Resource limit approaching"
  icon={<ExclamationTriangleIcon />}
/>

// Info popover (status context)
<Popover bodyContent="API key has no expiration">
  <Button icon={<InfoCircleIcon />} />
</Popover>
```

### ❌ Incorrect: Filled for General UI

```tsx
// Don't use filled icons for general UI elements
import { FolderIcon, QuestionCircleIcon, StarIcon } from '@patternfly/react-icons';

<MenuToggle icon={<FolderIcon />}>Project X</MenuToggle>  // ❌
<Button icon={<QuestionCircleIcon />} />                   // ❌
<StarIcon />                                               // ❌
```

## Information Icon: Popover and Placement Rules

The outlined question-circle icon (`OutlinedQuestionCircleIcon`) has additional usage requirements beyond style consistency:

**Interaction:** Information icons must always trigger a **popover**, not a tooltip. Popovers provide richer content and are dismissible, while tooltips are for brief labels only.

**Placement — use information icons next to:**
- Page titles
- Section headings (e.g., "Workbenches", "Pipelines")
- Complex form fields or settings

### ✅ Correct: Info Icon Triggering a Popover

```tsx
import { OutlinedQuestionCircleIcon } from '@patternfly/react-icons';

<Popover bodyContent="Projects allow you to organize resources.">
  <Button variant="plain" icon={<OutlinedQuestionCircleIcon />} />
</Popover>
```

### ❌ Incorrect: Info Icon Triggering a Tooltip

```tsx
<Tooltip content="Projects allow you to organize resources.">
  <Button variant="plain" icon={<OutlinedQuestionCircleIcon />} />
</Tooltip>
```

## Current Violations

**Using filled icons instead of outlined:**
- `src/app/ObserveMonitor/WorkloadMetrics/WorkloadMetrics.tsx` - `FolderIcon` (should be `OutlinedFolderIcon`)
- `src/app/GenAIStudio/Playground/Playground.tsx` - `FolderIcon` and `LightbulbIcon`
- `src/app/GenAIStudio/PromptEngineering/PromptEngineering.tsx` - `FolderIcon`
- `src/app/components/ContextPanel/SourcesTab.tsx` - `FolderIcon`
- `src/app/AppLayout/AppLayout.tsx` - `QuestionCircleIcon` (should be `OutlinedQuestionCircleIcon`)
- `src/app/FeatureFlags/FeatureFlags.tsx` - `StarIcon` (should be `OutlinedStarIcon`)

## Automated Checks

**Search for filled icons in general UI contexts:**
```bash
# Find filled folder icons (should be outlined)
grep -rn "FolderIcon" --include="*.tsx" src/ | grep -v "Outlined" | grep -v "FolderOpen" | grep -v "import"

# Find filled question icons (should be outlined)
grep -rn "QuestionCircleIcon" --include="*.tsx" src/ | grep -v "Outlined" | grep -v "import"

# Find filled star icons (should be outlined)
grep -rn "StarIcon" --include="*.tsx" src/ | grep -v "Outlined" | grep -v "import"

# Find filled lightbulb icons (should be outlined)
grep -rn "LightbulbIcon" --include="*.tsx" src/ | grep -v "Outlined" | grep -v "import"
```

**Find info icons used with tooltips instead of popovers:**
```bash
# OutlinedQuestionCircleIcon inside a Tooltip (should be Popover)
grep -rn "Tooltip" --include="*.tsx" src/ | grep "QuestionCircle"
```

**Exceptions (filled icons are correct):**
```bash
# These filled icons are intentional for status/state
grep -r "CheckCircleIcon\|ExclamationCircleIcon\|InfoCircleIcon\|ExclamationTriangleIcon" --include="*.tsx" src/
```

## Manual Review Checklist

- [ ] All folder/project icons are outlined style
- [ ] All question/help icons are outlined style
- [ ] All decorative icons (stars, lightbulbs) are outlined style
- [ ] Status/alert icons (check, warning, error, info) use filled style
- [ ] Icons match their semantic meaning (outlined = neutral, filled = status)
- [ ] No mixing of outlined and filled styles for the same icon type
- [ ] Information icons (OutlinedQuestionCircleIcon) trigger popovers, not tooltips
- [ ] Information icons are placed next to page titles, section headings, or complex form fields
