"""Repository functions: typed reads/writes over the SQLAlchemy models.

Implemented alongside each pipeline stage (ingest, score, apply/dismiss) in
later phases. service.py is the only caller.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobboard.config import CompanyConfig
from jobboard.dedupe import normalize_company
from jobboard.normalize import DATE_PRECISION_UPDATED_ONLY, NormalizedJob
from jobboard.store.models import Company, Job, Run


class UpsertResult(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def get_or_create_company(session: Session, company: CompanyConfig) -> Company:
    canonical_name = normalize_company(company.name)
    existing = session.execute(
        select(Company).where(Company.canonical_name == canonical_name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = Company(
        name=company.name,
        canonical_name=canonical_name,
        ats=company.ats,
        ats_slug=company.slug,
        careers_url=None,
        tags=json.dumps(company.tags),
        blocked=0,
    )
    session.add(row)
    session.flush()
    return row


def _frozen_source_posted_at(
    existing: Job, normalized: NormalizedJob
) -> datetime | None:
    """SPEC.md §5.3 rule 3: for 'updated_only' records, never let
    source_posted_at move later than the earliest value ever observed.
    """
    if (
        normalized.date_precision == DATE_PRECISION_UPDATED_ONLY
        and existing.date_precision == DATE_PRECISION_UPDATED_ONLY
        and existing.source_posted_at is not None
    ):
        if normalized.source_posted_at is None:
            return existing.source_posted_at
        return min(existing.source_posted_at, normalized.source_posted_at)
    return normalized.source_posted_at


def upsert_job(
    session: Session, normalized: NormalizedJob, company_id: int, now: datetime
) -> tuple[Job, UpsertResult]:
    existing = session.execute(
        select(Job).where(
            Job.source == normalized.source,
            Job.source_job_id == normalized.source_job_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        job = Job(
            company_id=company_id,
            source=normalized.source,
            source_job_id=normalized.source_job_id,
            canonical_key=normalized.canonical_key,
            title=normalized.title,
            location_raw=normalized.location_raw,
            location_normalized=normalized.location_normalized,
            remote_type=normalized.remote_type,
            employment_type=normalized.employment_type,
            description_md=normalized.description_md,
            apply_url=normalized.apply_url,
            salary_min=normalized.salary_min,
            salary_max=normalized.salary_max,
            salary_currency=normalized.salary_currency,
            source_posted_at=normalized.source_posted_at,
            date_precision=normalized.date_precision,
            first_seen_at=now,
            last_seen_at=now,
            content_hash=normalized.content_hash,
            closed_at=None,
            raw_json=normalized.raw_json,
        )
        session.add(job)
        session.flush()
        return job, UpsertResult.NEW

    existing.last_seen_at = now
    existing.closed_at = None
    existing.source_posted_at = _frozen_source_posted_at(existing, normalized)

    if existing.content_hash == normalized.content_hash:
        return existing, UpsertResult.UNCHANGED

    existing.content_hash = normalized.content_hash
    existing.canonical_key = normalized.canonical_key
    existing.title = normalized.title
    existing.location_raw = normalized.location_raw
    existing.location_normalized = normalized.location_normalized
    existing.remote_type = normalized.remote_type
    existing.employment_type = normalized.employment_type
    existing.description_md = normalized.description_md
    existing.apply_url = normalized.apply_url
    existing.salary_min = normalized.salary_min
    existing.salary_max = normalized.salary_max
    existing.salary_currency = normalized.salary_currency
    existing.raw_json = normalized.raw_json
    return existing, UpsertResult.UPDATED


def record_run(
    session: Session,
    *,
    source: str | None,
    status: str,
    fetched: int,
    new: int,
    updated: int,
    closed: int,
    error: str | None,
    started_at: datetime,
    finished_at: datetime,
) -> Run:
    run = Run(
        started_at=started_at,
        finished_at=finished_at,
        source=source,
        status=status,
        fetched=fetched,
        new=new,
        updated=updated,
        closed=closed,
        error=error,
    )
    session.add(run)
    session.flush()
    return run
