"""Generic CLI driver for any skill built on graph.py.

Not something a skill author edits. The sibling *_skill.py file is what you
write: a build_graph() function, router function(s), and optionally an
on_transition hook for skill-specific policy (e.g. counting a particular
loop as a retry). Everything else — stdin/stdout JSON, boundary validation,
step-budget handling, checkpointing, evidence logging — lives here once.

CLI contract (stdin -> stdout, both JSON):
  in:  {"current_node": "check", "data": {"understood": false}, "retry_count": 0,
        "max_retries": 2, "step_count": 0, "max_steps": 50, "run_id": "...",
        "log_path": "...", "checkpoint_path": "...",
        "actions": [{"tool": "Read", "target": "spec.md"}]}  # all but current_node optional
  out: {"next_node": "explain", "kind": "task", "goal": "...", "banner": "...",
        "preview": "...", "retry_count": 1, "max_retries": 2, "step_count": 1,
        "run_id": "...", "done": false}

`actions` is a log-only record of what the *previous* node actually did — tool
calls made, sources retrieved — passed on the call that reports that node's
result. It is appended to the evidence log against that transition and never
touches `State` or the checkpoint: it's provenance for after-the-fact review,
not routing data. A node with nothing to report omits it or sends `[]`.

`run_id` scopes one run's evidence log, checkpoint, and any artifacts the
command file writes under one directory: `runs/<run_id>/`. Omit it on the
first call and this generates one and returns it; carry the returned value
forward on every later call the same way `retry_count`/`step_count` already
are, or the next call gets its own fresh (and disconnected) run directory.
`log_path`/`checkpoint_path`, if given explicitly, override the `run_id`-based
default entirely — set one of those instead when a caller wants a specific
location.

`runs/latest` is a symlink to the most recent `run_id`'s directory,
recreated on every call that uses the default paths. Recovery path for a
session that lost track of `run_id` (context compaction, a fresh session):
read `runs/latest/<skill>.checkpoint.json` for `current_node` etc., and
`readlink runs/latest` for the `run_id` itself to resume the same run
instead of forking a new one.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from graph import Graph, State, StepBudgetExceeded, log_transition, save_checkpoint


def _new_run_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


def run_skill(
    skill_name: str,
    build_graph: Callable[[], Graph],
    on_transition: Callable[[State, str], None] | None = None,
) -> None:
    """on_transition(state, next_node), if given, runs after step() resolves
    next_node and before logging/checkpointing — the hook for skill-specific
    policy. It mutates state in place (e.g. state.retry_count += 1)."""
    try:
        payload = json.load(sys.stdin)
        state = State(
            current_node=payload["current_node"],
            data=payload.get("data", {}),
            retry_count=payload.get("retry_count", 0),
            max_retries=payload.get("max_retries", 2),
            step_count=payload.get("step_count", 0),
            max_steps=payload.get("max_steps", 50),
        )
        run_id = payload.get("run_id") or _new_run_id()
        run_dir = Path("runs") / run_id
        using_default_paths = not (
            payload.get("log_path") or payload.get("checkpoint_path")
        )
        log_path = Path(payload.get("log_path") or run_dir / f"{skill_name}.log.jsonl")
        checkpoint_path = Path(
            payload.get("checkpoint_path") or run_dir / f"{skill_name}.checkpoint.json"
        )
        actions = payload.get("actions", [])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"error": f"invalid input: {exc}"}), file=sys.stderr)
        sys.exit(1)

    graph = build_graph()
    from_node = state.current_node

    try:
        next_node = graph.step(state)
    except StepBudgetExceeded as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    if on_transition:
        on_transition(state, next_node)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    if using_default_paths:
        latest = Path("runs") / "latest"
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(run_id)
    save_checkpoint(checkpoint_path, state)
    log_transition(
        log_path,
        {
            "skill": skill_name,
            "from": from_node,
            "to": next_node,
            "data": state.data,
            "retry_count": state.retry_count,
            "max_retries": state.max_retries,
            "step_count": state.step_count,
            "actions": actions,
        },
    )

    try:
        meta = graph.node_meta(next_node)
        kind, goal = meta.kind.value, meta.goal
    except KeyError:
        kind, goal = None, None

    print(
        json.dumps(
            {
                "next_node": next_node,
                "kind": kind,
                "goal": goal,
                "banner": _banner(next_node, kind, goal, state),
                "preview": _preview(graph.nodes(), next_node, kind),
                "retry_count": state.retry_count,
                "max_retries": state.max_retries,
                "step_count": state.step_count,
                "run_id": run_id,
                "done": kind == "end",
            }
        )
    )


# Marker per node kind, so the user can see at a glance whether the graph is
# working, waiting on them, or finished.
_MARKERS = {"task": "▶", "human_gate": "⏸", "end": "■", "start": "▶"}


def _banner(node: str, kind: str | None, goal: str | None, state: State) -> str:
    """One preformatted line the command file prints verbatim.

    Preformatted on purpose: asking Claude to compose a progress line each turn
    invites drift in wording and in what gets omitted. Here the format is fixed
    and the only instruction is "print this".
    """
    parts = [f"step {state.step_count}"]
    if state.retry_count:
        parts.append(f"retry {state.retry_count}/{state.max_retries}")
    marker = _MARKERS.get(kind or "", "▶")
    head = f"{marker} {node} ({', '.join(parts)})"
    return f"{head} — {goal}" if goal else head


def _preview(node_order: list[str], current: str, kind: str | None) -> str:
    """One line showing the whole graph with the node about to run highlighted.

    Node order is the author's add_node() call order, not a live traversal —
    branches (conditional edges, retry loops) collapse onto whichever side
    was declared first. It's a fixed map for orientation, not a route.
    """
    marker = _MARKERS.get(kind or "", "▶")
    parts = [f"{marker}[{n}]" if n == current else n for n in node_order]
    return " → ".join(parts)
