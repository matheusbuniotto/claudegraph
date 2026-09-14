"""Delegate agent-node execution to Claude Code / Codex CLIs (headless).

The agent executor is NOT an LLM API client. It hands the task to the
installed agent CLI — `claude -p` or `codex exec` — which runs its own tool
loop with its own model/config. The agent's reply is a JSON envelope that
maps onto node results, channel writes, and interrupts:

    {"result": <json>, "writes": {channel: value, ...}, "request_input": "<prompt or null>"}
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

CLAUDE_PERMISSION_MODES = ("default", "acceptEdits", "bypassPermissions", "plan")
AGENT_NAMES = ("claude", "codex")


class AgentError(Exception):
    pass


def detect(agent: str | None) -> str:
    """Resolve which agent CLI to run: executor `agent` field > env
    AIRBEND_AGENT > auto (first of claude/codex found on PATH)."""
    wanted = agent or os.environ.get("AIRBEND_AGENT") or "auto"
    if wanted == "auto":
        for name in AGENT_NAMES:
            if shutil.which(name):
                return name
        raise AgentError(
            "no agent CLI found: install Claude Code (`claude`) or Codex (`codex`)"
            " on PATH, or set AIRBEND_AGENT"
        )
    if wanted in AGENT_NAMES:
        if not shutil.which(wanted):
            raise AgentError(
                f"agent CLI not found on PATH: `{wanted}`"
                " (set AIRBEND_AGENT to the one you have installed)"
            )
        return wanted
    raise AgentError(f"unknown agent: `{wanted}` (expected claude, codex, or auto)")


def build_command(name: str, task: str, spec: dict[str, Any]) -> list[str]:
    """The headless invocation for the chosen agent CLI."""
    exe = shutil.which(name)
    if name == "claude":
        mode = spec.get("permission_mode") or "bypassPermissions"
        if mode not in CLAUDE_PERMISSION_MODES:
            raise AgentError(
                f"invalid executor.permission_mode `{mode}` for claude"
                f" (expected one of {', '.join(CLAUDE_PERMISSION_MODES)})"
            )
        return [exe, "-p", task, "--permission-mode", mode, "--output-format", "json"]
    # codex
    cmd = [exe, "exec", "--json", task]
    if spec.get("permission_mode") == "danger-full-access":
        cmd.append("--full-auto")
    return cmd


def run_cli(argv: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    """Run the agent CLI. Returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=env, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise AgentError(f"agent timed out after {timeout}s") from None
    except OSError as e:
        raise AgentError(f"could not run agent: {e}") from e
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def parse_result(raw: str) -> Any:
    """CLI stdout → the agent's result.

    Handles both shapes:
    - the CLI's own structured output (`claude --output-format json`,
      `codex exec --json`) wrapping the answer in `{"result": ...}`;
    - the envelope / plain text directly on stdout.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip() or None
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        inner = data["result"]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            return inner
    return data
