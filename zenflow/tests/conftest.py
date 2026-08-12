"""Test fixtures: point AIRBEND_HOME at a per-session temp dir so tests never
touch the real ~/.airbend store."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRBEND_HOME", str(tmp_path_factory.mktemp("airbend-home")))
