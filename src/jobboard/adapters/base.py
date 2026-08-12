"""SourceAdapter Protocol and RawPosting model.

Implemented in Phase 1 (SPEC.md §4.2 stage 1, §4.3). Every adapter returns
list[RawPosting]; a failing adapter must record status='partial' on the run
and never abort the batch.
"""
