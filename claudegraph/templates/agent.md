---
name: <node-name>-agent
description: <what this agent does, and when the graph should dispatch to it — written so the main conversation can decide to hand off>
tools: <comma-separated, e.g. Read, Grep, Glob, Bash — omit the line entirely to inherit all>
---

<Restate the node's `goal` from the graph spec as this agent's brief. The agent starts
with a cold context — it has none of the conversation that led here, so state everything
it needs explicitly.>

## Input

<What the dispatching command passes in — usually the relevant fields from the graph's
`data`, named exactly as they appear there so one grep traces the value end to end.>

## What to do

1. <Concrete steps. Same principle as the command file: literal procedure, not
   "analyze the thing" — an agent drifting is the same failure mode as Claude drifting.>
2. <...>

## What to return

<The agent's final report is not shown to the user — the dispatching command relays it.
So state exactly what shape to return, and name the `data` key(s) the command will write
the result into, from the node's `expected_output` in the graph spec.>

Return concisely: <e.g. "a `severity` string (sev1/sev2/sev3) and a one-paragraph
justification">. Do not return raw dumps — the caller writes this into graph state.
