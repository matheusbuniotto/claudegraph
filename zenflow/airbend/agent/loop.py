"""The agent executor — a node executed by a Claude Code / Codex agent.

The installed agent CLI runs headless with the task + run context, drives
its own tool loop, and replies with a JSON envelope:

    {"result": <json>, "writes": {channel: value, ...}, "request_input": <prompt|absent>}

- `result` → the node's output (stored under the node-id channel)
- `writes` → channel writes applied to the run's data store
- `request_input` → pauses the run (node → deferred); `resume --input`
  re-enters and the injected value is available as channel `__input`
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from airbend.agent import runner

__all__ = ["AgentResult", "run_agent"]


@dataclass
class AgentResult:
    ok: bool
    output: Any = None
    error: str | None = None
    deferred: bool = False


def _fmt(v: Any) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


def _render(task: str, ctx: dict[str, Any]) -> str:
    """Template {{goal}}, {{params.<key>}}, {{channels.<key>}}."""
    out = task
    out = out.replace("{{goal}}", str(ctx.get("goal") or ""))
    for section in ("params", "channels"):
        for k, v in (ctx.get(section) or {}).items():
            out = out.replace(f"{{{{{section}.{k}}}}}", _fmt(v))
    return out


def _write_ctx(ctx: dict[str, Any]) -> Path:
    fd, path = tempfile.mkstemp(prefix="airbend-agent-ctx-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ctx, f)
    return Path(path)


def run_agent(
    spec: dict[str, Any],
    ctx: dict[str, Any],
    timeout: float,
    conn=None,
    run_id: str | None = None,
) -> AgentResult:
    try:
        name = runner.detect(spec.get("agent"))
    except runner.AgentError as e:
        return AgentResult(False, error=str(e))

    task = _render(spec.get("task") or "Execute the goal.", ctx)
    prompt = (
        f"Task: {task}\n\n"
        f"Context:\n- goal: {ctx.get('goal') or '-'}\n"
        f"- params: {_fmt(ctx.get('params') or {})}\n"
        f"- channels: {_fmt(ctx.get('channels') or {})}\n\n"
        "When done, reply with a single JSON object:\n"
        '{"result": <your result>, "writes": {channel: value, ...},'
        ' "request_input": "<prompt or absent>"}\n'
        "Set request_input to a prompt string to pause the run and ask the "
        "operator for input. Full context is available in the file at "
        "$AIRBEND_CTX_FILE."
    )

    try:
        argv = runner.build_command(name, prompt, spec)
    except runner.AgentError as e:
        return AgentResult(False, error=str(e))

    env = dict(os.environ)
    env["AIRBEND_RUN_ID"] = str(ctx.get("run_id", ""))
    env["AIRBEND_NODE_ID"] = str(ctx.get("node_id", ""))
    ctx_file = _write_ctx(ctx)
    env["AIRBEND_CTX_FILE"] = str(ctx_file)
    try:
        code, out, errout = runner.run_cli(argv, env, timeout)
    except runner.AgentError as e:
        return AgentResult(False, error=str(e))
    finally:
        ctx_file.unlink(missing_ok=True)

    if code != 0:
        lines = (errout or out).strip().splitlines()
        detail = lines[-1] if lines else f"agent exited with code {code}"
        return AgentResult(False, error=detail[:2000])

    envelope = runner.parse_result(out)
    if isinstance(envelope, dict):
        if envelope.get("request_input"):
            return AgentResult(
                False,
                output=str(envelope["request_input"]),
                error="request_input",
                deferred=True,
            )
        writes = envelope.get("writes")
        if isinstance(writes, dict) and conn is not None and run_id:
            from airbend import channels as channels_mod

            for k, v in writes.items():
                channels_mod.write(conn, run_id, str(k), v, "overwrite")
        result = envelope.get("result", envelope)
        return AgentResult(True, output=result)
    return AgentResult(True, output=envelope)
