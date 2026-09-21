"""Regex + validator finder. Also home of make_span(), shared by the other finders."""
from __future__ import annotations

import re

from pii_redact.model import Page, Span
from pii_redact.finders import validators

# identifier types: match with whitespace inside, strip it before validating
WS_TOLERANT = {"PAN", "AADHAAR", "CREDIT_CARD", "PHONE"}
CONTEXT_WINDOW = 60


def make_span(page: Page, view: str, start: int, end: int, type_: str, finder: str, confidence: float) -> Span:
    v = page.views[view]
    return Span(page=page.page_no, start=start, end=end, text=v.text[start:end], type=type_,
                finder=finder, confidence=confidence, view=view, word_ids=v.word_ids(start, end))


def has_context(text: str, start: int, end: int, words: list[str]) -> bool:
    window = text[max(0, start - CONTEXT_WINDOW):end + CONTEXT_WINDOW].lower()
    return any(re.search(r"\b" + re.escape(w.lower()) + r"\b", window) for w in words)


def find(page: Page, types: list[dict], cfg: dict) -> list[Span]:
    spans = []
    for view_name in ("raw", "layout"):
        v = page.views.get(view_name)
        if v is None:
            continue
        text = v.text
        for t in types:
            name = t["name"]
            for pat in t.get("regex", []):
                for m in re.finditer(pat, text):
                    s, e = m.span()
                    if s == e:
                        continue
                    # never start/end in the middle of a digit run (PHONE regex has no \b)
                    if (s > 0 and text[s - 1].isdigit()) or (e < len(text) and text[e].isdigit()):
                        continue
                    cand = re.sub(r"\s+", "", m.group(0)) if name in WS_TOLERANT else m.group(0)
                    validator = t.get("validator")
                    if validator:
                        if not getattr(validators, validator)(cand):
                            continue
                        conf = 1.0
                    else:
                        conf = 0.8
                    if t.get("requires_context") and not has_context(text, s, e, t.get("context_words", [])):
                        continue
                    spans.append(make_span(page, view_name, s, e, name, "regex", conf))
    return spans
