"""Step 10: scan the written output for any real entity text that survived."""
from __future__ import annotations

import re

from pii_redact.model import Doc

LEGEND_HEADING = "Redaction legend"
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub("", s).casefold()


def verify(doc: Doc, out_path: str, cfg: dict) -> dict:
    skip_legend = cfg.get("surrogates", {}).get("legend") == "full"
    units = _pdf_units(out_path) if doc.fmt == "pdf" else _docx_units(out_path)
    if skip_legend:
        cut = next((i for i, (_, _, t) in enumerate(units) if t.lstrip().startswith(LEGEND_HEADING)), None)
        if cut is not None:
            units = units[:cut]

    needles = []  # (entity_id, needle_text)
    for ent in doc.entities:
        seen = set()
        for raw in [ent.canonical] + [m.text for m in ent.mentions]:
            n = _norm(raw)
            if len(n) >= 3 and n not in seen:
                seen.add(n)
                needles.append((ent.id, raw))

    leaks = []
    for key, no, text in units:
        hay = _norm(text)
        for entity_id, raw in needles:
            if _norm(raw) in hay:
                leaks.append({key: no, "text": raw, "entity_id": entity_id})
    return {"ok": not leaks, "leaks": leaks}


def _pdf_units(path: str) -> list[tuple[str, int, str]]:
    import pymupdf

    with pymupdf.open(path) as pdf:
        return [("page", i + 1, p.get_text()) for i, p in enumerate(pdf)]


def _docx_units(path: str) -> list[tuple[str, int, str]]:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(path)
    units, i = [], 0

    def walk(container, elements):
        nonlocal i
        for el in elements:
            if el.tag == qn("w:p"):
                units.append(("para", i, Paragraph(el, container).text))
                i += 1
            elif el.tag == qn("w:tbl"):
                for row in Table(el, container).rows:
                    for cell in row.cells:
                        walk(cell, cell._element.iterchildren())

    walk(d, d.element.body.iterchildren())
    for sec in d.sections:
        for part in (sec.header, sec.footer):
            walk(part, part._element.iterchildren())
    return units
