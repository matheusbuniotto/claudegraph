"""run command behavior: start (--watch), status, events, list, and
interrupt/resume/retry error paths — all against an isolated store."""

from __future__ import annotations

import json

from airbend.cli import main

CFG = """\
id: t
version: 1
nodes:
  - id: a
    executor: {type: command, cmd: "true"}
  - id: b
    executor: {type: command, cmd: "true"}
    depends_on: [a]
"""


def _register(tmp_path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text(CFG)
    assert main(["dag", "register", str(p)]) == 0


def _run_id(capsys) -> str:
    out = capsys.readouterr().out
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("id: r_"):
            return line.split(": ", 1)[1]
    raise AssertionError(f"no run id in output: {out}")


def test_run_start_watch_success(tmp_path, capsys) -> None:
    _register(tmp_path)
    assert main(["run", "start", "t", "--watch"]) == 0
    out = capsys.readouterr().out
    assert '"type": "run.success"' in out
    assert "node.success" in out
    assert "status: success" in out


def test_run_status_and_events(tmp_path, capsys) -> None:
    _register(tmp_path)
    assert main(["run", "start", "t", "--watch"]) == 0
    run_id = _run_id(capsys)

    assert main(["run", "status", run_id]) == 0
    out = capsys.readouterr().out
    assert f"id: {run_id}" in out
    assert "status: success" in out
    assert "nodes[2:]{state,attempt" in out

    assert main(["run", "events", run_id]) == 0
    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
    assert lines and lines[0]["type"] == "run.started"
    assert lines[-1]["type"] == "run.success"


def test_run_list(tmp_path, capsys) -> None:
    _register(tmp_path)
    assert main(["run", "start", "t", "--watch"]) == 0
    assert main(["run", "list"]) == 0
    out = capsys.readouterr().out
    assert "count: 1 runs total" in out


def test_run_start_unknown_graph(capsys) -> None:
    assert main(["run", "start", "nope"]) == 1
    out = capsys.readouterr().out
    assert "graph not found" in out


def test_run_start_bad_params(tmp_path, capsys) -> None:
    _register(tmp_path)
    assert main(["run", "start", "t", "--params", "not-json"]) == 1
    out = capsys.readouterr().out
    assert "--params must be a JSON object" in out


def test_run_status_unknown(capsys) -> None:
    assert main(["run", "status", "r_missing"]) == 1
    assert "run not found" in capsys.readouterr().out


def test_interrupt_then_resume_flow(tmp_path, capsys) -> None:
    # Graph whose only node fails and routes to `interrupt`.
    p = tmp_path / "intr.yaml"
    p.write_text(
        "id: intr\nversion: 1\nnodes:\n"
        "  - id: a\n"
        "    executor: {type: command, cmd: 'false'}\n"
        "    routes: {failure: interrupt}\n"
    )
    assert main(["dag", "register", str(p)]) == 0
    assert main(["run", "start", "intr", "--watch"]) == 0
    out = capsys.readouterr().out
    assert "run.interrupted" in out
    run_id = next(
        line.split(": ", 1)[1]
        for line in out.splitlines()
        if line.strip().startswith("id: r_")
    )

    assert main(["run", "status", run_id]) == 0
    assert "status: interrupted" in capsys.readouterr().out

    # resume without input on an interrupt-only graph → node stays failing
    assert main(["run", "resume", run_id, "--watch"]) == 0
    out = capsys.readouterr().out
    assert "run.interrupted" in out  # re-deferred, still interrupted

    assert main(["run", "interrupt", run_id]) == 0
    out = capsys.readouterr().out
    assert "already interrupted (no-op)" in out


def test_retry_requires_failed_node(tmp_path, capsys) -> None:
    _register(tmp_path)
    assert main(["run", "start", "t", "--watch"]) == 0
    run_id = _run_id(capsys)
    assert main(["run", "retry", run_id, "--node", "a"]) == 1
    out = capsys.readouterr().out
    assert "only failed/deferred nodes can be retried" in out
