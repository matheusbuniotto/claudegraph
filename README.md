# claudegraph

Graph-based execution for Claude Code, in the style of LangGraph and Airflow.

Instructions in a markdown command are advisory. Claude can skip a step, merge two, or
report work it never did. This repo moves control flow out of prose and into code: a
deterministic engine decides which node runs next, and Claude only does the work for the
node it is on.

Two independent tools, no shared code. Pick by where the workflow runs:

| | `claudegraph/` | `airbend/` |
|---|---|---|
| Style | LangGraph: state machine, one active node | Airflow: DAG runtime, durable runs |
| Runs | Inside your Claude Code session (plugin) | Outside it (CLI calling `claude -p` per node) |
| Human in the loop | Yes, per step | Via interrupt / resume |
| Loops | Yes, bounded | No, retries only |
| State | JSON files per run | SQLite |
| Use for | Guided, conversational flows | Unattended pipelines, cron, retries |
| Deps | None | PyYAML |

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
