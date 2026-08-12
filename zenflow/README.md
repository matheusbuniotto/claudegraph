# airbend

Agent runtime + CLI — register DAGs as declarative config, run goals through
a graph/state-machine, and control every transition. The runner is an agent;
the CLI is the control plane. AXI-compliant: TOON output, structured errors,
agent-scriptable.

```
airbend dag register pipeline.yaml          # idempotent, versioned
airbend run start pipeline --goal "ship v2"
airbend run status r_ab12cd34               # per-node states
airbend run events r_ab12cd34 --follow      # JSONL event stream
airbend run interrupt r_ab12cd34            # pause (agent-in-the-loop)
airbend run resume r_ab12cd34 --input json  # continue with injected input
```

Design: `docs/airbend-plan.md`. Research grounding (Airflow vs LangGraph):
`research/airflow-and-langgraph.md`.

## What a graph looks like

```yaml
id: release_pipeline
version: 1
nodes:
  - id: plan
    executor: { type: agent, task: "Plan the release for: {{goal}}" }
  - id: build
    executor: { type: command, cmd: "scripts/build.sh" }
    retries: 2
    depends_on: [plan]
  - id: verify
    executor: { type: python, entry: "pkg.verify:run" }
    depends_on: [build]
    routes:
      success: deploy
      failure: triage        # failure-driven routing
  - id: triage
    executor: { type: agent, task: "Diagnose the failure" }
  - id: deploy
    executor: { type: http, url: "https://api.example.com/deploy" }
    depends_on: [verify]
    routes:
      failure: interrupt     # pause for agent/human input
```

Conditional edges use `routes:` (YAML 1.1 parses a bare `on:` as a boolean,
so that spelling is rejected with a hint). Node states: `pending → scheduled
→ running → {success, failed, skipped, deferred}`. A `deferred` node pauses
the run; `resume --input` injects input as channel `__input`.

## Install

```
uv sync          # Python >= 3.11; deps: PyYAML only
uv run airbend --version
```

## Agent integration — two paths (pick one)

**Session hook (recommended):** ambient live state in every agent session.

```
airbend setup                 # installs Claude Code + Codex SessionStart hooks
airbend setup --uninstall     # remove them
```

At session start the agent sees the airbend home view (running/interrupted
runs, registered graphs, next steps) without invoking anything.

**Installable skill (secondary):** loaded on demand when a matching task
appears; works in any agent that supports skills; no per-session cost.

```
airbend skill skills/airbend/SKILL.md        # generate
airbend skill skills/airbend/SKILL.md --check   # CI staleness gate
```

The skill is generated from the CLI's own content (single source of truth).
This repo also ships a richer hand-written skill at `.agents/skills/airbend/`
(SKILL.md + REFERENCE.md) — installable, pre-committed, and kept in sync with
the CLI by hand. OpenCode plugin support is not yet implemented.

## Daemon (optional)

```
airbend serve                    # cron-scheduled graphs fire on their schedule
airbend serve --webhook :8080    # also accept POST /v1/events {"graph": <id>, "goal": ...}
airbend serve --once             # one scheduling pass, then exit
```

Cron graphs use `schedule: cron "0 9 * * *"` (5 fields, `*`/lists/ranges/steps).
Event/manual graphs run on demand via `run start` or the webhook.

## Notes

- Output is TOON on stdout; every command accepts `--json`.
- Exit codes: `0` success/no-op, `1` error, `2` usage error. Unknown flags
  are rejected with the valid flag list inline (self-correcting).
- Everything is completable with flags — no interactive prompts.
- Runs execute in a detached `airbend run drive` subprocess; the SQLite store
  at `$AIRBEND_HOME/airbend.db` (default `~/.airbend/`) is the checkpoint.
- The agent executor delegates to an installed agent CLI — Claude Code
  (`claude`) or Codex (`codex`) on PATH (`AIRBEND_AGENT` chooses, default
  auto). It runs headless (`claude -p` / `codex exec`) and expects a JSON
  envelope reply: `{"result": ..., "writes": {...}, "request_input": ...}`.
