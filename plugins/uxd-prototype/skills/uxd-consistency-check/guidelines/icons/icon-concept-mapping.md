---
id: icon-concept-mapping
title: Icon-to-Concept Mapping
category: icons
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Icon-to-Concept Mapping

## Rule

Each RHOAI concept must use its designated icon. Do not substitute icons between concepts or introduce new icons without updating the design specification.

The canonical mapping is enforced through `typedObjectImage()` in `frontend/src/concepts/design/utils.ts` for header/card contexts, and through the `images/icons/` TypeScript icons for Standard-size usage.

## Standard Icons (32px+)

Used for page headers, informative cards, and selectable cards.

| Concept | Icon File | Icon Name |
|---------|-----------|-----------|
| Project | `images/icons/ProjectIcon.ts` | Folder |
| Data Connections | `images/icons/DataConnectionIcon.ts` | Data connections |
| Storage | `images/icons/StorageIcon.ts` | Storage stack |
| Storage Class | `images/icons/StorageClassIcon.ts` | Storage class |
| Pipelines | `images/icons/PipelineIcon.ts` | Path |
| Pipeline Runs | `images/icons/PipelineRunIcon.ts` | Run |
| Experiments | `images/icons/ExperimentIcon.ts` | Erlenmeyer flask |
| Workbenches | `images/icons/BuildIcon.ts` (ScrewWrenchIcon) | Wrench |
| Deployments | `images/icons/DeployedModelIcon.ts` | Rocket |
| Model | `images/icons/ModelIcon.ts` | AI model |
| Registered Models | `images/icons/RegisteredModelIcon.ts` | AI model (validated) |
| Model Servers | `images/icons/ModelServerIcon.ts` | Server stack |
| Model Catalog | `images/icons/ModelCatalogIcon.ts` | Collection |
| Model Registry | `images/icons/ModelRegistryIcon.ts` | Clipboard checklist |
| Single Model | `images/icons/SingleModelIcon.ts` | App |
| Multi Model | `images/icons/MultiModelIcon.ts` | Multiple apps |
| Distributed Workloads | `images/icons/DistributedWorkloadIcon.ts` | Analysis |
| Hardware Profiles | `images/icons/HardwareProfileIcon.ts` | Scale (growing) |
| Artifacts | `images/icons/ArtifactIcon.ts` | Platform |
| Enabled Applications | `images/icons/EnabledApplicationsIcon.ts` | Checked checkbox |
| Explore Applications | `images/icons/ExploreApplicationsIcon.ts` | Magnifying glass |
| Cluster Settings | `images/icons/ClusterSettingsIcon.ts` | Cluster |
| Permissions | `images/icons/PermissionsIcon.ts` | Single sign on |
| User | `images/icons/UserIcon.ts` | User |
| Group | `images/icons/GroupIcon.ts` | Community (people) |
| Notebook Images | `images/icons/NotebookImageIcon.ts` | Developer |
| Serving Runtimes | `images/icons/ServingRuntimeIcon.ts` | Sys admin |
| Resources / Learn | `images/icons/ResourcesIcon.ts` | Book |
| Lab Tuning | `images/icons/LabTuningIcon.ts` | Control panel |
| Model Evaluation | `images/icons/ModelEvaluationIcon.ts` | Evaluations |
| Checklist / Task Assistant | `images/icons/ChecklistIcon.ts` | Checklist |
| Prompt Management | `images/icons/PromptManagementIcon.ts` | Prompt management |
| MCP Catalog | `images/icons/McpCatalogIcon.ts` | MCP catalog |

## UI Icons (up to 24px)

Used for navigation, selectors, tables, and labels.

| Concept | SVG File | Icon Name |
|---------|----------|-----------|
| Project (selector) | `UI_icon-Red_Hat-Folder-RGB.svg` | Folder |
| Workbench | `UI_icon-Red_Hat-Wrench-RGB.svg` | Build/Wrench |
| Pipelines | `UI_icon-Red_Hat-Branch-RGB.svg` | Branch |
| Pipeline Runs | `UI_icon-Red_Hat-Double_arrow_right-RGB.svg` | Double arrow |
| Cluster Storage | `UI_icon-Red_Hat-Storage-RGB.svg` | Storage |
| Model Server | `UI_icon-Red_Hat-Server-RGB.svg` | Server |
| Deployed Models | `UI_icon-Red_Hat-Cubes-RGB.svg` | Cubes |
| Deploying Models | `UI_icon-Red_Hat-Server_upload-RGB.svg` | Server upload |
| Data Connections | `UI_icon-Red_Hat-Connected-RGB.svg` | Connected |
| User | `UI_icon-Red_Hat-User-RGB.svg` | User |
| Group | `UI_icon-Red_Hat-Shared_workspace-RGB.svg` | Shared workspace |
| Model Registry (selector) | `UI_icon-Red_Hat-Registered.svg` | Registered |
| Registered Models | `Icon-Red_Hat-Layered_A_Black-RGB.svg` | Layered A |

## Navigation Icons (14px via NavIcon)

