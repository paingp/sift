"""Shared test fixtures. Every test runs against an isolated tmp DB/config —
never touch data/jobs.db or a developer's real config from the suite.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JOBBOARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("JOBBOARD_CONFIG_DIR", str(tmp_path / "config"))
    from jobboard.config import get_settings
    from jobboard.store.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
