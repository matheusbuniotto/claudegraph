"""Version leaf module + AXI fast-path startup test.

Per AXI §10, the version probe must not pay for the CLI graph. The guard is a
relative one: `--version` startup measured against the `python -c "print(1)"`
floor in the same process, not an absolute millisecond budget.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from airbend.version import VERSION


def test_version_constant() -> None:
    assert VERSION == "0.1.0"


def test_pyproject_matches_version() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert pyproject["project"]["version"] == VERSION


def _timed(args: list[str], env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], float]:
    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, env=env
    )
    return result, time.perf_counter() - t0


def _median_of_three(args: list[str], env: dict[str, str]) -> float:
    times: list[float] = []
    for _ in range(3):
        _timed(args, env)  # warm-up + noise
        _, dt = _timed(args, env)
        times.append(dt)
    return statistics.median(times)


def test_version_fast_path(tmp_path: Path) -> None:
    env = {**os.environ, "AIRBEND_HOME": str(tmp_path)}
    floor = _median_of_three(["-c", "print(1)"], env)
    version_time = _median_of_three(["-m", "airbend", "--version"], env)
    # `-m` adds interpreter + package discovery; the fast path must stay near
    # the floor. A regression (e.g. importing the CLI graph) blows well past
    # this margin.
    assert version_time < floor + 0.15


def test_version_flag_spellings(tmp_path: Path) -> None:
    env = {**os.environ, "AIRBEND_HOME": str(tmp_path)}
    for flag in ("-v", "-V", "--version"):
        result, _ = _timed(["-m", "airbend", flag], env)
        assert result.returncode == 0, (flag, result.stderr)
        assert result.stdout.strip() == VERSION
