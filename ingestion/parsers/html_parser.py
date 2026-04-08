"""ingestion/parsers/html_parser.py

HTML wiki export parser using BeautifulSoup.
Splits on <h1>/<h2>/<h3> tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    Tag = None  # type: ignore


@dataclass
class Section:
    section_id: str
    title: str
    content: str


class HTMLParser:
    """Parse an HTML file into heading-delimited sections."""

    HEADING_TAGS = {"h1", "h2", "h3"}

    def parse(self, path: str) -> List[Section]:
        if BeautifulSoup is None:
            raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4")
        html = open(path, encoding="utf-8").read()
        return self.parse_html(html)

    def parse_html(self, html: str) -> List[Section]:
        soup = BeautifulSoup(html, "html.parser")
        sections: List[Section] = []
        current_title = "Introduction"
        current_texts: List[str] = []

        for element in soup.find_all(True):
            if element.name in self.HEADING_TAGS:
                if current_texts:
                    sections.append(
                        Section(
                            section_id=self._slugify(current_title),
                            title=current_title,
                            content=" ".join(current_texts),
                        )
                    )
                current_title = element.get_text(strip=True) or current_title
                current_texts = []
            elif element.name in {"p", "li", "td", "th"}:
                text = element.get_text(strip=True)
                if text:
                    current_texts.append(text)

        if current_texts:
            sections.append(
                Section(
                    section_id=self._slugify(current_title),
                    title=current_title,
                    content=" ".join(current_texts),
                )
            )
        return sections

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug[:64]

