"""Node and run state machines.

Airflow TaskInstance states, trimmed, plus the LangGraph-style `deferred`
state for interrupts: a run pauses at a safe point and `resume --input`
re-enters from the checkpoint.
"""

from __future__ import annotations

from enum import Enum


class NodeState(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"  # paused, awaiting agent/human input


TERMINAL_NODE_STATES = (NodeState.SUCCESS, NodeState.FAILED, NodeState.SKIPPED)


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL_RUN_STATES = (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.INTERRUPTED)
