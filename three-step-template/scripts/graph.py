"""Minimal, stdlib-only, LangGraph-style routing engine.

Skill-agnostic: this file knows nothing about "teaching" or any other
skill. It only tracks position in a node graph and decides what's next.
Content generation happens outside this process (Claude, inline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class State:
    current_node: str
    data: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 2


class Graph:
    """Build with add_node/add_edge/add_conditional_edge, query with step()."""

    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, Callable[[State], str]] = {}

    def add_node(self, name: str) -> None:
        self._nodes.add(name)

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges[from_node] = to_node

    def add_conditional_edge(
        self, from_node: str, router: Callable[[State], str]
    ) -> None:
        self._conditional_edges[from_node] = router

    def step(self, state: State) -> str:
        """Resolve the single next node for this state. Does not mutate state."""
        if state.current_node not in self._nodes:
            raise ValueError(f"unknown node: {state.current_node!r}")
        if state.current_node in self._conditional_edges:
            return self._conditional_edges[state.current_node](state)
        if state.current_node in self._edges:
            return self._edges[state.current_node]
        return state.current_node  # terminal: no outgoing edge, stay put
