"""PIN-code anchored address finder for Indian addresses.

GLiNER2-PII returns almost no addresses on this kind of document, so this finder anchors on the
6-digit PIN code ("Pune – 411 045") and expands backwards to the start of the address:
the nearest label colon, semicolon, sentence end or line start within `max_len` chars.
Forward it swallows the trailing ", Maharashtra, India".
"""
from __future__ import annotations

import re

from pii_redact.model import Page, Span
from pii_redact.finders.regex_finder import make_span

# Where an address can start: after a label ("Registered Office:"), a sentence, a list item, or a line.




def _patterns(tcfg: dict) -> tuple[re.Pattern, re.Pattern]:
    words = [w for w in tcfg.get("starts", [":", ";"]) if w.isalpha() or " " in w]
    puncts = [w for w in tcfg.get("starts", [":", ";"]) if not (w.isalpha() or " " in w)]
    start = re.compile(r"(?:[%s]\s*|\.\s+(?=[A-Z0-9])|\n%s)" % (
        re.escape("".join(puncts)), "".join(r"|\b" + re.escape(w) + r"\s+" for w in words)))
    kw = re.compile(r"\b(?:%s)(?![A-Za-z])" % "|".join(re.escape(w) for w in tcfg.get("keywords", [])), re.I)
    return start, kw


def _expand(text: str, pin_start: int, pin_end: int, tcfg: dict) -> tuple[int, int] | None:
    _START, _KEYWORD = _patterns(tcfg)
    max_len = tcfg.get("max_len", 260)
    lo = max(0, pin_start - max_len)
    starts = [m.end() for m in _START.finditer(text, lo, pin_start)]
    start = starts[-1] if starts else lo
    head = text[start:pin_start]
    if not re.search(r"\d", head) and len(head.split()) < 3:   # "Pune – 411 045" alone is not an address
        return None
    if not _KEYWORD.search(head):                              # OCR junk or a bare city name
        return None
    end = pin_end
    tail = text[pin_end:pin_end + 60]
    m = re.match(r"(?:[,\s]*\(?(?:%s)\)?)+" % "|".join(re.escape(w) for w in tcfg.get("end_words", ["India"])), tail)
    if m:
        end += m.end()
    return start, end


def find(page: Page, types: list[dict], cfg: dict) -> list[Span]:
    tcfg = next((t for t in types if t["name"] == "ADDRESS"), None)
    if not tcfg or not tcfg.get("pin_regex"):
        return []
    view = page.views.get("layout")
    if view is None:
        return []
    text, spans, seen = view.text, [], set()
    for m in re.finditer(tcfg["pin_regex"], text):
        # PIN must be preceded by a city/dash context, not be part of a bigger number or amount
        before = text[max(0, m.start() - 25):m.start()]
        if re.search(r"[\d,.]\s*$", before) or re.search(r"[₹$]", before):
            continue
        rng = _expand(text, m.start(), m.end(), tcfg)
        if not rng or rng in seen:
            continue
        seen.add(rng)
        s, e = rng
        spans.append(make_span(page, "layout", s, e, "ADDRESS", "regex", 0.85))
    return spans