| Concept | TypeScript File |
|---------|----------------|
| Home | `images/icons/HomeNavIcon.ts` |
| Develop and Train | `images/icons/DevelopAndTrainNavIcon.ts` |
| AI Hub | `images/icons/AiHubNavIcon.ts` |
| Applications | `images/icons/ApplicationsNavIcon.ts` |
| Observe & Monitor | `images/icons/ObserveAndMonitorNavIcon.ts` |
| Settings | `images/icons/SettingsNavIcon.ts` |
| Learning Resources | `images/icons/LearningResourcesNavIcon.ts` |
| Projects | `images/icons/ProjectsNavIcon.ts` |

## `typedObjectImage()` Mapping (utils.ts)

This function is the canonical source for which SVG image a `ProjectObjectType` maps to in header/card contexts:

| ProjectObjectType | Image Import |
|-------------------|-------------|
| `project`, `projectContext` | `UI_icon-Red_Hat-Folder-RGB.svg` |
| `notebook` | `UI_icon-Red_Hat-Wrench-RGB.svg` |
| `pipeline`, `pipelineSetup` | `UI_icon-Red_Hat-Branch-RGB.svg` |
| `pipelineRun` | `UI_icon-Red_Hat-Double_arrow_right-RGB.svg` |
| `clusterStorage` | `UI_icon-Red_Hat-Storage-RGB.svg` |
| `modelServer` | `UI_icon-Red_Hat-Server-RGB.svg` |
| `registeredModels` | `Icon-Red_Hat-Layered_A_Black-RGB.svg` |
| `deployedModels`, `connectedModels` | `UI_icon-Red_Hat-Cubes-RGB.svg` |
| `deployingModels` | `UI_icon-Red_Hat-Server_upload-RGB.svg` |
| `dataConnection`, `connections` | `UI_icon-Red_Hat-Connected-RGB.svg` |
| `user` | `UI_icon-Red_Hat-User-RGB.svg` |
| `group` | `UI_icon-Red_Hat-Shared_workspace-RGB.svg` |
| `modelRegistryContext` | `UI_icon-Red_Hat-Registered.svg` |

## Rationale

Consistent icon-to-concept mapping enables users to build spatial memory — seeing a Folder icon always means "Project," a Wrench always means "Workbench." Deviating from this mapping creates confusion and breaks the product's visual language.

## Examples

### ✅ Correct: Using the established mapping

```tsx
import HeaderIcon from '#~/concepts/design/HeaderIcon';
import { ProjectObjectType, SectionType } from '#~/concepts/design/utils';

// Project header → Folder icon (handled by typedObjectImage internally)
<HeaderIcon type={ProjectObjectType.project} sectionType={SectionType.organize} />

// Pipeline header → Branch icon
<HeaderIcon type={ProjectObjectType.pipeline} sectionType={SectionType.training} />
```

### ❌ Incorrect: Using wrong icon for a concept

```tsx
// Don't use a generic icon when a specific one is designated
import { CubesIcon } from '@patternfly/react-icons';

// Deployed models should use DeployedModelIcon or the Cubes SVG via typedObjectImage,
// not a random PF CubesIcon
<CubesIcon /> Deployed Models
```

### ❌ Incorrect: Bypassing typedObjectImage for a mapped concept

```tsx
// Don't import SVGs directly when typedObjectImage handles the mapping
import storageImg from '#~/images/UI_icon-Red_Hat-Storage-RGB.svg';

// Instead, use:
// <HeaderIcon type={ProjectObjectType.clusterStorage} />
<img src={storageImg} style={{ width: 40 }} />
```

## Automated Checks

**Verify typedObjectImage covers all expected ProjectObjectTypes:**
```bash
# List ProjectObjectType values that don't appear in typedObjectImage
grep "ProjectObjectType\." --include="utils.ts" src/concepts/design/ | grep -v "typedObjectImage" | grep -v "typedIconColor\|typedBackgroundColor\|typedColor\|typedEmptyImage\|sectionType" | grep "case "
```

**Find direct SVG imports that should use typedObjectImage instead:**
```bash
# Files importing UI_icon SVGs directly for header-like contexts
grep -rn "import.*UI_icon-Red_Hat\|import.*Icon-Red_Hat" --include="*.tsx" src/
```

**Find icon component usage that doesn't match expected concept:**
```bash
# Find ProjectIcon used outside of project-related contexts
grep -rn "ProjectIcon\|FolderIcon" --include="*.tsx" src/ | grep -v "project\|Project" | grep -v "import\|images/icons"
```

**Exceptions (correct direct SVG imports):**
```bash
# utils.ts is the canonical location for typedObjectImage SVG mappings
grep -rn "import.*UI_icon-Red_Hat\|import.*Icon-Red_Hat" --include="*.tsx" src/concepts/design/utils
```

## Manual Review Checklist

- [ ] Every concept in the tables above uses its designated icon — no substitutions
- [ ] `typedObjectImage()` in `utils.ts` matches the spec mappings
- [ ] New concepts get assigned an icon and are added to `typedObjectImage()`
- [ ] No "generic" PF icons are used when a specific Brand icon exists for the concept
- [ ] Navigation icons use the correct `*NavIcon.ts` component via `NavIcon`
- [ ] Icon requests for new concepts follow the process in the design doc
