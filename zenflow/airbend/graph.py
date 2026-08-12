"""Graph (DAG / state-machine) model and config validation.

A Graph is the static, versioned definition: nodes with executors, static
`depends_on` edges, and LangGraph-style conditional edges (`on: success` /
`on: failure`). Cycle-checked on load; versioned at registration (Airflow DAG
semantics). Config is data, not code — YAML in, validated Graph out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from airbend.errors import AirbendError

EXECUTOR_TYPES = ("command", "python", "http", "agent")
AVAILABLE_EXECUTOR_TYPES = ("command", "python", "http", "agent")
SCHEDULE_KINDS = ("manual", "goal", "event")
ROUTE_KEYWORDS = ("interrupt", "fail")
CHANNEL_OPS = ("overwrite", "append")
CONDITION_KINDS = ("success", "failure")


@dataclass
class Node:
    id: str
    executor: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    retries: int = 0
    timeout: float | None = None
    on: dict[str, str] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str  # "dep" | "success" | "failure" — how src's outcome releases dst


@dataclass
class Graph:
    id: str
    version: int
    schedule: str = "manual"
    channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_parallel: int = 1
    nodes: list[Node] = field(default_factory=list)

    @property
    def edges(self) -> list[Edge]:
        edges: list[Edge] = []
        for n in self.nodes:
            for dep in n.depends_on:
                edges.append(Edge(dep, n.id, "dep"))
            for cond, target in n.on.items():
                if target not in ROUTE_KEYWORDS:
                    edges.append(Edge(n.id, target, cond))
        return edges

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Graph":
        """Validate a raw config dict and build a Graph. Raises AirbendError."""
        return _from_config(cfg)

    def to_config(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "schedule": self.schedule,
            "channels": self.channels,
            "max_parallel": self.max_parallel,
            "nodes": [
                {
                    "id": n.id,
                    "executor": n.executor,
                    "depends_on": list(n.depends_on),
                    "retries": n.retries,
                    "timeout": n.timeout,
                    "on": dict(n.on),
                }
                for n in self.nodes
            ],
        }


def _raise(errors: list[str]) -> None:
    head = errors[0]
    if len(errors) > 1:
        head = f"{head} (and {len(errors) - 1} more)"
    raise AirbendError(head, "fix the config and re-register")


def _from_config(cfg: dict[str, Any]) -> Graph:
    """Validate a raw config dict and build a Graph. Raises AirbendError."""
    errors: list[str] = []

    graph_id = str(cfg.get("id", "")).strip()
    if not graph_id:
        errors.append("missing `id`")

    version = cfg.get("version")
    if not isinstance(version, int) or version < 1:
        errors.append("`version` must be an integer >= 1")

    schedule = cfg.get("schedule", "manual")
    if not isinstance(schedule, str) or (
        schedule not in SCHEDULE_KINDS and not schedule.startswith("cron ")
    ):
        errors.append(f"`schedule` must be one of {SCHEDULE_KINDS} or a `cron \"...\"` string")
    elif isinstance(schedule, str) and schedule.startswith("cron "):
        from airbend import cron

        # YAML plain scalars keep literal quotes (`cron "0 9 * * *"`), so the
        # documented syntax arrives with quotes attached — strip them.
        expr = schedule[len("cron "):].strip().strip("\"'")
        cron_errors = cron.validate(expr)
        if cron_errors:
            errors.append(f"`schedule`: {cron_errors[0]}")
        else:
            schedule = f"cron {expr}"

    max_parallel = cfg.get("max_parallel", 1)
    if not isinstance(max_parallel, int) or max_parallel < 1:
        errors.append("`max_parallel` must be an integer >= 1")

    channels: dict[str, dict[str, Any]] = {}
    raw_channels = cfg.get("channels") or {}
    if not isinstance(raw_channels, dict):
        errors.append("`channels` must be a mapping")
    else:
        for key, spec in raw_channels.items():
            op = spec.get("op", "overwrite") if isinstance(spec, dict) else None
            if op not in CHANNEL_OPS:
                errors.append(f"channel `{key}`: `op` must be one of {CHANNEL_OPS}")
                continue
            channels[str(key)] = {"op": op}

    raw_nodes = cfg.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        errors.append("`nodes` must be a non-empty list")
        raw_nodes = []

    nodes = _parse_nodes(raw_nodes, errors)
    if errors:
        _raise(errors)

    graph = Graph(
        id=graph_id,
        version=version,
        schedule=str(schedule),
        channels=channels,
        max_parallel=max_parallel,
        nodes=nodes,
    )
    cycle = _find_cycle(graph)
    if cycle is not None:
        _raise([f"cycle detected: {' -> '.join(cycle)}"])
    return graph


# Module-level alias so both `Graph.from_config(...)` and `from_config(...)`
# work.
from_config = _from_config


def _parse_on(raw: dict[str, Any], nid: str, errors: list[str]) -> dict[str, str]:
    """Parse conditional routes.

    `routes:` is the canonical key — YAML 1.1 (PyYAML) parses the bare key
    `on:` as the boolean True, so that spelling is a footgun; quoted `"on"`
    still works as a fallback.
    """
    routes = raw.get("routes")
    on = raw.get("on")
    value: dict[str, Any] | None = None
    if isinstance(routes, dict):
        value = routes
    elif isinstance(on, dict):
        value = on
    elif "routes" in raw or "on" in raw or any(isinstance(k, bool) for k in raw):
        # Covers YAML 1.1's bare `on:` / `off:` keys, which parse as booleans.
        errors.append(
            f"node `{nid}`: `routes` (or quoted `\"on\"`) must be a mapping"
            " — note YAML 1.1 parses an unquoted `on:` as a boolean"
        )
        return {}
    value = value or {}
    if not all(k in CONDITION_KINDS for k in value):
        errors.append(f"node `{nid}`: `routes` keys must be in {CONDITION_KINDS}")
        value = {}
    out: dict[str, str] = {}
    for cond, target in value.items():
        if not isinstance(target, str) or not target.strip():
            errors.append(f"node `{nid}`: `{cond}` route needs a target node or keyword")
            continue
        out[str(cond)] = target.strip()
    return out


def _parse_nodes(raw_nodes: list[Any], errors: list[str]) -> list[Node]:
    nodes: list[Node] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            errors.append(f"nodes[{i}]: must be a mapping")
            continue
        nid = str(raw.get("id", "")).strip()
        if not nid:
            errors.append(f"nodes[{i}]: missing `id`")
            continue
        if nid in seen:
            errors.append(f"duplicate node id: {nid}")
            continue
        seen.add(nid)

        ex = raw.get("executor")
        et = ex.get("type") if isinstance(ex, dict) else None
        if et not in EXECUTOR_TYPES:
            errors.append(f"node `{nid}`: `executor.type` must be one of {EXECUTOR_TYPES}")
            ex = {"type": "command", "cmd": "true"}
        elif et not in AVAILABLE_EXECUTOR_TYPES:
            errors.append(f"node `{nid}`: executor type `{et}` is not yet available")
        if et == "command" and not ex.get("cmd"):
            errors.append(f"node `{nid}`: command executor requires `cmd`")
        if et == "python" and not ex.get("entry"):
            errors.append(f"node `{nid}`: python executor requires `entry`")
        if et == "http" and not ex.get("url"):
            errors.append(f"node `{nid}`: http executor requires `url`")
        if et == "agent":
            agent = ex.get("agent") or "auto"
            if agent not in ("auto", "claude", "codex"):
                errors.append(
                    f"node `{nid}`: `executor.agent` must be auto, claude, or codex"
                )
            pm = ex.get("permission_mode")
            if pm is not None and pm not in (
                "default", "acceptEdits", "bypassPermissions", "plan", "danger-full-access"
            ):
                errors.append(f"node `{nid}`: invalid `executor.permission_mode` `{pm}`")

        retries = raw.get("retries", 0)
        if not isinstance(retries, int) or retries < 0:
            errors.append(f"node `{nid}`: `retries` must be an integer >= 0")
            retries = 0

        timeout = raw.get("timeout")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0
        ):
            errors.append(f"node `{nid}`: `timeout` must be a positive number")
            timeout = None

        on = _parse_on(raw, nid, errors)

        depends = raw.get("depends_on") or []
        if not isinstance(depends, list) or not all(isinstance(d, str) and d for d in depends):
            errors.append(f"node `{nid}`: `depends_on` must be a list of node ids")
            depends = []

        nodes.append(
            Node(
                id=nid,
                executor=dict(ex),
                depends_on=list(depends),
                retries=int(retries),
                timeout=float(timeout) if timeout is not None else None,
                on={str(k): str(v) for k, v in on.items()},
            )
        )

    ids = {n.id for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            if dep not in ids:
                errors.append(f"node `{n.id}`: depends_on references unknown node `{dep}`")
        for cond, target in n.on.items():
            if target not in ROUTE_KEYWORDS and target not in ids:
                errors.append(f"node `{n.id}`: `on: {cond}` references unknown node `{target}`")
    return nodes


def _find_cycle(graph: Graph) -> list[str] | None:
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        adj.setdefault(e.src, []).append(e.dst)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v) == GRAY:
                return stack[stack.index(v):] + [v]
            if color.get(v, WHITE) == WHITE:
                cyc = dfs(v)
                if cyc:
                    return cyc
        stack.pop()
        color[u] = BLACK
        return None

    for nid in adj:
        if color.get(nid, WHITE) == WHITE:
            cyc = dfs(nid)
            if cyc:
                return cyc
    return None


def load_config(path: str | Path) -> dict[str, Any]:
    """Read + parse a YAML config file (PyYAML imported lazily so the CLI
    fast path and non-config commands stay lean)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise AirbendError(f"cannot read config: {p}", str(e)) from e
    try:
        import yaml
    except ImportError:  # pragma: no cover
        raise AirbendError("PyYAML is required to load config files") from None
    try:
        cfg = yaml.safe_load(text)
    except Exception as e:
        raise AirbendError(f"invalid YAML in {p}", str(e)) from e
    if not isinstance(cfg, dict):
        raise AirbendError(f"config root must be a mapping, got {type(cfg).__name__}")
    return cfg
