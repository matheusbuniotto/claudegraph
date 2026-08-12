"""The optional daemon (phase 4): cron-driven scheduling + webhook event
intake. `airbend serve` runs the loop; runs are executed by detached
`airbend run drive` subprocesses (the DB is the checkpoint, so the daemon
and the CLI can coexist).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from airbend import cron, store
from airbend.graph import from_config
from airbend.runner import spawn_drive

_WINDOW = timedelta(seconds=60)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def due_cron_graphs(conn):
    """Registered graphs whose cron schedule fires now and that have no run
    started in the last 60s (avoids double-firing)."""
    graphs = []
    rows = conn.execute("SELECT * FROM graphs").fetchall()
    cutoff = (datetime.now(timezone.utc) - _WINDOW).isoformat()
    for r in rows:
        try:
            cfg = json.loads(r["config_json"])
        except json.JSONDecodeError:
            continue
        schedule = cfg.get("schedule", "manual")
        if not isinstance(schedule, str) or not schedule.startswith("cron "):
            continue
        expr = schedule[len("cron "):].strip()
        if not cron.matches(expr):
            continue
        recent = conn.execute(
            "SELECT id FROM runs WHERE graph_id = ? AND started_at >= ? LIMIT 1",
            (r["id"], cutoff),
        ).fetchone()
        if recent is None:
            graphs.append(r)
    return graphs


def schedule_tick(conn) -> list[str]:
    """One scheduling pass: create + hand off runs for due cron graphs."""
    created: list[str] = []
    for row in due_cron_graphs(conn):
        graph = from_config(json.loads(row["config_json"]))
        run = store.create_run(conn, graph)
        spawn_drive(run["id"])
        created.append(run["id"])
    return created


# ---------------------------------------------------------------------------
# Webhook intake: POST /v1/events {"graph": <id>, "goal"?: str, "params"?: {}}
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/v1/events":
            self._json(404, {"error": "not found", "help": "POST /v1/events with {\"graph\": <id>}"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8", "replace")) if length else {}
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "request body must be JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "request body must be a JSON object"})
            return
        graph_id = body.get("graph")
        conn = store.ensure_db()
        try:
            row = store.get_graph(conn, graph_id) if graph_id else None
            if row is None:
                self._json(
                    404,
                    {"error": f"graph not found: {graph_id}",
                     "help": "POST /v1/events with a registered graph id"},
                )
                return
            graph = from_config(json.loads(row["config_json"]))
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            run = store.create_run(conn, graph, goal=body.get("goal"), params=params)
        except Exception as e:  # structured error, never a raw traceback
            self._json(500, {"error": f"could not start run: {e}"})
            return
        finally:
            conn.close()
        spawn_drive(run["id"])
        self._json(202, {"run_id": run["id"], "status": "running", "graph": graph_id})

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:  # diagnostics → stderr only
        import sys

        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def start_webhook(port: int) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    return server, server.server_address[1]
