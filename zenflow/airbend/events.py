"""Event log — append-only, DB-backed. The agent-facing telemetry stream
(`airbend run events`). Every state transition emits one event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(
    conn,
    run_id: str,
    type_: str,
    node_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events (run_id, ts, type, node_id, payload_json) VALUES (?,?,?,?,?)",
        (run_id, _now(), type_, node_id, json.dumps(payload) if payload else None),
    )
    conn.commit()


def list_events(conn, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT seq, ts, type, node_id, payload_json FROM events"
        " WHERE run_id = ? AND seq > ? ORDER BY seq",
        (run_id, after_seq),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "seq": r["seq"],
                "ts": r["ts"],
                "type": r["type"],
                "node_id": r["node_id"],
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else None,
            }
        )
    return out
