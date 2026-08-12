---
name: <node-name>-agent
description: <When Claude should delegate to this subagent — this is what the dispatching command matches on, so name the trigger, not just the capability>
tools: Read, Grep, Glob
model: inherit
---

<!--
Frontmatter notes (see https://code.claude.com/docs/en/sub-agents):

  - Goes at `agents/<node-name>-agent.md` in the plugin root. The filename doesn't have
    to match `name`, but keeping them identical means one grep finds both.
  - Only `name` and `description` are required.
  - `name`: lowercase letters and hyphens. It MUST NOT contain `:` — that's reserved for
    plugin-scoped ids (`my-plugin:reviewer`), and a name containing one isn't loaded at
    all; the failure only shows up in the debug log.
  - `tools`: comma-separated string (`Read, Grep, Glob`). Note it is `tools` here, NOT
    `allowed-tools` — that hyphenated form is the skill field and does nothing in an
    agent. Omit the line entirely to inherit every tool available to subagents. If no
    entry resolves to a real tool, the subagent fails to launch. Prefer `disallowedTools`
    when the goal is "everything except X".
  - `model`: `inherit` (default), or `sonnet`/`opus`/`haiku`/`fable`, or a full model ID.
    Use `haiku` for narrow mechanical work to cut cost and latency.
  - IGNORED for plugin subagents — do not bother setting these here:
    `permissionMode`, `mcpServers`, `hooks`. They silently have no effect in a plugin.
  - Useful and honored: `disallowedTools`, `maxTurns`, `skills`, `effort`, `color`,
    `background`, `isolation: worktree`.

Delete this comment block when adapting.
-->

<Restate the node's `goal` from the graph spec as this agent's brief. The agent starts
with a cold context — it receives only this system prompt plus basic environment details,
none of the conversation that led here, so state everything it needs explicitly.>

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
