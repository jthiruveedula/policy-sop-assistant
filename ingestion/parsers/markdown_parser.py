"""ingestion/parsers/markdown_parser.py

Markdown parser: splits on ATX headings (# / ## / ###).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Section:
    section_id: str
    title: str
    content: str


class MarkdownParser:
    """Parse Markdown text into heading-based sections."""

    HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

    def parse(self, path: str) -> List[Section]:
        text = open(path, encoding="utf-8").read()
        return self.parse_text(text)

    def parse_text(self, text: str) -> List[Section]:
        sections: List[Section] = []
        matches = list(self.HEADING_RE.finditer(text))

        if not matches:
            return [Section(section_id="body", title="Body", content=text.strip())]

        # Text before first heading
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(Section(section_id="preamble", title="Preamble", content=preamble))

        for i, match in enumerate(matches):
            title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            sections.append(
                Section(
                    section_id=self._slugify(title),
                    title=title,
                    content=content,
                )
            )
        return sections

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug[:64]

