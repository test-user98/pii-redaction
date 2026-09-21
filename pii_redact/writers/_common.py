"""Helpers shared by the PDF and DOCX writers."""
from __future__ import annotations

from pii_redact.model import Doc, Entity, Span, Word

LEGEND_HEADING = "Redaction legend"


def mention_surrogate(entity: Entity, span: Span) -> str:
    try:
        from pii_redact.surrogates import mention_surrogate as ms
    except ImportError:
        return entity.surrogate
    return ms(entity, span)


def mentions_by_page(doc: Doc) -> dict[int, list[tuple[Span, str]]]:
    """page_no -> [(span, surrogate)] for every entity mention."""
    out: dict[int, list[tuple[Span, str]]] = {}
    for ent in doc.entities:
        for span in ent.mentions:
            out.setdefault(span.page, []).append((span, mention_surrogate(ent, span)))
    return out


def keep_punctuation(span: Span, words: list[Word], surrogate: str) -> str:
    """Words carry attached punctuation ("Malvadkar,"); keep what sits outside the span text."""
    joined = " ".join(w.text for w in words)
    i = joined.find(span.text)
    if i < 0:
        return surrogate
    return joined[:i] + surrogate + joined[i + len(span.text):]


def legend_rows(doc: Doc, cfg: dict) -> list[list[str]] | None:
    """Header + rows for the legend table, or None when legend == 'none'."""
    mode = cfg.get("surrogates", {}).get("legend", "none")
    if mode == "none":
        return None
    header = ["entity_id", "type", "surrogate"] + (["real"] if mode == "full" else [])
    rows = [header]
    for ent in doc.entities:
        row = [ent.id, ent.type, ent.surrogate]
        if mode == "full":
            row.append(ent.canonical)
        rows.append(row)
    return rows


def split_proportionally(text: str, weights: list[int]) -> list[str]:
    """Split text into len(weights) fragments, sized proportionally to weights."""
    if len(weights) == 1:
        return [text]
    total = sum(weights) or 1
    out, pos = [], 0
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            out.append(text[pos:])
            break
        cut = pos + round(len(text) * w / total)
        # prefer breaking at a space near the cut
        sp = text.rfind(" ", pos, cut + 1)
        if sp > pos:
            cut = sp + 1
        out.append(text[pos:cut].strip())
        pos = cut
    return out
