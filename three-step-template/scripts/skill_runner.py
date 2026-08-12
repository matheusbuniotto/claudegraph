"""Generic CLI driver for any skill built on graph.py.

Not something a skill author edits — teacher_skill.py shows what to write
instead: a build_graph() function, router function(s), and optionally an
on_transition hook for skill-specific policy (e.g. counting a particular
loop as a retry). Everything else — stdin/stdout JSON, boundary validation,
step-budget handling, checkpointing, evidence logging — lives here once.

CLI contract (stdin -> stdout, both JSON):
  in:  {"current_node": "check", "data": {"understood": false}, "retry_count": 0,
        "max_retries": 2, "step_count": 0, "max_steps": 50,
        "log_path": "...", "checkpoint_path": "..."}  # all but current_node optional
  out: {"next_node": "explain", "kind": "task", "goal": "...", "retry_count": 1,
        "max_retries": 2, "step_count": 1, "done": false}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

from graph import Graph, State, StepBudgetExceeded, log_transition, save_checkpoint


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
        log_path = Path(payload.get("log_path", f"{skill_name}_session.log.jsonl"))
        checkpoint_path = Path(
            payload.get("checkpoint_path", f"{skill_name}_session.checkpoint.json")
        )
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
                "retry_count": state.retry_count,
                "max_retries": state.max_retries,
                "step_count": state.step_count,
                "done": kind == "end",
            }
        )
    )
