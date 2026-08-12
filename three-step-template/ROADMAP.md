# Roadmap (deferred, not built)

Ideas considered while building this template and explicitly deferred, so they don't get
lost — and so future-us doesn't accidentally re-derive them from scratch.

## Terraform/IaC-style module graph

Instead of one active node moving through a linear/looping path, declare modules with a
`goal`, an execution kind, and dependencies — closer to Terraform's `depends_on` + implicit
parallelism than to a single-position state machine:

- Node kinds: `start`, `end`, `human_gate` (pause for a human response), `task` (runs an
  agent/skill)
- Edges: `depends_on` (a node is "ready" once all its dependencies are `done`)
- Parallelism falls out naturally: whenever the ready-set has more than one member, those
  nodes can run concurrently — it's not a node type to declare, it's a consequence of the
  dependency graph.

**Why this wasn't built into `three-step-template`:** it requires a different state model
(per-node status across the whole graph — `pending/ready/running/done/blocked` — not a
single `current_node`), and true parallel dispatch has to happen on Claude's side (parallel
Agent/Task calls), not inside the stateless routing script. That's a legitimate, bigger
project — a DAG scheduler, not a state machine — and building it here would contradict this
plugin's actual purpose (a minimal, KISS example). If pursued, it should be its own plugin,
designed starting from the state-model question, not the node-type taxonomy.

## Declarative graph spec (`Graph.from_spec`)

A factory that builds a `Graph` from plain data (`{"nodes": [...], "edges": {...},
"conditional_edges": [...]}`) instead of writing `add_node`/`add_edge` Python calls per skill.

**Still deferred, but distinguish this from `skill_runner.py` (which *was* built):**
`skill_runner.py` extracted the CLI driver boilerplate (stdin parsing, error handling,
checkpoint/log wiring) because it's identical, provably-duplicated code across any skill,
observed directly while writing the second version of `template_skill.py` — not a guess about
the future. `Graph.from_spec` would replace *topology-building Python* with *topology-as-data*,
which is a different, more speculative bet (does topology actually need to be non-code-editable
by whoever's writing the skill? unclear). `template_skill.py` is still the only topology example.
Revisit once a second skill's topology exists to generalize from two concrete cases.

## Hard enforcement via hooks

A `PreToolUse` hook that blocks other tool calls during a `/teacher`-style session unless the
most recent Bash call matched the routing script — would close the enforcement gap noted in
`README.md` ("Claude has to be told, in prose, to call the script") with a mechanical
guarantee instead of an instruction. The JSONL evidence log (`log_transition`, wired in
`skill_runner.py`) is a *detective* control built as a lighter-weight interim measure — it
proves after the fact whether a step ran, but a hook would be *preventive*, stopping
non-compliant tool use before it happens. Not built: more machinery than a KISS example plugin
needs, but a real option if a production use case needs a hard guarantee rather than strong
evidence.
