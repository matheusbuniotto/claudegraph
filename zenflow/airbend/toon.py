"""TOON (Token-Oriented Object Notation) encoder.

Implements the encoder side of the TOON v4.1 specification
(https://toonformat.dev/reference/spec.html): the JSON data model with root
objects, nested objects, inline primitive arrays (§9.1), tabular arrays of
uniform objects (§9.3), keyed tabular objects (§9.5), and list-form fallback
(§9.4).

Encoding invariants (§13.1): UTF-8 with LF, 2-space indentation, canonical
numbers (§2), spec quoting (§7.2) and escaping (§7.1), no comment lines, no
trailing whitespace. Internal logic stays on JSON; TOON is applied at the
stdout boundary.
"""

from __future__ import annotations

import math
import re
from typing import Any

_INDENT = "  "

# §7.1 escape table (matched before the generic \uXXXX fallback).
_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}

# §7.2: quote when the string contains a delimiter/colon/quote/backslash,
# brackets/braces, or control characters.
_NEEDS_QUOTE_CHARS = re.compile(r'[,:"\\[\]{}]|[\x00-\x1f]')
# §7.2: numeric-like strings MUST be quoted.
_NUMERIC_LIKE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?$", re.IGNORECASE)
# §7.3: keys may be unquoted only when they match this.
_UNQUOTED_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _escape(s: str) -> str:
    out: list[str] = []
    for ch in s:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def quote_string(s: str) -> str:
    """Encode a string value per §7.2 (quote exactly when required)."""
    if (
        s == ""
        or s != s.strip(" \t")
        or s in ("true", "false", "null")
        or _NUMERIC_LIKE.match(s)
        or _NEEDS_QUOTE_CHARS.search(s)
        or s.startswith(("-", "#"))
    ):
        if _SURROGATE.search(s):
            raise ValueError("TOON cannot encode unpaired surrogates")
        return '"' + _escape(s) + '"'
    return s


def encode_key(k: str) -> str:
    """Encode an object key per §7.3."""
    if _UNQUOTED_KEY.match(k):
        return k
    return '"' + _escape(k) + '"'


def _number(n: float) -> str:
    if n != n or n in (math.inf, -math.inf):
        return "null"  # §3 normalization
    if n == 0:
        return "0"  # also normalizes -0.0
    a = abs(n)
    if 1e-6 <= a < 1e21:
        # §2: canonical decimal — no exponent, no trailing zeros.
        fixed = f"{n:.17f}".rstrip("0").rstrip(".")
        if float(fixed) == n:
            return fixed
    # Outside the canonical range: exponent form via repr (shortest
    # round-trip, lowercase e, explicit sign, per §2).
    return repr(n)


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _number(v)
    if isinstance(v, str):
        return quote_string(v)
    raise ValueError(f"TOON cannot encode {type(v).__name__} as a scalar")


