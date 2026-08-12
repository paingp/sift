"""Hard filters (SPEC.md §4.2 stage 4, §6.2). Pure functions, no I/O, no models.

Runs before any model call and rejects with a logged reason: max_age_days,
location allowlist, title/company blocklist, seniority band, salary floor
(only when salary data exists), work-auth/clearance keywords.
"""
