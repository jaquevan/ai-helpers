---
name: uxd-experience-review
version: 0.1.0
description: >-
  Judge whether an experience narrative and prototype carry the framed problem,
  and draft the stakeholder demo. Use when reviewing a story-driven prototype
  or preparing to show an experience.
audience: "UX designers"
inputs: "A problem brief, an experience narrative, and a prototype"
outputs: "A review scorecard, improvement list, and presentation plan"
---

# Experience Review

Judges whether a story-driven prototype carries the framed problem, and helps the designer prepare to show it. This is not a heuristic audit, an acceptance-criteria check, or a usability study.

## Inputs

| Input | Required | Source |
|-------|----------|--------|
| Problem brief | **Yes** | `.artifacts/problem-brief.md` or `.artifacts/{ID}/problem-brief.md` |
| Experience narrative | **Yes** | `.artifacts/experience-narrative.md` or `.artifacts/{ID}/experience-narrative.md` |
| Prototype | **Yes** | Path, URL, or running app the user points to |

If the brief or narrative is missing, stop and name the skill that should produce it (`uxd-problem-brief-create`, `uxd-experience-narrative-create`). If no prototype is available, stop and ask where it lives. Do not search a default repository.

## Outputs

Write `.artifacts/experience-review.md` beside the other artifacts. When an id is known, write `.artifacts/{ID}/experience-review.md` instead.

## Arguments

$ARGUMENTS

Parse as: `<prototype-path-or-url> [--id <work-item-id>]`

---

## Step 1: See the prototype

Read the brief, the narrative, and the prototype source or running UI.

When a server is already running, or the project documents how to start one, use that. If the prototype gates the experience behind a flag, scenario, or query parameter, enable it the way that project does. Do not assume a package script, port, or flag file.

## Step 2: Scorecard

Rate each dimension **Strong**, **Adequate**, or **Needs work**, with a short assessment tied to something you actually saw.

1. **Narrative clarity** — Can someone outside the work follow the story in a few minutes? Is the problem immediate, and does the before/after contrast land?
2. **Problem grounding** — Does the prototype show the condition in the problem brief, with the brief's evidence, specifically enough that a partner would recognize it?
3. **Change demonstrated** — Is there a moment where the person experiences the change from their point of view, not as a feature label? When the narrative lists capabilities, this moment uses one of them.
4. **Outcome** — Does the after deliver the desired outcome from the brief, and is that outcome worth showing?
5. **Feasibility** — Could an engineer see a path to what was shown? When the narrative states a time horizon, judge against that horizon.
6. **Visual credibility** — Does it look like the product it extends? Realistic data, not placeholder copy. Judge against the design system that project uses. When that system is PatternFly, check that components, spacing, and theming match neighboring screens. When it is not, do not apply PatternFly rules.

## Step 3: Improvements

Sort changes into **Must fix**, **Should fix**, and **Nice to have**. Each item names the screen and the change. "Make it better" is not an item. "Replace the generic alert on screen 3 with the incident summary from beat 2" is.

## Step 4: Presentation plan

Draft with the designer:

- Opening line that frames the problem before the change
- Click path
- Where to pause
- Closing line that restates the desired outcome
- One- or two-sentence answers for: when could this be built, how it fits current work, what people have said (or that it has not been tested), what would be cut, and what is simulated versus real
- Who is in the room, how long, and whether they should drive or watch

## Step 5: Write the review

Write the review from [references/template.md](references/template.md). Keep every heading. When the project already keeps a design log, add the same Decisions entry there.

## Step 6: Close

Ask whether the designer has walked the prototype once without stopping, whether anyone else has seen it, and whether they can explain both the problem and what was shown.

If prototype code changed during the review, run the lint and build commands that repo documents. Skip this when the repo has none, or when nothing was changed. Do not impose a toolchain from another project.

## Quality checks

- All six dimensions are rated from the artifacts, not from the pitch
- Improvements name a screen and a change
- The demo script has an opening, a path, and a close
- At least three likely questions have answers
- The review does not assume a product, port, flag filename, or design-system rule the target project does not use

For acceptance criteria, usability, or a design-system critique, use `uxd-prototype-evaluate` or `uxd-evaluate-design-heuristics`. This skill stays on whether the experience carries the framed problem.
