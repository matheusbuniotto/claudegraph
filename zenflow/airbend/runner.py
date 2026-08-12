"""Process helpers — spawn the detached drive subprocess for a run.

Shared by `airbend run start` (app) and the `serve` daemon so both hand runs
to the same on-demand driver.
"""

from __future__ import annotations

import os
import subprocess
import sys

from airbend import store


def spawn_drive(run_id: str) -> None:
    log_dir = store.db_path().parent / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logf = open(log_dir / f"{run_id}.log", "a")
    subprocess.Popen(
        [sys.executable, "-m", "airbend", "run", "drive", run_id],
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=dict(os.environ),
    )
