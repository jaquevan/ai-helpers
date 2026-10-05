---
name: uxd-problem-brief-create
version: 0.1.0
description: >-
  Frame a product problem as a brief: who is affected, the current condition,
  evidence versus assumptions, and what is in scope. Use when framing a problem,
  writing a problem statement, or preparing an experience narrative.
audience: "UX designers and product managers"
inputs: "A problem, feature request, or discovery brief, plus optional evidence"
outputs: "A problem brief in markdown"
---

# Problem Brief

Produces an agreed problem frame. The statement describes the current condition and why it matters. It does not propose capabilities, a time horizon, screens, or a prototype.

Work one section at a time. Confirm what you heard before moving on. If a discovery brief already exists, start from it instead of re-interviewing.

## Inputs

| Input | Required | Source |
|-------|----------|--------|
| Problem, feature request, or discovery brief | **Yes** | User. Ask if omitted. |
| Evidence (research, tickets, analytics, observation) | Recommended | User, or a research-lookup skill if one is available |

## Outputs

Write `.artifacts/problem-brief.md` in the working project. When a work item id is known, write `.artifacts/{ID}/problem-brief.md` instead. Do not write into this skill's directory.

## Arguments

$ARGUMENTS

Parse as: `<problem-or-source> [--id <work-item-id>]`

| Flag | Default | Description |
|------|---------|-------------|
| `--id` | none | Work item id for the artifact path. |

---

## Step 1: The situation

Ask what problem this is, who feels it, and why it matters now. If the user handed you a solution ("build a dashboard"), restate the condition that solution is meant to change and confirm the restatement.

Summarize in 2–3 sentences before continuing.

## Step 2: Evidence

Look for what the team already knows before writing the pain.

If a research-lookup skill is available, use it for the people and the situation. Capture quotes, findings, method, sample size, date, and links. If it is unavailable or returns nothing, say so and continue.

Label every claim as **evidence** or **assumption**. A thin evidence base does not block the brief.

## Step 3: Current condition

Ask who the person is, what they are trying to do, what happens today, and which evidence supports that.

Reject a generic problem. "Users find it confusing" is not a condition. A specific role, a concrete situation, and a measurable friction is.

State the desired outcome as a change in that person's condition. Leave the feature that might cause the change unnamed.

## Step 4: Scope

Draw the boundary around the problem:

- The one situation this brief covers
- What is explicitly out of scope
- Constraints that are already known (time, technology, policy, org), separate from guesses

If the frame is a whole product, ask which single situation the team needs to agree on first.

## Step 5: Stakeholders

Ask who needs to agree that this is the problem, and what each of them cares about. Do not invent names. A presentation plan belongs in `uxd-experience-review`, when there is something to show.

## Step 6: Write the brief

Write the brief from [references/template.md](references/template.md). Keep every heading.

Read it back. Revise until the statement has no solution in it, evidence and assumptions are labeled, and the scope is one situation.

## Quality checks

- The problem statement names a person, a current condition, and why it matters
- The statement does not name a capability, screen, or implementation
- The desired outcome is a change in condition
- Evidence and assumptions are labeled
- Scope is one situation
- At least one stakeholder is named by role, with what they care about

When the user wants to show an experience that responds to this problem, the next skill is `uxd-experience-narrative-create`.
