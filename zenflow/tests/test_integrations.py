"""Session integrations: idempotent hook install/path-repair/uninstall,
Codex features, and SKILL.md generation + staleness gate."""

from __future__ import annotations

import json

from airbend import integrations
from airbend.cli import main


def test_ensure_hook_install_noop_and_repair(tmp_path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    changed, msg = integrations.ensure_hook(path, "SessionStart", "airbend home")
    assert changed and msg == "installed"
    data = json.loads(path.read_text())
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "airbend home"

    changed, msg = integrations.ensure_hook(path, "SessionStart", "airbend home")
    assert not changed and msg == "already installed (no-op)"

    changed, msg = integrations.ensure_hook(path, "SessionStart", "/new/bin/airbend home")
    assert changed and msg == "updated executable path"
    data = json.loads(path.read_text())
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/new/bin/airbend home"


def test_ensure_hook_preserves_other_entries(tmp_path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "", "hooks": [{"type": "command", "command": "other tool"}]}
                    ]
                }
            }
        )
    )
    integrations.ensure_hook(path, "SessionStart", "airbend home")
    data = json.loads(path.read_text())
    commands = [
        h["command"]
        for e in data["hooks"]["SessionStart"]
        for h in e["hooks"]
    ]
    assert "other tool" in commands and "airbend home" in commands


def test_remove_hook(tmp_path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    integrations.ensure_hook(path, "SessionStart", "airbend home")
    changed, msg = integrations.remove_hook(path, "SessionStart")
    assert changed and msg == "removed"
    assert json.loads(path.read_text()) == {}
    changed, msg = integrations.remove_hook(path, "SessionStart")
    assert not changed and msg == "not installed"


def test_ensure_codex_features_idempotent(tmp_path) -> None:
    home = tmp_path / "home"
    changed, _ = integrations.ensure_codex_features(home)
    assert changed
    cfg = home / ".codex" / "config.toml"
    assert "hooks = true" in cfg.read_text()
    changed, msg = integrations.ensure_codex_features(home)
    assert not changed and "no-op" in msg


def test_skill_content_shape() -> None:
    content = integrations.skill_content()
    assert content.startswith("---\nname: airbend")
    assert "airbend dag register" in content
    assert "airbend run resume" in content
    assert "installable" in content or "install" in content.lower()


def test_skill_write_check_cycle(tmp_path, capsys) -> None:
    path = tmp_path / "skills" / "airbend" / "SKILL.md"
    assert main(["skill", str(path)]) == 0
    assert path.exists()
    assert integrations.skill_is_current(path)

    assert main(["skill", str(path), "--check"]) == 0
    assert "current" in capsys.readouterr().out

    path.write_text("stale content")
    assert main(["skill", str(path), "--check"]) == 1
    out = capsys.readouterr().out
    assert "stale" in out

    assert main(["skill"]) == 0
    assert capsys.readouterr().out.startswith("---\nname: airbend")


def test_setup_installs_idempotent_uninstalls(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("airbend.integrations.hook_command", lambda: "airbend")

    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "claude-code" in out and "codex" in out

    cc = tmp_path / ".claude" / "settings.json"
    assert json.loads(cc.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "airbend home"
    codex = tmp_path / ".codex" / "hooks.json"
    assert json.loads(codex.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "airbend home"
    assert "hooks = true" in (tmp_path / "home" / ".codex" / "config.toml").read_text()

    # idempotent
    assert main(["setup"]) == 0
    assert "no-op" in capsys.readouterr().out

    # uninstall
    assert main(["setup", "--uninstall"]) == 0
    out = capsys.readouterr().out
    assert "removed" in out
    assert json.loads(cc.read_text()) == {}
    assert json.loads(codex.read_text()) == {}
