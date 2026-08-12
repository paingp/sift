"""initial schema

Revision ID: 5069806a4e8d
Revises:
Create Date: 2026-08-11 17:17:22.927420

Creates every table in SPEC.md §5.1, verbatim.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5069806a4e8d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE companies (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          canonical_name TEXT NOT NULL UNIQUE,   -- lowercased, suffixes stripped
          ats TEXT,                              -- greenhouse | lever | ashby | ...
          ats_slug TEXT,
          careers_url TEXT,
          tags TEXT,                             -- JSON array: sector, size, "dream", ...
          blocked INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE jobs (
          id INTEGER PRIMARY KEY,
          company_id INTEGER NOT NULL REFERENCES companies(id),
          source TEXT NOT NULL,                  -- adapter name
          source_job_id TEXT NOT NULL,
          canonical_key TEXT NOT NULL,           -- see SPEC.md §5.2
          title TEXT NOT NULL,
          location_raw TEXT,
          location_normalized TEXT,
          remote_type TEXT,                      -- onsite | hybrid | remote | unknown
          employment_type TEXT,
          description_md TEXT,
          apply_url TEXT NOT NULL,               -- canonical company/ATS URL, never a redirect
          salary_min INTEGER, salary_max INTEGER, salary_currency TEXT,
          source_posted_at TIMESTAMP,            -- from the source, may be NULL
          date_precision TEXT NOT NULL,          -- exact | updated_only | inferred  (§5.3)
          first_seen_at TIMESTAMP NOT NULL,
          last_seen_at  TIMESTAMP NOT NULL,
          content_hash TEXT NOT NULL,            -- change detection
          closed_at TIMESTAMP,                   -- set when it stops appearing in the feed
          raw_json TEXT NOT NULL,
          UNIQUE (source, source_job_id)
        )
    """)
    op.execute("CREATE INDEX idx_jobs_canonical ON jobs(canonical_key)")
    op.execute(
        "CREATE INDEX idx_jobs_sort ON jobs(COALESCE(source_posted_at, first_seen_at) DESC)"
    )

    op.execute("""
        CREATE TABLE job_scores (
          id INTEGER PRIMARY KEY,
          job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          scorer_version TEXT NOT NULL,          -- "v3:qwen2.5:14b:rubric-2026-08"
          embedding_similarity REAL,
          score_total INTEGER NOT NULL,          -- 0-100
          subscores TEXT NOT NULL,               -- JSON: must_have, nice_to_have, seniority, domain, logistics
          evidence TEXT,                         -- JSON: resume lines supporting the score
          gaps TEXT,                             -- JSON: requirements you don't meet
          verdict TEXT,                          -- strong | good | stretch | poor
          scored_at TIMESTAMP NOT NULL,
          UNIQUE (job_id, scorer_version)
        )
    """)

    op.execute("""
        CREATE TABLE applications (
          id INTEGER PRIMARY KEY,
          canonical_key TEXT NOT NULL UNIQUE,    -- keyed to the ROLE, not the posting row (§5.4)
          job_id INTEGER REFERENCES jobs(id),    -- the posting that triggered it
          status TEXT NOT NULL,                  -- interested|applied|screening|interview|offer|rejected|withdrawn|dismissed
          applied_at TIMESTAMP,
          notes TEXT,
          updated_at TIMESTAMP NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY,
          started_at TIMESTAMP, finished_at TIMESTAMP,
          source TEXT, status TEXT,              -- ok | partial | failed
          fetched INTEGER, new INTEGER, updated INTEGER, closed INTEGER,
          error TEXT
        )
    """)

    op.execute("""
        CREATE TABLE embeddings (
          content_hash TEXT PRIMARY KEY,
          model TEXT NOT NULL,
          vector BLOB NOT NULL                   -- float32 packed
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE embeddings")
    op.execute("DROP TABLE runs")
    op.execute("DROP TABLE applications")
    op.execute("DROP TABLE job_scores")
    op.execute("DROP INDEX idx_jobs_sort")
    op.execute("DROP INDEX idx_jobs_canonical")
    op.execute("DROP TABLE jobs")
    op.execute("DROP TABLE companies")
