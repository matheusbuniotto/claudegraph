"""airbend command graph. Imported lazily after the --version fast path.

AXI-conformant argparse wrapper: parse failures surface as structured errors
on stdout with exit code 2 (fail loud, self-correcting), `--help` always
passes, and no interactive prompts are ever raised. Operational errors
(AirbendError) surface as `error:`/`help:` on stdout with exit code 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, NoReturn

import airbend.errors as err
from airbend import events, scheduler, store
from airbend.errors import AirbendError
from airbend.graph import Graph, load_config
from airbend.runner import spawn_drive as _spawn_drive
from airbend.toon import dumps as toon_dumps

__all__ = ["main"]

_INVALID_CHOICE_RE = re.compile(
    r"invalid choice: '(?P<choice>[^']+)' \(choose from (?P<choices>.+)\)$"
)
_REQUIRED_RE = re.compile(r"^the following arguments are required: (?P<req>.+)$")


class _ArgError(Exception):
    def __init__(self, message: str, parser: "AxiParser") -> None:
        super().__init__(message)
        self.message = message
        self.parser = parser


class AxiSubparsers(argparse._SubParsersAction):
    """Subparsers action that remembers the deepest subparser it dispatched to,
    so the root parser's bubbled unknown-arg errors can target the right
    subcommand (per-subcommand flag sets, AXI §6)."""

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace,
                 values: Any, option_string: str | None = None) -> list[str]:
        if values:
            sub = self._name_parser_map.get(values[0])
            if sub is not None:
                self.last_parser = sub  # type: ignore[assignment]
        return super().__call__(parser, namespace, values, option_string)


class AxiParser(argparse.ArgumentParser):
    """argparse with AXI error semantics: parse failures become structured
    errors (exit 2) instead of argparse's stderr usage dump."""

    def __init__(self, *args: Any, renamed: dict[str, str] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.renamed = renamed or {}
        self._sub_action: AxiSubparsers | None = None

    def add_subparsers(self, *args: Any, **kwargs: Any) -> AxiSubparsers:
        kwargs.setdefault("action", AxiSubparsers)
        action = super().add_subparsers(*args, **kwargs)
        self._sub_action = action  # type: ignore[assignment]
        return action

    def _deepest(self) -> "AxiParser":
        ctx: AxiParser = self
        while ctx._sub_action is not None:
            nxt = getattr(ctx._sub_action, "last_parser", None)
            if nxt is None:
                break
            ctx = nxt
        return ctx

    def error(self, message: str) -> NoReturn:
        raise _ArgError(message, self._deepest())


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _emit(doc: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        print(json.dumps(doc))
    else:
        print(toon_dumps(doc), end="")


def _count_text(n: int, word: str) -> str:
    plural = "" if n == 1 else "s"
    return f"{n} {word}{plural} found"


def _self_path() -> str:
    exe = shutil.which("airbend")
    if not exe:
        return "airbend"
    try:
        exe = str(Path(exe).resolve())
    except OSError:
        pass
    home = str(Path.home())
    if exe.startswith(home + os.sep):
        exe = "~" + exe[len(home) :]
    return exe


def _flag_list(p: AxiParser) -> str:
    flags: list[str] = []
    for action in p._actions:
        if action.option_strings:
            flags.extend(action.option_strings)
    return ", ".join(flags)


def _usage_error(e: _ArgError) -> int:
    msg = e.message
    p = e.parser
    prog = p.prog
    doc: dict[str, str] = {}
    if msg.startswith("unrecognized arguments:"):
        rest = msg.split(":", 1)[1].strip()
        bad = rest.split()[0] if rest else "?"
        if bad in p.renamed:
            doc["error"] = f"{bad} was renamed; use {p.renamed[bad]} instead"
        else:
            doc["error"] = f"unknown flag {bad} for `{prog}`"
            doc["help"] = f"valid flags for `{prog}`: {_flag_list(p)} (--help always allowed)"
    elif (m := _REQUIRED_RE.match(msg)) is not None:
        doc["error"] = f"missing required argument `{m.group('req')}`"
        doc["help"] = p.format_usage().strip()
    elif (m := _INVALID_CHOICE_RE.search(msg)) is not None:
        choices = [
            c.strip().strip("'\"")
            for c in m.group("choices").split(",")
            if c.strip()
        ]
        doc["error"] = f"unknown command `{m.group('choice')}`"
        doc["help"] = f"valid commands: {', '.join(choices)}"
    else:
        doc["error"] = msg
        doc["help"] = f"see `{prog} --help`"
    print(toon_dumps(doc), end="")
    return err.EXIT_USAGE


def _load_graph_or_error(path: str) -> Graph:
    return Graph.from_config(load_config(path))


def _run_doc(run: dict[str, Any], graph_id: str) -> dict[str, Any]:
    return {
        "run": {
            "id": run["id"],
            "graph": graph_id,
            "status": run["status"],
        }
    }


# ---------------------------------------------------------------------------
# Commands — home
# ---------------------------------------------------------------------------

def cmd_home(args: argparse.Namespace) -> int:
    c = store.counts()
    recent = store.recent_runs()
    doc: dict[str, Any] = {
        "bin": _self_path(),
        "description": "Agent runtime — register graphs, run goals, control state",
        "graphs": _count_text(c["graphs"], "graph"),
    }
    if recent:
        doc["runs"] = recent
        doc["count"] = f"{c['runs']} runs total"
    else:
        doc["runs"] = _count_text(c["runs"], "run")
    doc["help"] = [
        "Run `airbend dag register <config.yaml>` to add a graph",
        "Run `airbend run start <dag> --goal \"<goal>\"` to run one",
        "Run `airbend run list` to see runs",
        "Run `airbend --help` for the full reference",
    ]
    _emit(doc, args)
    return err.EXIT_OK


# ---------------------------------------------------------------------------
# Commands — dag
# ---------------------------------------------------------------------------

def cmd_dag_register(args: argparse.Namespace) -> int:
    graph = _load_graph_or_error(args.file)
    conn = store.ensure_db()
    outcome = store.register_graph(conn, graph)
    doc = {
        "graph": {
            "id": graph.id,
            "version": graph.version,
            "nodes": len(graph.nodes),
            "schedule": graph.schedule,
            "status": "registered" if outcome == "registered" else "already registered (no-op)",
        }
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_dag_validate(args: argparse.Namespace) -> int:
    graph = _load_graph_or_error(args.file)
    doc = {
        "graph": {
            "id": graph.id,
            "version": graph.version,
            "nodes": len(graph.nodes),
            "status": "valid",
        }
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_dag_list(args: argparse.Namespace) -> int:
    graphs = store.list_graphs_brief()
    if not graphs:
        doc: dict[str, Any] = {
            "graphs": "0 graphs found",
            "help": ["Run `airbend dag register <config.yaml>` to add a graph"],
        }
    else:
        doc = {"graphs": graphs, "count": f"{len(graphs)} graphs total"}
    _emit(doc, args)
    return err.EXIT_OK


def cmd_dag_show(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    row = store.get_graph(conn, args.id)
    if row is None:
        raise AirbendError(
            f"graph not found: `{args.id}`",
            "Run `airbend dag list` to see registered graphs",
        )
    graph = Graph.from_config(json.loads(row["config_json"]))
    doc = {
        "graph": {
            "id": graph.id,
            "version": graph.version,
            "schedule": graph.schedule,
            "max_parallel": graph.max_parallel,
            "channels": f"{len(graph.channels)} declared",
        },
        "nodes": [
            {
                "id": n.id,
                "executor": n.executor["type"],
                "depends_on": " ".join(n.depends_on) or "-",
                "retries": n.retries,
                "on": " ".join(f"{k}:{v}" for k, v in n.on.items()) or "-",
            }
            for n in graph.nodes
        ],
        "count": f"{len(graph.nodes)} nodes",
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_dag_plan(args: argparse.Namespace) -> int:
    graph = _load_graph_or_error(args.file)
    conn = store.ensure_db()
    row = store.get_graph(conn, graph.id)
    cfg_json = json.dumps(graph.to_config(), sort_keys=True)
    if row is None:
        plan = (
            f"would register `{graph.id}` v{graph.version}"
            f" ({len(graph.nodes)} nodes, {graph.schedule})"
        )
    elif row["config_json"] == cfg_json:
        plan = f"no change for `{graph.id}` (v{graph.version} already registered)"
    else:
        old = Graph.from_config(json.loads(row["config_json"]))
        plan = (
            f"would update `{graph.id}`: version {old.version} -> {graph.version},"
            f" nodes {len(old.nodes)} -> {len(graph.nodes)},"
            f" schedule {old.schedule} -> {graph.schedule}"
        )
    _emit({"plan": plan}, args)
    return err.EXIT_OK


def cmd_dag_help(args: argparse.Namespace) -> int:
    doc = {
        "error": "missing required argument `<subcommand>`",
        "help": "valid commands: list, register, validate, show, plan",
    }
    print(toon_dumps(doc), end="")
    return err.EXIT_USAGE


# ---------------------------------------------------------------------------
# Commands — run
# ---------------------------------------------------------------------------

def cmd_run_start(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    row = store.get_graph(conn, args.dag)
    if row is None:
        raise AirbendError(
            f"graph not found: `{args.dag}`",
            "Run `airbend dag list` to see registered graphs",
        )
    graph = Graph.from_config(json.loads(row["config_json"]))
    params: dict[str, Any] = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            raise AirbendError("--params must be a JSON object", str(e)) from e
        if not isinstance(params, dict):
            raise AirbendError("--params must be a JSON object")
    run = store.create_run(conn, graph, goal=args.goal, params=params)
    if args.watch:
        status = scheduler.drive_run(conn, run["id"], stream=True)
        doc = _run_doc(store.get_run(conn, run["id"]) or run, graph.id)
        doc["run"]["status"] = status
        _emit(doc, args)
        return err.EXIT_OK
    _spawn_drive(run["id"])
    doc = _run_doc(run, graph.id)
    doc["help"] = [
        "Run `airbend run status <id>` to inspect progress",
        "Run `airbend run events <id> --follow` to watch live events",
    ]
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_drive(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    status = scheduler.drive_run(conn, args.run_id, stream=False)
    print(json.dumps({"run_id": args.run_id, "status": status}))
    return err.EXIT_OK


def cmd_run_list(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    rows = store.list_runs(conn, status=args.status)
    if not rows:
        doc: dict[str, Any] = {
            "runs": (
                "0 runs found"
                if not args.status
                else f"0 runs with status `{args.status}` found"
            ),
            "help": ["Run `airbend run start <dag>` to run a graph"],
        }
    else:
        doc = {
            "runs": [
                {"id": r["id"], "graph": r["graph_id"] or "-", "status": r["status"]}
                for r in rows
            ],
            "count": f"{len(rows)} runs total",
        }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_status(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    run = store.get_run(conn, args.run_id)
    if run is None:
        raise AirbendError(
            f"run not found: `{args.run_id}`",
            "Run `airbend run list` to see runs",
        )
    states = store.get_node_states(conn, args.run_id)
    doc: dict[str, Any] = {
        "run": {
            "id": run["id"],
            "graph": run["graph_id"] or "-",
            "status": run["status"],
            "goal": run["goal"],
        },
        "nodes": {
            nid: {
                "state": s["state"],
                "attempt": s["attempt"],
                "error": s["error"],
            }
            for nid, s in states.items()
        },
        "count": f"{len(states)} nodes",
    }
    if run["status"] == "interrupted":
        doc["help"] = ["Run `airbend run resume <id> --input json` to continue"]
    elif run["status"] == "running":
        doc["help"] = ["Run `airbend run events <id> --follow` to watch live events"]
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_events(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    run = store.get_run(conn, args.run_id)
    if run is None:
        raise AirbendError(
            f"run not found: `{args.run_id}`",
            "Run `airbend run list` to see runs",
        )
    seq = 0
    printed = False

    def drain() -> bool:
        nonlocal seq, printed
        for e in events.list_events(conn, args.run_id, after_seq=seq):
            print(json.dumps(e), flush=True)
            printed = True
            seq = e["seq"]
        return printed

    drain()
    if not args.follow:
        if not printed:
            print("events: 0 events found", end="")
        return err.EXIT_OK

    terminal = ("success", "failed", "interrupted")
    grace = 0
    while True:
        if drain():
            grace = 0
        run_now = store.get_run(conn, args.run_id)
        if run_now is not None and run_now["status"] in terminal:
            grace += 1
            if grace >= 3:
                if not printed:
                    print("events: 0 events found", end="")
                return err.EXIT_OK
        time.sleep(0.5)


def cmd_run_interrupt(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    run = store.get_run(conn, args.run_id)
    if run is None:
        raise AirbendError(
            f"run not found: `{args.run_id}`",
            "Run `airbend run list` to see runs",
        )
    if run["status"] == "interrupted":
        doc = {"run": {"id": run["id"], "status": "already interrupted (no-op)"}}
        _emit(doc, args)
        return err.EXIT_OK
    if run["status"] in ("success", "failed"):
        raise AirbendError(
            f"cannot interrupt run `{args.run_id}`: already {run['status']}"
        )
    store.set_run_status(conn, run["id"], "interrupted")
    doc = {
        "run": {"id": run["id"], "status": "interrupted"},
        "help": ["Run `airbend run resume <id> --input json` to continue"],
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_resume(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    run = store.get_run(conn, args.run_id)
    if run is None:
        raise AirbendError(
            f"run not found: `{args.run_id}`",
            "Run `airbend run list` to see runs",
        )
    if run["status"] not in ("interrupted", "failed"):
        raise AirbendError(
            f"run `{args.run_id}` is {run['status']}; nothing to resume",
            "Use `airbend run interrupt <id>` first, or `run retry` on a failed node",
        )
    if args.input:
        try:
            input_val = json.loads(args.input)
        except json.JSONDecodeError as e:
            raise AirbendError("--input must be valid JSON", str(e)) from e
        store.set_channel(conn, run["id"], "__input", input_val)

    states = store.get_node_states(conn, run["id"])
    revived = 0
    for nid, s in states.items():
        if s["state"] == "deferred":
            store.set_node_state(
                conn, run["id"], nid, "scheduled", attempt=s["attempt"] + 1, error=None
            )
            revived += 1
    if revived == 0:
        raise AirbendError(
            f"no deferred nodes in run `{args.run_id}`",
            "Use `airbend run retry <id> --node <node>` to rerun a failed node",
        )
    store.set_run_status(conn, run["id"], "running")
    if args.watch:
        status = scheduler.drive_run(conn, run["id"], stream=True)
        doc = _run_doc(store.get_run(conn, run["id"]) or run, run["graph_id"] or "-")
        doc["run"]["status"] = status
    else:
        _spawn_drive(run["id"])
        doc = _run_doc(run, run["graph_id"] or "-")
    doc["resumed"] = f"{revived} nodes"
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_retry(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    run = store.get_run(conn, args.run_id)
    if run is None:
        raise AirbendError(
            f"run not found: `{args.run_id}`",
            "Run `airbend run list` to see runs",
        )
    states = store.get_node_states(conn, run["id"])
    s = states.get(args.node)
    if s is None:
        raise AirbendError(f"node `{args.node}` not found in run `{run['id']}`")
    if s["state"] not in ("failed", "deferred"):
        raise AirbendError(
            f"node `{args.node}` is {s['state']}; only failed/deferred nodes can be retried"
        )
    next_attempt = s["attempt"] + 1
    store.set_node_state(
        conn, run["id"], args.node, "scheduled", attempt=next_attempt, error=""
    )
    was_terminal = run["status"] in ("success", "failed", "interrupted")
    store.set_run_status(conn, run["id"], "running")
    if was_terminal:
        if args.watch:
            scheduler.drive_run(conn, run["id"], stream=True)
        else:
            _spawn_drive(run["id"])
    elif args.watch:
        raise AirbendError(
            f"run `{run['id']}` is already running; retry is queued",
            "Use `airbend run events <id> --follow` to watch it proceed",
        )
    doc = {
        "run": {"id": run["id"], "status": "running"},
        "node": {"id": args.node, "state": "scheduled", "attempt": next_attempt},
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_run_help(args: argparse.Namespace) -> int:
    doc = {
        "error": "missing required argument `<subcommand>`",
        "help": "valid commands: start, list, status, events, interrupt, resume, retry",
    }
    print(toon_dumps(doc), end="")
    return err.EXIT_USAGE


# ---------------------------------------------------------------------------
# Commands — goal
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (truncated, {len(text)} chars total)"


def cmd_goal_create(args: argparse.Namespace) -> int:
    text = args.text.strip()
    if not text:
        raise AirbendError("goal text is empty")
    conn = store.ensure_db()
    run = None
    if args.run:
        if not args.graph:
            raise AirbendError(
                "--run requires --graph <id>",
                "Run `airbend dag list` to see registered graphs",
            )
        row = store.get_graph(conn, args.graph)
        if row is None:
            raise AirbendError(
                f"graph not found: `{args.graph}`",
                "Run `airbend dag list` to see registered graphs",
            )
        graph = Graph.from_config(json.loads(row["config_json"]))
        run = store.create_run(conn, graph, goal=text)
        _spawn_drive(run["id"])
    goal = store.create_goal(conn, text, run_id=run["id"] if run else None, source="cli")
    doc: dict[str, Any] = {
        "goal": {
            "id": goal["id"],
            "text": text,
            "status": goal["status"],
            "run_id": goal["run_id"],
        }
    }
    if run:
        doc["run"] = {"id": run["id"], "status": "running"}
    _emit(doc, args)
    return err.EXIT_OK


def cmd_goal_list(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    rows = store.list_goals(conn)
    if not rows:
        doc: dict[str, Any] = {
            "goals": "0 goals found",
            "help": [
                'Run `airbend goal create "<text>" --run --graph <id>` to add one'
            ],
        }
    else:
        doc = {
            "goals": [
                {
                    "id": g["id"],
                    "text": _truncate(g["text"], 80),
                    "status": g["status"],
                    "run": g["run_id"] or "-",
                }
                for g in rows
            ],
            "count": f"{len(rows)} goals total",
        }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_goal_view(args: argparse.Namespace) -> int:
    conn = store.ensure_db()
    goal = store.get_goal(conn, args.id)
    if goal is None:
        raise AirbendError(
            f"goal not found: `{args.id}`",
            "Run `airbend goal list` to see goals",
        )
    doc = {
        "goal": {
            "id": goal["id"],
            "text": goal["text"],
            "status": goal["status"],
            "run_id": goal["run_id"],
            "source": goal["source"],
            "created_at": goal["created_at"],
        }
    }
    _emit(doc, args)
    return err.EXIT_OK


def cmd_goal_help(args: argparse.Namespace) -> int:
    doc = {
        "error": "missing required argument `<subcommand>`",
        "help": "valid commands: create, list, view",
    }
    print(toon_dumps(doc), end="")
    return err.EXIT_USAGE


# ---------------------------------------------------------------------------
# Commands — integrations
# ---------------------------------------------------------------------------

def cmd_setup(args: argparse.Namespace) -> int:
    from airbend import integrations

    if args.uninstall:
        doc: dict[str, Any] = {}
        for agent in _selected_agents(args):
            if agent == "claude-code":
                _, msg = integrations.remove_hook(
                    Path.cwd() / ".claude" / "settings.json", integrations.CC_EVENT
                )
            elif agent == "codex":
                _, msg = integrations.remove_hook(
                    Path.cwd() / ".codex" / "hooks.json", integrations.CODEX_EVENT
                )
            else:
                raise AirbendError(
                    f"unknown agent: {agent}", "supported agents: claude-code, codex"
                )
            doc[agent] = msg
        doc["help"] = ["Run `airbend setup` to reinstall"]
        _emit(doc, args)
        return err.EXIT_OK

    command = f"{integrations.hook_command()} home"
    doc = {}
    for agent in _selected_agents(args):
        if agent == "claude-code":
            path = Path.cwd() / ".claude" / "settings.json"
            _, msg = integrations.ensure_hook(path, integrations.CC_EVENT, command)
            doc[agent] = f"{msg} ({path})"
        elif agent == "codex":
            path = Path.cwd() / ".codex" / "hooks.json"
            _, msg = integrations.ensure_hook(path, integrations.CODEX_EVENT, command)
            _, feat = integrations.ensure_codex_features(Path.home())
            doc[agent] = f"{msg} ({path}); {feat}"
        else:
            raise AirbendError(
                f"unknown agent: {agent}", "supported agents: claude-code, codex"
            )
    doc["help"] = [
        "Session hooks inject the airbend home view into every agent session",
        "Run `airbend skill skills/airbend/SKILL.md` to also install the discoverable skill",
    ]
    _emit(doc, args)
    return err.EXIT_OK


def _selected_agents(args: argparse.Namespace) -> list[str]:
    raw = (getattr(args, "agents", None) or "claude-code,codex").split(",")
    return [a.strip() for a in raw if a.strip()]


def cmd_skill(args: argparse.Namespace) -> int:
    from airbend import integrations

    if args.check:
        if not args.path:
            raise AirbendError("--check requires a path")
        path = Path(args.path)
        if integrations.skill_is_current(path):
            _emit({"skill": {"path": str(path), "status": "current"}}, args)
            return err.EXIT_OK
        raise AirbendError(
            f"skill is stale: {path}",
            f"Run `airbend skill {path}` to regenerate it",
        )
    if args.path:
        path = Path(args.path)
        integrations.write_skill(path)
        _emit({"skill": {"path": str(path), "status": "written"}}, args)
        return err.EXIT_OK
    print(integrations.skill_content(), end="")
    return err.EXIT_OK


# ---------------------------------------------------------------------------
# Commands — serve (daemon)
# ---------------------------------------------------------------------------

def _parse_port(spec: str) -> int:
    text = spec.strip()
    if text.startswith(":"):
        text = text[1:]
    try:
        port = int(text)
    except ValueError as e:
        raise AirbendError(f"invalid port: {spec}") from e
    if not 0 <= port <= 65535:
        raise AirbendError(f"port out of range: {port}")
    return port


def cmd_serve(args: argparse.Namespace) -> int:
    from airbend import server

    conn = store.ensure_db()
    if args.once:
        created = server.schedule_tick(conn)
        doc = {
            "serve": {
                "mode": "once",
                "runs_created": len(created),
                "run_ids": created,
            }
        }
        _emit(doc, args)
        return err.EXIT_OK

    if args.webhook:
        import threading

        httpd, bound = server.start_webhook(_parse_port(args.webhook))
        print(
            f"serve: webhook listening on 127.0.0.1:{bound} (POST /v1/events)",
            file=sys.stderr,
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print(f"serve: scheduling every {args.tick}s (Ctrl-C to stop)", file=sys.stderr)
    try:
        while True:
            created = server.schedule_tick(conn)
            for rid in created:
                print(json.dumps({"type": "run.scheduled", "run_id": rid}), flush=True)
            time.sleep(args.tick)
    except KeyboardInterrupt:
        print("serve: stopped", file=sys.stderr)
        return err.EXIT_OK


# ---------------------------------------------------------------------------
# Parser graph
# ---------------------------------------------------------------------------

def _add_json_flag(p: AxiParser) -> None:
    p.add_argument("--json", action="store_true", help="emit JSON instead of TOON")


def build_parser() -> AxiParser:
    parser = AxiParser(
        prog="airbend",
        description="Agent runtime — register graphs, run goals, control state",
    )
    _add_json_flag(parser)
    sub = parser.add_subparsers(dest="command", metavar="<command>", title="commands")

    # --- dag ---
    dag = sub.add_parser("dag", help="manage graphs (DAGs)", description="Manage registered graphs.")
    dag.set_defaults(func=cmd_dag_help)
    dag_sub = dag.add_subparsers(dest="dag_command", metavar="<subcommand>", title="dag subcommands")
    for name, help_text in (
        ("register", "register a graph from a config file"),
        ("validate", "validate a config file without registering"),
        ("list", "list registered graphs"),
        ("show", "show a registered graph's structure"),
        ("plan", "diff a config file against what is registered"),
    ):
        p = dag_sub.add_parser(name, help=help_text)
        _add_json_flag(p)
        if name in ("register", "validate", "plan"):
            p.add_argument("file", help="path to a YAML config")
        if name == "show":
            p.add_argument("id", help="registered graph id")
        p.set_defaults(func={
            "register": cmd_dag_register,
            "validate": cmd_dag_validate,
            "list": cmd_dag_list,
            "show": cmd_dag_show,
            "plan": cmd_dag_plan,
        }[name])

    # --- run ---
    run = sub.add_parser("run", help="execute and control runs")
    run.set_defaults(func=cmd_run_help)
    run_sub = run.add_subparsers(dest="run_command", metavar="<subcommand>", title="run subcommands")

    def add_run_cmd(name: str, help_text: str, *, hidden: bool = False) -> AxiParser:
        p = run_sub.add_parser(name, help=argparse.SUPPRESS if hidden else help_text)
        _add_json_flag(p)
        return p

    p = add_run_cmd("start", "start a run of a registered graph")
    p.add_argument("dag", help="registered graph id")
    p.add_argument("--goal", help="goal text (injected into agent-node tasks)")
    p.add_argument("--params", help="JSON object of run parameters")
    p.add_argument("--watch", action="store_true", help="run in the foreground, streaming events")
    p.set_defaults(func=cmd_run_start)

    p = add_run_cmd("list", "list runs")
    p.add_argument("--status", help="filter by run status")
    p.set_defaults(func=cmd_run_list)

    p = add_run_cmd("status", "show a run's state and per-node states")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_status)

    p = add_run_cmd("events", "stream a run's events as JSONL")
    p.add_argument("run_id")
    p.add_argument("--follow", action="store_true", help="keep polling until the run finishes")
    p.set_defaults(func=cmd_run_events)

    p = add_run_cmd("interrupt", "pause a running run at the next safe point")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_interrupt)

    p = add_run_cmd("resume", "resume a paused run, optionally injecting input")
    p.add_argument("run_id")
    p.add_argument("--input", help="JSON value injected into the run (channel `__input`)")
    p.add_argument("--watch", action="store_true")
    p.set_defaults(func=cmd_run_resume)

    p = add_run_cmd("retry", "re-run a failed node")
    p.add_argument("run_id")
    p.add_argument("--node", required=True, help="node id to re-run")
    p.add_argument("--watch", action="store_true")
    p.set_defaults(func=cmd_run_retry)

    p = add_run_cmd("drive", "internal: drive a run to completion", hidden=True)
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_drive)

    # --- goal ---
    goal = sub.add_parser("goal", help="manage goals")
    goal.set_defaults(func=cmd_goal_help)
    goal_sub = goal.add_subparsers(dest="goal_command", metavar="<subcommand>", title="goal subcommands")

    p = goal_sub.add_parser("create", help="create a goal (optionally start a run)")
    p.add_argument("text", help="goal text")
    p.add_argument("--graph", help="graph to run the goal against (with --run)")
    p.add_argument("--run", action="store_true", help="start a run for this goal")
    _add_json_flag(p)
    p.set_defaults(func=cmd_goal_create)

    p = goal_sub.add_parser("list", help="list goals")
    _add_json_flag(p)
    p.set_defaults(func=cmd_goal_list)

    p = goal_sub.add_parser("view", help="show a goal")
    p.add_argument("id")
    _add_json_flag(p)
    p.set_defaults(func=cmd_goal_view)

    # --- top-level: integrations ---
    home = sub.add_parser("home", help=argparse.SUPPRESS)
    _add_json_flag(home)
    home.set_defaults(func=cmd_home)

    setup = sub.add_parser("setup", help="install session hooks (Claude Code + Codex)")
    setup.add_argument("--agents", help="comma-separated: claude-code,codex (default all)")
    setup.add_argument("--uninstall", action="store_true", help="remove hooks")
    _add_json_flag(setup)
    setup.set_defaults(func=cmd_setup)

    skill = sub.add_parser("skill", help="generate or check the installable SKILL.md")
    skill.add_argument("path", nargs="?", help="write the skill to this path (default: stdout)")
    skill.add_argument("--check", action="store_true", help="fail if the file is stale")
    _add_json_flag(skill)
    skill.set_defaults(func=cmd_skill)

    serve = sub.add_parser("serve", help="run the daemon (cron scheduling + webhook intake)")
    serve.add_argument("--webhook", help="listen for events on a port, e.g. :8080")
    serve.add_argument("--tick", type=int, default=15, help="scheduling tick in seconds")
    serve.add_argument("--once", action="store_true", help="run one scheduling pass and exit")
    _add_json_flag(serve)
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _ArgError as e:
        return _usage_error(e)
    except SystemExit as e:
        # `--help` prints to stdout and exits 0 via argparse.
        code = e.code
        return code if isinstance(code, int) else err.EXIT_OK
    func = getattr(args, "func", None)
    if func is None:
        return cmd_home(args)
    try:
        return func(args)
    except AirbendError as e:
        print(e.toon(), end="")
        return err.EXIT_ERROR
