"""Channel semantics: overwrite (LastValue) and append (Topic). Channels have
a foreign key to runs, so tests run against a real registered run."""

from __future__ import annotations

from airbend import channels, store
from airbend.graph import from_config

GRAPH = {
    "id": "ch",
    "version": 1,
    "nodes": [{"id": "a", "executor": {"type": "command", "cmd": "true"}}],
}


def _run() -> tuple[object, str]:
    conn = store.ensure_db()
    graph = from_config(GRAPH)
    store.register_graph(conn, graph)
    return conn, store.create_run(conn, graph)["id"]


def test_overwrite() -> None:
    conn, rid = _run()
    channels.write(conn, rid, "x", {"v": 1}, "overwrite")
    channels.write(conn, rid, "x", {"v": 2}, "overwrite")
    assert store.read_channels(conn, rid) == {"x": {"v": 2}}


def test_append() -> None:
    conn, rid = _run()
    channels.write(conn, rid, "log", "first", "append")
    channels.write(conn, rid, "log", "second", "append")
    assert store.read_channels(conn, rid) == {"log": ["first", "second"]}


def test_append_promotes_scalar() -> None:
    conn, rid = _run()
    channels.write(conn, rid, "log", "first", "overwrite")
    channels.write(conn, rid, "log", "second", "append")
    assert store.read_channels(conn, rid) == {"log": ["first", "second"]}


def test_declared_op_default() -> None:
    assert channels.declared_op({}, "x") == "overwrite"
    assert channels.declared_op({"x": {"op": "append"}}, "x") == "append"

