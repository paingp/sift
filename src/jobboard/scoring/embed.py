"""Embedding similarity (SPEC.md §4.2 stage 5, §6.3).

Ollama POST /api/embed against profile documents, cosine similarity via
plain NumPy brute force (no vector database — not worth it at this scale).
Cached in the embeddings table by content_hash; re-embed only on change.
"""
