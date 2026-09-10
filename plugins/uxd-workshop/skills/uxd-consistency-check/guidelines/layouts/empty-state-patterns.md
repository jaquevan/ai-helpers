---
id: empty-state-patterns
title: Empty State Patterns
category: layouts
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Empty State Patterns

## Rule

Use the correct empty state pattern based on the context. Each category has specific requirements for icons/illustrations, text, and CTA button styling.

### 1. Creation Pages (Happy Path)

Pages where users can complete the **primary action** associated with the page (creating their first object of a given type).

- Use **brand illustrations** (not icons)
- Show heading: "Start by creating your \<object\>"
- Show descriptive body text
- Show **primary CTA button** (e.g., "Create project")
- **Do NOT show:** table structure, toolbar, or pagination

### 2. Configuration Needed

Before accessing creation pages, some configurations must be completed by the user (without needing an admin).

- Use the **fa-cog (gear/settings) icon** — NOT the wrench icon
- Show heading describing what needs to be configured (e.g., "Enable pipelines")
- Show body text explaining the configuration step
- Show **primary CTA button** (e.g., "Configure pipeline server")

### 3. Contact Admin

Users must contact an administrator for assistance. This involves a configuration issue the user cannot resolve on their own.

- Use the **"support" (headset) icon**
- Show heading (e.g., "Start by requesting a project")
- Show body text explaining they need to contact their admin
- CTA is **NOT a primary button** — use **link button styling** with a blue question-circle icon before the link text
- Example CTA: "Who's my administrator?" as a link that triggers a popover

### 4. Addition or Creation (Non-Primary)

When something needs to be added or created, but it is **not the primary action** associated with the page.

- Use a **"plus" icon only if there's no specific custom icon** for the object type
- Use a **custom icon** if one exists for the object type
- Show the **icon itself, not an illustration**
- There may be no CTA if the page has no primary action associated with it

### 5. Status Empty States

When displaying a status message instead of content. Use PatternFly status colors:

| Status | Icon | Color |
|--------|------|-------|
| Error | ExclamationCircleIcon | Red — when data cannot be retrieved due to a backend failure or error |
| Success | CheckCircleIcon | Green — when a task or process completed successfully |
| Warning | ExclamationTriangleIcon | Yellow/orange — when there is an issue (e.g., unsupported versions) |

Warning status empty states may include a primary CTA to resolve the issue (e.g., "Create pipeline server") and an informational link.

### 6. No Results (Filtered Empty State)

When a filter is applied but no data matches.

- Use the **search icon (magnifying glass)**
- Show heading: "No results found"
- Show body text: "Adjust your filters and try again."
- Show **"Clear all filters" as a link button** (not primary)
- **Keep visible:** toolbar with active filters, filter chips, table headers, pagination
- Table structure remains visible so users can adjust or clear their filter

### 7. Archived

When on an archived resource page with no archived items.

- Use the **archive (folder) icon**
- Show heading: "No archived \<objects\>"
- Show body text explaining what archiving does
- No primary CTA needed

### 8. Empty State for Tables Created Within a Row

Special case (e.g., Permissions tab) where multiple tables appear on a page, each initially empty.

- Show table headers immediately
- Display an **"Add \<something\>" link button** below the headers
- Clicking the link creates the first row, allowing users to fill in the columns
- No illustration or icon needed — the table structure provides context

### 9. Empty State for Cards

When a card tile needs to show an empty state.

- Use the **XS empty state** variant (PatternFly)
- Show concept icon + link text (e.g., folder icon + "Create project")
- For contact-admin variant: icon + heading question + description + "Who's my administrator?" link

### 10. Object Starting / Initializing

When a background process is initializing (e.g., starting a pipeline server).

- Show a **spinner** above the empty state text
- Show heading: "Starting \<object\>"
- Show body text explaining the initialization process
- Optionally show a "Learn more" link
- Variants: full page, tab, or card/tile context

## Icon and Illustration Selection

| Scenario | Visual | Example |
|----------|--------|---------|
| Creation page (primary action, happy path) | Brand illustration | Projects, Workbenches, API Keys |
| Configuration needed by user | fa-cog (gear) icon | Enable pipelines, Configure pipeline server |
| Contact admin | Support (headset) icon | Request a project, Request access to model registries |
| Addition (non-primary action) | Custom icon or "plus" fallback | Artifacts (custom icon), Metrics (plus icon) |
| No results from filter | Search (magnifying glass) icon | "No results found" in filtered table |
| Status: error | ExclamationCircleIcon (red) | Backend failure |
| Status: success | CheckCircleIcon (green) | Process completed |
| Status: warning | ExclamationTriangleIcon (yellow) | Unsupported version |
| Archived resource | Archive (folder) icon | No archived models |
| Object starting | Spinner | Pipeline server starting |
| Card empty state | XS empty state with concept icon | Create project card |

## Button Behavior

Empty state CTAs must follow these rules:

