"""Agent executor: delegation to Claude Code / Codex CLIs (headless).

The real CLI is never invoked in tests — a fake `runner.run_cli` returns the
agent's stdout, and a fake `shutil.which` makes `claude` appear installed.
"""

from __future__ import annotations

import json

import pytest

from airbend import scheduler, store
from airbend.agent import runner
from airbend.graph import from_config

AGENT_CFG = {
    "id": "ag",
    "version": 1,
    "nodes": [
        {
            "id": "a",
            "executor": {"type": "agent", "task": "Do the thing for {{goal}}"},
        }
    ],
}


def _start(conn, cfg=AGENT_CFG, **kwargs) -> str:
    graph = from_config(cfg)
    store.register_graph(conn, graph)
    return store.create_run(conn, graph, **kwargs)["id"]


def _patch(monkeypatch, out: str, code: int = 0, captured: dict | None = None):
    def fake_cli(argv, env, timeout):
        if captured is not None:
            captured["argv"] = argv
            captured["env"] = env
        return code, out, ""

    monkeypatch.setattr(runner, "run_cli", fake_cli)
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda name: f"/fake/{name}" if name in ("claude", "codex") else None,
    )
    monkeypatch.setenv("AIRBEND_AGENT", "claude")


def test_agent_envelope_result_and_writes(monkeypatch) -> None:
    envelope = json.dumps({"result": {"answer": 42}, "writes": {"greeting": "hi"}})
    _patch(monkeypatch, envelope)
    conn = store.ensure_db()
    run_id = _start(conn, goal="ship v2")

    assert scheduler.drive_run(conn, run_id) == "success"
    channels = store.read_channels(conn, run_id)
    assert channels["greeting"] == "hi"
    assert channels["a"] == {"answer": 42}


def test_agent_claude_outer_json_format(monkeypatch) -> None:
    # claude --output-format json wraps the answer string in {"result": "..."}.
    outer = json.dumps({"result": json.dumps({"result": "done"})})
    _patch(monkeypatch, outer)
    conn = store.ensure_db()
    run_id = _start(conn)
    assert scheduler.drive_run(conn, run_id) == "success"
    assert store.read_channels(conn, run_id)["a"] == "done"


def test_agent_plain_text_output(monkeypatch) -> None:
    _patch(monkeypatch, "just some text")
    conn = store.ensure_db()
    run_id = _start(conn)
    assert scheduler.drive_run(conn, run_id) == "success"
    assert store.read_channels(conn, run_id)["a"] == "just some text"


def test_agent_request_input_defers(monkeypatch) -> None:
    envelope = json.dumps({"result": None, "request_input": "approve deploy?"})
    _patch(monkeypatch, envelope)
    conn = store.ensure_db()
    run_id = _start(conn)
    assert scheduler.drive_run(conn, run_id) == "interrupted"
    states = store.get_node_states(conn, run_id)
    assert states["a"]["state"] == "deferred"


def test_agent_nonzero_exit_fails_run(monkeypatch) -> None:
    _patch(monkeypatch, "boom", code=1)
    conn = store.ensure_db()
    run_id = _start(conn)
    assert scheduler.drive_run(conn, run_id) == "failed"
    assert "boom" in store.get_node_states(conn, run_id)["a"]["error"]


def test_agent_templating_and_ctx_env(monkeypatch) -> None:
    captured: dict = {}
    _patch(monkeypatch, json.dumps({"result": "done"}), captured=captured)
    conn = store.ensure_db()
    run_id = _start(conn, goal="ship v2", params={"region": "eu"})
    assert scheduler.drive_run(conn, run_id) == "success"
    argv = captured["argv"]
    prompt = argv[2]  # claude: [claude, -p, prompt, ...]
    assert "Do the thing for ship v2" in prompt
    assert '"region": "eu"' in prompt
    assert captured["env"]["AIRBEND_CTX_FILE"]
    assert captured["env"]["AIRBEND_NODE_ID"] == "a"


def test_agent_no_cli_installed(monkeypatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.delenv("AIRBEND_AGENT", raising=False)
    conn = store.ensure_db()
    run_id = _start(conn)
    assert scheduler.drive_run(conn, run_id) == "failed"
    assert "no agent CLI found" in store.get_node_states(conn, run_id)["a"]["error"]


def test_agent_unknown_agent_field_rejected_at_validate() -> None:
    from airbend.errors import AirbendError

    cfg = {
        "id": "ag2",
        "version": 1,
        "nodes": [
            {"id": "a", "executor": {"type": "agent", "agent": "nope", "task": "x"}}
        ],
    }
    with pytest.raises(AirbendError, match="`executor.agent` must be auto"):
        from_config(cfg)
