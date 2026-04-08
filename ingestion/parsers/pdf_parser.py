"""ingestion/parsers/pdf_parser.py

PDF document parser using PyMuPDF (fitz).
Extracts text page-by-page and splits into heading-based sections.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore


@dataclass
class Section:
    section_id: str
    title: str
    content: str
    page_start: int = 0
    page_end: int = 0
    tokens: List[str] = field(default_factory=list)


class PDFParser:
    """Parse a PDF file into a list of Section objects."""

    # Heading pattern: lines that are ALL-CAPS or start with a digit+dot
    HEADING_RE = re.compile(r"^(?:[A-Z][A-Z\s]{4,}|\d+\.\s+\S.*)$")

    def parse(self, path: str) -> List[Section]:
        """Return a list of sections extracted from *path*."""
        if fitz is None:
            raise ImportError("PyMuPDF is required: pip install pymupdf")

        doc = fitz.open(path)
        sections: List[Section] = []
        current_title = "Introduction"
        current_pages: List[str] = []
        page_start = 0

        for page_num, page in enumerate(doc):
            text = page.get_text()  # type: ignore[attr-defined]
            lines = text.splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if self.HEADING_RE.match(line) and len(line) < 120:
                    # Flush previous section
                    if current_pages:
                        sections.append(
                            Section(
                                section_id=self._slugify(current_title),
                                title=current_title,
                                content="\n".join(current_pages),
                                page_start=page_start,
                                page_end=page_num,
                            )
                        )
                    current_title = line
                    current_pages = []
                    page_start = page_num
                else:
                    current_pages.append(line)

        # Flush last section
        if current_pages:
            sections.append(
                Section(
                    section_id=self._slugify(current_title),
                    title=current_title,
                    content="\n".join(current_pages),
                    page_start=page_start,
                    page_end=len(doc) - 1,
                )
            )
        doc.close()
        return sections

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _slugify(text: str) -> str:
        """Convert heading text to a URL-safe section_id."""
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug[:64]

