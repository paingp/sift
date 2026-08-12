"""SQLAlchemy ORM models mirroring SPEC.md §5.1, verbatim.

These are the schema of record; the Alembic migration in
alembic/versions/ creates them. Business logic (upserts, state machines,
queries) lives in repository.py / service.py, not here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    canonical_name: Mapped[str] = mapped_column(unique=True)
    ats: Mapped[str | None]
    ats_slug: Mapped[str | None]
    careers_url: Mapped[str | None]
    tags: Mapped[str | None]
    blocked: Mapped[int] = mapped_column(default=0)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id"),
        Index("idx_jobs_canonical", "canonical_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    source: Mapped[str]
    source_job_id: Mapped[str]
    canonical_key: Mapped[str]
    title: Mapped[str]
    location_raw: Mapped[str | None]
    location_normalized: Mapped[str | None]
    remote_type: Mapped[str | None]
    employment_type: Mapped[str | None]
    description_md: Mapped[str | None]
    apply_url: Mapped[str]
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    salary_currency: Mapped[str | None]
    source_posted_at: Mapped[datetime | None]
    date_precision: Mapped[str]
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    content_hash: Mapped[str]
    closed_at: Mapped[datetime | None]
    raw_json: Mapped[str]


class JobScore(Base):
    __tablename__ = "job_scores"
    __table_args__ = (UniqueConstraint("job_id", "scorer_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    scorer_version: Mapped[str]
    embedding_similarity: Mapped[float | None]
    score_total: Mapped[int]
    subscores: Mapped[str]
    evidence: Mapped[str | None]
    gaps: Mapped[str | None]
    verdict: Mapped[str | None]
    scored_at: Mapped[datetime]


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(unique=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    status: Mapped[str]
    applied_at: Mapped[datetime | None]
    notes: Mapped[str | None]
    updated_at: Mapped[datetime]


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    source: Mapped[str | None]
    status: Mapped[str | None] = mapped_column(
        CheckConstraint("status IN ('ok', 'partial', 'failed')", name="ck_runs_status")
    )
    fetched: Mapped[int | None]
    new: Mapped[int | None]
    updated: Mapped[int | None]
    closed: Mapped[int | None]
    error: Mapped[str | None]


class Embedding(Base):
    __tablename__ = "embeddings"

    content_hash: Mapped[str] = mapped_column(primary_key=True)
    model: Mapped[str]
    vector: Mapped[bytes]
