"""Greenhouse adapter (SPEC.md §3.2).

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
One request returns the whole board, no pagination. `content` is HTML and
HTML-escaped. Only `updated_at` is exposed, not first-published, so records
from this source get date_precision='updated_only'.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from jobboard.adapters.base import RawPosting
from jobboard.config import CompanyConfig

NAME: Final = "greenhouse"

USER_AGENT: Final = (
    "jobboard/0.1 (+personal job board; single user; contact: phksub@gmail.com)"
)
TIMEOUT: Final = 30.0
BOARD_URL: Final = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 5xx and timeouts only. A 4xx means our request is wrong, not
    the server — retrying it would just waste time and hammer the endpoint.
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def _fetch_board(slug: str, client: httpx.Client) -> dict[str, Any]:
    response = client.get(
        BOARD_URL.format(slug=slug),
        params={"content": "true"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


class GreenhouseAdapter:
    name = NAME

    def fetch(self, config: CompanyConfig) -> list[RawPosting]:
        fetched_at = datetime.now(UTC)
        with httpx.Client() as client:
            payload = _fetch_board(config.slug, client)

        return [
            RawPosting(
                source=self.name,
                source_job_id=str(job["id"]),
                raw=job,
                fetched_at=fetched_at,
            )
            for job in payload.get("jobs", [])
        ]
