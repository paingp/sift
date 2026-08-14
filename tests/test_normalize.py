"""normalize.py tests: html.unescape + markdown conversion, and that
Greenhouse records always land as date_precision='updated_only'.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jobboard.adapters.base import RawPosting
from jobboard.config import CompanyConfig
from jobboard.normalize import DATE_PRECISION_UPDATED_ONLY, normalize

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "greenhouse_board.json"
BOARD_JSON = json.loads(FIXTURE_PATH.read_text())
WARP = CompanyConfig(name="Warp", ats="greenhouse", slug="warp")


def _posting(raw: dict) -> RawPosting:
    return RawPosting(
        source="greenhouse",
        source_job_id=str(raw["id"]),
        raw=raw,
        fetched_at=datetime(2026, 8, 12, tzinfo=None),
    )


def test_unescapes_html_and_converts_content_to_markdown() -> None:
    raw = dict(BOARD_JSON["jobs"][0])
    raw["content"] = "&lt;p&gt;Hello &lt;strong&gt;World&lt;/strong&gt;&lt;/p&gt;"

    job = normalize(_posting(raw), WARP)

    assert job.description_md is not None
    assert "&lt;" not in job.description_md
    assert "&gt;" not in job.description_md
    assert "Hello" in job.description_md
    assert "**World**" in job.description_md


def test_greenhouse_records_get_updated_only_precision() -> None:
    raw = BOARD_JSON["jobs"][0]

    job = normalize(_posting(raw), WARP)

    assert job.date_precision == DATE_PRECISION_UPDATED_ONLY
    expected = datetime.fromisoformat(raw["updated_at"]).astimezone(UTC).replace(tzinfo=None)
    assert job.source_posted_at == expected


def test_apply_url_and_title_pass_through() -> None:
    raw = BOARD_JSON["jobs"][0]

    job = normalize(_posting(raw), WARP)

    assert job.apply_url == raw["absolute_url"]
    assert job.title == raw["title"]
    assert job.source_job_id == str(raw["id"])
    assert job.canonical_key
