# airbend — config & command reference

Companion to [SKILL.md](SKILL.md). Airbend executes declarative graphs as durable
runs; this reference covers the full config schema, commands, and the agent
envelope contract.

## Graph config (YAML)

```yaml
id: release_pipeline        # required; unique id (also the registration key)
version: 1                  # required; bump to replace a registered config
schedule: manual            # manual | goal | event | cron "0 9 * * *"
channels:                   # optional channel declarations
  notes: { op: append }     #   op: overwrite | append
max_parallel: 3             # optional concurrency bound (>= 1; execution is serial in v1)
nodes:                      # required; at least one
  - id: build               # required; unique within the graph
    executor: { type: command, cmd: "scripts/build.sh" }   # required
    depends_on: [plan]      # static edges (must reference existing node ids)
    retries: 2              # extra attempts after failure (default 0)
    timeout: 300            # seconds; per-executor defaults apply when unset
    routes:                 # conditional edges (LangGraph-style)
      success: deploy       #   released when this node SUCCEEDS
      failure: triage       #   released when this node FAILS terminally
      # failure: interrupt  #   keyword: pause the run instead of routing
```

Validation: cycle check over all edges (dep + conditional), schema checks,
executor field checks, cron expression checks. Errors list the first problem
and a count of the rest.

## Executors

| type | required fields | notes |
|---|---|---|
| `command` | `cmd` | run via shell; stdout JSON-parsed if possible, else raw text; env: `AIRBEND_CTX_FILE`, `AIRBEND_RUN_ID`, `AIRBEND_NODE_ID`, `AIRBEND_GOAL` |
| `python` | `entry` (`pkg.module:func`, default func `run`) | receives the context dict; must `print(json.dumps(result))` |
| `http` | `url` | POSTs the context as JSON; parses the response body |
| `agent` | `task` (optional) | delegates to Claude Code / Codex headless — see "Agent envelope" |

Defaults: `retries: 0`; timeouts 300s (command/python), 60s (http), 600s (agent).

## Edges and failure semantics

- `depends_on`: satisfied when the upstream node `success` (skipped does not
  release; skipped propagates to dependents).
- `routes.success: <node>`: released when this node succeeds.
- `routes.failure: <node>`: released when this node fails terminally (after
  retries). Without it, a failed node fails the run immediately.
- `routes.failure: interrupt`: node becomes `deferred`, the run pauses.
- Unreachable alternatives (e.g. a `failure` route target whose source
  succeeded) are marked `skipped` at the end, Airflow-style.
- Run outcome is rolled up from **leaf** nodes: any leaf failed → run failed;
  any leaf deferred → interrupted; else success.

## Channels

- Every successful node writes its output to the channel named by its node id.
- A dict output also writes each key as its own channel (overwrite; `append` if
  declared under `channels:`).
- `airbend run resume --input` stores the injected value as channel `__input`.
- Agents can write arbitrary channels via the envelope `writes` field.

## Commands

| command | purpose |
|---|---|
| `airbend` | content-first home: recent runs, graph count, next steps |
| `airbend dag register <file>` | idempotent, versioned registration |
| `airbend dag validate <file>` | schema + cycle check, no write |
| `airbend dag list` / `dag show <id>` | registered graphs / structure |
| `airbend dag plan <file>` | diff vs registered |
| `airbend run start <dag> [--goal] [--params json] [--watch]` | start a run |
| `airbend run status <id>` / `run list [--status s]` | inspect |
| `airbend run events <id> [--follow]` | JSONL event stream |
| `airbend run interrupt <id>` / `run resume <id> [--input json]` | pause / continue |
| `airbend run retry <id> --node <n>` | re-run one failed/deferred node |
| `airbend goal create "<text>" [--run --graph <id>]` / `goal list` / `goal view <id>` | goals |
| `airbend serve [--webhook :port] [--once]` | cron + webhook daemon |
| `airbend setup [--uninstall]` | install Claude Code / Codex session hooks |
| `airbend skill [path] [--check]` | generate / verify the minimal installable skill |

## Agent envelope contract

Agent nodes delegate to an installed agent CLI headless and expect a JSON
envelope on stdout:

```json
{"result": <node output>, "writes": {"channel": value}, "request_input": "<prompt or absent>"}
```

- `result` → node output (stored under the node-id channel).
- `writes` → applied to the run's channels (overwrite).
- `request_input` → run pauses (`deferred`); `resume --input` re-enters and the
  value is available as channel `__input`.

CLI selection: executor `agent: claude|codex|auto` → env `AIRBEND_AGENT` →
auto-detect (`claude` then `codex` on PATH). Agent-specific options:
`permission_mode` (`default|acceptEdits|bypassPermissions|plan` for claude;
`danger-full-access` → `--full-auto` for codex). Context (`goal`, `params`,
`channels`) is templated into the prompt; the full context JSON is at
`$AIRBEND_CTX_FILE`.

## Output format (AXI)

- TOON on stdout; `--json` on every command. Example table:

```
runs[2]{id,graph,status}:
  r_ab12,release_pipeline,running
  r_cd34,data_sync,interrupted
count: 2 runs total
```

- Exit codes: `0` success/no-op, `1` error, `2` usage. Errors are structured:
  `error: <what>` + `help: <how to fix>` on stdout.
- Never prompts; unknown flags rejected with the valid set listed inline.

## Environment

| var | meaning |
|---|---|
| `AIRBEND_HOME` | state directory (default `~/.airbend`) |
| `AIRBEND_AGENT` | agent CLI selection: `claude` \| `codex` \| `auto` |
