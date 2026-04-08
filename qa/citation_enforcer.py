"""qa/citation_enforcer.py

Validates that every LLM answer contains at least one citation in the
mandatory format:  [source: <section_id> | <doc_url>]

Raises CitationError for answers that contain no valid citations.
"""
from __future__ import annotations

import re
from typing import Dict, List


CITATION_PATTERN = re.compile(
    r"\[source:\s*(?P<section_id>[^|\]]+)\|\s*(?P<doc_url>https?://[^\]]+)\]"
)


class CitationError(ValueError):
    """Raised when an answer has no valid citations."""


class CitationEnforcer:
    """Parse and validate structured citations in LLM-generated answers."""

    def extract(self, text: str) -> List[Dict[str, str]]:
        """Return all citations found in *text* as a list of dicts.

        Each dict has keys: 'section_id' and 'doc_url'.
        """
        citations = []
        for match in CITATION_PATTERN.finditer(text):
            citations.append(
                {
                    "section_id": match.group("section_id").strip(),
                    "doc_url": match.group("doc_url").strip(),
                }
            )
        return citations

    def validate(self, text: str) -> None:
        """Raise CitationError if *text* contains no valid citations."""
        citations = self.extract(text)
        if not citations:
            raise CitationError(
                "Answer contains no citations. "
                "Expected at least one [source: <section_id> | <doc_url>] block."
            )

    def strip_citations(self, text: str) -> str:
        """Return *text* with all citation blocks removed."""
        return CITATION_PATTERN.sub("", text).strip()

    def format_citations(self, citations: List[Dict[str, str]]) -> str:
        """Return a formatted citations block for display."""
        lines = []
        for i, c in enumerate(citations, start=1):
            lines.append(f"[{i}] {c['section_id']} — {c['doc_url']}")
        return "\n".join(lines)

