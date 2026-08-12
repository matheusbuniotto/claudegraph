# airbend — Agent Runtime CLI (Implementation Plan)

## 1. Context & vision

**airbend** is an agent runtime + CLI (name: *air*flow + *bend* the graph). It receives **goals/events**, executes them as **runs** through a declarative **DAG/state-machine graph**, and exposes full control over graph, state, retries, and interrupts through an **AXI-compliant CLI** that AI agents can script.

The synthesis grounding (from `research/airflow-and-langgraph.md`):

| Concept | Borrowed from | Why |
|---|---|---|
| Durable, DB-backed runs; explicit per-node states; retries; XCom-style data passing | Airflow | Agents need the same observability/durability guarantees as batch orchestration |
| Conditional edges (`on: success/failure/value`), interrupts + resume with injected input, per-step checkpoints | LangGraph | This is what makes it a *state machine*, not just a DAG — runtime-decided control flow, agent-in-the-loop |
| **The runner is an agent** (LLM-driven, tool-using, like Claude Code / Kimi) | new | The "executor" of each node is an agent loop; the CLI is the control plane over the graph/state |

## 2. Core concepts

| airbend concept | Description |
|---|---|
| **Graph** | Static, versioned definition (YAML): nodes, static edges (`depends_on`), conditional edges (`on:`), schedule. Cycle-checked, like Airflow's DAG. |
| **Run** | One instantiation of a graph (Airflow DAGRun + LangGraph checkpointed thread merged). Durable row in SQLite. May carry a **goal** string. |
| **NodeRun** | Stateful record of one node execution within a run (Airflow TaskInstance / LangGraph PregelNode step). |
| **Channels** | The data-passing store (XCom + LangGraph channels): `overwrite` (LastValue), `append` (Topic), `reduce` (BinaryOperatorAggregate). Read/write by nodes and executors. |
| **Executor** | Pluggable way a node runs: `command`, `python`, `http`, `agent` (the LLM-driven runner). |
| **Event** | Append-only JSONL record of every transition (`pending→scheduled→running→…`); the agent-facing telemetry stream. |
| **Goal** | A first-class input object (`goal create "…"`) that can trigger a run; also accepted inline via `run start --goal`. |

### Node state machine (the core abstraction)

```
pending → scheduled → running → { success, failed, skipped, deferred }
                                    │
              failed ── retries left? ──→ scheduled (attempt++)
              failed ── no retries ──→ conditional edge `on: failure` → next node
                                        (or run failed)
              deferred ← interrupt: paused waiting on external input
              deferred → resume --input <json> → scheduled (input injected)
```

- `deferred` = LangGraph-style interrupt (agent-in-the-loop / human-in-the-loop): the run pauses at a safe point, state is checkpointed, and `airbend run resume --input` re-enters.
- Failure-driven routing (`on: failure: <node>`) is the headline synthesis feature Airflow lacks.

## 3. Architecture

Layers:

```
┌─────────────────────────────────────────────────────┐
│ CLI (control plane) — argparse + AXI wrapper        │  fast --version path, TOON out
├─────────────────────────────────────────────────────┤
│ Runtime core: Graph model · Scheduler loop · States │
├─────────────────────────────────────────────────────┤
│ Store: SQLite (graphs, runs, node_runs, channels,   │
│        events, goals)                               │
├─────────────────────────────────────────────────────┤
│ Executors: command | python | http | agent          │
├─────────────────────────────────────────────────────┤
│ Agent executor: LLM loop + tools (the runner)       │  lazy-imported (keeps CLI fast)
└─────────────────────────────────────────────────────┘
```

### Module layout (Python package `airbend/`)

```
airbend/
  version.py     # VERSION constant — leaf module, stdlib only (AXI fast path)
  cli.py         # entry; fast --version check BEFORE heavy imports; arg dispatch
  toon.py        # TOON serializer + truncation helpers (internal JSON, TOON at boundary)
  errors.py      # structured errors → stdout + exit codes (0/1/2)
  graph.py       # Graph, Node, Edge, conditional edges, validate() (cycle check)
  states.py      # NodeState enum + allowed transitions
  run.py         # Run model + repository
  scheduler.py   # per-run loop: ready-set → dispatch → apply results → events
  store.py       # SQLite schema + repositories
  channels.py    # overwrite / append / reduce semantics
  events.py      # event emission + JSONL sink
  executors/
    base.py      # Executor protocol: execute(node_ctx) -> Result
    command.py   # shell command
    python.py    # python callable (dotted path)
    http.py      # HTTP/webhook
    agent.py     # LLM agent loop
  agent/
    loop.py      # agent executor: task render → prompt → envelope parse
    runner.py    # headless Claude Code / Codex CLI delegation (claude -p / codex exec)
  server.py      # PHASE 2+: `serve` daemon + session hook + skill assets
```

### Scheduler loop (per run, on-demand — no daemon in v1)

