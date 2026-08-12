"""Cron matcher: wildcards, steps, ranges, lists, and validation."""

from __future__ import annotations

from datetime import datetime

from airbend.cron import matches, validate


def test_star_matches_anything() -> None:
    dt = datetime(2026, 8, 12, 14, 30)
    assert matches("* * * * *", dt)
    assert matches("*/5 * * * *", dt)  # minute 30 is a multiple of 5
    assert not matches("*/7 * * * *", dt)


def test_hour_and_minute() -> None:
    dt = datetime(2026, 8, 12, 9, 0)
    assert matches("0 9 * * *", dt)
    assert not matches("0 10 * * *", dt)
    assert not matches("5 9 * * *", dt)


def test_step_and_range() -> None:
    assert matches("*/15 * * * *", datetime(2026, 8, 12, 10, 15))
    assert matches("0 9-11 * * *", datetime(2026, 8, 12, 10, 0))
    assert not matches("0 12-14 * * *", datetime(2026, 8, 12, 10, 0))


def test_list() -> None:
    dt = datetime(2026, 8, 12, 0, 30)
    assert matches("0,30 * * * *", dt)
    assert not matches("0,15 * * * *", dt)


def test_day_of_week_sunday() -> None:
    # 2026-08-09 is a Sunday; Python weekday() = 6 → cron dow 0.
    dt = datetime(2026, 8, 9, 8, 0)
    assert dt.weekday() == 6
    assert matches("0 8 * * 0", dt)
    assert matches("0 8 * * 7", dt)  # 7 accepted as Sunday
    assert not matches("0 8 * * 1", dt)


def test_validate() -> None:
    assert validate("* * * * *") == []
    assert validate("0 9 * * 1-5") == []
    errs = validate("* * *")
    assert len(errs) == 1 and "5 fields" in errs[0]
    errs = validate("61 * * * *")
    assert any("out of range" in e for e in errs)
    errs = validate("* * * * nope")
    assert any("bad token" in e for e in errs)
