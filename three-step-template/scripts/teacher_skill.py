"""Example skill built on graph.py + skill_runner.py.

COPY THIS FILE as the starting point for a new skill. Only three things are
skill-specific — everything else (CLI parsing, checkpointing, logging,
step-budget enforcement) lives once in skill_runner.py and is reused as-is:

  1. SKILL_NAME
  2. build_graph() — your nodes (with kind/goal/agent) and edges
  3. router function(s) for any conditional_edge, plus an optional
     on_transition() hook for skill-specific policy

Claude is the one holding the conversation and doing the actual explaining/
demonstrating/quizzing; this file only decides where to go next.
"""

from __future__ import annotations

from graph import Graph, NodeKind, State
from skill_runner import run_skill

SKILL_NAME = "teacher"


def check_router(state: State) -> str:
    """Pure: reads state, decides next node, never mutates."""
    if state.data.get("understood"):
        return "end"
    if state.retry_count >= state.max_retries:
        return "end"
    return "explain"


def build_graph() -> Graph:
    g = Graph()
    g.add_node(
        "explain",
        kind=NodeKind.TASK,
        goal="3-5 sentence plain-language explanation",
        agent="claude-inline",
    )
    g.add_node(
        "demonstrate",
        kind=NodeKind.TASK,
        goal="one concrete example",
        agent="claude-inline",
    )
    g.add_node(
        "check",
        kind=NodeKind.HUMAN_GATE,
        goal="ask one question, wait for the user's answer",
        agent="claude-inline",
    )
    g.add_node("end", kind=NodeKind.END, goal="wrap up", agent="claude-inline")
    g.add_edge("explain", "demonstrate")
    g.add_edge("demonstrate", "check")
    g.add_conditional_edge("check", check_router)
    return g


def on_transition(state: State, next_node: str) -> None:
    """Skill-specific policy: a loop from check -> explain counts as a retry."""
    if state.current_node == "check" and next_node == "explain":
        state.retry_count += 1


if __name__ == "__main__":
    run_skill(SKILL_NAME, build_graph, on_transition)
