"""Adzuna adapter (SPEC.md §3.3, Tier 2).

developer.adzuna.com — app_id + app_key from environment. Free tier caps at
~1,000 calls/month; cap queries per run and log usage. `created` field ->
date_precision='exact' (aggregator's ingest time, exact-ish).
"""
