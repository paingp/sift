"""Lever adapter (SPEC.md §3.2).

GET https://api.lever.co/v0/postings/{company}?mode=json
Returns a flat JSON array, no wrapper object. `createdAt` is epoch millis,
a real creation timestamp -> date_precision='exact'. EU-resident boards live
at api.eu.lever.co.
"""
