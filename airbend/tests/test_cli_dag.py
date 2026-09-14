"""dag command behavior: register/validate/list/show/plan + AXI idempotency."""

from __future__ import annotations

from airbend.cli import main

OK_CFG = """\
id: t
version: 1
nodes:
  - id: a
    executor: {type: command, cmd: "true"}
  - id: b
    executor: {type: command, cmd: "true"}
    depends_on: [a]
"""


def _write(tmp_path, name: str, text: str):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_register(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "register", path]) == 0
    out = capsys.readouterr().out
    assert "registered" in out
    assert "t" in out


def test_register_idempotent_noop(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "register", path]) == 0
    assert main(["dag", "register", path]) == 0
    out = capsys.readouterr().out
    assert "no-op" in out


def test_register_conflict_without_version_bump(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "register", path]) == 0
    changed = OK_CFG.replace('cmd: "true"', 'cmd: "false"', 1)
    path2 = _write(tmp_path, "g2.yaml", changed)
    assert main(["dag", "register", path2]) == 1
    out = capsys.readouterr().out
    assert "already registered" in out
    assert "bump `version`" in out


def test_register_new_version_updates(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "register", path]) == 0
    bumped = OK_CFG.replace("version: 1", "version: 2")
    path2 = _write(tmp_path, "g2.yaml", bumped)
    assert main(["dag", "register", path2]) == 0
    out = capsys.readouterr().out
    assert "registered" in out


def test_validate_ok_and_cycle(tmp_path, capsys) -> None:
    ok = _write(tmp_path, "ok.yaml", OK_CFG)
    assert main(["dag", "validate", ok]) == 0
    assert "valid" in capsys.readouterr().out

    cycle = _write(
        tmp_path,
        "cyc.yaml",
        "id: c\nversion: 1\nnodes:\n"
        "  - {id: a, executor: {type: command, cmd: 'true'}, depends_on: [b]}\n"
        "  - {id: b, executor: {type: command, cmd: 'true'}, depends_on: [a]}\n",
    )
    assert main(["dag", "validate", cycle]) == 1
    out = capsys.readouterr().out
    assert "cycle detected" in out


def test_validate_missing_file(capsys) -> None:
    assert main(["dag", "validate", "/nonexistent.yaml"]) == 1
    out = capsys.readouterr().out
    assert "cannot read config" in out


def test_list_and_show(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "register", path]) == 0
    assert main(["dag", "list"]) == 0
    out = capsys.readouterr().out
    assert "graphs[1]{id,version}:" in out
    assert "t,1" in out

    assert main(["dag", "show", "t"]) == 0
    out = capsys.readouterr().out
    assert "nodes[2]{id,executor" in out
    assert "count: 2 nodes" in out


def test_show_unknown_graph(capsys) -> None:
    assert main(["dag", "show", "nope"]) == 1
    out = capsys.readouterr().out
    assert "graph not found" in out


def test_plan_no_change_and_would_register(tmp_path, capsys) -> None:
    path = _write(tmp_path, "g.yaml", OK_CFG)
    assert main(["dag", "plan", path]) == 0
    assert "would register" in capsys.readouterr().out

    assert main(["dag", "register", path]) == 0
    assert main(["dag", "plan", path]) == 0
    assert "no change" in capsys.readouterr().out
