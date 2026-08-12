---
name: build-graph
description: Build a new LangGraph-style plugin — interrogates for a complete graph spec, then scaffolds and fills in a working plugin.
---

Request: $ARGUMENTS

Generate a new plugin that reuses this plugin's engine (`scripts/graph.py` +
`scripts/skill_runner.py`) unchanged, writing only the domain-specific parts: one skill
file, one command file, and tests for the new plugin's real graph.

The engine is fixed and proven. The variable is the graph — so output quality is decided
entirely by how precisely the graph gets specified before any file is written.

## 1. Interrogate until the graph spec is complete

**Do not scaffold from a partial spec.** Every field in
`${CLAUDE_PLUGIN_ROOT}/references/graph-spec.md` must be filled by the user's answer, never
by invention. An unfilled field is a question still owed. Read that file now — it holds the
field schema, a worked non-teacher example, and how each field maps to code.

This applies whether the user arrives with nothing or with a written spec. A supplied spec is
a starting point, not a finished interrogation — read it, then drive out what it left
implicit: unstated edge cases, goals too vague to generate from, outputs nothing downstream
reads, loops with no termination.

Ask in this order, in small batches rather than one overwhelming block:

1. **Identity** — plugin name (kebab-case) and one-line description.
2. **Node inventory** — what are the steps, in order? Names only, first.
3. **Per node** — `kind`, `goal`, `agent`/tools, `expected_output`, and any extra
   `log_fields`. Use AskUserQuestion for `kind` (fixed choice: task / human_gate / end); ask
   open questions for goals and domain logic.
4. **Edges** — the plain path, then for every branching node: the exact condition and the
   exact destination for each branch.
5. **Loop/retry policy** — for any edge returning to an earlier node: trigger, termination
   condition, and which transition increments the retry counter.
6. **Observability** — anything needed beyond the default evidence log (`from`/`to`/`data`/
   `retry_count`/`step_count` are already logged).

Before writing files, **restate the collected spec in the structured form of
`references/graph-spec.md` and get explicit confirmation.** Prose answers get converted to
that shape first — the restatement is where mismatched assumptions surface cheaply.

Stop and flag, rather than designing around it, if the request needs concurrent branches:
this engine is single-active-node (see `${CLAUDE_PLUGIN_ROOT}/ROADMAP.md`'s Terraform/DAG
section). A parallel graph is a different, unbuilt foundation.

## 2. Run the mechanical scaffold

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_plugin.py --name <name> --description "<description>" --dest <parent-dir>
```

Copies the plugin, verifies `graph.py`/`skill_runner.py` land byte-identical, renames the
template skill/test/command files, and rewrites `plugin.json`. It prints what remains
domain-specific — treat that list as the remaining work.

**Never hand-edit `graph.py` or `skill_runner.py`** in the generated plugin to fit one
plugin's logic. A failing byte-identity check is a bug in the scaffold script, not something
to patch around in its output.

## 3. Write the domain logic

The generated plugin's `README.md` "Customize" section holds the exact shape each file needs.
Fill in from the confirmed spec:

- `scripts/<name>_skill.py` — `SKILL_NAME`, `build_graph()`, router(s), `on_transition()`
- `commands/<name>.md` — a literal numbered procedure, not abstract prose (see
  `${CLAUDE_PLUGIN_ROOT}/LEARNING_CHECKLIST.md` on why that distinction carries the enforcement)
- `scripts/test_<name>_skill.py` — replace inherited teacher-shaped scenarios with the real
  graph's: each router branch, the loop, and the termination
- `AGENTS.md`/`README.md` — replace remaining teacher/explain-demonstrate-check mentions with
  the real domain

Keep it navigable as the graph grows: one `add_node` block per node, routers named
`<node>_router`, non-trivial `on_transition` branching factored into named helpers, and node
names spelled identically across graph, command file, and tests so one grep traces a node
end-to-end.

## 4. Verify

```
cd <new-plugin> && python3 -m unittest scripts.test_<name>_skill -v
```

Tests must pass **and** exercise the new graph. Tests still describing
`explain`/`demonstrate`/`check` mean step 3 is unfinished, not that the plugin is ready.
Every router branch and the loop termination need a test — those are the paths a wrong answer
actually reaches.
