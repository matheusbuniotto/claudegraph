"""Session integrations (AXI §7) — ambient context for agents.

- SessionStart hooks for Claude Code (project `.claude/settings.json`) and
  Codex (project `.codex/hooks.json` + `~/.codex/config.toml` features),
  installed idempotently with executable-path repair.
- A generated, installable SKILL.md (single source of truth = this module)
  with a `--check` staleness gate for CI.

OpenCode's plugin surface is not yet supported (documented in the README).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

DESCRIPTION = "Agent runtime — register graphs, run goals, control state"
CC_EVENT = "SessionStart"
CODEX_EVENT = "SessionStart"


def hook_command() -> str:
    """Portable hook command: the PATH-verified `airbend` name when it
    resolves to the current executable, the absolute path otherwise."""
    exe = shutil.which("airbend")
    try:
        if exe and os.path.samefile(exe, sys.argv[0]):
            return "airbend"
    except OSError:
        pass
    return str(Path(sys.argv[0]).resolve())


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ours_command(command: str) -> bool:
    """Our hooks run `<airbend> home`; that signature tells our entries apart
    from other tools' command hooks when merging settings files."""
    return "airbend" in command or command.rstrip().endswith(" home")


def _has_our_entry(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("hooks"), list)
        and any(
            isinstance(h, dict)
            and h.get("type") == "command"
            and _ours_command(h.get("command") or "")
            for h in entry["hooks"]
        )
    )


def ensure_hook(settings_path: Path, event: str, command: str) -> tuple[bool, str]:
    """Idempotent hook install with path repair. Returns (changed, message)."""
    data = _load_json(settings_path)
    entries = data.setdefault("hooks", {}).setdefault(event, [])
    for e in entries:
        if _has_our_entry(e):
            current = e["hooks"][0].get("command")
            if current == command:
                return False, "already installed (no-op)"
            e["hooks"][0]["command"] = command
            _write_json(settings_path, data)
            return True, "updated executable path"
    entries.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})
    _write_json(settings_path, data)
    return True, "installed"


def remove_hook(settings_path: Path, event: str) -> tuple[bool, str]:
    """Remove our hook entry, leaving any others intact."""
    if not settings_path.exists():
        return False, "not installed"
    data = _load_json(settings_path)
    entries = data.get("hooks", {}).get(event, [])
    kept = [e for e in entries if not _has_our_entry(e)]
    if len(kept) == len(entries):
        return False, "not installed"
    if kept:
        data["hooks"][event] = kept
    else:
        data["hooks"].pop(event, None)
        if not data["hooks"]:
            data.pop("hooks", None)
    _write_json(settings_path, data)
    return True, "removed"


def ensure_codex_features(home: Path) -> tuple[bool, str]:
    """`[features].hooks = true` in ~/.codex/config.toml, idempotent."""
    cfg = home / ".codex" / "config.toml"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if "hooks" in text:
        return False, "hooks already enabled (no-op)"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    with cfg.open("a", encoding="utf-8") as f:
        f.write("\n[features]\nhooks = true\n")
    return True, "enabled hooks in ~/.codex/config.toml"


# ---------------------------------------------------------------------------
# SKILL.md — generated from this module (single source of truth)
# ---------------------------------------------------------------------------

def skill_content() -> str:
    return f"""---
name: airbend
description: >-
  Manage and run airbend agent-runtime graphs (DAGs / state machines):
  register graphs from YAML config, start goal-driven runs, inspect and
  control run state, interrupt and resume. Use when the user mentions
  airbend, DAGs, graphs, goals, runs, or wants a goal executed.
---

# airbend

{DESCRIPTION}

Graphs are static DAG/state-machine definitions (YAML). Runs execute them;
nodes are command/python/http/agent steps. The runner is an agent; the CLI
controls graph, state, retries, and interrupts. All output is TOON on
stdout; every command accepts `--json`. Exit codes: 0 success/no-op,
1 error, 2 usage. Never interactive — pass values as flags.

## dag

- `airbend dag register <config.yaml>` — register a graph (idempotent; bump `version` to replace)
- `airbend dag validate <config.yaml>` — validate without registering
- `airbend dag list` — registered graphs
- `airbend dag show <id>` — structure: nodes, edges, routes
- `airbend dag plan <config.yaml>` — diff against what is registered

## run

- `airbend run start <dag> [--goal "<goal>"] [--params json] [--watch]` — start a run
- `airbend run status <run_id>` — run + per-node states
- `airbend run list [--status s]` — recent runs
- `airbend run events <run_id> [--follow]` — JSONL event stream
- `airbend run interrupt <run_id>` — pause at the next safe point
- `airbend run resume <run_id> [--input json]` — continue a paused run (input → channel `__input`)
- `airbend run retry <run_id> --node <node>` — re-run a failed/deferred node

## goal

- `airbend goal create "<text>" [--run --graph <id>]` — create a goal, optionally start a run
- `airbend goal list` / `airbend goal view <id>`

## install

- `airbend setup` — install SessionStart hooks (Claude Code + Codex) so every
  agent session starts with live run state
- `airbend skill <path> --check` — verify this skill file is current (CI gate)

Node failure semantics: retries first; then `routes: {{failure: <node>}}`
reroutes; `routes: {{failure: interrupt}}` pauses the run for input.
"""


def write_skill(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skill_content(), encoding="utf-8")


def skill_is_current(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8") == skill_content()
    except OSError:
        return False
