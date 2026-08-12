"""Minimal, stdlib-only, LangGraph-style routing engine.

Skill-agnostic: this file knows nothing about "teaching" or any other
skill. It only tracks position in a node graph and decides what's next.
Content generation happens outside this process (Claude, inline).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class NodeKind(Enum):
    START = "start"
    TASK = "task"
    HUMAN_GATE = "human_gate"
    END = "end"


@dataclass
class NodeMeta:
    name: str
    kind: NodeKind = NodeKind.TASK
    goal: str | None = None
    agent: str | None = None


@dataclass
class State:
    current_node: str
    data: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 2
    step_count: int = 0
    max_steps: int = 50


class StepBudgetExceeded(RuntimeError):
    """Raised when a State's step_count exceeds its max_steps.

    Engine-level safety net, independent of any skill's own retry policy —
    a skill author forgetting to bound their own loop doesn't leave the
    graph able to run forever.
    """


class Graph:
    """Build with add_node/add_edge/add_conditional_edge, query with step()."""

    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._node_order: list[str] = []
        self._node_meta: dict[str, NodeMeta] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, Callable[[State], str]] = {}

    def add_node(
        self,
        name: str,
        *,
        kind: NodeKind = NodeKind.TASK,
        goal: str | None = None,
        agent: str | None = None,
    ) -> None:
        if name not in self._nodes:
            self._node_order.append(name)
        self._nodes.add(name)
        self._node_meta[name] = NodeMeta(name=name, kind=kind, goal=goal, agent=agent)

    def nodes(self) -> list[str]:
        """Node names in add_node() call order — the author's own flow order,
        used to render a whole-graph preview rather than to route anything."""
        return list(self._node_order)

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges[from_node] = to_node

    def add_conditional_edge(
        self, from_node: str, router: Callable[[State], str]
    ) -> None:
        self._conditional_edges[from_node] = router

    def node_meta(self, name: str) -> NodeMeta:
        return self._node_meta[name]

    def step(self, state: State) -> str:
        """Resolve the single next node for this state.

        Mutates only the engine's own bookkeeping (state.step_count) —
        never state.data or state.retry_count, which stay skill-owned.
        """
        if state.current_node not in self._nodes:
            raise ValueError(f"unknown node: {state.current_node!r}")

        state.step_count += 1
        if state.step_count > state.max_steps:
            raise StepBudgetExceeded(
                f"step_count ({state.step_count}) exceeded max_steps ({state.max_steps})"
            )

        if state.current_node in self._conditional_edges:
            return self._conditional_edges[state.current_node](state)
        if state.current_node in self._edges:
            return self._edges[state.current_node]
        return state.current_node  # terminal: no outgoing edge, stay put


def log_transition(log_path: Path, event: dict[str, Any]) -> None:
    """Append one JSON line as evidence this transition actually ran.

    Deliberately dumb (append-only, no rotation, no locking) — it exists to answer
    "did the script really get called here," not to be a production logging system.
    """
    record = {"ts": time.time(), **event}
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def save_checkpoint(path: Path, state: State) -> None:
    """Write the full state to disk. Explicit save, no auto-resume magic —
    a future call still has to re-supply current_node etc. in its payload;
    this just gives something outside Claude's own context to recover from."""
    path.write_text(json.dumps(asdict(state)))


def load_checkpoint(path: Path) -> State:
    return State(**json.loads(path.read_text()))
