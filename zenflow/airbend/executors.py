"""Executor protocol — how a node runs. Executors run out-of-process
(command/python via subprocess, http via urllib) so a hung node cannot kill
the runtime; the scheduler enforces timeouts.

Contract: each executor receives a context dict and returns a Result
(ok, output, error). Structured output becomes channel writes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from airbend.graph import Node

DEFAULT_TIMEOUTS = {"command": 300, "python": 300, "http": 60, "agent": 600}


@dataclass
class Result:
    ok: bool
    output: Any = None
    error: str | None = None
    deferred: bool = False


def execute(node: Node, ctx: dict[str, Any], conn=None) -> Result:
    spec = node.executor
    etype = spec.get("type")
    timeout = node.timeout or DEFAULT_TIMEOUTS.get(etype, 300)
    if etype == "command":
        return _run_command(spec, ctx, timeout)
    if etype == "python":
        return _run_python(spec, ctx, timeout)
    if etype == "http":
        return _run_http(spec, ctx, timeout)
    if etype == "agent":
        # Imported lazily so the CLI fast path and non-agent runs stay lean.
        from airbend.agent.loop import run_agent

        result = run_agent(spec, ctx, timeout, conn=conn, run_id=ctx.get("run_id"))
        return Result(
            ok=result.ok,
            output=result.output,
            error=result.error,
            deferred=result.deferred,
        )
    return Result(False, error=f"executor type `{etype}` is not available")


def _parse_output(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _write_ctx(ctx: dict[str, Any]) -> Path:
    fd, path = tempfile.mkstemp(prefix="airbend-ctx-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ctx, f)
    return Path(path)


def _base_env(ctx: dict[str, Any], ctx_file: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["AIRBEND_CTX_FILE"] = str(ctx_file)
    env["AIRBEND_RUN_ID"] = str(ctx.get("run_id", ""))
    env["AIRBEND_NODE_ID"] = str(ctx.get("node_id", ""))
    if ctx.get("goal"):
        env["AIRBEND_GOAL"] = str(ctx["goal"])
    return env


def _run_command(spec: dict[str, Any], ctx: dict[str, Any], timeout: float) -> Result:
    ctx_file = _write_ctx(ctx)
    try:
        proc = subprocess.run(
            spec["cmd"],
            shell=True,
            env=_base_env(ctx, ctx_file),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Result(False, error=f"timed out after {timeout}s")
    except OSError as e:
        return Result(False, error=f"could not run command: {e}")
    finally:
        ctx_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return Result(False, error=f"exit {proc.returncode}: {detail}"[:2000])
    return Result(True, output=_parse_output(proc.stdout))


def _run_python(spec: dict[str, Any], ctx: dict[str, Any], timeout: float) -> Result:
    entry = spec["entry"]
    module, _, func = entry.partition(":")
    func = func or "run"
    code = (
        "import importlib, json, os, sys\n"
        f"m = importlib.import_module({module!r})\n"
        f"f = getattr(m, {func!r})\n"
        "ctx = json.load(open(os.environ['AIRBEND_CTX_FILE'], encoding='utf-8'))\n"
        "r = f(ctx)\n"
        "print(json.dumps(r))\n"
    )
    ctx_file = _write_ctx(ctx)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=_base_env(ctx, ctx_file),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Result(False, error=f"timed out after {timeout}s")
    except OSError as e:
        return Result(False, error=f"could not run python: {e}")
    finally:
        ctx_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = detail[-1] if detail else "unknown error"
        return Result(False, error=f"python error: {detail}"[:2000])
    return Result(True, output=_parse_output(proc.stdout))


def _run_http(spec: dict[str, Any], ctx: dict[str, Any], timeout: float) -> Result:
    url = spec["url"]
    method = spec.get("method", "POST")
    body = json.dumps(ctx).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        return Result(False, error=f"HTTP {e.code} {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return Result(False, error=f"http error: {e}")
    if not 200 <= status < 300:
        return Result(False, error=f"HTTP {status}")
    return Result(True, output=_parse_output(raw))