def _is_primitive(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


class _Field:
    __slots__ = ("name", "sub")

    def __init__(self, name: str, sub: list["_Field"] | None = None) -> None:
        self.name = name
        self.sub = sub


def _uniform_keys(objs: list[dict[str, Any]]) -> bool:
    keys = set(objs[0].keys())
    return all(set(o.keys()) == keys for o in objs[1:])


def _classify(values: list[Any], name: str) -> _Field | None:
    """Return a field for the column, or None if it is not uniform-primitive
    or nested-uniform (§9.3) — which disqualifies tabular form."""
    if all(_is_primitive(v) for v in values):
        return _Field(name, None)
    if all(isinstance(v, dict) and v for v in values) and _uniform_keys(values):
        sub = _build_fields(values)
        if sub is not None:
            return _Field(name, sub)
    return None


def _build_fields(objs: list[dict[str, Any]]) -> list[_Field] | None:
    fields: list[_Field] = []
    for key in objs[0].keys():
        col = _classify([o[key] for o in objs], key)
        if col is None:
            return None
        fields.append(col)
    return fields


def _row_cells(obj: dict[str, Any], fields: list[_Field]) -> list[str]:
    cells: list[str] = []
    for f in fields:
        v = obj[f.name]
        if f.sub is None:
            cells.append(_scalar(v))
        else:
            cells.extend(_row_cells(v, f.sub))
    return cells


def _field_names(fields: list[_Field]) -> str:
    parts: list[str] = []
    for f in fields:
        if f.sub is None:
            parts.append(encode_key(f.name))
        else:
            parts.append(encode_key(f.name) + "{" + _field_names(f.sub) + "}")
    return ",".join(parts)


def _keyed_fields(d: dict[str, Any]) -> list[_Field] | None:
    """§9.5 detection: ≥2 entries, every value a non-empty uniform object."""
    if len(d) < 2:
        return None
    values = list(d.values())
    if not all(isinstance(v, dict) and v for v in values):
        return None
    if not _uniform_keys(values):
        return None
    return _build_fields(values)


def _member_line(key: str, value: Any) -> str:
    """A single object-field line (used for the first field on a list-item
    hyphen line, §10)."""
    if isinstance(value, dict):
        return encode_key(key) + ":"
    if isinstance(value, list):
        if not value:
            return encode_key(key) + ": []"
        if all(_is_primitive(v) for v in value):
            return f"{encode_key(key)}[{len(value)}]: " + ",".join(_scalar(v) for v in value)
        return f"{encode_key(key)}[{len(value)}]:"
    return encode_key(key) + ": " + _scalar(value)


def _emit_array(key: str, items: list[Any], depth: int, lines: list[str]) -> None:
    ind = _INDENT * depth
    if not items:
        lines.append(f"{ind}{encode_key(key)}: []")  # §9.1 empty-array form
        return
    if all(_is_primitive(v) for v in items):
        cells = [_scalar(v) for v in items]  # §9.1 inline form
        lines.append(f"{ind}{encode_key(key)}[{len(items)}]: " + ",".join(cells))
        return
    if all(isinstance(v, dict) and v for v in items) and _uniform_keys(items):
        fields = _build_fields(items)
        if fields is not None:
            lines.append(f"{ind}{encode_key(key)}[{len(items)}]{{{_field_names(fields)}}}:")
            for item in items:
                cells = _row_cells(item, fields)
                lines.append(_INDENT * (depth + 1) + ",".join(cells))
            return
    # §9.4 list form
    lines.append(f"{ind}{encode_key(key)}[{len(items)}]:")
    for item in items:
        _emit_list_item(item, depth + 1, lines)


def _emit_list_item(item: Any, depth: int, lines: list[str]) -> None:
    ind = _INDENT * depth
    if _is_primitive(item):
        lines.append(f"{ind}- {_scalar(item)}")
    elif isinstance(item, dict):
        if not item:
            lines.append(f"{ind}-")  # §10 bare marker for an empty object
            return
        keys = list(item.keys())
        lines.append(f"{ind}- {_member_line(keys[0], item[keys[0]])}")
        for k in keys[1:]:
            _emit_member(k, item[k], depth + 1, lines)
    elif isinstance(item, list):
        if not item:
            lines.append(f"{ind}- []")
        elif all(_is_primitive(v) for v in item):
            lines.append(f"{ind}- [{len(item)}]: " + ",".join(_scalar(v) for v in item))
        else:
            lines.append(f"{ind}- [{len(item)}]:")
            for sub in item:
                _emit_list_item(sub, depth + 1, lines)
    else:
        raise ValueError(f"TOON cannot encode {type(item).__name__} as a list item")


def _emit_member(key: str, value: Any, depth: int, lines: list[str]) -> None:
    ind = _INDENT * depth
    if isinstance(value, dict):
        if not value:
            lines.append(f"{ind}{encode_key(key)}:")  # §8 empty object
            return
        kt = _keyed_fields(value)
        if kt is not None:
            lines.append(f"{ind}{encode_key(key)}[{len(value)}:]{{{_field_names(kt)}}}:")
            for entry_key, entry_val in value.items():
                cells = _row_cells(entry_val, kt)
                lines.append(
                    _INDENT * (depth + 1) + f"{encode_key(entry_key)}: " + ",".join(cells)
                )
            return
        lines.append(f"{ind}{encode_key(key)}:")
        for k, v in value.items():
            _emit_member(k, v, depth + 1, lines)
    elif isinstance(value, list):
        _emit_array(key, value, depth, lines)
    else:
        lines.append(f"{ind}{encode_key(key)}: " + _scalar(value))


def dumps(doc: dict[str, Any]) -> str:
    """Encode a JSON-model object as a TOON document (LF line endings)."""
    if not isinstance(doc, dict):
        raise ValueError("TOON root must be an object")
    if not doc:
        return ""  # §8: an empty root object yields an empty document
    lines: list[str] = []
    for k, v in doc.items():
        _emit_member(k, v, 0, lines)
    return "\n".join(lines) + "\n"
