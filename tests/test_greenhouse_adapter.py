"""Adapter-level tests: parsing and retry behavior, offline against the
recorded fixture in tests/fixtures/greenhouse_board.json. Never hits the
live API (CLAUDE.md "Adapter tests run offline").
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from jobboard.adapters.greenhouse import BOARD_URL, GreenhouseAdapter
from jobboard.config import CompanyConfig

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "greenhouse_board.json"
BOARD_JSON = json.loads(FIXTURE_PATH.read_text())
WARP = CompanyConfig(name="Warp", ats="greenhouse", slug="warp")


def test_fetch_parses_fixture_without_pagination(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=BOARD_URL.format(slug="warp") + "?content=true", json=BOARD_JSON)

    postings = GreenhouseAdapter().fetch(WARP)

    assert len(postings) == len(BOARD_JSON["jobs"])
    assert {p.source for p in postings} == {"greenhouse"}
    assert {p.source_job_id for p in postings} == {str(j["id"]) for j in BOARD_JSON["jobs"]}
    # the adapter hands back the raw job dict untouched; unescaping/parsing
    # of `content` happens in normalize.py, not here.
    first = next(p for p in postings if p.source_job_id == str(BOARD_JSON["jobs"][0]["id"]))
    assert first.raw["content"] == BOARD_JSON["jobs"][0]["content"]
    assert "&lt;" in first.raw["content"]


def test_fetch_sends_descriptive_user_agent(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=BOARD_URL.format(slug="warp") + "?content=true", json=BOARD_JSON)

    GreenhouseAdapter().fetch(WARP)

    [request] = httpx_mock.get_requests()
    assert "jobboard" in request.headers["User-Agent"]


def test_fetch_retries_on_5xx_then_succeeds(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=502)
    httpx_mock.add_response(status_code=502)
    httpx_mock.add_response(json=BOARD_JSON)

    postings = GreenhouseAdapter().fetch(WARP)

    assert len(postings) == len(BOARD_JSON["jobs"])
    assert len(httpx_mock.get_requests()) == 3


def test_fetch_does_not_retry_on_4xx(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=404)

    with pytest.raises(httpx.HTTPStatusError):
        GreenhouseAdapter().fetch(WARP)

    assert len(httpx_mock.get_requests()) == 1


def test_fetch_gives_up_after_repeated_5xx(httpx_mock: HTTPXMock) -> None:
    for _ in range(4):
        httpx_mock.add_response(status_code=503)

    with pytest.raises(httpx.HTTPStatusError):
        GreenhouseAdapter().fetch(WARP)

    assert len(httpx_mock.get_requests()) == 4
