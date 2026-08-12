"""goal command behavior: create/list/view, and create --run wiring."""

from __future__ import annotations

import json

from airbend.cli import main

CFG = """\
id: t
version: 1
nodes:
  - id: a
    executor: {type: command, cmd: "true"}
"""


def test_goal_create_list_view(tmp_path, capsys) -> None:
    assert main(["goal", "create", "ship v2"]) == 0
    out = capsys.readouterr().out
    assert "ship v2" in out
    assert "status: open" in out
    gid = next(
        line.split(": ", 1)[1] for line in out.splitlines() if line.strip().startswith("id: g_")
    )

    assert main(["goal", "list"]) == 0
    out = capsys.readouterr().out
    assert "1 goals total" in out
    assert "ship v2" in out

    assert main(["goal", "view", gid]) == 0
    out = capsys.readouterr().out
    assert "status: open" in out
    assert "source: cli" in out


def test_goal_list_empty_state(capsys) -> None:
    assert main(["goal", "list"]) == 0
    out = capsys.readouterr().out
    assert "goals: 0 goals found" in out


def test_goal_create_empty_text(capsys) -> None:
    assert main(["goal", "create", "   "]) == 1
    out = capsys.readouterr().out
    assert "goal text is empty" in out


def test_goal_create_run_requires_graph(capsys) -> None:
    assert main(["goal", "create", "do it", "--run"]) == 1
    out = capsys.readouterr().out
    assert "--run requires --graph" in out


def test_goal_create_run_unknown_graph(capsys) -> None:
    assert main(["goal", "create", "do it", "--run", "--graph", "nope"]) == 1
    out = capsys.readouterr().out
    assert "graph not found" in out


def test_goal_create_run_starts_run(tmp_path, capsys) -> None:
    p = tmp_path / "g.yaml"
    p.write_text(CFG)
    assert main(["dag", "register", str(p)]) == 0
    capsys.readouterr().out  # consume register output
    assert main(["goal", "create", "run this", "--run", "--graph", "t"]) == 0
    out = capsys.readouterr().out
    assert "run:" in out
    assert "status: running" in out

    assert main(["goal", "list"]) == 0
    out = capsys.readouterr().out
    assert "1 goals total" in out
    assert "running" in out


def test_goal_view_unknown(capsys) -> None:
    assert main(["goal", "view", "g_missing"]) == 1
    out = capsys.readouterr().out
    assert "goal not found" in out


def test_goal_json(tmp_path, capsys) -> None:
    assert main(["goal", "create", "jsontest", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["goal"]["text"] == "jsontest"
