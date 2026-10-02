---
id: status-label-terminology
title: Status Label Terminology
category: labels
automatable: true
automation_result: candidate
checkpoints: [local, mr, signoff]
severity: warning
---

# Status Label Terminology

## Rule

Use standardized status terminology consistently across all resources. Do not introduce synonyms or non-standard terms for existing statuses.

The approved status terms are:
- **Success states**: Ready, Complete, Cached, Skipped, Admitted
- **Warning states**: Inadmissible, Evicted, Preempted, Unavailable
- **Error states**: Failed
- **In-progress states**: Starting, Running, Pending, New
- **Neutral/stopped states**: Paused, Stopping, Stopped, Canceling, Canceled, Deleting, Queued, Unknown

## Resource-Specific Status Mappings

Not every status applies to every resource type. Use only the statuses defined for each resource:

| Status | Distributed Workloads | Models & Deployments | Jobs | Model Transfer Jobs | Pipeline Runs | Workbenches | Model Registry Settings | Executions | Model Eval Runs |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Queued** | ✓ | | ✓ | | | | | ✓ | |
| **Pending** | ✓ | | ✓ | | ✓ | | | ✓ | ✓ |
| **New** | | | | | | | | ✓ | |
| **Admitted** | ✓ | | | | | | | | |
| **Starting** | | ✓ | | | | ✓ | ✓ | | |
| **Running** | ✓ | | ✓ | ✓ | ✓ | | | ✓ | ✓ |
| **Stopping** | | ✓ | | | | ✓ | ✓ | | |
| **Canceling** | | | | | ✓ | | | | |
| **Deleting** | | | ✓ | | | | | | |
| **Paused** | | | ✓ | | | | | | |
| **Ready** | | ✓ | | | | ✓ | ✓ | | |
| **Complete** | ✓ | | ✓ | ✓ | ✓ | | | ✓ | ✓ |
| **Cached** | | | | | ✓ | | | ✓ | |
| **Skipped** | | | | | ✓ | | | | |
| **Stopped** | | ✓ | | | | ✓ | | | |
| **Canceled** | | | | | | | | ✓ | ✓ |
| **Failed** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Inadmissible** | ✓ | | ✓ | | | | | | |
| **Evicted** | ✓ | | | | | | | | |
| **Preempted** | | | ✓ | | | | | | |
| **Unavailable** | | | | | | | ✓ | | |
| **Unknown** | | ✓ | | | | | | ✓ | |

### Lifecycle Categories

Each resource type groups its statuses into lifecycle phases:

- **Active / In-Progress**: The resource is doing work (Running, Starting, Pending)
- **Transitional / Attention**: Requires attention or may resolve itself (Inadmissible, Evicted, Preempted)
- **Terminal**: Final state, no further transitions (Complete, Failed)
- **Special**: Context-specific statuses (Cached, Skipped — pipeline-only)

## Rationale

Consistent terminology reduces cognitive load and prevents confusion when the same underlying process is described with varied terms. Users should see "Running" everywhere, not "In progress" in one place, "Active" in another, and "Executing" elsewhere.

Standardization across the platform enables users to build reliable mental models of system states. The resource-specific mappings ensure that only contextually valid statuses are used — for example, "Cached" should never appear on a Workbench, and "Admitted" only applies to Distributed Workloads.

## Common Violations

### ❌ Non-standard terms

| Don't Use | Use Instead |
|-----------|-------------|
| In progress | Running or Starting |
| Done | Complete |
| Finished | Complete |
| Active | Running or Ready |
| Executing | Running |
| Initializing | Starting |
| Terminating | Stopping |
| Removed | Deleted or Canceled |
| Succeeded | Complete |
| Error | Failed |
| Rejected | Inadmissible or Failed |

## Examples

### ✅ Correct: Standard terminology

```tsx
<Label variant="outline" color="green">
  Complete
</Label>

<Label variant="filled" color="blue">
  Running
</Label>

<Label variant="outline" color="red">
  Failed
</Label>
```

### ❌ Incorrect: Non-standard terminology

```tsx
// Don't use synonyms for standard statuses
<Label variant="outline" color="green">
  Done
</Label>

<Label variant="filled" color="blue">
  In progress
</Label>

<Label variant="outline" color="red">
  Error
</Label>
```

## Automated Checks

**Find non-standard status terms:**
```bash
# Check for common non-standard terms in Label components
grep -rn "<Label" --include="*.tsx" src/ | grep -E "In progress|Done|Finished|Active|Executing|Initializing|Terminating|Removed|Succeeded|Error[^s]|Rejected"
```

**Find standard terms (for validation):**
```bash
# Verify approved terms are being used
grep -rn "<Label" --include="*.tsx" src/ | grep -E "Running|Complete|Failed|Starting|Stopping|Stopped|Ready|Pending|Canceled|Paused"
```

## Manual Review Checklist

- [ ] All status labels use approved terminology from the standard list
- [ ] No synonyms or alternative phrasings are used (e.g., "Done" instead of "Complete")
- [ ] Status terminology is consistent across different resource types (workbenches, pipelines, models, etc.)
- [ ] Statuses used for each resource match the resource-specific mapping table (e.g., no "Cached" on Workbenches)
- [ ] New statuses have been approved by the E2E Consistency Working Group before implementation
