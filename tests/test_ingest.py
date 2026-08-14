"""End-to-end ingest tests: service.ingest() against a migrated temp SQLite
DB, with the Greenhouse HTTP call mocked by pytest-httpx. Covers upsert
idempotency and the date-freeze rule (SPEC.md §5.3 rule 3).
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from pytest_httpx import HTTPXMock
from sqlalchemy import select

from alembic import command
from jobboard import service
from jobboard.store.db import get_session
from jobboard.store.models import Job, Run

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "greenhouse_board.json"
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/warp/jobs?content=true"


def _board() -> dict:
    return copy.deepcopy(json.loads(FIXTURE_PATH.read_text()))


@pytest.fixture
def migrated_db_with_companies() -> Iterator[None]:
    # isolated_env (autouse, conftest.py) already pointed JOBBOARD_CONFIG_DIR
    # and JOBBOARD_DB at an isolated tmp_path for this test.
    from jobboard.config import get_settings

    config_dir = get_settings().config_dir
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "config.yaml", config_dir / "config.yaml")
    (config_dir / "companies.yaml").write_text(
        "companies:\n  - name: Warp\n    ats: greenhouse\n    slug: warp\n    tags: []\n"
    )

    alembic_cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")
    yield


def test_ingest_twice_is_idempotent(
    migrated_db_with_companies: None, httpx_mock: HTTPXMock
) -> None:
    board = _board()
    httpx_mock.add_response(url=BOARD_URL, json=board)
    httpx_mock.add_response(url=BOARD_URL, json=board)

    first = service.ingest("greenhouse", "warp")
    assert first.status == "ok"
    assert first.fetched == len(board["jobs"])
    assert first.new == len(board["jobs"])
    assert first.updated == 0

    second = service.ingest("greenhouse", "warp")
    assert second.status == "ok"
    assert second.new == 0
    assert second.updated == 0

    with get_session() as session:
        jobs = session.execute(select(Job)).scalars().all()
        assert len(jobs) == len(board["jobs"])
        runs = session.execute(select(Run)).scalars().all()
        assert len(runs) == 2


def test_date_freeze_keeps_earliest_source_posted_at(
    migrated_db_with_companies: None, httpx_mock: HTTPXMock
) -> None:
    first_board = _board()
    target = first_board["jobs"][0]
    original_updated_at = target["updated_at"]

    httpx_mock.add_response(url=BOARD_URL, json=first_board)
    service.ingest("greenhouse", "warp")

    edited_board = _board()
    edited_target = edited_board["jobs"][0]
    assert edited_target["id"] == target["id"]
    edited_target["updated_at"] = "2030-01-01T00:00:00-04:00"
    edited_target["content"] = edited_target["content"] + "&lt;p&gt;typo fix&lt;/p&gt;"

    httpx_mock.add_response(url=BOARD_URL, json=edited_board)
    result = service.ingest("greenhouse", "warp")

    assert result.updated == 1

    with get_session() as session:
        job = session.execute(
            select(Job).where(Job.source_job_id == str(target["id"]))
        ).scalar_one()

        # content changed, so the row was updated...
        assert "typo fix" in (job.description_md or "")
        # ...but the recorded post date must stay frozen at the earliest
        # value ever observed, never jump forward to the edit's updated_at.
        expected = datetime.fromisoformat(original_updated_at).astimezone(UTC).replace(tzinfo=None)
        assert job.source_posted_at == expected
        assert job.date_precision == "updated_only"
