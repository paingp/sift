"""SourceAdapter Protocol and RawPosting model.

Implemented in Phase 1 (SPEC.md §4.2 stage 1, §4.3). Every adapter returns
list[RawPosting]; a failing adapter must record status='partial' on the run
and never abort the batch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from jobboard.config import CompanyConfig


class RawPosting(BaseModel):
    """One posting exactly as returned by a source, before normalization."""

    source: str
    source_job_id: str
    raw: dict[str, Any]
    fetched_at: datetime


class SourceAdapter(Protocol):
    """Implemented once per source (SPEC.md §3.2/§3.3)."""

    name: str

    def fetch(self, config: CompanyConfig) -> list[RawPosting]:
        """Fetch every posting currently on the source for this company."""
        ...
