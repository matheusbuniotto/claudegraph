# AGENTS.md

`claudegraph` is a Claude Code plugin for LangGraph-style workflows. A stdlib-only engine
(`scripts/graph.py` + `scripts/skill_runner.py`) decides routing. Commands are literal
procedures that call a skill script after every step. See `README.md` for the model.

## Where code belongs

- **`scripts/graph.py`**: skill-agnostic engine logic only.
- **`scripts/skill_runner.py`**: CLI plumbing shared by every skill (stdin/stdout JSON,
  validation, logging, checkpoints, banner).
- **`scripts/<name>_skill.py`**: everything specific to one skill: nodes, edges, routers,
  `on_transition` policy.
- **`commands/<name>.md`**: a literal numbered procedure. Prose like "follow the graph"
  is the drift this project exists to prevent.

Never edit `graph.py` or `skill_runner.py` to fit one skill. Add an engine capability
only when a real caller needs it.

## Rules

- **Stdlib only.** The plugin must run wherever it is installed, with no pip install.
- **Three commands.** `/graph-spec` plans, `/build-graph` implements, `/teacher` is the
  example. A fourth needs a concrete reason.
- **Generated plugins stay clean.** They must not inherit the generator's commands,
  templates, or references. `EXCLUDE_RELPATHS` in `scripts/scaffold_plugin.py` enforces
  this, and `scripts/test_scaffold_plugin.py` checks it.
- **Attachments are opt-in per node.** Follow the rules in `references/graph-spec.md`. A
  plugin where every node has an agent, a skill, and an MCP server is a design failure.

## Flag before building

Raise the tradeoff and a smaller alternative before any change that would:

- add a third-party dependency;
- add parallel execution, which belongs in `../airbend`, not here;
- weaken input validation or the step budget;
- change the `skill_runner.py` JSON contract without updating every command and test.

## Every change ships with

```
python3 -m unittest discover -s scripts -p "test_*.py"
```

passing, and `README.md` updated if behavior changed.