```
load graph + run
loop:
  ready = nodes whose deps satisfied AND conditions met AND state == pending/scheduled
  if not ready:
      if any node deferred: wait (run stays alive or pauses) → resume re-enters
      elif all terminal: finish run (leaf-state rollup like DagRun.update_state)
      else: run failed (deadlock/cycle/errors) → emit failure event
  for node in ready (respect max_parallel):
      mark running; dispatch to executor (subprocess for command/python; HTTP; agent loop)
      on result: apply channel writes; set success/failed/skipped; emit event
      on failure: retry policy → scheduled, or `on: failure` edge, or interrupt
```

## 4. Data model (SQLite, stdlib `sqlite3`)

```
graphs(id TEXT PK, version INT, config_json TEXT, created_at, updated_at)
runs(id TEXT PK, graph_id FK, goal TEXT NULL, status TEXT, params_json,
     started_at, ended_at)
node_runs(run_id FK, node_id TEXT, state TEXT, attempt INT, input_json,
          output_json, error TEXT, started_at, ended_at,
          PK(run_id, node_id))
channels(run_id FK, key TEXT, value_json, op TEXT, PK(run_id, key))
events(seq INTEGER PK AUTOINCREMENT, run_id FK, ts, type TEXT, node_id TEXT,
       payload_json)
goals(id TEXT PK, text, status, run_id FK NULL, source TEXT, created_at)
```

Runs support **resume** natively: a run in `interrupted`/`deferred` state keeps its node_runs/channels, so `resume` re-enters the loop without losing checkpoint state (LangGraph checkpoint semantics, simplified to SQLite).

## 5. Config format (IaC, YAML)

```yaml
id: release_pipeline
schedule: manual            # manual | goal | cron "..." | event (daemon, phase 2+)
version: 1
channels:
  result: { op: overwrite }      # default overwrite; append/reduce available
max_parallel: 3
nodes:
  - id: plan
    executor: { type: agent, model: null, max_steps: 10, task: "Plan the release for: {{goal}}" }
  - id: build
    executor: { type: command, cmd: "scripts/build.sh" }
    retries: 2
    timeout: 300
    depends_on: [plan]
  - id: verify
    executor: { type: python, entry: "pkg.verify:run" }
    depends_on: [build]
    routes:
      success: deploy
      failure: triage        # conditional edge — failure-driven routing
  - id: triage
    executor: { type: agent, task: "Diagnose failure; write root cause to channel `diagnosis`" }
  - id: deploy
    executor: { type: http, url: "https://api.example.com/deploy", method: POST }
    depends_on: [verify]
    routes:
      failure: interrupt     # `interrupt` keyword → pause run for agent input
```

> Config note: conditional edges use the `routes:` key. YAML 1.1 parsers (e.g.
> PyYAML) interpret a bare `on:` as the boolean `true`, so that spelling is
> rejected with a hint; a quoted `"on":` is still accepted.

Goal-driven runs: `airbend run start --graph release_pipeline --goal "ship v2.0"` — `{{goal}}` templates into agent-node tasks. With no `--graph`, a default single-agent-node run executes the goal directly.

## 6. CLI surface (AXI-compliant)

### Home view — content first (no args)

```
$ airbend
bin: ~/.local/bin/airbend
description: Agent runtime — register graphs, run goals, control state
runs[2]{id,graph,status}:
  r_8f2a,release_pipeline,running
  r_91c1,data_sync,interrupted
goals: 1 open
count: 2 runs total
help[4]:
  Run `airbend run status <id>` to inspect a run
  Run `airbend run resume <id> --input json` to continue an interrupted run
  Run `airbend dag register <config.yaml>` to add a graph
  Run `airbend --help` for the full reference
```

### Commands

```
airbend dag register <file>          # idempotent: same version → no-op, exit 0
airbend dag validate <file>          # schema + cycle check; errors on stdout, exit 1
airbend dag list                     # id,version,nodes,schedule (TOON, default 100)
airbend dag show <id>                # detail: nodes, edges, conditional routes
airbend dag plan <file>              # diff vs registered (what register would change)
airbend run start <dag> [--goal "…"] [--params json] [--watch]
airbend run list [--status …]        # aggregates: "count: N of M total"
airbend run status <run_id>          # aggregate + per-node states
airbend run events <run_id> [--follow]  # JSONL event stream (stdout)
airbend run logs <run_id> --node <id>   # truncated logs + total size + escape hatch
airbend run interrupt <run_id>          # pause at next safe point → state deferred
airbend run resume <run_id> --input json
airbend run retry <run_id> --node <id>
airbend goal create "…" [--graph <id>] [--run]   # goal → run
airbend goal list / goal view <id>
airbend setup                        # phase 3: install session hook + skill
airbend --version / -v / -V          # bare version, exit 0, fast path (<20ms)
```

Every command accepts `--json` to switch stdout to JSON (internal format is always JSON; TOON is the boundary serializer). `--help` available on every command.

### AXI compliance (mapped to implementation)

