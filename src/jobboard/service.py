"""The only business-logic entrypoint.

The CLI, the FastAPI routes, and the MCP server are thin adapters over this
module. No SQL in a route handler, no business logic in the CLI — every
frontend calls functions defined here.

Most of this module is stubbed until its corresponding build phase
(BUILD_GUIDE.md). `run_doctor()` is implemented now because Phase 0 needs a
real health check.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from jobboard.config import ConfigError, get_settings, load_app_config, load_companies, load_profile
from jobboard.store.db import get_engine


@dataclass
class HealthCheck:
    name: str
    status: str  # ok | warn | fail
    detail: str


def _check_database() -> HealthCheck:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            tables = inspect(conn).get_table_names()
        db_path = get_settings().database_path
        if "jobs" not in tables:
            return HealthCheck(
                "database", "fail", f"{db_path}: no 'jobs' table (run alembic upgrade head)"
            )
        return HealthCheck("database", "ok", str(db_path))
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator, not swallowed
        return HealthCheck("database", "fail", f"unreachable: {exc}")


def _check_migrations() -> HealthCheck:
    try:
        repo_root = Path(__file__).resolve().parents[2]
        alembic_cfg = AlembicConfig(str(repo_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(repo_root / "alembic"))
        script = ScriptDirectory.from_config(alembic_cfg)
        head = script.get_current_head()

        engine = get_engine()
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()

        if current == head:
            return HealthCheck("migrations", "ok", f"at head ({current})")
        return HealthCheck(
            "migrations", "fail", f"current={current} head={head} — run alembic upgrade head"
        )
    except Exception as exc:  # noqa: BLE001
        return HealthCheck("migrations", "fail", f"could not determine revision: {exc}")


def _check_ollama() -> HealthCheck:
    host = get_settings().ollama_host
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m.get("name") for m in resp.json().get("models", [])]
        return HealthCheck("ollama", "ok", f"{host} ({len(models)} model(s))")
    except Exception as exc:  # noqa: BLE001
        return HealthCheck("ollama", "warn", f"{host} unreachable: {exc}")


def _check_config() -> HealthCheck:
    try:
        load_app_config()
    except ConfigError as exc:
        return HealthCheck("config", "fail", str(exc))

    notes = []
    for label, loader in (("companies.yaml", load_companies), ("profile.yaml", load_profile)):
        try:
            loader()
        except ConfigError:
            notes.append(f"{label} not set up yet")

    detail = "config.yaml valid" if not notes else "config.yaml valid; " + "; ".join(notes)
    status = "ok" if not notes else "warn"
    return HealthCheck("config", status, detail)


def run_doctor() -> list[HealthCheck]:
    return [
        _check_config(),
        _check_database(),
        _check_migrations(),
        _check_ollama(),
    ]
