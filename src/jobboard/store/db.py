"""Engine/session management.

Reads the database path from config/env ($JOBBOARD_DB), never hardcodes it,
so dev and scheduled runs stay separated (CLAUDE.md "Data handling").
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from jobboard.config import get_settings


def database_path() -> Path:
    return get_settings().database_path


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


def get_session() -> Session:
    return Session(get_engine())
