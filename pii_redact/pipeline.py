"""Orchestrates the steps in DESIGN.md: parse → views → finders → propagate → merge → judge
→ entities/surrogates → write (same format) → verify → review. Pages run in a thread pool."""
from __future__ import annotations

import csv
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import merge as merge_mod
from . import judge as judge_mod
from . import surrogates, verify
from .audit import Audit
from .config import backends, pii_types
from .finders import gliner_finder, llm_finder, propagate, regex_finder
from .model import Doc, Page, Span
from .normalize import build_views
from .ocr import ocr_images
from .parse import parse_document


def _timed(audit: Audit, stage: str, page: int | None, backend: str, fn, **extra):
    t = time.time()
    out = fn()
    n = len(out) if isinstance(out, (list, dict)) else None
    audit.log(stage, page, backend, latency_ms=round((time.time() - t) * 1000), count=n, **extra)
    return out


def _page_pass(page: Page, doc: Doc, types, cfg, audit: Audit, use_llm: bool, llm_pages: set[int]) -> list[Span]:
    if page.images:
        page.words.extend(_timed(audit, "ocr", page.page_no, cfg["ocr"]["engine"], lambda: ocr_images(page, cfg)))
    page.views = build_views(page)
    audit.log("route", page.page_no, "rules", evidence=page.signals, hard=page.hard)

    spans: list[Span] = []
    spans += _timed(audit, "find", page.page_no, "regex", lambda: regex_finder.find(page, types, cfg))
    spans += _timed(audit, "find", page.page_no, "gliner", lambda: gliner_finder.find(page, types, cfg))
    if use_llm and page.page_no in llm_pages:
        spans += _timed(audit, "find", page.page_no, cfg["llm"]["model"], lambda: llm_finder.find(page, types, cfg),
                        unlocated=list(llm_finder.unlocated))
        llm_finder.unlocated.clear()
    return spans


def run(path: str, out_dir: str, *, use_llm: bool = True, use_review: bool = True,
        only_pages: set[int] | None = None, workers: int = 4) -> dict:
    cfg, types = backends(), pii_types()
    out = Path(out_dir)
    doc: Doc = parse_document(path, cfg)
    out = out / doc.doc_id
    out.mkdir(parents=True, exist_ok=True)
    audit = Audit(out, uuid.uuid4().hex[:8], doc.doc_id)
    t0 = time.time()

    pages = [p for p in doc.pages if not only_pages or p.page_no in only_pages]
    sample_every = int(round(1 / cfg["routing"]["llm_easy_page_sample"])) if cfg["routing"]["llm_easy_page_sample"] else 0
    llm_pages = {p.page_no for p in pages if p.hard or (sample_every and p.page_no % sample_every == 0)}
    use_llm = use_llm and cfg["llm"]["provider"] != "none"

    # Steps 2–5 per page, in parallel.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        raw = dict(zip([p.page_no for p in pages],
                       ex.map(lambda p: _page_pass(p, doc, types, cfg, audit, use_llm, llm_pages), pages)))

    # Step 5d: propagate confirmed mentions across the whole document.
    confirmed = [s for spans in raw.values() for s in spans if s.confidence >= 0.7]
    for s in _timed(audit, "find", None, "propagate", lambda: propagate.find(doc, confirmed, types, cfg)):
        raw.setdefault(s.page, []).append(s)

    # Steps 6–7: merge and judge per page.
    review_rows = []
    for p in pages:
        p.spans = raw.get(p.page_no, [])
        p.spans = merge_mod.merge(p)
        kept, review = judge_mod.judge(p, types, cfg)
        p.spans = kept
        review_rows += [(p.page_no, s.text, s.type, s.finder, s.confidence) for s in review]
        audit.log("judge", p.page_no, "rules", count=len(kept), review=len(review))

    # Step 8: entities and surrogates (whole document).
    doc.entities = surrogates.cluster_entities(doc)
    surrogates.assign_surrogates(doc.entities, cfg)
    surrogates.write_mapping(doc, out)

    # Step 9: same-format output (+ DOCX copy for PDF input).
    src = Path(path)
    out_file = out / f"{src.stem}.redacted{src.suffix}"
    if doc.fmt == "pdf":
        from .writers.pdf_writer import write_pdf
        from .writers.pdf_to_docx import pdf_to_docx
        _timed(audit, "write", None, "pymupdf", lambda: write_pdf(doc, str(src), str(out_file), cfg) or [])
        pdf_to_docx(str(out_file), str(out / f"{src.stem}.redacted.docx"))
    else:
        from .writers.docx_writer import write_docx
        _timed(audit, "write", None, "python-docx", lambda: write_docx(doc, str(src), str(out_file), cfg) or [])

    # Step 10: verify no original value survived.
    result = verify.verify(doc, str(out_file), cfg)
    audit.log("verify", None, "search", evidence=result)

    # Step 10b: LLM review, flag-only.
    if use_review and cfg["review"]["enabled"]:
        from .review import review_page
        _write_review(doc, pages, out, out_file, cfg, audit)

    _write_spans(doc, pages, out, review_rows)
    summary = {"doc_id": doc.doc_id, "fmt": doc.fmt, "pages": len(pages), "hard_pages": sorted(p.page_no for p in pages if p.hard),
               "llm_pages": sorted(llm_pages) if use_llm else [], "entities": len(doc.entities),
               "spans": sum(len(p.spans) for p in pages), "review_items": len(review_rows),
               "verify": result, "output": str(out_file), "seconds": round(time.time() - t0, 1)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _write_spans(doc: Doc, pages, out: Path, review_rows):
    by_span = {id(s): e for e in doc.entities for s in e.mentions}
    with open(out / "spans.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["page", "text", "type", "entity_id", "finder", "confidence", "surrogate"])
        for p in pages:
            for s in p.spans:
                e = by_span.get(id(s))
                w.writerow([p.page_no, s.text, s.type, e.id if e else "", s.finder, round(s.confidence, 2),
                            surrogates.mention_surrogate(e, s) if e else ""])
    with open(out / "review.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["page", "text", "type", "finder", "confidence", "human_label"])
        w.writerows([list(r) + [""] for r in review_rows])


def _write_review(doc: Doc, pages, out: Path, out_file: Path, cfg, audit: Audit):
    from .review import review_page
    redacted = _page_texts(out_file, doc.fmt)
    by_span = {id(s): e for e in doc.entities for s in e.mentions}
    with open(out / "review.jsonl", "w") as f:
        for p in pages:
            mapping = [{"real": s.text, "surrogate": surrogates.mention_surrogate(by_span[id(s)], s), "type": s.type}
                       for s in p.spans if id(s) in by_span]
            t = time.time()
            r = review_page(p.views["layout"].text, redacted.get(p.page_no, ""), mapping, cfg)
            audit.log("review", p.page_no, cfg["review"]["model"], latency_ms=round((time.time() - t) * 1000), evidence=r)
            f.write(json.dumps({"page": p.page_no, **r}) + "\n")


def _page_texts(path: Path, fmt: str) -> dict[int, str]:
    if fmt == "pdf":
        import pymupdf
        with pymupdf.open(path) as d:
            return {i + 1: pg.get_text() for i, pg in enumerate(d)}
    import docx
    from .parse import iter_docx_paragraphs
    paras = [p.text for p in iter_docx_paragraphs(docx.Document(path))]
    return {i // 50 + 1: "\n".join(paras[i:i + 50]) for i in range(0, len(paras), 50)}
