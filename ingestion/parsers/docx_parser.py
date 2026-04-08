"""ingestion/parsers/docx_parser.py

DOCX parser using python-docx.
Maps Heading 1/2/3 styles to section boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

try:
    from docx import Document as DocxDocument
except ImportError:  # pragma: no cover
    DocxDocument = None  # type: ignore


@dataclass
class Section:
    section_id: str
    title: str
    content: str


class DocxParser:
    """Parse a DOCX file into sections based on heading styles."""

    HEADING_STYLES = {"Heading 1", "Heading 2", "Heading 3"}

    def parse(self, path: str) -> List[Section]:
        if DocxDocument is None:
            raise ImportError("python-docx is required: pip install python-docx")

        doc = DocxDocument(path)
        sections: List[Section] = []
        current_title = "Introduction"
        current_lines: List[str] = []

        for para in doc.paragraphs:
            if para.style.name in self.HEADING_STYLES:
                if current_lines:
                    sections.append(
                        Section(
                            section_id=self._slugify(current_title),
                            title=current_title,
                            content="\n".join(current_lines),
                        )
                    )
                current_title = para.text.strip() or current_title
                current_lines = []
            else:
                text = para.text.strip()
                if text:
                    current_lines.append(text)

        if current_lines:
            sections.append(
                Section(
                    section_id=self._slugify(current_title),
                    title=current_title,
                    content="\n".join(current_lines),
                )
            )
        return sections

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug[:64]

