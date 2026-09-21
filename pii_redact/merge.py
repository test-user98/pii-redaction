"""Step 6 — merge: union spans from all finders and views into one span per word set.

Input is ``page.spans`` (raw candidate spans from every finder / view). Output is the
merged list; the caller stores it back into ``page.spans`` before judge.py runs.
Overlap is decided on word ids only — offsets in the raw and layout views are
different coordinate systems.
"""
from __future__ import annotations

from dataclasses import replace
import re

from .judge import _FINDER_RANK, finder_names, pick_type, type_rank
from .model import Page, Span

# A validator-passed regex span of one of these types sets the boundaries and type of its group,
# so an LLM span like "PAN NBWPS 1951N" does not drag the label word into the redaction.
STRUCTURED: set[str] = set()   # filled from config (types with `structured: true`) on each merge() call


def _validated(s: Span) -> bool:
    return s.type in STRUCTURED and s.confidence >= 1.0 and finder_names(s) == ["regex"]


def _finder_label(spans: list[Span]) -> str:
    names = {n for s in spans for n in finder_names(s)}
    return "+".join(sorted(names, key=lambda n: (_FINDER_RANK.get(n, 9), n)))


def _type_fits(type_: str, text: str, by_name: dict) -> bool:
    """Structured types must match their own regex on the merged text (an address is not a PHONE)."""
    if type_ not in STRUCTURED or not by_name:
        return True
    pats = by_name.get(type_, {}).get("regex") or []
    return len(text) <= 60 and any(re.search(pat, text) for pat in pats)


def _set_start(a: Span, cut: int, page: Page) -> None:
    v = page.views[a.view]
    while cut < a.end and not v.text[cut].isalnum():
        cut += 1
    a.start, a.text, a.word_ids = cut, v.text[cut:a.end], v.word_ids(cut, a.end)


def _set_end(a: Span, cut: int, page: Page) -> None:
    v = page.views[a.view]
    while cut > a.start and not v.text[cut - 1].isalnum():
        cut -= 1
    a.end, a.text, a.word_ids = cut, v.text[a.start:cut], v.word_ids(a.start, cut)


def _trim(spans: list[Span], page: Page) -> None:
    """Keep separate things separate before grouping.

    1. A span that runs well past a validated identifier (DIN, PAN, email, ...) is cut at the
       identifier's edge instead of being swallowed by it: "0011419 3 12 Buena Monte" -> "12 Buena Monte".
    2. A PIN-anchored address that starts with the row before it ("Rajesh Kushal Hegde Managing
       Director 00114193 12 Buena Monte, ...") starts after the last PERSON/DIN inside it, or after an
       ORG that begins it.
    """
    for a in spans:
        if a.view not in page.views or _validated(a):
            continue
        for v in spans:
            if v is a or v.view != a.view or not _validated(v) or v.end <= a.start or v.start >= a.end:
                continue
            if a.end - a.start < v.end - v.start + 8:      # mostly the identifier ("PAN NBWPS 1951N"):
                a.start, a.end, a.text, a.word_ids = v.start, v.end, v.text, list(v.word_ids)   # become it, keep the vote
            elif v.start - a.start <= a.end - v.end:
                _set_start(a, v.end, page)
            else:
                _set_end(a, v.start, page)
    for a in spans:
        if a.type != "ADDRESS" or "regex" not in a.finder or a.view not in page.views:
            continue
        cut = a.start
        for s in spans:
            if s is a or s.view != a.view or s.start < a.start or s.end > a.end - 8 or s.confidence < 0.7:
                continue
            if s.type in ("PERSON", "DIN") or (s.type == "ORG" and s.start == a.start):
                cut = max(cut, s.end)
        if cut > a.start:
            _set_start(a, cut, page)


def merge(page: Page, types: list[dict] | None = None) -> list[Span]:
    by_name = {t["name"]: t for t in types} if types else {}
    if types:
        STRUCTURED.clear()
        STRUCTURED.update(t["name"] for t in types if t.get("structured"))
    elif not STRUCTURED:
        STRUCTURED.update({"EMAIL", "PHONE", "PAN", "AADHAAR", "CREDIT_CARD", "SSN", "IP", "GSTIN", "IFSC", "DIN", "DOB"})
    _trim(page.spans, page)
    spans = []
    for s in page.spans:
        if not s.word_ids and s.view in page.views:
            s.word_ids = page.views[s.view].word_ids(s.start, s.end)
        if s.word_ids:
            spans.append(s)

    # Connected components over shared word ids.
    group_of: dict[int, int] = {}          # word id -> group index
    groups: list[list[Span]] = []
    for s in spans:
        hit = sorted({group_of[w] for w in s.word_ids if w in group_of})
        if not hit:
            gi = len(groups)
            groups.append([])
        else:
            gi = hit[0]
            for other in hit[1:]:          # fold other groups into the first one
                groups[gi].extend(groups[other])
                groups[other] = []
        groups[gi].append(s)
        for m in groups[gi]:
            for w in m.word_ids:
                group_of[w] = gi

    merged = []
    for members in groups:
        if not members:
            continue
        validated = [s for s in members if _validated(s)]
        best = min(validated or members, key=lambda s: (-len(s.word_ids), -len(s.text), type_rank(s)))
        if validated:
            type_ = best.type
        else:
            fitting = [s for s in members if _type_fits(s.type, best.text, by_name)]
            type_ = pick_type(fitting or members)
        words = list(best.word_ids) if validated else sorted({w for s in members for w in s.word_ids})
        merged.append(replace(best,                       # "Alice Beth" + "Beth Carter" -> all three words redacted
                              type=type_,
                              finder=_finder_label(members),
                              confidence=max(s.confidence for s in members),
                              word_ids=words))
    merged.sort(key=lambda s: (min(s.word_ids), -len(s.word_ids)))
    return merged
