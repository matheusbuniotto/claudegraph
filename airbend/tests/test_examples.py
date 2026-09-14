"""Shipped example graphs stay valid, and the command-only one runs to success."""

from __future__ import annotations

from pathlib import Path

import pytest

from airbend import scheduler, store
from airbend.graph import Graph, load_config

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_validates(path: Path) -> None:
    Graph.from_config(load_config(path))


def test_hello_example_runs() -> None:
    graph = Graph.from_config(load_config(Path(__file__).parent.parent / "examples/hello.yaml"))
    conn = store.ensure_db()
    store.register_graph(conn, graph)
    run = store.create_run(conn, graph)
    assert scheduler.drive_run(conn, run["id"]) == "success"
    states = store.get_node_states(conn, run["id"])
    assert states["report"]["state"] == "success"
    assert states["triage"]["state"] == "skipped"
