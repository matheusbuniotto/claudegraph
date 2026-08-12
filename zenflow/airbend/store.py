"""SQLite state store — the durability seam (Airflow's metadata DB meets
LangGraph's checkpoint).

Single file at $AIRBEND_HOME/airbend.db (default ~/.airbend/airbend.db), WAL
mode so concurrent CLI + run processes share it. All state lives here; the
scheduler heartbeats against these rows exactly like Airflow's
SchedulerJobRunner heartbeats against its DB.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from airbend.graph import Graph

SCHEMA = """
CREATE TABLE IF NOT EXISTS graphs (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  graph_id TEXT,
  goal TEXT,
  status TEXT NOT NULL,
  params_json TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  FOREIGN KEY (graph_id) REFERENCES graphs(id)
);

CREATE TABLE IF NOT EXISTS node_runs (
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  state TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  input_json TEXT,
  output_json TEXT,
  error TEXT,
  started_at TEXT,
  ended_at TEXT,
  PRIMARY KEY (run_id, node_id),
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS channels (
  run_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value_json TEXT,
  op TEXT NOT NULL DEFAULT 'overwrite',
  PRIMARY KEY (run_id, key),
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  node_id TEXT,
  payload_json TEXT,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  status TEXT NOT NULL,
  run_id TEXT,
  source TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_node_runs_run ON node_runs(run_id, node_id);
"""


def db_path() -> Path:
    home = os.environ.get("AIRBEND_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".airbend"
    return base / "airbend.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def ensure_db() -> sqlite3.Connection:
    conn = connect()
    init_db(conn)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return "r_" + secrets.token_hex(4)


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------

def get_graph(conn: sqlite3.Connection, graph_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM graphs WHERE id = ?", (graph_id,)).fetchone()
    return dict(row) if row else None


def register_graph(conn: sqlite3.Connection, graph: "Graph") -> str:
    """Idempotent, versioned registration. Returns 'registered' or 'no-op'.
    A different config at a version <= the stored one raises AirbendError."""
    from airbend.errors import AirbendError

    existing = get_graph(conn, graph.id)
    config_json = json.dumps(graph.to_config(), sort_keys=True)
    now = utcnow()
    if existing is None:
        conn.execute(
            "INSERT INTO graphs (id, version, config_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (graph.id, graph.version, config_json, now, now),
        )
        conn.commit()
        return "registered"
    if existing["config_json"] == config_json:
        if graph.version != existing["version"]:
            conn.execute(
                "UPDATE graphs SET version = ?, updated_at = ? WHERE id = ?",
                (max(graph.version, existing["version"]), now, graph.id),
            )
            conn.commit()
        return "no-op"
    if graph.version <= existing["version"]:
        raise AirbendError(
            f"graph `{graph.id}` already registered at version {existing['version']}"
            " with a different config",
            f"bump `version` to {existing['version'] + 1} and re-register",
        )
    conn.execute(
        "UPDATE graphs SET version = ?, config_json = ?, updated_at = ? WHERE id = ?",
        (graph.version, config_json, now, graph.id),
    )
    conn.commit()
    return "registered"


def list_graphs_brief(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    try:
        c = conn or connect()
        rows = c.execute(
            "SELECT id, version FROM graphs ORDER BY updated_at DESC, id ASC"
        ).fetchall()
        return [{"id": r["id"], "version": r["version"]} for r in rows]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# Runs + node_runs
# ---------------------------------------------------------------------------

def create_run(
    conn: sqlite3.Connection,
    graph: "Graph",
    goal: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = new_run_id()
    now = utcnow()
    conn.execute(
        "INSERT INTO runs (id, graph_id, goal, status, params_json, started_at)"
        " VALUES (?,?,?,?,?,?)",
        (run_id, graph.id, goal, "running", json.dumps(params or {}), now),
    )
    for n in graph.nodes:
        conn.execute(
            "INSERT INTO node_runs (run_id, node_id, state, attempt, started_at)"
            " VALUES (?,?,?,?,?)",
            (run_id, n.id, "pending", 1, now),
        )
    conn.commit()
    run = get_run(conn, run_id)
    assert run is not None
    return run


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT r.*, g.config_json AS config_json FROM runs r"
        " LEFT JOIN graphs g ON r.graph_id = g.id WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    return dict(row) if row else None


def list_runs(
    conn: sqlite3.Connection, status: str | None = None
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT id, graph_id, goal, status, started_at FROM runs"
            " WHERE status = ? ORDER BY started_at DESC LIMIT 100",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, graph_id, goal, status, started_at FROM runs"
            " ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


def set_run_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    ended = utcnow() if status in ("success", "failed", "interrupted") else None
    if ended:
        conn.execute(
            "UPDATE runs SET status = ?, ended_at = ? WHERE id = ?",
            (status, ended, run_id),
        )
    else:
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    conn.commit()


def get_node_states(conn: sqlite3.Connection, run_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT node_id, state, attempt, input_json, output_json, error,"
        " started_at, ended_at FROM node_runs WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r["node_id"]] = {
            "node_id": r["node_id"],
            "state": r["state"],
            "attempt": r["attempt"],
            "input": json.loads(r["input_json"]) if r["input_json"] else None,
            "output": json.loads(r["output_json"]) if r["output_json"] else None,
            "error": r["error"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
        }
    return out


def set_node_state(
    conn: sqlite3.Connection,
    run_id: str,
    node_id: str,
    state: str,
    *,
    attempt: int | None = None,
    error: str | None = None,
    output: Any = None,
    set_output: bool = False,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> None:
    sets = ["state = ?"]
    params: list[Any] = [state]
    if attempt is not None:
        sets.append("attempt = ?")
        params.append(attempt)
    if error is not None:
        sets.append("error = ?")
        params.append(error)
    if set_output:
        sets.append("output_json = ?")
        params.append(json.dumps(output))
    if started_at is not None:
        sets.append("started_at = ?")
        params.append(started_at)
    if ended_at is not None:
        sets.append("ended_at = ?")
        params.append(ended_at)
    params.extend([run_id, node_id])
    conn.execute(
        f"UPDATE node_runs SET {', '.join(sets)} WHERE run_id = ? AND node_id = ?",
        params,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def get_channel_value(conn: sqlite3.Connection, run_id: str, key: str) -> Any:
    row = conn.execute(
        "SELECT value_json FROM channels WHERE run_id = ? AND key = ?",
        (run_id, key),
    ).fetchone()
    if row is None or row["value_json"] is None:
        return None
    return json.loads(row["value_json"])


def set_channel(conn: sqlite3.Connection, run_id: str, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO channels (run_id, key, value_json, op) VALUES (?,?,?, 'overwrite')"
        " ON CONFLICT(run_id, key) DO UPDATE SET value_json = excluded.value_json",
        (run_id, key, json.dumps(value)),
    )
    conn.commit()


def read_channels(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT key, value_json FROM channels WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {r["key"]: json.loads(r["value_json"]) if r["value_json"] else None for r in rows}


# ---------------------------------------------------------------------------
# Home view
# ---------------------------------------------------------------------------

def new_goal_id() -> str:
    return "g_" + secrets.token_hex(4)


def create_goal(
    conn: sqlite3.Connection,
    text: str,
    run_id: str | None = None,
    source: str = "cli",
) -> dict[str, Any]:
    goal_id = new_goal_id()
    now = utcnow()
    conn.execute(
        "INSERT INTO goals (id, text, status, run_id, source, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (goal_id, text, "running" if run_id else "open", run_id, source, now),
    )
    conn.commit()
    goal = get_goal(conn, goal_id)
    assert goal is not None
    return goal


def get_goal(conn: sqlite3.Connection, goal_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return dict(row) if row else None


def list_goals(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, text, status, run_id, created_at FROM goals"
        " ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_runs(
    conn: sqlite3.Connection | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Most recent runs for the content-first home view."""
    try:
        c = conn or connect()
        rows = c.execute(
            "SELECT id, graph_id, status FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"id": r["id"], "graph": r["graph_id"] or "-", "status": r["status"]}
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def counts(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Counts for the home view. Missing tables → zeros (definitive empty
    state rather than a crash on a fresh store)."""
    try:
        c = conn or connect()
        row = c.execute(
            "SELECT"
            " (SELECT COUNT(*) FROM runs) AS runs,"
            " (SELECT COUNT(*) FROM graphs) AS graphs,"
            " (SELECT COUNT(*) FROM goals) AS goals"
        ).fetchone()
        return {"runs": row["runs"], "graphs": row["graphs"], "goals": row["goals"]}
    except sqlite3.OperationalError:
        return {"runs": 0, "graphs": 0, "goals": 0}
