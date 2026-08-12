"""Calibration harness (SPEC.md §6.5).

Scores tests/labeled_jobs.jsonl with the current SCORER_VERSION and reports
Spearman rho, mean absolute error, and score distribution. Target rho > 0.7.
"""
