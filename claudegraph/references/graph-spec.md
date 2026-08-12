# Graph spec schema

The structured artifact the interrogation produces, and how each field becomes code.
Nothing here is invented by the agent — every value comes from the user's answers.

## Per-node fields

| Field | Required | Becomes | Notes |
|---|---|---|---|
| `name` | yes | `add_node("<name>", ...)`, node names in edges/tests/command file | snake_case, one word if possible — it's grepped end-to-end |
| `kind` | yes | `kind=NodeKind.TASK / HUMAN_GATE / END` | `human_gate` means the command file must stop and wait for a human answer before the next script call |
| `goal` | yes | `goal="..."` — surfaced in the script's stdout, read by the command file | one imperative line; this is what Claude actually generates at that node |
| `agent` | yes | `agent="..."` | `claude-inline` (Claude generates it in-conversation) or a named subagent/tool the command file should dispatch to |
| `expected_output` | yes | keys the command file writes into `data` after the node runs | what downstream routers read; a node whose output nothing reads is a smell worth raising |
| `log_fields` | no | extra keys merged into the `log_transition` event | defaults already cover from/to/data/retry_count/step_count — only add what's genuinely missing |

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
    agent: claude-inline
    expected_output: data.evidence_summary (string)
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
