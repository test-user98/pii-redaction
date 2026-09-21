"""Step 2: text views of a page with an exact char -> Word.id map (see CONTRACTS.md)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Page, PageText, Word

MIN_COLUMN_LEN = 3  # single-letter lines needed before we call it a spaced-out word
# "Rastogi/Abhijit": two names the text layer joined with a slash; each side is a plain word of 2+ letters
_SLASHED = re.compile(r"([(\[]?)([A-Za-z]{2,}(?:/[A-Za-z]{2,})+)([,.;:)\]]*)")


def build_views(page: Page) -> dict[str, PageText]:
    _split_slashed_words(page)
    words = sorted(page.words, key=lambda w: w.id)
    return {"raw": _raw(page.page_no, words), "layout": _layout(page.page_no, words)}


def _split_slashed_words(page: Page) -> None:
    """Split a text-layer word like "Rastogi/Abhijit" into "Rastogi/" + "Abhijit" **at the Word level**
    (page.words is rewritten; later ids shift up). A space in the view alone would not do: both names
    would still share one Word id and merge would fuse them back into one span. The new Word keeps
    block/line/source and gets a bbox cut in proportion to its characters (PDF/OCR) or an offset
    shifted inside the same run (DOCX)."""
    out: list[Word] = []
    for w in sorted(page.words, key=lambda w: w.id):
        m = _SLASHED.fullmatch(w.text) if ("bbox" in w.loc or "offset" in w.loc) else None
        if not m:
            w.id = len(out)
            out.append(w)
            continue
        open_, body, close = m.groups()
        parts = body.split("/")
        pieces = [open_ + parts[0] + "/"] + [p + "/" for p in parts[1:-1]] + [parts[-1] + close]
        n, pos, orig = len(w.text), 0, dict(w.loc)     # keep the original loc: piece 0 reuses w and overwrites w.loc
        for k, piece in enumerate(pieces):
            if "bbox" in orig:
                x0, y0, x1, y1 = orig["bbox"]
                loc = dict(orig, bbox=(x0 + (x1 - x0) * pos / n, y0, x0 + (x1 - x0) * (pos + len(piece)) / n, y1))
            else:
                loc = dict(orig, offset=orig["offset"] + pos)
            part = w if k == 0 else Word(id=0, page=w.page, text="", loc={}, source=w.source, block=w.block, line=w.line)
            part.id, part.text, part.loc = len(out), piece, loc
            out.append(part)
            pos += len(piece)
    page.words = out


class _Buf:
    def __init__(self):
        self.parts: list[str] = []
        self.ids: list[int] = []

    def add(self, text: str, ids: int | list[int]):
        self.parts.append(text)
        self.ids.extend([ids] * len(text) if isinstance(ids, int) else ids)

    def page_text(self, page_no: int, view: str) -> PageText:
        return PageText(page=page_no, view=view, text="".join(self.parts), char_word=self.ids)


def _raw(page_no: int, words: list[Word]) -> PageText:
    buf = _Buf()
    for i, w in enumerate(words):
        if i:
            buf.add("\n" if _new_block(words[i - 1], w) else " ", -1)
        buf.add(w.text, w.id)
    return buf.page_text(page_no, "raw")


def _new_block(prev: Word, cur: Word) -> bool:
    return cur.block != prev.block or cur.source != prev.source


# ---------------------------------------------------------------- layout

@dataclass
class _Tok:
    text: str
    ids: list[int]  # one id per char


@dataclass
class _Line:
    block: int
    line: int
    source: str
    toks: list[_Tok] = field(default_factory=list)
    bbox: list[float] | None = None  # PDF only

    def add(self, w: Word):
        self.toks.append(_Tok(w.text, [w.id] * len(w.text)))
        if "bbox" in w.loc:
            self.bbox = _union(self.bbox, w.loc["bbox"])

    @property
    def single_letter(self) -> bool:
        return len(self.toks) == 1 and len(self.toks[0].text) == 1


def _layout(page_no: int, words: list[Word]) -> PageText:
    lines = _lines(words)
    if lines and lines[0].bbox is not None:
        lines = _collapse_columns(lines)
    buf = _Buf()
    for i, line in enumerate(lines):
        if i:
            buf.add(_separator(lines[i - 1], line), -1)
        for j, tok in enumerate(line.toks):
            if j:
                buf.add(" ", -1)
            buf.add(tok.text, tok.ids)
    return buf.page_text(page_no, "layout")


def _lines(words: list[Word]) -> list[_Line]:
    """Group consecutive words by (block, line). For DOCX words `line` is the
    token number, so fragments of one token (split across runs) are glued into a
    single _Tok."""
    lines: list[_Line] = []
    for w in words:
        if not lines or _new_block(lines[-1], w) or w.line != lines[-1].line:
            lines.append(_Line(block=w.block, line=w.line, source=w.source))
        cur = lines[-1]
        if "para" in w.loc and cur.toks:
            cur.toks[0].text += w.text
            cur.toks[0].ids += [w.id] * len(w.text)
        else:
            cur.add(w)
    return lines


def _union(a, b):
    return list(b) if a is None else [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _adjacent(a: _Line, b: _Line) -> bool:
    """b sits directly under a: x-ranges overlap, vertical gap under 40% of a's height."""
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    return bx0 < ax1 and ax0 < bx1 and -0.5 * (ay1 - ay0) <= by0 - ay1 <= 0.4 * (ay1 - ay0)


