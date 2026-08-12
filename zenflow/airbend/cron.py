"""Minimal 5-field cron matcher (stdlib only): minute hour dom month dow.
Supports `*`, lists, ranges, and step (`/N`). Used by graph validation and
the `serve` daemon. Python weekday (Mon=0) maps to cron dow (Sun=0).
"""

from __future__ import annotations

from datetime import datetime

FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),  # 7 is accepted as Sunday
)


def validate(expr: str) -> list[str]:
    errors: list[str] = []
    parts = expr.split()
    if len(parts) != 5:
        return ["cron expression must have 5 fields: minute hour dom month dow"]
    for (name, lo, hi), field in zip(FIELDS, parts):
        try:
            _expand(field, lo, hi)
        except ValueError as e:
            errors.append(f"cron `{name}` field: {e}")
    return errors


def _expand(field: str, lo: int, hi: int) -> set[int]:
    if not field:
        raise ValueError("empty field")
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty element in `{field}`")
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            if not step_s.isdigit() or int(step_s) < 1:
                raise ValueError(f"bad step in `{part}/{step_s}`")
            step = int(step_s)
        if part == "*":
            rng = range(lo, hi + 1)
        elif "-" in part:
            a, _, b = part.partition("-")
            if not a.isdigit() or not b.isdigit():
                raise ValueError(f"bad range `{part}`")
            rng = range(int(a), int(b) + 1)
        elif part.isdigit():
            rng = [int(part)]
        else:
            raise ValueError(f"bad token `{part}`")
        values.update(rng[::step])
    for v in values:
        if not lo <= v <= hi:
            raise ValueError(f"value {v} out of range {lo}-{hi}")
    return values


def matches(expr: str, dt: datetime | None = None) -> bool:
    dt = dt or datetime.now()
    parts = expr.split()
    if len(parts) != 5:
        return False
    dow_value = (dt.weekday() + 1) % 7  # cron: 0=Sunday .. 6=Saturday
    values = (dt.minute, dt.hour, dt.day, dt.month, dow_value)
    for (name, lo, hi), field, v in zip(FIELDS, parts, values):
        expanded = _expand(field, lo, hi)
        if name == "day of week" and 7 in expanded:
            expanded.add(0)
        if v not in expanded:
            return False
    return True
