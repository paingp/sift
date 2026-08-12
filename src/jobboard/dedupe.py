"""Dedupe: within-source by source_job_id, cross-source by canonical_key.

canonical_key = sha1(normalize_company + "|" + normalize_title + "|" +
normalize_location), per SPEC.md §5.2. Backbone of FR-8 (applied jobs never
resurface).
"""
