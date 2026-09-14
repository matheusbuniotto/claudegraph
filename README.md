# claudegraph

Graph-based execution for Claude Code, in the style of LangGraph and Airflow.

Instructions in a markdown command are advisory. Claude can skip a step, merge two, or
report work it never did. This repo moves control flow out of prose and into code: a
deterministic engine decides which node runs next, and Claude only does the work for the
node it is on.

It ships two independent components that solve this at different levels.

| Component | Model | Runs where | Dependencies |
|---|---|---|---|
| [`claudegraph/`](claudegraph/) | LangGraph-style state machine: one active node, conditional edges, bounded loops, human gates | Inside an interactive Claude Code session, as a plugin | None (stdlib) |
| [`airbend/`](airbend/) | Airflow-style DAG runtime: durable runs, retries, failure routing, interrupt/resume, cron | Outside the session, as a CLI that calls `claude -p` per node | PyYAML |

## Which one to use

- **Use `claudegraph`** when a human is in the loop and the workflow lives in a
  conversation: tutoring, triage, guided reviews. Routing is enforced per step, and every
  transition is logged.
- **Use `airbend`** when the workflow should run unattended: pipelines that mix shell,
  Python, HTTP, and agent steps, need retries and a persistent run history, or fire on a
  schedule.

## Quick start

**claudegraph** (Claude Code plugin):

```
/plugin marketplace add matheusbuniotto/claudegraph
/plugin install claudegraph@claudegraph
/teacher recursion
```

**airbend** (CLI):

```
cd airbend
uv sync
uv run airbend dag register examples/hello.yaml
uv run airbend run start hello --watch
```

See each component's README for the full model, configuration, and limitations.

## Development

```
# claudegraph: stdlib unittest
cd claudegraph && python3 -m unittest discover -s scripts -p "test_*.py"

# airbend: pytest + ruff
cd airbend && uv run pytest && uv run ruff check .
```

## License

MIT
