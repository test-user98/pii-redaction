"""Regex + validator finder. Also home of make_span(), shared by the other finders."""
from __future__ import annotations

import re
import threading

from pii_redact.model import Page, Span
from pii_redact.finders import validators

# identifier types: match with whitespace inside, strip it before validating
WS_TOLERANT = {"PAN", "AADHAAR", "CREDIT_CARD", "PHONE", "DIN"}
CONTEXT_WINDOW = 60
_LOCK = threading.Lock()   # pages run in parallel; the doc-scope bookkeeping below is shared through cfg


def make_span(page: Page, view: str, start: int, end: int, type_: str, finder: str, confidence: float) -> Span:
    v = page.views[view]
    return Span(page=page.page_no, start=start, end=end, text=v.text[start:end], type=type_,
                finder=finder, confidence=confidence, view=view, word_ids=v.word_ids(start, end))


def _word_re(w: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(w.lower()) + r"\b")


def has_context(text: str, start: int, end: int, words: list[str], scope: str = "window") -> bool:
    window = (text if scope in ("page", "doc") else text[max(0, start - CONTEXT_WINDOW):end + CONTEXT_WINDOW]).lower()
    return any(_word_re(w).search(window) for w in words)


def context_words_in(text: str, words: list[str]) -> set[str]:
    low = text.lower()
    return {w.lower() for w in words if _word_re(w).search(low)}


def _park_for_doc_context(cfg: dict, page_no: int, seen: set[str], span: Span | None) -> None:
    """`context_scope: doc`: record which context words this page shows, and park a span whose context
    is missing on its own page. judge resolves parked spans against the previous page once every page's
    finder pass is done (pages run in parallel, so it cannot be decided here)."""
    with _LOCK:
        cfg.setdefault("_doc_context_seen", {}).setdefault(page_no, set()).update(seen)
        if span is not None:
            cfg.setdefault("_doc_context_pending", {}).setdefault(page_no, []).append(span)


def find(page: Page, types: list[dict], cfg: dict) -> list[Span]:
    spans = []
    for view_name in ("raw", "layout"):
        v = page.views.get(view_name)
        if v is None:
            continue
        text = v.text
        for t in types:
            name = t["name"]
            scope = t.get("context_scope", "window")
            ctx_words = t.get("context_words", [])
            if t.get("requires_context") and scope == "doc":
                _park_for_doc_context(cfg, page.page_no, context_words_in(text, ctx_words), None)
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
                    if t.get("requires_context") and not has_context(text, s, e, ctx_words, scope):
                        if scope == "doc":
                            _park_for_doc_context(cfg, page.page_no, set(), make_span(page, view_name, s, e, name, "regex", conf))
                        continue
                    spans.append(make_span(page, view_name, s, e, name, "regex", conf))
    return spans
