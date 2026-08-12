"""Personal, single-user job board.

Ingests postings from public ATS APIs, scores them against a resume with a
local Ollama model, and hides anything already applied to or dismissed.
"""
