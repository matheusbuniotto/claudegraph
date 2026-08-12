"""AXI CLI behavior: content-first home, empty states, structured usage
errors, help. Runs in-process against an isolated AIRBEND_HOME."""

from __future__ import annotations

import json

from airbend.cli import main
from airbend.version import VERSION


def test_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == VERSION


def test_home_content_first(capsys) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert 'description: "Agent runtime' in out
    assert "runs: 0 runs found" in out
    assert "graphs: 0 graphs found" in out
    assert "help[4]:" in out


def test_home_json(capsys) -> None:
    assert main(["--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["runs"] == "0 runs found"
    assert isinstance(doc["help"], list)


def test_dag_list_empty_state(capsys) -> None:
    assert main(["dag", "list"]) == 0
    out = capsys.readouterr().out
    assert "graphs: 0 graphs found" in out
    assert "help[1]:" in out


def test_dag_without_subcommand(capsys) -> None:
    assert main(["dag"]) == 2
    out = capsys.readouterr().out
    assert "missing required argument `<subcommand>`" in out
    assert "valid commands: list" in out


def test_unknown_flag_self_correcting(capsys) -> None:
    assert main(["dag", "list", "--stat"]) == 2
    out = capsys.readouterr().out
    assert "unknown flag --stat for `airbend dag list`" in out
    assert "valid flags for `airbend dag list`:" in out
    assert "--help always allowed" in out


def test_unknown_flag_on_root(capsys) -> None:
    assert main(["--stat"]) == 2
    out = capsys.readouterr().out
    assert "unknown flag --stat for `airbend`" in out


def test_unknown_command(capsys) -> None:
    assert main(["plan"]) == 2
    out = capsys.readouterr().out
    assert "unknown command `plan`" in out
    assert "valid commands: dag, run, goal" in out


def test_unknown_subcommand_under_dag(capsys) -> None:
    assert main(["dag", "prune"]) == 2
    out = capsys.readouterr().out
    assert "unknown command `prune`" in out
    assert "valid commands: register" in out
    assert "list" in out


def test_help_exits_zero(capsys) -> None:
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: airbend" in out


def test_subcommand_help_exits_zero(capsys) -> None:
    assert main(["dag", "list", "--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: airbend dag list" in out
