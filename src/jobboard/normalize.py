"""RawPosting -> Job normalization (SPEC.md §4.2 stage 2, §5.1).

One canonical shape for every source. Implements the date-freeze rule for
'updated_only' sources (SPEC.md §5.3 rule 3): once stored, source_posted_at
must never move later.
"""
