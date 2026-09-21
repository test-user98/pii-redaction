"""Step 6 — merge: union spans from all finders and views into one span per word set.

Input is ``page.spans`` (raw candidate spans from every finder / view). Output is the
merged list; the caller stores it back into ``page.spans`` before judge.py runs.
Overlap is decided on word ids only — offsets in the raw and layout views are
different coordinate systems.
"""
from __future__ import annotations

from dataclasses import replace

from .judge import _FINDER_RANK, finder_names, pick_type, type_rank
from .model import Page, Span

# A validator-passed regex span of one of these types sets the boundaries and type of its group,
# so an LLM span like "PAN NBWPS 1951N" does not drag the label word into the redaction.
STRUCTURED = {"EMAIL", "PHONE", "PAN", "AADHAAR", "CREDIT_CARD", "SSN", "IP", "GSTIN", "IFSC", "DIN", "DOB"}


def _validated(s: Span) -> bool:
    return s.type in STRUCTURED and s.confidence >= 1.0 and finder_names(s) == ["regex"]


def _finder_label(spans: list[Span]) -> str:
    names = {n for s in spans for n in finder_names(s)}
    return "+".join(sorted(names, key=lambda n: (_FINDER_RANK.get(n, 9), n)))


def merge(page: Page) -> list[Span]:
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
        merged.append(replace(best,
                              type=best.type if validated else pick_type(members),
                              finder=_finder_label(members),
                              confidence=max(s.confidence for s in members),
                              word_ids=list(best.word_ids)))
    merged.sort(key=lambda s: (min(s.word_ids), -len(s.word_ids)))
    return merged
