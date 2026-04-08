"""ingestion/chunker.py

Splits oversized sections into overlapping token-window chunks.
Used when a section exceeds MAX_TOKENS for Vertex AI Search.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

MAX_TOKENS: int = 500  # Vertex AI Search recommended max per chunk
OVERLAP_TOKENS: int = 50


@dataclass
class Chunk:
    chunk_id: str
    section_id: str
    title: str
    content: str
    chunk_index: int = 0


class SectionChunker:
    """Split sections into Chunk objects respecting MAX_TOKENS."""

    def __init__(self, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP_TOKENS):
        self.max_tokens = max_tokens
        self.overlap = overlap

    def chunk(self, sections: List[Any]) -> List[Chunk]:
        """Return a flat list of Chunk objects from all sections."""
        chunks: List[Chunk] = []
        for section in sections:
            section_id = getattr(section, "section_id", "unknown")
            title = getattr(section, "title", "")
            content = getattr(section, "content", "")
            words = content.split()

            if len(words) <= self.max_tokens:
                chunks.append(
                    Chunk(
                        chunk_id=f"{section_id}-0",
                        section_id=section_id,
                        title=title,
                        content=content,
                        chunk_index=0,
                    )
                )
            else:
                sub_chunks = self._sliding_window(words)
                for idx, window in enumerate(sub_chunks):
                    chunks.append(
                        Chunk(
                            chunk_id=f"{section_id}-{idx}",
                            section_id=section_id,
                            title=f"{title} (part {idx + 1})",
                            content=" ".join(window),
                            chunk_index=idx,
                        )
                    )
        return chunks

    def _sliding_window(self, words: List[str]) -> List[List[str]]:
        windows: List[List[str]] = []
        start = 0
        while start < len(words):
            end = start + self.max_tokens
            windows.append(words[start:end])
            if end >= len(words):
                break
            start = end - self.overlap
        return windows

