# Graph spec schema

The structured artifact the interrogation produces, and how each field becomes code.
Nothing here is invented by the agent — every value comes from the user's answers.

## Per-node fields

| Field | Required | Becomes | Notes |
|---|---|---|---|
| `name` | yes | `add_node("<name>", ...)`, node names in edges/tests/command file | snake_case, one word if possible — it's grepped end-to-end |
| `kind` | yes | `kind=NodeKind.TASK / HUMAN_GATE / END` | `human_gate` means the command file must stop and wait for a human answer before the next script call |
| `goal` | yes | `goal="..."` — surfaced in the script's stdout, read by the command file | one imperative line; this is what Claude actually generates at that node |
| `agent` | yes | `agent="..."` | `claude-inline` (Claude generates it in-conversation) or a named subagent the command file should dispatch to — see "Node attachments" below |
| `expected_output` | yes | keys the command file writes into `data` after the node runs, or a `runs/<run_id>/artifacts/<node>.md` file for substantial content | what downstream routers read; a node whose output nothing reads is a smell worth raising. Put full content (a report, a log summary) in an artifact and only a pointer/short signal in `data` — `data` rides in every log line and the checkpoint on every step, so it should stay small |
| `log_fields` | no | extra keys merged into the `log_transition` event | defaults already cover from/to/data/retry_count/step_count — only add what's genuinely missing |
| `skill` | no | a `skills/<name>/SKILL.md` in the generated plugin | only when the node needs reusable domain knowledge — see below |
| `mcp_tools` | no | an entry in the generated plugin's `.mcp.json` | the external system(s) this node reads or writes |

## Node attachments — agent / skill / MCP

All three are **optional and per node**. The default (`agent: claude-inline`, no skill, no
MCP) is correct for most nodes, and a plugin where every node has all three is a plugin
that will be harder to read than the problem it solves. Templates to adapt live in
`../templates/` — see its `README.md` for destination paths and the frontmatter fields
that fail silently when confused (`tools` vs `allowed-tools`; the fields plugin subagents
ignore; the six-field limit on packaged skills).

**Dedicated agent** (`templates/agent.md`) — warranted when the node's work would flood the
main conversation or needs isolation:

- long or exploratory work (searching a codebase, reading many files) whose intermediate
  output the user doesn't need to see
- work needing a restricted or different tool set
- work that benefits from a cold context, e.g. an independent review that shouldn't inherit
  the reasoning it's reviewing

Not warranted for short generation — explaining a concept, asking a question, summarizing
what's already in context. Inline is cheaper and keeps the conversation coherent. A
subagent starts cold and re-derives context the conversation already holds.

**Skill** (`templates/skill.md`) — warranted when several nodes (or several plugins) need
the same domain knowledge, schema, or procedure. A skill used by exactly one node, adding
nothing the node's `goal` doesn't already say, is that `goal` in disguise — don't create it.

**MCP** (`templates/.mcp.json`) — warranted when a node must reach an external system
(database, issue tracker, API) rather than reason about what's already in context.

Scaffolding an MCP entry writes *configuration for a server the user must already have*.
It does not install the server, and a wrong `command` surfaces as a plugin-load failure,
not a scaffold error. Confirm with the user that the server exists and the command is
right — and say plainly that this part is unverified until they run it.

## Edge fields

| Field | Required | Becomes |
|---|---|---|
| `from` → `to` (plain) | yes | `add_edge("from", "to")` |
| `from` + condition(s) | if branching | `add_conditional_edge("from", <from>_router)`; each condition is one `if` in the router returning one destination node |
| loop-back edge | if looping | a router return value pointing at an earlier node — **requires** a stated termination condition (see below) |

## Loop / retry policy

Required whenever any router can return an earlier node:

- **Trigger**: which `data` value sends it back (e.g. `data["approved"] is False`).
- **Termination**: what stops it — normally `retry_count >= max_retries` returning a terminal node.
- **Counter increment**: which transition counts as a retry → becomes the `on_transition()` hook.

A loop without a stated termination is not a spec gap to fill in with a default — it's an
answer still owed by the user. The engine's `max_steps` is a crash-guard, not a policy.

## Diagram

Every spec includes an ASCII diagram of the topology, placed right after the node list —
readable directly in a terminal or a plain-text editor, no renderer required (this is why
it's ASCII, not Mermaid: a fenced Mermaid block is inert text outside something that parses
it, and the spec is meant to be reviewed on the spot, not exported). Use the same kind
markers as the runtime `banner`/`preview` (`▶` task, `⏸` human_gate, `■` end) so the two
stay visually consistent:

- Plain edges: left-to-right chain joined by `→`.
- A loop-back edge: draw it as a return arrow under the chain, labeled with the trigger
  condition — not just "(retry)" restated, the actual condition from the loop policy.
- A branching node (conditional edge with more than one destination): list each
  `condition → destination` on its own line under that node rather than forcing multiple
  outgoing arrows into one cramped line.

## Worked example — incident triage (non-teacher domain)

```
plugin: incident-triage
description: Walk an on-call engineer through triaging a production alert.

nodes:
  - name: classify
    kind: task
    goal: read the alert payload and state severity (sev1/sev2/sev3) with reasoning
    agent: claude-inline
    expected_output: data.severity  (string)
  - name: gather_evidence
    kind: task
    goal: pull recent logs/metrics for the named service and summarize anomalies
    agent: gather-evidence-agent      # long, noisy search — isolate it from the conversation
    mcp_tools: [grafana]              # needs metrics from an external system
    expected_output: runs/<run_id>/artifacts/gather_evidence.md (full summary),
                     data.evidence_path (string, pointer to that file)
  - name: confirm_with_human
    kind: human_gate
    goal: present the severity + evidence, ask the engineer to confirm or correct
    agent: claude-inline
    expected_output: data.confirmed (bool)
    log_fields: severity
  - name: end
    kind: end
    goal: write the triage summary
    agent: claude-inline

edges:
  classify -> gather_evidence
  gather_evidence -> confirm_with_human
  confirm_with_human -> conditional:
      data.confirmed is True            -> end
      retry_count >= max_retries        -> end
      otherwise                         -> classify

loop policy:
  trigger: engineer rejects the classification (data.confirmed False)
  termination: retry_count >= max_retries (default 2)
  increment: confirm_with_human -> classify counts as one retry
```

Diagram:

```
▶ classify → ▶ gather_evidence → ⏸ confirm_with_human
     ▲                                  │
     │                                  ├─ data.confirmed is True       → ■ end
     │                                  ├─ retry_count >= max_retries   → ■ end
     └───────────── otherwise (engineer rejects the classification) ───┘
```

Maps to:

```python
def confirm_with_human_router(state: State) -> str:
    if state.data.get("confirmed"):
        return "end"
    if state.retry_count >= state.max_retries:
        return "end"
    return "classify"


def on_transition(state: State, next_node: str) -> None:
    if state.current_node == "confirm_with_human" and next_node == "classify":
        state.retry_count += 1
```
