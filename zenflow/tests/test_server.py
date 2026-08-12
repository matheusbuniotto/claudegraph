"""serve daemon: cron scheduling pass and webhook event intake."""

from __future__ import annotations

import json
import urllib.request

from airbend import server, store
from airbend.graph import from_config


def _register(conn, graph_id: str, schedule: str) -> None:
    graph = from_config(
        {
            "id": graph_id,
            "version": 1,
            "schedule": schedule,
            "nodes": [{"id": "a", "executor": {"type": "command", "cmd": "true"}}],
        }
    )
    store.register_graph(conn, graph)


def test_schedule_tick_creates_due_runs(tmp_path) -> None:
    conn = store.ensure_db()
    _register(conn, "nightly", "cron * * * * *")
    _register(conn, "manual", "manual")

    created = server.schedule_tick(conn)
    assert len(created) == 1  # only the cron graph

    # second immediate pass: no duplicate within the 60s window
    assert server.schedule_tick(conn) == []

    rows = store.list_runs(conn)
    assert len(rows) == 1
    assert rows[0]["graph_id"] == "nightly"


def test_schedule_tick_skips_not_due() -> None:
    conn = store.ensure_db()
    _register(conn, "rare", "cron 0 3 * * 1")  # Monday 03:00; today is not that
    assert server.schedule_tick(conn) == []


def test_due_cron_graphs_ignores_invalid_config() -> None:
    conn = store.ensure_db()
    conn.execute(
        "INSERT INTO graphs (id, version, config_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        ("broken", 1, "{not json", "t", "t"),
    )
    conn.commit()
    assert server.due_cron_graphs(conn) == []


def test_webhook_starts_run() -> None:
    conn = store.ensure_db()
    _register(conn, "t", "event")
    httpd, port = server.start_webhook(0)
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/events",
            data=json.dumps({"graph": "t", "goal": "via webhook", "params": {"x": 1}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 202
            body = json.loads(resp.read())
            assert body["run_id"].startswith("r_")
    finally:
        httpd.shutdown()

    rows = store.list_runs(conn)
    assert len(rows) == 1
    assert rows[0]["goal"] == "via webhook"


def test_webhook_unknown_graph() -> None:
    httpd, port = server.start_webhook(0)
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/events",
            data=json.dumps({"graph": "nope"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 404
    finally:
        httpd.shutdown()


def test_webhook_bad_path() -> None:
    httpd, port = server.start_webhook(0)
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/other",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 404
    finally:
        httpd.shutdown()
