---
name: uxd-experience-narrative-create
version: 0.1.0
description: >-
  Turn a problem brief into a scene-by-scene experience a prototype can show.
  Use when writing the story of an experience, defining before-and-after beats,
  or listing the screens a prototype needs.
audience: "UX designers"
inputs: "A problem brief, optional time horizon and enabling capabilities, optional target codebase"
outputs: "An experience narrative with a screen breakdown"
---

# Experience Narrative

Turns a problem brief into the story a prototype can act out. This skill does not build the prototype.

Enabling capabilities and a time horizon are recorded here when the user is describing a future experience. They are not required for every story.

## Inputs

| Input | Required | Source |
|-------|----------|--------|
| Problem brief | **Yes** | `.artifacts/problem-brief.md`, `.artifacts/{ID}/problem-brief.md`, a discovery brief, or user-provided text |
| Enabling context | No | Time horizon and user-facing capabilities, when the story depends on a change that does not exist today |
| Persona reference | No | Persona cards in the target project or an installed plugin, when they match the brief |
| Target codebase | No | Only to learn real navigation. Skip routes when no codebase is available. |

If no problem brief exists, stop and ask the user to run `uxd-problem-brief-create` or paste the problem.

## Outputs

Write `.artifacts/experience-narrative.md` beside the brief. When an id is known, write `.artifacts/{ID}/experience-narrative.md` instead.

## Arguments

$ARGUMENTS

Parse as: `[path-to-brief] [--workspace <path>] [--horizon <time>] [--id <work-item-id>]`

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | none | Codebase whose navigation the screen list should follow. |
| `--horizon` | none | Time horizon for a future experience, such as 6–12 months. |
| `--id` | none | Work item id for the artifact path. |

---

## Step 1: Enabling context

Ask for this only when the story depends on a change the product does not offer today, or the user asked for a vision or a future experience.

- What is the time horizon?
- Which capabilities or investments make the new experience possible, and is each committed, being explored, or aspirational?

Write each capability as something the person can do. "Add AI" is not a capability. "Show the three most likely causes, with the evidence each one is based on" is.

Skip this step when the story is the intended experience of work already in scope. Do not invent a horizon or a capability list.

## Step 2: Set the scene

Establish who, when, and what is at stake. Use the person and situation from the problem brief.

Give them a name. If persona cards are available and one fits, use it and say which one. If none fits, invent a specific person and label them as synthetic.

Write a 2–3 sentence scene-setter. Example of the level of specificity, not a required domain:

> It's Tuesday morning. Priya, a platform engineer, opens her laptop to 47 unread alerts. Three tools each show part of what might be the same incident. She has 15 minutes before standup.

## Step 3: Today (before)

Write 3–5 beats of the current experience from the brief's evidence. Each beat has:

- What the person does
- What the product does, or fails to do
- How it feels
- Research source, when the beat comes from the brief

Ask whether each beat matches what people actually do today. Label beats that are assumptions.

## Step 4: The change

Write the moment the experience diverges from today. It is a specific action with a specific result.

When enabling capabilities were provided, the change comes from one of them and is credible for the stated horizon. When they were not, the change is the proposed experience itself. Not magic, and not "the AI helps."

## Step 5: After

Write 3–5 beats for the same person and scenario after the change. Mirror the before beats so the contrast is obvious.

Each beat: what the person does, what the product does, and what that enables. Name the objects on screen.

## Step 6: Payoff

Close on the desired outcome from the problem brief. What can this person do now, and what would they tell a colleague?

## Step 7: Screens

List the 3–5 views a prototype must show. For each:

- Screen name
- Placement in the product: existing page, new view in an existing area, or new area
- Which beat it carries
- What must be visible
- What the person does

Include a route only when you have read the target app's navigation and the route is real or follows that app's routing pattern. Do not invent paths from another product.

## Step 8: Write the narrative

Write the narrative from [references/template.md](references/template.md). Omit **Enabling Context** when Step 1 was skipped. Repeat the beat headings for each beat.

Read it back. Revise until the before matches the brief, the after is concrete, and someone outside the work can follow the story.

## Quality checks

- The person has a name, a role, and a stake taken from the brief
- Before beats trace to the brief's evidence, or are labeled as assumptions
- After beats are concrete interactions
- Capabilities, when present, show up as things the person does
- The screen list is enough to prototype, without product paths that were not discovered from the target codebase
- Someone unfamiliar with the product can follow the story

When the user wants this story built, the next skill is `uxd-prototype-create`, with this narrative as the source. Pass `--workspace` when one was used. Do not build the prototype in this skill.
