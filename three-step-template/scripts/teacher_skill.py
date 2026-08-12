"""Example skill built on graph.py. Just a demo — any skill can follow this shape.

CLI contract (stdin -> stdout, both JSON):
  in:  {"current_node": "check", "data": {"understood": false}, "retry_count": 0, "max_retries": 2}
  out: {"next_node": "explain", "retry_count": 1, "max_retries": 2, "done": false}

Claude is the one holding the conversation and doing the actual explaining/
demonstrating/quizzing; this script only decides where to go next.
"""

from __future__ import annotations

import json
import sys

from graph import Graph, State

NODES = ("explain", "demonstrate", "check", "end")


def check_router(state: State) -> str:
    """Pure: reads state, decides next node, never mutates."""
    if state.data.get("understood"):
        return "end"
    if state.retry_count >= state.max_retries:
        return "end"
    return "explain"


def build_graph() -> Graph:
    g = Graph()
    for node in NODES:
        g.add_node(node)
    g.add_edge("explain", "demonstrate")
    g.add_edge("demonstrate", "check")
    g.add_conditional_edge("check", check_router)
    return g


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        state = State(
            current_node=payload["current_node"],
            data=payload.get("data", {}),
            retry_count=payload.get("retry_count", 0),
            max_retries=payload.get("max_retries", 2),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"error": f"invalid input: {exc}"}), file=sys.stderr)
        sys.exit(1)

    graph = build_graph()
    next_node = graph.step(state)

    # Skill-specific policy: a loop from check -> explain counts as a retry.
    if state.current_node == "check" and next_node == "explain":
        state.retry_count += 1

    print(
        json.dumps(
            {
                "next_node": next_node,
                "retry_count": state.retry_count,
                "max_retries": state.max_retries,
                "done": next_node == "end",
            }
        )
    )


if __name__ == "__main__":
    main()
