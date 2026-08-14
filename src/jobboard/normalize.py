"""RawPosting -> Job normalization (SPEC.md §4.2 stage 2, §5.1).

One canonical shape for every source. Implements the date-freeze rule for
'updated_only' sources (SPEC.md §5.3 rule 3): once stored, source_posted_at
must never move later. That freeze happens in store/repository.py at upsert
time — this module only computes what a source says *right now*.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from markdownify import markdownify
from pydantic import BaseModel

from jobboard.adapters.base import RawPosting
from jobboard.config import CompanyConfig
from jobboard.dedupe import canonical_key

DATE_PRECISION_EXACT = "exact"
DATE_PRECISION_UPDATED_ONLY = "updated_only"
DATE_PRECISION_INFERRED = "inferred"


class NormalizedJob(BaseModel):
    """Source-agnostic shape matching the `jobs` table (SPEC.md §5.1), minus
    the columns the store assigns: id, company_id, first_seen_at,
    last_seen_at, closed_at.
    """

    source: str
    source_job_id: str
    canonical_key: str
    title: str
    location_raw: str | None
    location_normalized: str | None
    remote_type: str | None
    employment_type: str | None
    description_md: str | None
    apply_url: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    source_posted_at: datetime | None
    date_precision: str
    content_hash: str
    raw_json: str


def _content_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _infer_remote_type(location_raw: str | None) -> str | None:
    if not location_raw:
        return None
    return "remote" if "remote" in location_raw.lower() else "unknown"


def normalize_greenhouse(posting: RawPosting, company: CompanyConfig) -> NormalizedJob:
    raw = posting.raw
    title = str(raw["title"])
    location_raw = (raw.get("location") or {}).get("name")
    description_html = html.unescape(raw.get("content") or "")
    description_md = markdownify(description_html, heading_style="ATX").strip() or None
    # Store as naive UTC: SQLite drops tzinfo on round-trip, so converting
    # here (rather than downstream) keeps every source_posted_at comparison
    # — including the date-freeze rule in repository.py — apples-to-apples.
    source_posted_at = (
        datetime.fromisoformat(raw["updated_at"]).astimezone(UTC).replace(tzinfo=None)
    )

    return NormalizedJob(
        source=posting.source,
        source_job_id=posting.source_job_id,
        canonical_key=canonical_key(company.name, title, location_raw or ""),
        title=title,
        location_raw=location_raw,
        location_normalized=location_raw.strip().lower() if location_raw else None,
        remote_type=_infer_remote_type(location_raw),
        employment_type=None,
        description_md=description_md,
        apply_url=str(raw["absolute_url"]),
        source_posted_at=source_posted_at,
        date_precision=DATE_PRECISION_UPDATED_ONLY,
        content_hash=_content_hash(raw),
        raw_json=json.dumps(raw, sort_keys=True, default=str),
    )


_NORMALIZERS: dict[str, Callable[[RawPosting, CompanyConfig], NormalizedJob]] = {
    "greenhouse": normalize_greenhouse,
}


def normalize(posting: RawPosting, company: CompanyConfig) -> NormalizedJob:
    try:
        normalizer = _NORMALIZERS[posting.source]
    except KeyError:
        raise ValueError(f"no normalizer registered for source {posting.source!r}") from None
    return normalizer(posting, company)
