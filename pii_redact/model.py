"""Shared data model. Every module imports from here; nothing else defines these."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    """One token in the source document with its physical location.

    loc for PDF:  {"bbox": (x0, y0, x1, y1)}
    loc for DOCX: {"para": int, "run": int, "offset": int}   # char offset inside the run
    source: "text" (from the text layer) | "ocr" (from an image)
    """
    id: int
    page: int
    text: str
    loc: dict
    source: str = "text"
    block: int = 0
    line: int = 0


@dataclass
class Image:
    page: int
    bbox: tuple[float, float, float, float]
    xref: int | None = None          # PDF image xref, or None for DOCX
    ref: str | None = None           # DOCX relationship id
    png: bytes | None = None         # rendered pixels for OCR


@dataclass
class PageText:
    """A text *view* of a page. char_word[i] is the Word.id behind character i,
    or -1 for whitespace we inserted. Views: 'raw' (words joined in order),
    'layout' (cells/lines joined, spaced letters collapsed, hyphens rejoined)."""
    page: int
    view: str
    text: str
    char_word: list[int]

    def word_ids(self, start: int, end: int) -> list[int]:
        ids = [w for w in self.char_word[start:end] if w >= 0]
        return sorted(set(ids), key=ids.index)


@dataclass
class Span:
    """A PII candidate found in one view of one page."""
    page: int
    start: int
    end: int
    text: str
    type: str
    finder: str            # "regex" | "gliner" | "llm" | "propagate"
    confidence: float
    view: str
    word_ids: list[int] = field(default_factory=list)


@dataclass
class Page:
    page_no: int
    words: list[Word]
    images: list[Image] = field(default_factory=list)
    signals: dict = field(default_factory=dict)   # text_density, single_letter_ratio, image_area_ratio
    hard: bool = False
    views: dict[str, PageText] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)   # merged, after judge


@dataclass
class Entity:
    """One real-world thing (a person, a company, a phone number) and all its mentions."""
    id: str                 # e.g. "P1", "ORG3", "PHONE2"
    type: str
    canonical: str
    mentions: list[Span] = field(default_factory=list)
    surrogate: str = ""
    name_tokens: dict = field(default_factory=dict)   # PERSON only: {"Kushal": "John", "Hegde": "Doe"}


@dataclass
class Doc:
    doc_id: str
    path: str
    fmt: str                # "pdf" | "docx"
    pages: list[Page]
    entities: list[Entity] = field(default_factory=list)
