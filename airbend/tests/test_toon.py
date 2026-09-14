"""Encoder conformance against the TOON v4.1 encoding rules used by AXI."""

from __future__ import annotations

import pytest

from airbend.toon import dumps


def test_scalars() -> None:
    assert dumps({"a": 1, "b": True, "c": None, "d": 1.5}) == "a: 1\nb: true\nc: null\nd: 1.5\n"


def test_quoting_rule7_2() -> None:
    doc = {
        "colon": "hello: world",
        "empty": "",
        "num": "42",
        "comma": "a,b",
        "dash": "-x",
        "hash": "#x",
        "lead_ws": "  x",
        "brackets": "[x]",
        "true_lit": "true",
        "plain": "Fix auth bug",
        "slash": "3/3 passed",
    }
    assert dumps(doc) == (
        'colon: "hello: world"\n'
        'empty: ""\n'
        'num: "42"\n'
        'comma: "a,b"\n'
        'dash: "-x"\n'
        'hash: "#x"\n'
        'lead_ws: "  x"\n'
        'brackets: "[x]"\n'
        'true_lit: "true"\n'
        "plain: Fix auth bug\n"
        "slash: 3/3 passed\n"
    )


def test_nested_object() -> None:
    assert dumps({"run": {"id": "r1", "status": "running"}}) == (
        "run:\n  id: r1\n  status: running\n"
    )


def test_empty_object_and_empty_doc() -> None:
    assert dumps({"run": {}}) == "run:\n"
    assert dumps({}) == ""


def test_primitive_array_inline() -> None:
    assert dumps({"help": ["a", "b"]}) == "help[2]: a,b\n"


def test_empty_array() -> None:
    assert dumps({"runs": []}) == "runs: []\n"


def test_tabular_form() -> None:
    doc = {
        "tasks": [
            {"id": "1", "title": "Fix auth bug", "status": "open"},
            {"id": "2", "title": "Add pagination", "status": "closed"},
        ]
    }
    # Numeric-like ids are quoted per §7.2 — matching AXI's own example
    # `"1",Fix auth bug,open,alice`.
    assert dumps(doc) == (
        "tasks[2]{id,title,status}:\n"
        '  "1",Fix auth bug,open\n'
        '  "2",Add pagination,closed\n'
    )


def test_tabular_cell_quoting() -> None:
    doc = {"runs": [{"id": "r_1", "note": "a,b"}]}
    assert dumps(doc) == 'runs[1]{id,note}:\n  r_1,"a,b"\n'


def test_tabular_key_order_from_first_element() -> None:
    doc = {"runs": [{"id": "r1", "state": "open"}, {"state": "closed", "id": "r2"}]}
    assert dumps(doc) == "runs[2]{id,state}:\n  r1,open\n  r2,closed\n"


def test_keyed_tabular_form() -> None:
    doc = {
        "nodes": {
            "plan": {"state": "success", "attempt": 1},
            "build": {"state": "running", "attempt": 1},
        }
    }
    assert dumps(doc) == "nodes[2:]{state,attempt}:\n  plan: success,1\n  build: running,1\n"


def test_nested_uniform_column() -> None:
    doc = {
        "runs": [
            {"id": "r1", "meta": {"version": 1, "env": "prod"}},
            {"id": "r2", "meta": {"version": 2, "env": "dev"}},
        ]
    }
    assert dumps(doc) == "runs[2]{id,meta{version,env}}:\n  r1,1,prod\n  r2,2,dev\n"


def test_list_form_fallback_for_non_uniform() -> None:
    doc = {"items": [{"a": 1}, {"a": 2, "b": 3}]}
    assert dumps(doc) == "items[2]:\n  - a: 1\n  - a: 2\n    b: 3\n"


def test_list_form_fallback_for_empty_object_element() -> None:
    doc = {"items": [{"a": 1}, {}]}
    assert dumps(doc) == "items[2]:\n  - a: 1\n  -\n"


def test_escapes() -> None:
    assert dumps({"k": 'say "hi"\n\\'}) == 'k: "say \\"hi\\"\\n\\\\"\n'


def test_numbers_canonical() -> None:
    assert dumps({"a": 1000000, "b": 1.5, "c": 0.000001, "d": 1e-7, "e": -0.0, "f": 1e21}) == (
        "a: 1000000\nb: 1.5\nc: 0.000001\nd: 1e-07\ne: 0\nf: 1e+21\n"
    )


def test_nan_infinity_null() -> None:
    assert dumps({"a": float("nan"), "b": float("inf")}) == "a: null\nb: null\n"


def test_key_quoting() -> None:
    assert dumps({"my-key": 1}) == '"my-key": 1\n'


def test_quoted_key_in_header() -> None:
    doc = {("my-key"): [{"a": 1}]}
    assert dumps(doc) == '"my-key"[1]{a}:\n  1\n'


def test_unicode_unquoted() -> None:
    assert dumps({"msg": "olá 👋"}) == "msg: olá 👋\n"


def test_rejects_unencodable() -> None:
    with pytest.raises(ValueError):
        dumps({"k": object()})  # type: ignore[arg-type]
