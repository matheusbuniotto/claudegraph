---
name: airbend
description: >-
  Manage and operate airbend, the agent runtime CLI: register DAG/state-machine
  graphs from YAML, start goal-driven runs, inspect per-node state, stream
  events, retry failed nodes, and interrupt/resume paused runs. Use when the
  user mentions airbend, DAGs, graphs, pipelines, goals, runs, or wants a
  workflow executed by an agent.
---

# airbend

Airbend executes declarative DAG/state-machine graphs as durable runs. Nodes are
command/python/http steps or delegate to a Claude Code / Codex agent. The CLI is
the control plane: register graphs, run goals, control state.

## Quick start
```
airbend dag register pipeline.yaml                  # validate + register (idempotent)
airbend run start pipeline --goal "ship v2" --watch # run in the foreground
airbend run status <run_id>                         # per-node states
airbend run events <run_id> --follow                # live JSONL event stream
```
## Core model
- **graph** — static, versioned YAML definition: nodes, `depends_on` edges,
  conditional `routes:` edges, schedule. `airbend dag` manages graphs.
- **run** — one instantiation of a graph; durable in SQLite at
  `$AIRBEND_HOME/airbend.db` (default `~/.airbend/`).
- **node state** — `pending → scheduled → running → {success, failed, skipped, deferred}`.
  `deferred` = paused, awaiting operator input.
- **channels** — data passed between nodes; a node's result lands under its
  node id, and dict results fan out per key for downstream nodes.

## Workflows
### Register a graph
```
airbend dag validate pipeline.yaml    # schema + cycle check (exit 0 = valid)
airbend dag plan pipeline.yaml        # diff vs registered, before registering
airbend dag register pipeline.yaml    # idempotent; bump `version:` to replace
```
Validation errors print `error:`/`help:` on stdout with exit 1.

### Run a goal
```
airbend run start pipeline --goal "ship v2" --params '{"env": "prod"}'
```
Without `--watch` the run executes in a detached subprocess; poll with
`run status` and `run events --follow`. `--watch` streams events, then prints
the final status.

### Inspect
- `airbend run list [--status running]` — recent runs
- `airbend run status <run_id>` — run + per-node states; read the `error:` cell
  on failed/deferred nodes
- `airbend run events <run_id>` — full event log (JSONL, one event per line)

### Handle a failure
1. `airbend run status <run_id>` — find the failed/deferred node and its error.
2. `airbend run retry <run_id> --node <node>` — re-run one node.
3. Or continue from an interrupt: `airbend run resume <run_id> --input json`.

### Pause and resume (agent-in-the-loop)
```
airbend run interrupt <run_id>                      # pause at next safe point
airbend run resume <run_id> --input '{"ok": true}'  # continue; input → channel `__input`
```
### Goals
```
airbend goal create "deploy the service" --run --graph pipeline
airbend goal list / airbend goal view <goal_id>
```
### Schedule / webhook (optional daemon)
```
airbend serve                    # fires graphs with schedule: cron "..."
airbend serve --webhook :8080    # also accepts POST /v1/events {"graph": id, "goal": "..."}
```
## Interacting with airbend
- **Output** is TOON on stdout: `key: value` lines and `name[N]{f1,f2}:` tables.
  Every command accepts `--json` for JSON instead.
- **Exit codes**: 0 success/no-op, 1 error, 2 usage. Errors are structured on
  stdout (`error:` + `help:`) — never raw tracebacks.
- **Never interactive**: pass values as flags; a missing required value fails
  with exit 2 and the valid flags listed inline. `--help` always works.
- **Durable**: state lives in SQLite, so a restart does not lose a run —
  `run status`/`run resume` pick up where it left off.

## Reference
Full config schema (executors, routes, channels, schedule), command reference,
and the agent envelope contract: see [REFERENCE.md](REFERENCE.md).
