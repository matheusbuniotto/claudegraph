# {{NAME}}

{{DESCRIPTION}}

Routing is enforced by deterministic Python rather than by prose instructions: a small
state graph decides which node runs next, and Claude generates the content for whatever
node it's told it's on.

## Use it

```
/{{NAME}}
```

Each step prints a line naming the node and its goal, so a run reads as a visible trace:

```
▶ first-node (step 1) — what this node produces
⏸ a-human-gate (step 2) — waiting on your answer
■ end (step 3) — wrap up
```

`▶` working, `⏸` waiting on you, `■` finished.

## Structure

```
{{NAME}}/
├── .claude-plugin/plugin.json      # manifest
├── AGENTS.md                        # rules for agents editing this plugin
├── CLAUDE.md -> AGENTS.md           # symlink, one source of truth
├── commands/
│   └── {{NAME}}.md                  # the procedure that walks the graph
└── scripts/
    ├── graph.py                     # engine: nodes, edges, routing, step budget,
    │                                #   checkpointing, evidence log — don't edit
    ├── skill_runner.py              # CLI driver: stdin/stdout JSON, validation — don't edit
    ├── {{PY_STEM}}_skill.py         # THIS PLUGIN'S GRAPH: nodes, routers, retry policy
    └── test_{{PY_STEM}}_skill.py    # stdlib unittest
```

## Develop

```
python3 -m unittest scripts.test_{{PY_STEM}}_skill -v
```

The skill file is a CLI: it takes state as JSON on stdin and returns the next node on
stdout, so a single step can be exercised directly.

```
echo '{"current_node": "<node>", "data": {}}' | python3 scripts/{{PY_STEM}}_skill.py
```

Read `AGENTS.md` before changing anything — it covers where code belongs and which
constraints are deliberate.

## Built with

[claudegraph](https://github.com/matheusbuniotto/claudegraph).
