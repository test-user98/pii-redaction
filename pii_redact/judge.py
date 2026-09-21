"""Step 7 — judge: type precedence, ORG allowlist, keep / drop / review.

Input is ``page.spans`` (the merged spans from merge.py). Output is (kept, review);
the caller stores ``kept`` back into ``page.spans``.
"""
from __future__ import annotations

import re

from .finders import validators
from .finders.regex_finder import WS_TOLERANT, has_context
from .model import Page, Span

# Lower rank wins when overlapping spans disagree on type.
_FINDER_RANK = {"regex": 1, "gliner": 2, "llm": 3, "propagate": 4}
MAX_STRUCTURED_LEN = 60   # same cap as merge._type_fits: an identifier is never a paragraph


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
    flat = " ".join(text.split())
    for entry in type_cfg.get("allowlist") or []:
        if re.search(r"\b" + re.escape(" ".join(entry.split())) + r"\b", flat, re.IGNORECASE):
            return True
    return False


def is_generic(text: str, type_cfg: dict) -> bool:
    """'our Company', 'Stock Exchanges', 'Director', 'BRLMs' are document roles, not names."""
    generic = {w.lower() for w in type_cfg.get("generic_words") or []}
    tokens = re.findall(r"[A-Za-z][A-Za-z'&.-]*", text)
    if not tokens:
        return True
    if all(t.lower() in generic for t in tokens):
        return True
    if len(tokens) == 1 and len(tokens[0]) <= 6 and sum(c.isupper() for c in tokens[0]) >= 2 \
            and sum(c.islower() for c in tokens[0]) <= 1:
        return True                                     # bare acronym: BRLMs, SCSBs, UPI
    return False


is_generic_org = is_generic


def _name_shaped(span: Span) -> bool:
    """A name or company mention has at least one capital letter ('rice', 'our' are not names)."""
    return any(c.isupper() for c in span.text)


def shape_ok(span: Span, type_cfg: dict) -> bool:
    """A span of a `structured` type must look like that type whoever found it: its own text contains
    a match of the type's regex that passes the type's validator, and it is short. This is what stops
    an LLM span like "5,587.12" (CREDIT_CARD) or "Telephone" (PHONE) from being redacted."""
    if not type_cfg.get("structured"):
        return True
    if len(span.text) > MAX_STRUCTURED_LEN:
        return False
    validator = type_cfg.get("validator")
    for pat in type_cfg.get("regex") or []:
        for m in re.finditer(pat, span.text):
            cand = re.sub(r"\s+", "", m.group(0)) if span.type in WS_TOLERANT else m.group(0)
            if not validator or getattr(validators, validator)(cand):
                return True
    return not type_cfg.get("regex")


def seed_ok(span: Span, tcfg: dict) -> bool:
    """May this span seed cross-page propagation? Same shape rules the judge applies to keep a span."""
    if is_exempt(span.text, tcfg) or not shape_ok(span, tcfg):
        return False
    if span.type in ("PERSON", "ORG") and (not _name_shaped(span) or is_generic(span.text, tcfg)):
        return False
    return len(span.text.strip()) >= 4


def _independent_finders(span: Span) -> int:
    """propagate only echoes another finder's hit, so it is not independent evidence."""
    return len([n for n in finder_names(span) if n != "propagate"])


def _org_context(span: Span, page: Page, type_cfg: dict) -> bool:
    """Single-token ORG from one finder: 'Supa', 'Mega', 'Reliance' need a corporate word nearby."""
    view = page.views.get(span.view)
    if view is None:
        return False
    return has_context(view.text, span.start, span.end, type_cfg.get("context_words") or [])


def _resolve_doc_context(page: Page, types: list[dict], cfg: dict, audit) -> None:
    """`context_scope: doc` (DIN): regex_finder parked spans whose context word is not on their page in
    cfg["_doc_context_pending"]. Accept them if the previous page showed the context word (a table
    whose "DIN" header is on the page before), then re-merge so they take their place like any regex hit.
    Runs here because judge is sequential and every page's finder pass has finished by now."""
    pending = cfg.get("_doc_context_pending", {}).pop(page.page_no, [])
    if not pending:
        return
    by_name = {t["name"]: t for t in types}
    seen = cfg.get("_doc_context_seen", {}).get(page.page_no - 1, set())
    resolved = [s for s in pending
                if {w.lower() for w in by_name.get(s.type, {}).get("context_words") or []} & seen]
    if not resolved:
        return
    from .merge import merge                      # merge imports judge; import lazily
    if audit:
        for s in resolved:
            audit.log("judge_doc_context", page.page_no, "judge", confidence=s.confidence, evidence=s.text, type=s.type)
    page.spans = page.spans + resolved
    page.spans = merge(page, types)


def judge(page: Page, types: list[dict], cfg: dict, audit=None) -> tuple[list[Span], list[Span]]:
    """Return (kept, review) from page.spans.

    - allowlist hit or policy "exempt"  -> dropped (audited as judge_exempt when audit given)
    - structured type whose text does not match the type's regex/validator -> dropped (judge_shape)
    - shorter than the type's `min_chars`, or an ADDRESS with no letters -> dropped (judge_short / judge_shape)
    - policy "review"                   -> review
    - single finder, conf < drop        -> dropped
    - single finder, drop <= conf < review threshold -> review
    - single-token ORG from one finder with no corporate context word nearby -> review
    - otherwise kept (multi-finder spans are never dropped)
    """
    jcfg = cfg.get("judge", {})
    drop_below = jcfg.get("drop_single_finder_below", 0.5)
    review_below = jcfg.get("review_single_finder_below", 0.7)
    by_name = {t["name"]: t for t in types}
    _resolve_doc_context(page, types, cfg, audit)

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
        if not shape_ok(span, tcfg) or (span.type == "ADDRESS" and not any(c.isalpha() for c in span.text)):
            if audit:
                audit.log("judge_shape", page.page_no, "judge", confidence=span.confidence,
                          evidence=span.text, type=span.type, finder=span.finder)
            continue
        if len(span.text.strip()) < tcfg.get("min_chars", 0):
            if audit:
                audit.log("judge_short", page.page_no, "judge", evidence=span.text, type=span.type)
            continue
        if policy == "review":
            review.append(span)
            continue
        if span.type in ("PERSON", "ORG") and not _name_shaped(span):
            continue
        if span.type in ("PERSON", "ORG") and is_generic(span.text, tcfg):
            if audit:
                audit.log("judge_generic", page.page_no, "judge", evidence=span.text)
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
        if span.type == "ORG" and tcfg.get("single_token_needs_context") and len(span.text.split()) == 1 \
                and _independent_finders(span) <= 1 and not _org_context(span, page, tcfg):
            if audit:
                audit.log("judge_org_context", page.page_no, "judge", confidence=span.confidence,
                          evidence=span.text, finder=span.finder)
            review.append(span)
            continue
        # An LLM-only ORG without a corporate word nearby ("Maharashtra", "Supa Facility", committee names)
        # or an LLM-only ADDRESS with no digit is a guess, not evidence: review, don't redact.
        if finder_names(span) == ["llm"] and (
                (span.type == "ORG" and not _org_context(span, page, tcfg)) or
                (span.type == "ADDRESS" and not any(c.isdigit() for c in span.text))):
            if audit:
                audit.log("judge_llm_only", page.page_no, "judge", evidence=span.text, type=span.type)
            review.append(span)
            continue
        kept.append(span)
    return kept, review