| AXI rule | Implementation |
|---|---|
| TOON output, JSON internal | `toon.py`; all logic on dicts, TOON at stdout boundary |
| Minimal default schemas | lists default to 4 fields; `--fields` flag for more |
| Content truncation | `logs`/`show` truncate at 1000 chars, print total size + `--full` hint |
| Pre-computed aggregates | `run status` shows per-node summary inline; `list` prints `count: N of M total` |
| Definitive empty states | `runs: 0 runs found` (never blank stdout) |
| Idempotent mutations | `dag register` same-version → `no-op`, exit 0; `interrupt` on interrupted run → no-op |
| Structured errors on stdout | `error: …` + `help: <command>`; never leak tracebacks; exit 1 |
| No interactive prompts | every op completable with flags; missing value → immediate error, exit 2 |
| Fail loud on unknown flags | per-subcommand flag sets; `error: unknown flag --stat for \`list\`` + valid flags inline; `--help` always passes; renamed flags get targeted hint |
| Exit codes | 0 success/no-op, 1 error, 2 usage error; progress/logs to stderr only |
| Content first | home view = live runs + goals + hints |
| Contextual disclosure | help hints are complete commands with `<placeholders>` |
| `--version` fast path | `version.py` leaf module (stdlib only); `cli.py` checks argv before importing deps; test compares against `python -c "print(1)"` floor |
| Session integration + skill (phase 3) | `airbend setup` installs hook (Claude Code/Codex/OpenCode), generates SKILL.md from home-view content, `--check` staleness gate in CI |

## 7. Phases & acceptance criteria

**Phase 0 — Scaffold**
- `pyproject.toml` (uv), package layout, `version.py` leaf, fast `--version` path, `toon.py`, `errors.py`, CLI skeleton with home view + per-command `--help`, empty-state + unknown-flag handling.
- ✅ `airbend --version` exits 0 in <20ms; `airbend` prints content-first TOON home; unknown flag → exit 2 with self-correcting hint.

**Phase 1 — Core state machine**
- `graph.py` (+ validate/cycle check), `store.py` (SQLite schema), `states.py`, `scheduler.py`, `channels.py`, `events.py`, executors `command`/`python`/`http`; CLI `dag register/validate/list/show/plan`, `run start/list/status/events`, retry policy, `on: failure` routing.
- ✅ Register + validate a 3-node YAML graph; run succeeds end-to-end with events streamed; a failing node retries then routes via `on: failure`; cycle config → validate rejects, exit 1.

**Phase 2 — Agent executor + goals**
- `agent/` (LLM loop, tools: read/write channel, emit event, request_input), `executor: agent` nodes, `run start --goal`, `goal create/list/view`, `run interrupt/resume --input`, `run retry`.
- ✅ An agent node receives `{{goal}}`, writes a channel result, run completes; interrupt pauses the run, `resume --input` re-enters with injected input and finishes.

**Phase 3 — Agent integration surface (AXI §7)**
- `airbend setup` (idempotent, path-repairing hook install for Claude Code/Codex/OpenCode; SessionStart dashboard = home view), installable `SKILL.md` generated from home-view content with `--check` staleness gate, README documenting hook + skill as two paths.
- ✅ Hook install is a silent no-op on re-run; session-start context renders the same content as `airbend`; `airbend skill --check` passes in CI.

**Phase 4 — Optional daemon (`airbend serve`)**
- Event-driven intake (webhooks → goals/runs), `event` schedule type, cron scheduling via the daemon loop.

## 8. Decisions & rationale

- **Python** (chosen by user): domain fit with Airflow/LangGraph; `agent` executors can import python callables.
- **stdlib `argparse` + thin AXI wrapper** over Typer/Click: full control over AXI error formats (per-subcommand unknown-flag rejection, inline help), near-zero startup cost, no dependency weight. Rich help text is hand-written, TOON output, so Typer's auto-formats buy little.
- **stdlib `sqlite3`** store: zero deps, single file, durable checkpoints; WAL mode for concurrent CLI + run.
- **TOON**: small internal serializer (~150 lines) — TOON is a simple line-oriented format; no external dependency needed.
- **LLM provider**: none — the agent executor delegates to the installed
  agent CLI (Claude Code `claude -p` / Codex `codex exec`), which runs its
  own tool loop with its own model/config. Selection: executor `agent:`
  field > `AIRBEND_AGENT` env > auto-detect. The agent replies with a JSON
  envelope (`result` / `writes` / `request_input`).
- **Executors run as subprocesses** (command/python) so a hung node cannot kill the runtime; timeouts enforced by the scheduler.

## 9. Non-goals (v1)

- No webserver/UI, RBAC, plugins, sensors-as-operators, backfill matrix, Celery.
- No DAG-file parsing subprocess farm (Airflow's DagFileProcessor) — graphs are data, not code.
- No Pregel bulk-sync-parallel machinery; no recursion limits (cycles are invalid — `validate` rejects them).
- Multi-node fleet scheduling is out of scope; single machine, SQLite-backed.
