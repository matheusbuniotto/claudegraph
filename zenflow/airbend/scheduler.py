"""The run loop — airbend's scheduler.

Airflow's SchedulerJobRunner loop and LangGraph's Pregel superstep, collapsed
into one sequential on-demand driver: compute the ready set from edge
conditions, run one node, apply channel writes, resolve retries / conditional
routing / interrupts, persist every transition. The DB is the checkpoint.

Sequential execution honors `max_parallel` (at most N nodes at once, N≥1);
parallelism via threads is a future phase.
"""

from __future__ import annotations

import json
from typing import Any

from airbend import channels as channels_mod
from airbend import events, executors, store
from airbend.graph import Graph, Node


def _refresh(conn, run_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    run = store.get_run(conn, run_id)
    assert run is not None
    states = store.get_node_states(conn, run_id)
    return run, states


def drive_run(conn, run_id: str, stream: bool = False) -> str:
    """Drive a run to a terminal state. Returns the final run status.
    Events are always persisted; with stream=True they are also printed to
    stdout as JSONL (used by `run start --watch`)."""
    run = store.get_run(conn, run_id)
    if run is None:
        from airbend.errors import AirbendError

        raise AirbendError(f"run not found: {run_id}")

    if run["status"] in ("success", "failed", "interrupted"):
        return run["status"]

    graph = Graph.from_config(json.loads(run["config_json"])) if run["graph_id"] else Graph(
        id="goal", version=1, nodes=[]
    )
    nodes = {n.id: n for n in graph.nodes}
    edges = graph.edges
    incoming: dict[str, list[Any]] = {nid: [] for nid in nodes}
    for e in edges:
        incoming.setdefault(e.dst, []).append(e)
    leaves = [nid for nid in nodes if not any(e.src == nid for e in edges)]

    def emit(type_: str, node_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        events.emit(conn, run_id, type_, node_id, payload)
        if stream:
            print(json.dumps({"ts": None, "type": type_, "node_id": node_id,
                              "payload": payload}, default=str), flush=True)

    _, states = _refresh(conn, run_id)

    def is_ready(nid: str) -> bool:
        if states[nid]["state"] != "pending":
            return False
        for e in incoming.get(nid, []):
            s = states[e.src]["state"]
            if e.kind == "dep" and s != "success":
                return False
            if e.kind == "success" and s != "success":
                return False
            if e.kind == "failure" and s != "failed":
                return False
        return True

    def _unreachable(nid: str) -> bool:
        """A pending node whose every incoming edge can never fire — an
        alternative path (e.g. a `routes: failure` target whose source
        succeeded). Skipped, Airflow-style."""
        if not incoming.get(nid):
            return False
        for e in incoming[nid]:
            s = states[e.src]["state"]
            if s in ("pending", "scheduled", "running"):
                return False  # source may still resolve
            if e.kind == "dep" and s == "success":
                return False
            if e.kind == "success" and s == "success":
                return False
            if e.kind == "failure" and s == "failed":
                return False
        return True

    def apply_writes(node: Node, output: Any) -> None:
        declared = graph.channels
        if isinstance(output, dict):
            for k, v in output.items():
                channels_mod.write(
                    conn, run_id, str(k), v, channels_mod.declared_op(declared, str(k))
                )
        channels_mod.write(conn, run_id, node.id, output, "overwrite")

    def build_ctx(node: Node) -> dict[str, Any]:
        params = json.loads(run["params_json"]) if run["params_json"] else {}
        return {
            "run_id": run_id,
            "node_id": node.id,
            "goal": run["goal"],
            "params": params,
            "attempt": states[nid]["attempt"],
            "channels": store.read_channels(conn, run_id),
        }

    def rollup() -> str:
        states_now = store.get_node_states(conn, run_id)
        if any(states_now[l]["state"] == "deferred" for l in leaves):
            status = "interrupted"
        elif any(states_now[l]["state"] == "failed" for l in leaves):
            status = "failed"
        else:
            status = "success"
        store.set_run_status(conn, run_id, status)
        emit(f"run.{status}")
        return status

    emit("run.started", payload={"graph": graph.id})
    while True:
        run = store.get_run(conn, run_id)
        assert run is not None
        if run["status"] == "interrupted":
            break

        for nid in nodes:
            if is_ready(nid):
                store.set_node_state(conn, run_id, nid, "scheduled")
                states[nid] = {**states[nid], "state": "scheduled"}
                emit("node.scheduled", nid)

        scheduled = [nid for nid in nodes if states[nid]["state"] == "scheduled"]
        if not scheduled:
            if any(states[nid]["state"] == "deferred" for nid in nodes):
                store.set_run_status(conn, run_id, "interrupted")
                emit("run.interrupted")
                break
            if all(states[nid]["state"] in ("success", "failed", "skipped") for nid in nodes):
                rollup()
                break
            # Alternative paths that can never fire (e.g. a `routes: failure`
            # target whose source succeeded) are skipped, then we re-loop so
            # the skip cascades to their dependents.
            changed = False
            for nid in nodes:
                if states[nid]["state"] != "pending":
                    continue
                if _unreachable(nid):
                    store.set_node_state(
                        conn, run_id, nid, "skipped", ended_at=store.utcnow()
                    )
                    states[nid] = {**states[nid], "state": "skipped"}
                    emit("node.skipped", nid)
                    changed = True
            if changed:
                continue
            store.set_run_status(conn, run_id, "failed")
            emit("run.failed", payload={"reason": "no schedulable nodes"})
            break

        nid = scheduled[0]
        node = nodes[nid]
        attempt = states[nid]["attempt"]
        store.set_node_state(conn, run_id, nid, "running", started_at=store.utcnow())
        emit("node.running", nid, {"attempt": attempt})
        result = executors.execute(node, build_ctx(node), conn=conn)

        if result.deferred:
            # Agent requested input (LangGraph-style interrupt): pause the
            # run; `resume --input` re-enters from this checkpoint.
            store.set_node_state(
                conn, run_id, nid, "deferred", error=result.error,
                ended_at=store.utcnow(),
            )
            emit("node.deferred", nid, {"reason": result.output or "request_input"})
        elif result.ok:
            apply_writes(node, result.output)
            store.set_node_state(
                conn, run_id, nid, "success", output=result.output,
                set_output=True, ended_at=store.utcnow(),
            )
            emit("node.success", nid, {"attempt": attempt})
        else:
            if attempt <= node.retries:
                store.set_node_state(
                    conn, run_id, nid, "scheduled", attempt=attempt + 1,
                    error=result.error,
                )
                emit("node.retry", nid, {"attempt": attempt + 1, "error": result.error})
            elif node.on.get("failure") == "interrupt":
                store.set_node_state(
                    conn, run_id, nid, "deferred", error=result.error,
                    ended_at=store.utcnow(),
                )
                emit("node.deferred", nid, {"error": result.error})
            elif node.on.get("failure"):
                store.set_node_state(
                    conn, run_id, nid, "failed", error=result.error,
                    ended_at=store.utcnow(),
                )
                emit("node.failed", nid, {"error": result.error})
            else:
                store.set_node_state(
                    conn, run_id, nid, "failed", error=result.error,
                    ended_at=store.utcnow(),
                )
                emit("node.failed", nid, {"error": result.error})
                store.set_run_status(conn, run_id, "failed")
                emit("run.failed")
                break

        _, states = _refresh(conn, run_id)

    return store.get_run(conn, run_id)["status"]  # type: ignore[index]
