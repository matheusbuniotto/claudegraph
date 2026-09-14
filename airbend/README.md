# airbend

An Airflow-style runtime for agent workflows. Define a graph in YAML, run it as a durable
run, and control every transition from the CLI. Nodes can be shell commands, Python
functions, HTTP calls, or Claude Code / Codex agents running headless.

```
airbend dag register pipeline.yaml          # validate + register (idempotent, versioned)
airbend run start pipeline --goal "ship v2" # start a run
airbend run status r_ab12cd34               # per-node state
airbend run events r_ab12cd34 --follow      # live JSONL event stream
airbend run interrupt r_ab12cd34            # pause at the next safe point
airbend run resume r_ab12cd34 --input '{}'  # continue with injected input
airbend run retry r_ab12cd34 --node build   # re-run one failed node
```

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run airbend --version
```

## Try it

```
uv run airbend dag register examples/hello.yaml
uv run airbend run start hello --watch
```

`examples/hello.yaml` uses only command nodes and runs anywhere.
`examples/review.yaml` reviews the last git commit with two agent nodes and needs
`claude` or `codex` on `PATH`.

## Model

| Concept | Meaning | Borrowed from |
|---|---|---|
| Graph | Versioned YAML definition: nodes, `depends_on` edges, conditional `routes`, schedule. Cycle-checked on load. | Airflow DAG |
| Run | One execution of a graph, optionally with a goal and params. Persisted in SQLite. | Airflow DagRun, LangGraph thread |
| Node state | `pending → scheduled → running → success / failed / skipped / deferred` | Airflow TaskInstance |
| Channels | Per-run key/value store nodes read and write. | Airflow XCom, LangGraph channels |
| Routes | `success:` / `failure:` edges chosen at runtime, or `failure: interrupt` to pause. | LangGraph conditional edges |
| Interrupt / resume | A `deferred` node pauses the run. `resume --input` injects a value as channel `__input`. | LangGraph `interrupt` |

The SQLite database is the checkpoint. A crashed or stopped driver loses nothing, and
`run resume` continues from the stored state.

## A graph

```yaml
id: release
version: 1
nodes:
  - id: plan
    executor: { type: agent, task: "Plan the release for: {{goal}}" }
  - id: build
    executor: { type: command, cmd: "scripts/build.sh" }
    depends_on: [plan]
    retries: 2
  - id: verify
    executor: { type: python, entry: "pkg.verify:run" }
    depends_on: [build]
    routes:
      success: deploy
      failure: triage
  - id: triage
    executor: { type: agent, task: "Diagnose the failure: {{channels.verify}}" }
  - id: deploy
    executor: { type: http, url: "https://api.example.com/deploy" }
    routes:
      failure: interrupt
```

Use `routes:`, not `on:`. YAML 1.1 parses a bare `on` key as a boolean, so airbend rejects
it with a hint. The full schema, executor fields, and agent reply contract are in
[docs/reference.md](docs/reference.md).

## Agent nodes

An `agent` node runs the installed agent CLI headless: `claude -p` or `codex exec`. The
executor's `agent` field picks one, then the `AIRBEND_AGENT` variable, then whichever is
found on `PATH`. The task template is rendered with the goal, params, and channels, and
the agent replies with a JSON envelope:

```json
{"result": "...", "writes": {"channel": "value"}, "request_input": "optional prompt"}
```

Setting `request_input` pauses the run until an operator resumes it.

Claude agent nodes default to `bypassPermissions` so unattended runs don't stall on
prompts. Set `permission_mode: plan` or `default` on any node that should not edit files
or run commands freely.

## Scheduling

```
airbend serve                   # fire graphs with `schedule: cron "0 9 * * *"`
airbend serve --webhook :8080   # also accept POST /v1/events {"graph": "<id>", "goal": "..."}
airbend serve --once            # one scheduling pass, then exit
```

The webhook binds to `127.0.0.1` and has no authentication. Put it behind a proxy
before exposing it.

## Agent integration

airbend's output is built for agents to read: TOON on stdout, `--json` on every command,
structured `error:` / `help:` messages, exit codes `0` success, `1` error, `2` usage, and
no interactive prompts.

```
airbend setup                        # SessionStart hook: Claude Code and Codex see live runs
airbend setup --uninstall
airbend skill skills/airbend/SKILL.md          # write an installable skill
airbend skill skills/airbend/SKILL.md --check  # CI check that it is current
```

State lives in `$AIRBEND_HOME/airbend.db`, default `~/.airbend/`.

## Limitations

- **Execution is serial.** One node runs at a time. `max_parallel` is validated but not
  yet used.
- **Graphs are acyclic.** Retries cover repeat attempts. Loops that return to an earlier
  node are rejected at validation.
- **Single machine.** One SQLite file, no distributed workers.

## Development

```
uv run pytest
uv run ruff check .
```

Design background on the Airflow and LangGraph internals this borrows from is in
[docs/airflow-and-langgraph.md](docs/airflow-and-langgraph.md).
