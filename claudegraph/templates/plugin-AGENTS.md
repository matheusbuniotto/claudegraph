# AGENTS.md

`{{NAME}}` — {{DESCRIPTION}}

A graph-executed plugin: `scripts/{{PY_STEM}}_skill.py` defines the node graph,
`commands/{{NAME}}.md` is the procedure that walks it, and `scripts/graph.py` +
`scripts/skill_runner.py` are the engine that decides routing deterministically.

## Where code belongs

- **`scripts/graph.py` and `scripts/skill_runner.py` are the engine — don't edit them
  to fit this plugin's logic.** They're deliberately skill-agnostic. Anything that
  needs to know about this plugin's domain belongs in the skill file instead.
- **`scripts/{{PY_STEM}}_skill.py`** — nodes, edges, router functions, and the
  `on_transition()` policy hook. All domain logic lives here.
- **`commands/{{NAME}}.md`** — a literal, numbered procedure. Keep it literal: prose
  like "follow the graph" is exactly the drift the engine exists to prevent. Keep the
  step that prints the script's `banner` field verbatim, so the user sees which node is
  running and why, and the step that prints `preview` verbatim, the one-line map of the
  whole graph with that node highlighted.
- **`scripts/test_{{PY_STEM}}_skill.py`** — every router branch and every loop
  termination needs a case. Those are the paths a wrong answer actually reaches.

## Constraints worth knowing before changing things

- **Stdlib only.** No pip installs — the plugin must work wherever it's installed.
- **Single active node.** The engine models one position moving through the graph over
  time, not concurrent branches. A request for parallel execution needs a different
  engine, not a patch to this one — say so rather than faking it.
- **`max_steps` is a crash guard, not policy.** It stops a runaway loop; real
  termination logic belongs in the router (`retry_count` vs `max_retries`).
- **Enforcement is partial.** Routing is deterministic once the script is called, but
  nothing forces Claude to call it. The JSONL evidence log proves after the fact whether
  it ran; it doesn't prevent skipping.

## Every change ships with

```
python3 -m unittest scripts.test_{{PY_STEM}}_skill -v
```

passing, and updated docs if behavior changed. State plainly when something is untested
rather than implying it works.
