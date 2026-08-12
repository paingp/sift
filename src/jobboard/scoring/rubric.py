"""LLM rubric scoring (SPEC.md §4.2 stage 6, §6.4). Owns SCORER_VERSION.

Ollama /api/chat with structured JSON-schema output, top-N candidates only.
score_total is always summed in Python from bounded subscores, never taken
from the model. evidence strings are validated as verbatim profile
substrings (the hallucination check).
"""
