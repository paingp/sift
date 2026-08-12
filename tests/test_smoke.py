"""Phase 0 smoke test: the app boots, config loads, migrations apply, and
`jobs doctor` reports what it finds. No adapter or scoring logic exists yet.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from alembic.config import Config as AlembicConfig
from typer.testing import CliRunner

from alembic import command
from jobboard.cli import app
from jobboard.config import ConfigError, load_app_config

REPO_ROOT = Path(__file__).resolve().parents[1]

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "doctor" in result.output


def test_load_app_config_reads_committed_config() -> None:
    cfg = load_app_config(REPO_ROOT / "config" / "config.yaml")
    assert cfg.scoring.top_n == 40
    assert cfg.sources["greenhouse"].enabled is True


def test_load_app_config_missing_file_raises_config_error(tmp_path: Path) -> None:
    try:
        load_app_config(tmp_path / "nope.yaml")
    except ConfigError:
        pass
    else:
        raise AssertionError("expected ConfigError for a missing config file")


def test_doctor_runs_end_to_end(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(REPO_ROOT / "config" / "config.yaml", config_dir / "config.yaml")
    monkeypatch.setenv("JOBBOARD_CONFIG_DIR", str(config_dir))

    from jobboard.config import get_settings
    from jobboard.store.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()

    alembic_cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")

    result = runner.invoke(app, ["doctor"])
    assert "database" in result.output
    assert "migrations" in result.output
    assert "OK" in result.output
    # database and migrations must be green regardless of whether a local
    # Ollama happens to be reachable in this environment.
    assert "database    OK" in result.output
    assert "migrations  OK" in result.output
