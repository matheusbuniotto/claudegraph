"""Graph config validation: structure, cross-references, cycle detection."""

from __future__ import annotations

import pytest

from airbend.errors import AirbendError
from airbend.graph import Graph, from_config


def _base() -> dict:
    return {
        "id": "g",
        "version": 1,
        "nodes": [
            {"id": "a", "executor": {"type": "command", "cmd": "true"}},
            {"id": "b", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["a"]},
        ],
    }


def test_valid_graph() -> None:
    g = from_config(_base())
    assert isinstance(g, Graph)
    assert g.id == "g" and g.version == 1 and len(g.nodes) == 2
    assert len(g.edges) == 1 and g.edges[0].kind == "dep"


def test_missing_id() -> None:
    with pytest.raises(AirbendError, match="missing `id`"):
        from_config({"version": 1, "nodes": _base()["nodes"]})


def test_bad_version() -> None:
    cfg = _base()
    cfg["version"] = 0
    with pytest.raises(AirbendError, match="`version` must be an integer"):
        from_config(cfg)


def test_bad_schedule() -> None:
    cfg = _base()
    cfg["schedule"] = "daily"
    with pytest.raises(AirbendError, match="`schedule`"):
        from_config(cfg)


def test_cron_schedule_with_quotes_normalized() -> None:
    # The documented YAML form `cron "0 9 * * *"` arrives with literal quotes.
    cfg = _base()
    cfg["schedule"] = 'cron "0 9 * * *"'
    assert from_config(cfg).schedule == "cron 0 9 * * *"


def test_invalid_cron_rejected() -> None:
    cfg = _base()
    cfg["schedule"] = 'cron "99 * * * *"'
    with pytest.raises(AirbendError, match="out of range"):
        from_config(cfg)


def test_unknown_dependency() -> None:
    cfg = _base()
    cfg["nodes"][1]["depends_on"] = ["nope"]
    with pytest.raises(AirbendError, match="unknown node `nope`"):
        from_config(cfg)


def test_duplicate_node_id() -> None:
    cfg = _base()
    cfg["nodes"].append(dict(cfg["nodes"][0]))
    with pytest.raises(AirbendError, match="duplicate node id: a"):
        from_config(cfg)


def test_missing_executor_fields() -> None:
    cfg = _base()
    cfg["nodes"][0]["executor"] = {"type": "http"}
    with pytest.raises(AirbendError, match="http executor requires `url`"):
        from_config(cfg)
    cfg["nodes"][0]["executor"] = {"type": "nope"}
    with pytest.raises(AirbendError, match="`executor.type`"):
        from_config(cfg)


def test_agent_executor_accepted() -> None:
    cfg = _base()
    cfg["nodes"][0]["executor"] = {"type": "agent", "task": "do the thing"}
    g = from_config(cfg)
    assert g.nodes[0].executor["type"] == "agent"


def test_dep_cycle_detected() -> None:
    cfg = _base()
    cfg["nodes"] = [
        {"id": "a", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["c"]},
        {"id": "b", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["a"]},
        {"id": "c", "executor": {"type": "command", "cmd": "true"}, "depends_on": ["b"]},
    ]
    with pytest.raises(AirbendError, match="cycle detected"):
        from_config(cfg)


def test_conditional_edge_cycle_detected() -> None:
    cfg = _base()
    cfg["nodes"] = [
        {"id": "a", "executor": {"type": "command", "cmd": "true"}, "on": {"failure": "b"}},
        {"id": "b", "executor": {"type": "command", "cmd": "true"}, "on": {"failure": "a"}},
    ]
    with pytest.raises(AirbendError, match="cycle detected"):
        from_config(cfg)


def test_unknown_on_target() -> None:
    cfg = _base()
    cfg["nodes"][0]["on"] = {"failure": "nope"}
    with pytest.raises(AirbendError, match="references unknown node"):
        from_config(cfg)


def test_route_keywords_allowed() -> None:
    cfg = _base()
    cfg["nodes"][0]["on"] = {"failure": "interrupt"}
    assert from_config(cfg).nodes[0].on == {"failure": "interrupt"}


def test_routes_key_alias() -> None:
    cfg = _base()
    cfg["nodes"][0]["routes"] = {"failure": "interrupt"}
    assert from_config(cfg).nodes[0].on == {"failure": "interrupt"}


def test_unquoted_on_yaml_bool_is_rejected() -> None:
    # Simulates YAML 1.1 turning the bare key `on` into True.
    cfg = _base()
    cfg["nodes"][0][True] = {"failure": "interrupt"}  # type: ignore[assignment]
    with pytest.raises(AirbendError, match="`routes` \\(or quoted"):
        from_config(cfg)


def test_bad_channel_op() -> None:
    cfg = _base()
    cfg["channels"] = {"x": {"op": "reduce"}}
    with pytest.raises(AirbendError, match="`op` must be one of"):
        from_config(cfg)


def test_empty_nodes_rejected() -> None:
    cfg = _base()
    cfg["nodes"] = []
    with pytest.raises(AirbendError, match="`nodes` must be a non-empty list"):
        from_config(cfg)


def test_edges_include_conditional() -> None:
    cfg = _base()
    cfg["nodes"][0]["on"] = {"failure": "b"}
    g = from_config(cfg)
    kinds = {(e.src, e.dst, e.kind) for e in g.edges}
    assert ("a", "b", "failure") in kinds
    assert ("a", "b", "dep") in kinds