1. **Creation pages**: Use a **primary button** for the main action
2. **Configuration pages**: Use a **primary button** for the configuration action
3. **Contact admin**: Use **link button styling** (not primary or secondary) — present as a link in the body text with a question-circle icon
4. **No results**: Use **"Clear all filters" link** (not a primary button)
5. **Status with resolution**: Warning states may include a primary CTA to fix the issue
6. **Single CTA rule**: When there is only one CTA, present it as a **primary button** or as **a link in the body text** (per PatternFly guidelines) — do NOT use a secondary button alone without a primary

## Empty State with Labels

If a label provides relevant context, it can be added between the description and the CTA. Maintain **16px vertical spacing** between the label and the CTA.

Example: "Multi-model serving enabled" label shown between body text and "Add model server" button.

## Rationale

Empty states are critical onboarding moments. Creation pages guide new users directly to their first action with an inviting illustration. Configuration and contact-admin states clearly communicate what blocks progress and how to resolve it. Consistent icon and illustration usage across empty state categories helps users instantly recognize what type of action is needed.

Using the wrong visual (e.g., a happy-path illustration on a configuration-required page) confuses users about their current state. Using secondary buttons where primary or link styling is specified creates inconsistent visual hierarchy.

## Examples

### ✅ Correct: Creation Page Empty State

```tsx
<PageSection>
  <EmptyState variant="lg">
    <EmptyStateHeader
      titleText="Start by creating your project"
      icon={<EmptyStateIcon icon={ProjectIllustration} />}
      headingLevel="h1"
    />
    <EmptyStateBody>
      Projects allow you and your team to organize and collaborate on resources
      within separate namespaces.
    </EmptyStateBody>
    <EmptyStateFooter>
      <Button variant="primary" onClick={handleCreate}>
        Create project
      </Button>
    </EmptyStateFooter>
  </EmptyState>
</PageSection>
```

### ✅ Correct: Configuration Needed Empty State

```tsx
<PageSection>
  <EmptyState variant="lg">
    <EmptyStateHeader
      titleText="Enable pipelines"
      icon={<EmptyStateIcon icon={CogIcon} />}
      headingLevel="h1"
    />
    <EmptyStateBody>
      Pipelines are platforms for building and deploying portable and scalable
      machine-learning (ML) workflows. Before you can work with pipelines,
      you must first configure a pipeline server in your project.
    </EmptyStateBody>
    <EmptyStateFooter>
      <Button variant="primary" onClick={handleConfigure}>
        Configure pipeline server
      </Button>
    </EmptyStateFooter>
  </EmptyState>
</PageSection>
```

### ✅ Correct: Contact Admin Empty State

```tsx
<PageSection>
  <EmptyState variant="lg">
    <EmptyStateHeader
      titleText="Start by requesting a project"
      icon={<EmptyStateIcon icon={HeadsetIcon} />}
      headingLevel="h1"
    />
    <EmptyStateBody>
      Projects allow you and your team to organize and collaborate on resources
      within separate namespaces. To request a project, contact your administrator.
    </EmptyStateBody>
    <EmptyStateFooter>
      <Button
        variant="link"
        icon={<QuestionCircleIcon />}
        onClick={handleShowAdminPopover}
      >
        Who's my administrator?
      </Button>
    </EmptyStateFooter>
  </EmptyState>
</PageSection>
```

### ✅ Correct: No Results (Filtered) Empty State

```tsx
<>
  <Toolbar>
    <ToolbarContent>
      <ToolbarGroup variant="filter-group">
        <ToolbarItem>
          <SearchInput value={filterValue} onChange={handleChange} />
        </ToolbarItem>
      </ToolbarGroup>
    </ToolbarContent>
    <ToolbarContent>
      <ToolbarItem>
        <ChipGroup>
          <Chip onClick={handleRemoveFilter}>User: username</Chip>
        </ChipGroup>
      </ToolbarItem>
      <ToolbarItem>
        <Button variant="link" onClick={handleClearFilters}>
          Clear all filters
        </Button>
      </ToolbarItem>
    </ToolbarContent>
  </Toolbar>

  <Table>
    <Thead>
      <Tr><Th>Name</Th><Th>Owner</Th><Th>Created</Th></Tr>
    </Thead>
    <Tbody>
      <Tr>
        <Td colSpan={3}>
          <EmptyState variant="sm">
            <EmptyStateHeader
              titleText="No results found"
              icon={<EmptyStateIcon icon={SearchIcon} />}
            />
            <EmptyStateBody>
              Adjust your filters and try again.
            </EmptyStateBody>
            <EmptyStateFooter>
              <Button variant="link" onClick={handleClearFilters}>
                Clear all filters
              </Button>
            </EmptyStateFooter>
          </EmptyState>
        </Td>
      </Tr>
    </Tbody>
  </Table>
</>
```

### ✅ Correct: Status Empty State (Warning)

```tsx
<EmptyState variant="lg">
  <EmptyStateHeader
    titleText="This pipeline version is no longer supported"
    icon={<EmptyStateIcon icon={ExclamationTriangleIcon} color="var(--pf-v6-global--warning-color--100)" />}
    headingLevel="h1"
  />
  <EmptyStateBody>
    To remove unsupported versions, delete this project's pipeline server and create a new one.
  </EmptyStateBody>
  <EmptyStateFooter>
    <Button variant="primary" onClick={handleCreate}>
      Create pipeline server
    </Button>
    <Button variant="link" component="a" href={docsUrl} target="_blank">
      Learn more about supported versions and data recovery
    </Button>
  </EmptyStateFooter>
</EmptyState>
```

