"""Step 7 — judge: type precedence, ORG allowlist, keep / drop / review.

Input is ``page.spans`` (the merged spans from merge.py). Output is (kept, review);
the caller stores ``kept`` back into ``page.spans``.
"""
from __future__ import annotations

import re

from .model import Page, Span

# Lower rank wins when overlapping spans disagree on type.
_FINDER_RANK = {"regex": 1, "gliner": 2, "llm": 3, "propagate": 4}


def finder_names(span: Span) -> list[str]:
    return [f for f in span.finder.split("+") if f]


def type_rank(span: Span) -> tuple[int, float]:
    """Validator-passed regex (confidence 1.0) beats everything; then regex, gliner, llm, propagate."""
    names = finder_names(span)
    if "regex" in names and span.confidence >= 1.0:
        return (0, -span.confidence)
    return (min(_FINDER_RANK.get(n, 9) for n in names), -span.confidence)


def pick_type(spans: list[Span]) -> str:
    return min(spans, key=type_rank).type


def is_exempt(text: str, type_cfg: dict) -> bool:
    """True if any allowlist entry appears in text as a whole word/phrase (case-insensitive)."""
    for entry in type_cfg.get("allowlist") or []:
        if re.search(r"\b" + re.escape(entry) + r"\b", text, re.IGNORECASE):
            return True
    return False


def judge(page: Page, types: list[dict], cfg: dict, audit=None) -> tuple[list[Span], list[Span]]:
    """Return (kept, review) from page.spans.

    - allowlist hit or policy "exempt"  -> dropped (audited as judge_exempt when audit given)
    - policy "review"                   -> review
    - single finder, conf < drop        -> dropped
    - single finder, drop <= conf < review threshold -> review
    - otherwise kept (multi-finder spans are never dropped)
    """
    jcfg = cfg.get("judge", {})
    drop_below = jcfg.get("drop_single_finder_below", 0.5)
    review_below = jcfg.get("review_single_finder_below", 0.7)
    by_name = {t["name"]: t for t in types}

    kept: list[Span] = []
    review: list[Span] = []
    for span in page.spans:
        tcfg = by_name.get(span.type, {})
        policy = tcfg.get("policy", "redact")
        if policy == "exempt" or is_exempt(span.text, tcfg):
            if audit:
                audit.log("judge_exempt", page.page_no, "judge", confidence=span.confidence,
                          evidence=span.text, type=span.type)
            continue
        if policy == "review":
            review.append(span)
            continue
        if len(finder_names(span)) == 1:
            if span.confidence < drop_below:
                if audit:
                    audit.log("judge_drop", page.page_no, "judge", confidence=span.confidence,
                              evidence=span.text, type=span.type, finder=span.finder)
                continue
            if span.confidence < review_below:
                review.append(span)
                continue
        kept.append(span)
    return kept, review
