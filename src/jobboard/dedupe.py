"""Dedupe: within-source by source_job_id, cross-source by canonical_key.

canonical_key = sha1(normalize_company + "|" + normalize_title + "|" +
normalize_location), per SPEC.md §5.2. Backbone of FR-8 (applied jobs never
resurface).

The normalizers here are a first pass sufficient to compute a stable key for
a single source (Phase 1). Phase 2 extends normalize_location with real
metro-area mapping and adds the extensive normalizer test suite called for
in BUILD_GUIDE.md.
"""

from __future__ import annotations

import hashlib
import re

_COMPANY_SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|gmbh)\b")
_COMPANY_PUNCTUATION = re.compile(r"[,.]")
_REQ_ID = re.compile(r"\(?\b[a-z]{0,3}-?\d{3,7}\b\)?", re.IGNORECASE)
_BRACKETS = re.compile(r"[()\[\]]")
_WHITESPACE = re.compile(r"\s+")
_SENIORITY_ABBREVIATIONS = {"sr": "senior", "jr": "junior"}


def normalize_company(name: str) -> str:
    text = name.strip().lower()
    text = _COMPANY_PUNCTUATION.sub("", text)
    text = _COMPANY_SUFFIXES.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    text = title.strip().lower()
    text = _REQ_ID.sub(" ", text)
    text = _BRACKETS.sub(" ", text)
    words = [w.rstrip(".,") for w in text.split()]
    words = [_SENIORITY_ABBREVIATIONS.get(w, w) for w in words if w]
    return " ".join(words)


def normalize_location(location: str) -> str:
    text = location.strip().lower()
    text = _COMPANY_PUNCTUATION.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def canonical_key(company: str, title: str, location: str) -> str:
    payload = "|".join(
        (normalize_company(company), normalize_title(title), normalize_location(location))
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
