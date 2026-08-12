# three-step-template

Shareable Claude Code plugin scaffold. The `/teacher` command is a worked example of a
small, stdlib-only, LangGraph-style state graph — enforced routing logic, not just
prose instructions Claude may or may not follow. Copy this directory to start a new plugin.

## Structure

```
three-step-template/
├── .claude-plugin/
│   └── plugin.json           # manifest (required)
├── commands/
│   └── teacher.md            # /teacher — literal, numbered procedure that calls the script
├── scripts/
│   ├── graph.py               # generic engine: State, Graph (add_node/add_edge/
│   │                          #   add_conditional_edge/step) — knows nothing about teaching
│   ├── teacher_skill.py       # example skill: explain -> demonstrate -> check,
│   │                          #   loops on misunderstanding, exits via retry_count vs max_retries
│   └── test_teacher_skill.py  # stdlib unittest, run: python3 -m unittest scripts.test_teacher_skill -v
├── LEARNING_CHECKLIST.md     # design rationale from building this: problem / solution / context
└── README.md
```

## Install

**Fast dev loop** (no marketplace, loads the plugin directly for a session):
```
claude --plugin-dir ./three-step-template
```

**Real install path** (what an actual user goes through — needs a marketplace):
```
/plugin marketplace add /path/to/marketplace-repo
/plugin install three-step-template@<marketplace-name>
```
See `../.claude-plugin/marketplace.json` in this repo for a working local marketplace example.
Note: local-path marketplaces are CLI-only — the Claude Desktop/Cowork plugin UI only installs
from registered marketplace listings, not an arbitrary local directory.

## Customize

1. Rename `name` in `.claude-plugin/plugin.json` (and in `marketplace.json`'s `plugins[].name`/`source`).
2. `scripts/graph.py` is the reusable part — leave it alone unless the engine itself needs to change.
3. Write your own `scripts/<your_skill>.py` following `teacher_skill.py`'s shape: define nodes,
   wire `add_edge`/`add_conditional_edge`, write a pure router function per conditional node,
   handle malformed stdin at the boundary, print `{next_node, ...}` JSON — never generate content
   in Python. Content generation stays Claude's job, driven by the command file.
4. Write `commands/<your_command>.md` as a literal numbered procedure (see `teacher.md`) that calls
   your script after each step and reads `next_node` — abstract prose ("follow the graph") is
   exactly the enforcement gap this pattern exists to shrink.

## Why KISS

The engine (`graph.py`) is genuinely minimal: stdlib only, one class, one factory-worth of
methods. Complexity was deliberately deferred at several points along the way — see
`LEARNING_CHECKLIST.md` for the actual design decisions and the YAGNI calls (e.g. no
"list possible next nodes" introspection method, no declarative graph-spec loader) made
while building this, and `ROADMAP.md` for a bigger direction (Terraform-style parallel/
depends_on graphs) considered and explicitly deferred as a separate, future project.

## Known limitations

- **Enforcement is partial, not absolute.** The script's routing is deterministic once called,
  but nothing mechanically forces Claude to call it instead of free-forming — that still rests
  on `commands/teacher.md`'s instructions. A `PreToolUse` hook could make this a hard guarantee;
  not built here, see `ROADMAP.md`.
- **Single active node only.** This models one position moving through the graph over time —
  not concurrent branches. See `ROADMAP.md` for what a true parallel/DAG version would require.
