"""Scheduler state machine: success path, retries, failure routing,
interrupts, and resume-with-input. Runs in-process against an isolated store.
"""

from __future__ import annotations

from airbend import events, scheduler, store
from airbend.graph import from_config


def _conn() -> store.sqlite3.Connection:
    return store.ensure_db()


def test_success_path_and_channels() -> None:
    conn = _conn()
    cfg = {
        "id": "suc",
        "version": 1,
        "nodes": [
            {"id": "a", "executor": {"type": "command", "cmd": "printf '{\"x\": 1}'"}},
            {"id": "b", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["a"]},
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    status = scheduler.drive_run(conn, run["id"])
    assert status == "success"
    states = store.get_node_states(conn, run["id"])
    assert states["a"]["state"] == "success"
    assert states["b"]["state"] == "success"
    channels = store.read_channels(conn, run["id"])
    assert channels["a"] == {"x": 1}
    assert channels["x"] == 1
    ev_types = [e["type"] for e in events.list_events(conn, run["id"])]
    assert "run.success" in ev_types
    assert "node.success" in ev_types


def test_retry_then_success(tmp_path) -> None:
    conn = _conn()
    cnt = tmp_path / "cnt"
    cfg = {
        "id": "ret",
        "version": 1,
        "nodes": [
            {
                "id": "a",
                "executor": {
                    "type": "command",
                    "cmd": (
                        f"cnt={cnt}; n=$(( $(cat $cnt 2>/dev/null || echo 0) + 1 ));"
                        " echo $n > $cnt; test $n -ge 2"
                    ),
                },
                "retries": 2,
            }
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    status = scheduler.drive_run(conn, run["id"])
    assert status == "success"
    states = store.get_node_states(conn, run["id"])
    assert states["a"]["state"] == "success"
    assert states["a"]["attempt"] == 2
    ev_types = [e["type"] for e in events.list_events(conn, run["id"])]
    assert ev_types.count("node.retry") == 1


def test_exhausted_retries_fails_run() -> None:
    conn = _conn()
    cfg = {
        "id": "fail",
        "version": 1,
        "nodes": [
            {"id": "a", "executor": {"type": "command", "cmd": "false"}, "retries": 1}
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    status = scheduler.drive_run(conn, run["id"])
    assert status == "failed"
    states = store.get_node_states(conn, run["id"])
    assert states["a"]["state"] == "failed"
    assert states["a"]["attempt"] == 2


def test_failure_routing_keeps_run_alive() -> None:
    conn = _conn()
    cfg = {
        "id": "route",
        "version": 1,
        "nodes": [
            {
                "id": "a",
                "executor": {"type": "command", "cmd": "false"},
                "on": {"failure": "triage"},
            },
            {"id": "triage", "executor": {"type": "command", "cmd": "true"}},
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    status = scheduler.drive_run(conn, run["id"])
    assert status == "success"  # leaf (triage) succeeded
    states = store.get_node_states(conn, run["id"])
    assert states["a"]["state"] == "failed"
    assert states["triage"]["state"] == "success"


def test_interrupt_route_pauses_run() -> None:
    conn = _conn()
    cfg = {
        "id": "intr",
        "version": 1,
        "nodes": [
            {
                "id": "a",
                "executor": {"type": "command", "cmd": "false"},
                "on": {"failure": "interrupt"},
            }
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    status = scheduler.drive_run(conn, run["id"])
    assert status == "interrupted"
    states = store.get_node_states(conn, run["id"])
    assert states["a"]["state"] == "deferred"


def test_resume_with_injected_input() -> None:
    conn = _conn()
    check = (
        "python3 -c 'import json,os;"
        "c=json.load(open(os.environ[\"AIRBEND_CTX_FILE\"]));"
        'print("yes" if c["channels"].get("__input") is not None else "no")' + "'"
    )
    cfg = {
        "id": "resume",
        "version": 1,
        "nodes": [
            {
                "id": "a",
                "executor": {"type": "command", "cmd": f'[ "$({check})" = yes ]'},
                "on": {"failure": "interrupt"},
            }
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    assert scheduler.drive_run(conn, run["id"]) == "interrupted"

    store.set_channel(conn, run["id"], "__input", {"approve": True})
    store.set_node_state(conn, run["id"], "a", "scheduled", attempt=2)
    store.set_run_status(conn, run["id"], "running")
    status = scheduler.drive_run(conn, run["id"])
    assert status == "success"
    assert store.get_node_states(conn, run["id"])["a"]["state"] == "success"


def test_downstream_not_run_after_unhandled_failure() -> None:
    conn = _conn()
    cfg = {
        "id": "depfail",
        "version": 1,
        "nodes": [
            {"id": "a", "executor": {"type": "command", "cmd": "false"}},
            {"id": "b", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["a"]},
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    assert scheduler.drive_run(conn, run["id"]) == "failed"
    states = store.get_node_states(conn, run["id"])
    assert states["b"]["state"] == "pending"


def test_alternative_path_skipped() -> None:
    conn = _conn()
    cfg = {
        "id": "alt",
        "version": 1,
        "nodes": [
            {
                "id": "verify",
                "executor": {"type": "command", "cmd": "true"},
                "on": {"success": "deploy", "failure": "triage"},
            },
            {"id": "triage", "executor": {"type": "command", "cmd": "true"}},
            {"id": "deploy", "executor": {"type": "command", "cmd": "true"}},
        ],
    }
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    assert scheduler.drive_run(conn, run["id"]) == "success"
    states = store.get_node_states(conn, run["id"])
    assert states["verify"]["state"] == "success"
    assert states["deploy"]["state"] == "success"
    assert states["triage"]["state"] == "skipped"