def _collapse_columns(lines: list[_Line]) -> list[_Line]:
    """Vertical text in table cells comes out as one letter per line
    ("P r o m o t e r"). Find runs of >= MIN_COLUMN_LEN stacked single-letter lines,
    absorb a stacked one-word line on either side (PyMuPDF often splits off "Pro"
    as its own block), and merge the run into one token."""
    out: list[_Line] = []
    i = 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j].single_letter and (j == i or _adjacent(lines[j - 1], lines[j])):
            j += 1
        if j - i < MIN_COLUMN_LEN:
            out.append(lines[i])
            i += 1
            continue
        run = lines[i:j]
        if out and len(out[-1].toks) == 1 and _adjacent(out[-1], run[0]):
            run.insert(0, out.pop())
        if j < len(lines) and len(lines[j].toks) == 1 and _adjacent(run[-1], lines[j]):
            run.append(lines[j])
            j += 1
        merged = _Line(block=run[0].block, line=run[0].line, source=run[0].source, toks=[_Tok("", [])])
        for ln in run:
            merged.toks[0].text += ln.toks[0].text
            merged.toks[0].ids += ln.toks[0].ids
            merged.bbox = _union(merged.bbox, ln.bbox)
        out.append(merged)
        i = j
    return out


def _separator(prev: _Line, cur: _Line) -> str:
    """"" when cur continues prev's last token; " " inside a block; "\\n" between
    blocks. Continuations: `word-` + newline + `word`, and an email/URL wrapped
    mid-token ("...co" + "m", "...iciciban" + "k.com"), which PyMuPDF may even put
    in a new block. The tail must look like a domain scrap (lowercase, one char or
    containing a dot) so "...@x.com" + "Telephone:" stays two tokens."""
    last, first = prev.toks[-1].text, cur.toks[0].text
    if prev.bbox is not None and cur.bbox is not None and _adjacent(prev, cur):
        hyphenated = len(last) > 1 and last.endswith("-") and first[0].isalpha()
        link = "@" in last or last.startswith(("www.", "http"))
        scrap = first != "a" and (len(first) == 1 or "." in first) and first == first.lower() and not set(" @") & set(first)
        if hyphenated or (link and scrap):
            return ""
    return " " if prev.block == cur.block and prev.source == cur.source else "\n"
