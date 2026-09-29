# Live browser persona API phase

Each selected persona receives its bundled profile, experience overlay, goal,
and relevant acceptance criteria. The persona uses only browser observation,
click, type, same-origin navigation, and keyboard actions. Every action returns
fresh DOM evidence and a rendered screenshot. Source code, shell, file search,
workspace exploration, Jira, and implementation details are unavailable.

The final persona result is constrained by a strict JSON schema and is accepted
only after at least one browser interaction.

The runner reserves its final model turn for that JSON result. A persona may use
at most one fewer browser actions than its turn allocation. When the interface
does not reveal the needed information after its most relevant inspection, the
persona records a blocked or abandoned result with rendered evidence instead of
repeating controls.
