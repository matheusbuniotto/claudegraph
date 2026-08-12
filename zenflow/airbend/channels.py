"""Channel semantics — the data-passing store (Airflow XComs + LangGraph
channels). Ops: `overwrite` (LastValue), `append` (Topic). Values are JSON.
`reduce` (BinaryOperatorAggregate) is reserved for a future phase.
"""

from __future__ import annotations

from typing import Any

from airbend import store


def declared_op(graph_channels: dict[str, dict[str, Any]], key: str) -> str:
    spec = graph_channels.get(key) or {}
    return spec.get("op", "overwrite")


def write(
    conn,
    run_id: str,
    key: str,
    value: Any,
    op: str = "overwrite",
) -> None:
    if op == "append":
        existing = store.get_channel_value(conn, run_id, key)
        base: list[Any] = existing if isinstance(existing, list) else (
            [] if existing is None else [existing]
        )
        value = base + [value]
    store.set_channel(conn, run_id, key, value)


def read(conn, run_id: str) -> dict[str, Any]:
    return store.read_channels(conn, run_id)
