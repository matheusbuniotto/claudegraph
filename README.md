# claudegraph

A Claude Code plugin for creating LangGraph-style plugins.

Claude following a numbered list in a markdown command file is *advisory* — nothing stops it
from skipping a step, merging two, or narrating work it never did. `claudegraph` moves the
routing into deterministic, stdlib-only Python: a small state-graph engine decides what happens
next, and Claude generates the content for whatever node it's told it's on.

## What's in here

- **`claudegraph/`** — the plugin.
  - **`skills/scaffold-graph-plugin/`** — the generator. Interrogates you for a complete graph
    spec (per node: kind, goal, tools, expected output, logging; per edge: exact conditions and
    destinations; per loop: trigger and termination), then produces a working plugin from it.
  - **`scripts/graph.py` + `scripts/skill_runner.py`** — the engine. Nodes, edges, conditional
    edges, a step budget, checkpointing, and an append-only evidence log. No dependencies.
  - **`/teacher`** — a worked example that proves the pattern end to end.
- **`.claude-plugin/marketplace.json`** — marketplace manifest, so the plugin installs the same
  way any published plugin does.

## Install

```
/plugin marketplace add matheusbuniotto/claudegraph
/plugin install claudegraph@claudegraph
```

Then run `/teacher <topic>` to see the pattern, or ask Claude to scaffold a new graph-based
plugin to use the generator.

## Design notes

The repo documents its own reasoning rather than just its API:

- **`claudegraph/README.md`** — structure, install, and how to customize.
- **`claudegraph/ROADMAP.md`** — ideas considered and *deliberately deferred*, with why
  (parallel/DAG execution, declarative graph specs, hook-based hard enforcement).
- **`claudegraph/LEARNING_CHECKLIST.md`** — the design decisions behind the current shape.

Known limitations are stated plainly in `claudegraph/README.md` — most importantly that this
shrinks the "Claude might not follow instructions" problem rather than eliminating it, and that
the engine is single-active-node, not a parallel DAG scheduler.

## License

MIT
