"""Greenhouse adapter (SPEC.md §3.2).

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
One request returns the whole board, no pagination. `content` is HTML and
HTML-escaped. Only `updated_at` is exposed, not first-published, so records
from this source get date_precision='updated_only'.
"""
