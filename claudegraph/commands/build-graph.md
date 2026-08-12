---
name: build-graph
description: Implement a graph spec as a working plugin — scaffolds the engine, writes the domain logic, and verifies. Runs /graph-spec first if no spec exists.
---

Spec file or request: $ARGUMENTS

Turn a confirmed graph spec into a working plugin that reuses this plugin's engine
(`scripts/graph.py` + `scripts/skill_runner.py`) unchanged, writing only the
domain-specific parts.

## 0. Get a complete spec

Locate the spec: the path in `$ARGUMENTS`, or a `*.graph-spec.md` in the working directory.

**If no spec file exists**, run the protocol in
`${CLAUDE_PLUGIN_ROOT}/commands/graph-spec.md` to completion first — including writing and
confirming the spec file — then continue here. Do not implement from a spec held only in the
conversation.

**If a spec file exists**, read it against the schema in
`${CLAUDE_PLUGIN_ROOT}/references/graph-spec.md`. Any field missing or too vague to generate
from is a question owed to the user, not a blank to fill with a plausible default. Ask, then
update the spec file before writing code.

## 1. Scaffold

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_plugin.py --name <name> --description "<description>" --dest <parent-dir>
```

Copies the plugin, verifies `graph.py`/`skill_runner.py` land byte-identical, renames the
template skill/test/command files, and rewrites `plugin.json`. It prints what remains
domain-specific — treat that list as the remaining work.

**Never hand-edit `graph.py` or `skill_runner.py`** in the generated plugin to fit one
plugin's logic. A failing byte-identity check is a bug in the scaffold script, not something
to patch around in its output.

## 2. Write the domain logic

The generated plugin's `README.md` "Customize" section holds the exact shape each file needs.
Fill in from the spec:

- `scripts/<name>_skill.py` — `SKILL_NAME`, `build_graph()`, router(s), `on_transition()`
- `commands/<name>.md` — a literal numbered procedure, not abstract prose (see
  `${CLAUDE_PLUGIN_ROOT}/LEARNING_CHECKLIST.md` on why that distinction carries the enforcement).
  Keep the inherited step that prints the script's `banner` field verbatim — that line is how
  the user sees which node is running and why — and the step that prints `preview` verbatim,
  the one-line map of the whole graph with that node highlighted. Both cost nothing to preserve.
- `scripts/test_<name>_skill.py` — replace inherited teacher-shaped scenarios with the real
  graph's: each router branch, the loop, and the termination
- `AGENTS.md`/`README.md` — replace remaining teacher/explain-demonstrate-check mentions with
  the real domain

Then, **only for nodes the spec flagged with an attachment**, adapt the matching template
from `${CLAUDE_PLUGIN_ROOT}/templates/`. Read `${CLAUDE_PLUGIN_ROOT}/templates/README.md`
first — it lists the destination paths and the frontmatter traps that fail silently. Each
template also carries its own comment block of rules; **delete that block when adapting.**

- `templates/agent.md` → `agents/<node>-agent.md` in the generated plugin root. Carry the
  node's `goal` in as the brief and its `expected_output` in as the return contract, then
  make the generated command file dispatch to it at that node instead of generating inline.
- `templates/skill.md` → `skills/<kebab-name>/SKILL.md` (filename exactly `SKILL.md`).
- `templates/mcp.json` → `.mcp.json` **with the leading dot**, at the generated plugin's
  root, one entry per external system. Tell the user plainly that this config is unverified
  until they run it — the server has to already exist on their machine.

A node with no flagged attachment gets nothing extra. Resist emitting all three for
symmetry: the generated plugin should stay readable in one sitting.

Keep it navigable as the graph grows: one `add_node` block per node, routers named
`<node>_router`, non-trivial `on_transition` branching factored into named helpers, and node
names spelled identically across graph, command file, and tests so one grep traces a node
end-to-end.

## 3. Verify

```
cd <new-plugin> && python3 -m unittest scripts.test_<name>_skill -v
```

Tests must pass **and** exercise the new graph. Tests still describing
`explain`/`demonstrate`/`check` mean step 2 is unfinished, not that the plugin is ready.
Every router branch and the loop termination need a test — those are the paths a wrong answer
actually reaches.
