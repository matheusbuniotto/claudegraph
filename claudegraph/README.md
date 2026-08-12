# claudegraph

A cookie-cutter builder for LangGraph-style Claude Code plugins: stdlib-only state-graph
execution where routing is enforced by deterministic code, not by prose instructions Claude
may or may not follow.

Three commands ship here — two that build, one that demonstrates:

- **`/graph-spec`** — interrogates you for the plan and writes it to
  `<name>.graph-spec.md`. Plan only, no code. The file is reviewable and hand-editable
  before anything is generated.
- **`/build-graph`** — implements a spec: scaffolds the engine, writes the domain logic,
  verifies. Runs `/graph-spec` first if no spec exists. Where a node warrants it, also
  generates a dedicated subagent, a skill, or `.mcp.json` config from `templates/` —
  optional and per node, not emitted by default.
- **`/teacher`** — the worked example that proves the pattern end to end, and the code you'd
  copy by hand if you'd rather not use the generator.

Splitting spec from build is deliberate: "is this spec complete?" is a fuzzy bound, and
leaving the implementation steps visible right behind it is exactly what makes an agent rush
it. The spec file is the hand-off that removes the pull.

## Structure

```
claudegraph/
├── AGENTS.md                 # rules for agents working in this repo: how to add a skill/
│   │                          #   feature, where new code belongs, when to push back
├── CLAUDE.md -> AGENTS.md    # symlink, same content — single source of truth
├── .claude-plugin/
│   └── plugin.json           # manifest (required)
├── commands/
│   ├── graph-spec.md         # /graph-spec — PLAN: interrogate, write <name>.graph-spec.md
│   ├── build-graph.md        # /build-graph — IMPLEMENT: scaffold, write domain logic, verify
│   └── teacher.md            # /teacher — EXAMPLE: literal, numbered procedure calling the script
├── references/
│   └── graph-spec.md         # field schema the interrogation fills, worked example, how each
│                              #   field maps to code, and when a node warrants an attachment
├── templates/                # see templates/README.md. plugin-README/plugin-AGENTS are
│   ├── plugin-README.md       #   rendered into every generated plugin so it documents itself
│   ├── plugin-AGENTS.md       #   rather than inheriting claudegraph's docs; agent/skill/mcp
│   ├── agent.md               #   are adapted per node, only when graph-spec rules flag it
│   ├── skill.md               #
│   └── mcp.json               #
├── scripts/
│   ├── graph.py               # generic engine: NodeKind, NodeMeta, State, Graph
│   │                          #   (add_node/add_edge/add_conditional_edge/step/node_meta),
│   │                          #   log_transition(), save_checkpoint()/load_checkpoint() —
│   │                          #   knows nothing about teaching
│   ├── skill_runner.py        # generic CLI driver: stdin/stdout JSON, boundary validation,
│   │                          #   step-budget handling, checkpointing, evidence logging, and
│   │                          #   the preformatted `banner` progress line — reused as-is by
│   │                          #   every skill, never edited per-skill
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

## Visible progress

Every call returns a preformatted `banner` the command file prints verbatim, so a run reads
as a visible trace rather than undifferentiated prose:

```
▶ explain (step 1) — 3-5 sentence plain-language explanation
▶ demonstrate (step 2) — one concrete example
⏸ check (step 3) — ask one question, wait for the user's answer
▶ explain (step 4, retry 1/2) — 3-5 sentence plain-language explanation
■ end (step 6, retry 1/2) — wrap up
```

`▶` task, `⏸` waiting on you, `■` finished. Retry counts appear only once looping. The line
is composed in `skill_runner.py`, not by Claude — asking for a progress line each turn invites
drift in wording and in what gets dropped; the only instruction is "print this".

The full graph state (`next_node`/`kind`/`goal`/`retry_count`/`step_count`/`done`) is already
the script's entire stdout contract — JSON in, JSON out. `banner` is one more key in that same
object: a plain-text projection of it for the human reading the terminal. There's no separate
"print of graph state" to convert — the machine-readable form already exists, and turning the
banner itself into JSON would just make the visible trace above harder to read for no gain.

## Runs, evidence, and artifacts

Every call is scoped to a `run_id` — generated on the first call (no `run_id` in the payload)
and returned in the output for the command file to carry forward on every later call, the same
way `retry_count`/`step_count` already are. Everything that run produces lives under
`runs/<run_id>/`:

- `runs/<run_id>/<skill>.log.jsonl` — one JSONL line per call: `skill`, `from`, `to`, `data`,
  `retry_count`, `max_retries`, `step_count`, `ts`, and `actions` (see below).
- `runs/<run_id>/<skill>.checkpoint.json` — the full `State` after the last call, for recovering
  `current_node` etc. if a session gets interrupted.
- `runs/<run_id>/artifacts/<node>.md` — a convention, not engine-enforced: when a node's output
  is substantial enough that a later node or a human should reread it without scrolling back
  through the conversation, the command file writes it here with `Write` instead of growing
  `data` to carry full content across steps. `data` stays for small routing signals a router
  reads (e.g. `data.understood`); artifacts are for the content itself.

`runs/latest` is a symlink to the most recent `run_id`'s directory, recreated on every call
that uses the default paths. It exists for one failure mode: a session that loses track of
`run_id` (context compaction, a fresh Claude session picking up mid-task) previously had no
way back to its own evidence log — it would just start a new, disconnected run. Now it reads
`runs/latest/<skill>.checkpoint.json` for `current_node` and `readlink runs/latest` for
`run_id`, and resumes the same run instead. Passing explicit `log_path`/`checkpoint_path`
opts out of `runs/<run_id>/` entirely, including this symlink.

`actions` is a log-only record of what the *previous* node actually did — tool calls made,
sources retrieved, an artifact written — passed on the call that reports that node's result.
It's appended to the log entry for that transition and never touches `State` or the
checkpoint: provenance for after-the-fact review, not routing data a router could read.

Passing explicit `log_path`/`checkpoint_path` overrides the `run_id`-based default entirely,
for a caller that wants a specific location instead. See the CLI contract in
`skill_runner.py`'s module docstring for the exact shape.

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
