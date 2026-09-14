# claudegraph

A Claude Code plugin for LangGraph-style workflows. A small, stdlib-only state-graph engine
decides which node runs next. Claude generates the content for that node and nothing else.

Without it, a multi-step command is a numbered list Claude may or may not follow. With it,
each step is a call to a script that returns the next node, its goal, and a progress line,
and every transition is appended to an evidence log.

## Commands

| Command | Purpose |
|---|---|
| `/graph-spec` | Interviews you for a graph plan and writes `<name>.graph-spec.md`. No code. |
| `/build-graph` | Implements a spec as a new plugin: scaffolds the engine, writes the graph, runs its tests. |
| `/teacher` | A working example: explain, demonstrate, check understanding, and loop until it sticks. |

Planning and building are separate on purpose. The spec file is reviewed and edited before
any code exists, which keeps implementation from racing ahead of an incomplete plan.

## Install

```
/plugin marketplace add matheusbuniotto/claudegraph
/plugin install claudegraph@claudegraph
```

For local development, load the plugin directly:

```
claude --plugin-dir ./claudegraph
```

## How it works

A skill defines its graph in Python:

```python
def check_router(state: State) -> str:
    if state.data.get("understood") or state.retry_count >= state.max_retries:
        return "end"
    return "explain"

def build_graph() -> Graph:
    g = Graph()
    g.add_node("explain", kind=NodeKind.TASK, goal="3-5 sentence explanation")
    g.add_node("demonstrate", kind=NodeKind.TASK, goal="one concrete example")
    g.add_node("check", kind=NodeKind.HUMAN_GATE, goal="ask one question, wait")
    g.add_node("end", kind=NodeKind.END, goal="wrap up")
    g.add_edge("explain", "demonstrate")
    g.add_edge("demonstrate", "check")
    g.add_conditional_edge("check", check_router)
    return g
```

The command file calls the skill with the current state as JSON on stdin, and gets the
next step on stdout:

```
$ echo '{"current_node": "explain"}' | python3 scripts/template_skill.py
{"next_node": "demonstrate", "kind": "task", "goal": "one concrete example",
 "banner": "▶ demonstrate (step 1) — one concrete example",
 "preview": "explain → ▶[demonstrate] → check → end",
 "retry_count": 0, "max_retries": 2, "step_count": 1, "run_id": "...", "done": false}
```

Claude prints `banner` and `preview` verbatim, so a run reads as a trace:

```
▶ explain (step 1) — 3-5 sentence plain-language explanation
▶ demonstrate (step 2) — one concrete example
⏸ check (step 3) — ask one question, wait for the user's answer
▶ explain (step 4, retry 1/2) — 3-5 sentence plain-language explanation
■ end (step 6, retry 1/2) — wrap up
```

`▶` means a task, `⏸` waits on you, and `■` means finished.

## Engine features

- **Conditional edges.** A router function picks the next node from state.
- **Bounded loops.** Skills own their retry policy through an `on_transition` hook. A global
  `max_steps` budget stops any runaway loop.
- **Human gates.** A `human_gate` node tells the command file to stop and wait for input.
- **Runs.** Each run gets a `run_id`. Its log, checkpoint, and artifacts live under
  `runs/<run_id>/`, and `runs/latest` points at the most recent run.
- **Evidence log.** Every transition is appended to a JSONL log, along with any tool calls
  the previous node reports in `actions`.
- **Checkpoints.** The full state is written after every step, so an interrupted session
  can resume the same run.

## Structure

```
claudegraph/
├── .claude-plugin/plugin.json
├── AGENTS.md                  # rules for agents editing this plugin (CLAUDE.md links here)
├── commands/                  # /graph-spec, /build-graph, /teacher
├── references/graph-spec.md   # spec schema, worked example, field-to-code mapping
├── templates/                 # docs and optional agent/skill/MCP files for generated plugins
└── scripts/
    ├── graph.py               # engine: nodes, edges, routing, step budget, checkpoints, log
    ├── skill_runner.py        # CLI driver shared by every skill: JSON in/out, validation
    ├── template_skill.py      # the /teacher graph, and the starting point for new skills
    ├── scaffold_plugin.py     # the mechanical half of /build-graph
    └── test_*.py              # stdlib unittest
```

## Writing a skill by hand

`/build-graph` is the normal path. To do it manually:

1. Copy `scripts/template_skill.py` to `scripts/<name>_skill.py`.
2. Edit `SKILL_NAME`, `build_graph()`, the router functions, and `on_transition()`.
3. Write `commands/<name>.md` as a literal numbered procedure that calls the script after
   each step, using `commands/teacher.md` as the model.
4. Leave `graph.py` and `skill_runner.py` unchanged. They are shared by every skill.

## Limitations

- **Enforcement is partial.** Routing is deterministic once the script is called, but
  nothing forces Claude to call it. The evidence log shows afterwards whether it did.
  A `PreToolUse` hook could make this a hard guarantee, and is not built.
- **One active node.** The engine models a single position moving through the graph. For
  parallel branches, retries with persistent state, or unattended runs, use
  [airbend](../airbend/).
- **Resume is manual.** Checkpoints are written automatically, but a new session has to
  read `runs/latest` and pass the state back in.

## Development

```
python3 -m unittest discover -s scripts -p "test_*.py" -v
```
