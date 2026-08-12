# claudegraph

A cookie-cutter builder for LangGraph-style Claude Code plugins: stdlib-only state-graph
execution where routing is enforced by deterministic code, not by prose instructions Claude
may or may not follow.

Two commands ship here:

- **`/build-graph`** — the generator. Interrogates you for a complete graph spec, then
  scaffolds and fills in a real plugin on top of this engine.
- **`/teacher`** — the worked example that proves the pattern end to end, and the code you'd
  copy by hand if you'd rather not use the generator.

## Structure

```
claudegraph/
├── AGENTS.md                 # rules for agents working in this repo: how to add a skill/
│   │                          #   feature, where new code belongs, when to push back
├── CLAUDE.md -> AGENTS.md    # symlink, same content — single source of truth
├── .claude-plugin/
│   └── plugin.json           # manifest (required)
├── commands/
│   ├── build-graph.md        # /build-graph — GENERATOR: interrogates for the graph spec,
│   │                          #   scaffolds, then fills in the new plugin's domain logic
│   └── teacher.md            # /teacher — EXAMPLE: literal, numbered procedure calling the script
├── references/
│   └── graph-spec.md         # field schema the interrogation fills, worked example,
│                              #   and how each field maps to code (read by /build-graph)
├── scripts/
│   ├── graph.py               # generic engine: NodeKind, NodeMeta, State, Graph
│   │                          #   (add_node/add_edge/add_conditional_edge/step/node_meta),
│   │                          #   log_transition(), save_checkpoint()/load_checkpoint() —
│   │                          #   knows nothing about teaching
│   ├── skill_runner.py        # generic CLI driver: stdin/stdout JSON, boundary validation,
│   │                          #   step-budget handling, checkpointing, evidence logging —
│   │                          #   reused as-is by every skill, never edited per-skill
│   ├── scaffold_plugin.py     # the mechanical half of /build-graph: copies the engine
│   │                          #   byte-identically, renames files, excludes generator machinery
│   ├── template_skill.py       # THE TEMPLATE — copy this file for a new skill. Only defines
│   │                          #   SKILL_NAME, build_graph(), a router, and an on_transition
│   │                          #   policy hook; everything else comes from skill_runner.py
│   └── test_template_skill.py  # stdlib unittest, run: python3 -m unittest scripts.test_template_skill -v
├── LEARNING_CHECKLIST.md     # design rationale from building this: problem / solution / context
├── ROADMAP.md                # ideas considered and deliberately deferred
└── README.md
```

## Install

**Fast dev loop** (no marketplace, loads the plugin directly for a session):
```
claude --plugin-dir ./claudegraph
```

**Install from GitHub:**
```
/plugin marketplace add matheusbuniotto/claudegraph
/plugin install claudegraph@claudegraph
```

**Install from a local clone:**
```
/plugin marketplace add /path/to/claudegraph
/plugin install claudegraph@claudegraph
```
Note: local-path marketplaces are CLI-only — the Claude Desktop/Cowork plugin UI only installs
from registered marketplace listings, not an arbitrary local directory.

## Customize

1. Rename `name` in `.claude-plugin/plugin.json` (and in `marketplace.json`'s `plugins[].name`/`source`).
2. `scripts/graph.py` and `scripts/skill_runner.py` are the reusable parts — leave them alone
   unless the engine or driver plumbing itself needs to change.
3. Copy `scripts/template_skill.py` to `scripts/<your_skill>.py` and edit only what it says is
   skill-specific: `SKILL_NAME`, `build_graph()` (nodes with `kind`/`goal`/`agent`, edges), a
   router function per `add_conditional_edge`, and an optional `on_transition()` hook for
   skill-specific policy (e.g. counting a particular loop as a retry). End the file with
   `run_skill(SKILL_NAME, build_graph, on_transition)`. Never generate content in Python —
   that stays Claude's job, driven by the command file, based on the `goal`/`kind` the script
   returns for the current node.
4. Write `commands/<your_command>.md` as a literal numbered procedure (see `teacher.md`) that calls
   your script after each step and reads `next_node`/`kind`/`goal` — abstract prose ("follow the
   graph") is exactly the enforcement gap this pattern exists to shrink.

## Why KISS

The engine (`graph.py`) is genuinely minimal: stdlib only, one class, a handful of methods.
Complexity was deliberately deferred at several points along the way — see
`LEARNING_CHECKLIST.md` for the design decisions and YAGNI calls made while building the first
version, and `ROADMAP.md` for a bigger direction (Terraform-style parallel/depends_on graphs)
considered and explicitly deferred as a separate, future project. The `skill_runner.py` split
(generic driver vs. per-skill template) *was* built, unlike the declarative `Graph.from_spec`
idea in `ROADMAP.md` — the difference: the driver boilerplate (stdin parsing, error handling,
checkpoint/log wiring) was proven to be identical duplication across skills the moment a second
skill's worth of scaffolding was written, not a hypothetical future need.

## Known limitations

- **Enforcement is partial, not absolute.** The script's routing is deterministic once called,
  but nothing mechanically forces Claude to call it instead of free-forming — that still rests
  on `commands/teacher.md`'s instructions. Every real call appends evidence to a JSONL log
  (`log_transition` in `graph.py`, wired in `skill_runner.py`) — a *detective* control (proves
  after the fact whether the script ran), not a *preventive* one. A `PreToolUse` hook could make
  it a hard guarantee instead; not built here, see `ROADMAP.md`.
- **Single active node only.** This models one position moving through the graph over time —
  not concurrent branches. See `ROADMAP.md` for what a true parallel/DAG version would require.
- **Checkpointing narrows, not eliminates, context loss.** `save_checkpoint`/`load_checkpoint`
  write/read a JSON snapshot of `State` after every step, so a session interrupted by, say,
  context compaction has something to recover from. But recovery is explicit, not automatic —
  something (a human, or a fresh Claude session) has to read the checkpoint and re-supply
  `current_node` etc. in the next call. There's no auto-resume.
- **`max_steps` is a blunt global ceiling** (default 50), independent of any skill's own
  `retry_count`/`max_retries` policy. It exists so a buggy future skill can't loop forever even
  if its author forgot their own bound — it is not a substitute for skill-level retry logic.
