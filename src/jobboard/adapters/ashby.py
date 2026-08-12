"""Ashby adapter (SPEC.md §3.2).

GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
Has `publishedAt` -> date_precision='exact'. Best structured compensation
data of the Tier-1 sources; parse into salary_min/max/currency.
"""