### ✅ Correct: Card Empty State (XS variant)

```tsx
<Card isSelectable>
  <CardBody>
    <EmptyState variant="xs">
      <EmptyStateIcon icon={FolderIcon} />
      <Button variant="link" onClick={handleCreate}>
        Create project
      </Button>
    </EmptyState>
  </CardBody>
</Card>
```

### ❌ Incorrect: Using wrench icon for configuration (should be cog)

```tsx
<EmptyStateHeader
  titleText="Enable pipelines"
  icon={<EmptyStateIcon icon={WrenchIcon} />}
/>
```

### ❌ Incorrect: Using primary button for contact admin

```tsx
<EmptyStateFooter>
  <Button variant="primary" onClick={handleContactAdmin}>
    Who's my administrator?
  </Button>
</EmptyStateFooter>
```

### ❌ Incorrect: Secondary button alone without primary

```tsx
<EmptyStateFooter>
  <Button variant="secondary" onClick={handleAction}>
    Request access
  </Button>
</EmptyStateFooter>
```

### ❌ Incorrect: Showing toolbar/table for initial empty state

```tsx
{allResources.length === 0 && (
  <>
    <Toolbar>{/* Filters shouldn't be shown */}</Toolbar>
    <Table>{/* Table headers shouldn't be shown */}</Table>
    <EmptyState>...</EmptyState>
  </>
)}
```

### ❌ Incorrect: Using illustration for configuration page

```tsx
<EmptyStateHeader
  titleText="Enable pipelines"
  icon={<EmptyStateIcon icon={PipelineIllustration} />}
/>
```

## Implementation Pattern

```tsx
if (isInitializing) {
  return <ObjectStartingState />;      // Spinner + "Starting <object>"
}

if (needsAdminAction) {
  return <ContactAdminEmptyState />;    // Headset icon + link CTA
}

if (needsConfiguration) {
  return <ConfigurationEmptyState />;   // Cog icon + primary CTA
}

if (allResources.length === 0) {
  return <CreationEmptyState />;        // Illustration + primary CTA, no toolbar
}

if (filteredResources.length === 0) {
  return <NoResultsEmptyState />;       // Search icon + "Clear all filters", with toolbar
}

return <TableWithData />;
```

## Automated Checks

**Find pages that may need review for proper empty state patterns:**
```bash
# Find EmptyState usage across the codebase
grep -rn "EmptyState" --include="*.tsx" src/
```

**Check for wrench icon used in configuration contexts (should be cog):**
```bash
# WrenchIcon in empty state context — should use CogIcon for configuration
grep -rn "WrenchIcon" --include="*.tsx" src/ | grep -i "empty\|enable\|configure\|config"
```

**Check for correct contact-admin button styling (should be link, not primary):**
```bash
# Find "administrator" or "admin" near button components
grep -rn "administrator\|contact.*admin" --include="*.tsx" src/ | grep -i "Button\|variant"
```

**Find empty states using secondary buttons alone:**
```bash
# Secondary buttons in EmptyStateFooter (should be primary or link)
grep -rn "variant=\"secondary\"" --include="*.tsx" src/ -B 2 | grep "EmptyState"
```

**Check for toolbar/table shown with initial empty states:**
```bash
# Find pages that show both EmptyState and Toolbar — review whether toolbar should be hidden
grep -l "EmptyState" --include="*.tsx" src/ | xargs grep -l "Toolbar"
```

**Find status empty states to verify correct icons and colors:**
```bash
# ExclamationCircleIcon, CheckCircleIcon, ExclamationTriangleIcon near EmptyState
grep -rn "ExclamationCircleIcon\|CheckCircleIcon\|ExclamationTriangleIcon" --include="*.tsx" src/ | grep -i "empty"
```

## Manual Review Checklist

- [ ] Creation pages use brand illustrations (not icons)
- [ ] Configuration pages use the cog/gear icon (not wrench)
- [ ] Contact-admin pages use the support/headset icon with link-button CTA
- [ ] Addition (non-primary) pages use a custom icon or plus fallback
- [ ] No results states show search icon with "Clear all filters" link
- [ ] Status empty states use correct color-coded icons (red=error, green=success, yellow=warning)
- [ ] Archived pages use the archive icon
- [ ] Card empty states use the XS PatternFly variant
- [ ] Initial empty states do NOT show toolbar, table, or pagination
- [ ] Filtered empty states DO show toolbar, table headers, and filter chips
- [ ] Contact-admin CTA is a link button (not primary or secondary)
- [ ] No secondary buttons used alone without a primary
- [ ] Labels between description and CTA maintain 16px vertical spacing
- [ ] Object-starting states show a spinner above the empty state text
- [ ] Conditional logic checks initialization, admin, configuration, then resource count in the correct order
