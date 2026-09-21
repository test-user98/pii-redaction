"""PDF -> PDF: true redaction in place, surrogate text drawn in the same boxes."""
from __future__ import annotations

import io

import pymupdf
from PIL import Image as PILImage

from pii_redact.model import Doc, Page, Word
from pii_redact.writers._common import LEGEND_HEADING, keep_punctuation, legend_rows, mentions_by_page, split_proportionally
from pii_redact.writers.image_redact import redact_image


def write_pdf(doc: Doc, src_path: str, out_path: str, cfg: dict) -> None:
    pdf = pymupdf.open(src_path)
    per_page = mentions_by_page(doc)
    for page_model in doc.pages:
        if page_model.page_no not in per_page:
            continue
        page = pdf[page_model.page_no - 1]
        words = {w.id: w for w in page_model.words}
        image_boxes: dict[int, list] = {}  # index into page_model.images -> [(bbox_px, text)]
        for span, surrogate in per_page[page_model.page_no]:
            span_words = [words[i] for i in span.word_ids if i in words]
            text_words = [w for w in span_words if w.source != "ocr"]
            ocr_words = [w for w in span_words if w.source == "ocr"]
            if text_words:
                _redact_text_span(page, text_words, keep_punctuation(span, text_words, surrogate))
            if ocr_words:
                _collect_ocr_box(page_model, ocr_words, surrogate, image_boxes)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        _redact_images(page, page_model, image_boxes)

    rows = legend_rows(doc, cfg)
    if rows:
        _append_legend(pdf, rows)
    pdf.set_metadata({})
    pdf.del_xml_metadata()
    pdf.save(out_path, garbage=3, deflate=True)
    pdf.close()


def _redact_text_span(page: pymupdf.Page, span_words: list[Word], surrogate: str) -> None:
    lines: dict[tuple[int, int], list[Word]] = {}
    for w in span_words:
        lines.setdefault((w.block, w.line), []).append(w)
    groups = list(lines.values())
    fragments = split_proportionally(surrogate, [sum(len(w.text) for w in g) for g in groups])
    for group, frag in zip(groups, fragments):
        rect = pymupdf.Rect(group[0].loc["bbox"])
        for w in group[1:]:
            rect |= pymupdf.Rect(w.loc["bbox"])
        page.add_redact_annot(
            rect, text=frag, fontname="helv", fontsize=max(5.0, rect.height * 0.8),
            fill=(1, 1, 1), text_color=(0, 0, 0), align=0,
        )


def _collect_ocr_box(page_model: Page, ocr_words: list[Word], surrogate: str, image_boxes: dict) -> None:
    """One box (union of the span's OCR word rects, in image px) per span, keyed by image index."""
    wr = pymupdf.Rect(ocr_words[0].loc["bbox"])
    for w in ocr_words[1:]:
        wr |= pymupdf.Rect(w.loc["bbox"])
    for idx, img in enumerate(page_model.images):
        ir = pymupdf.Rect(img.bbox)
        if img.png and ir.intersects(wr):
            pw, ph = PILImage.open(io.BytesIO(img.png)).size
            sx, sy = pw / ir.width, ph / ir.height
            box = ((wr.x0 - ir.x0) * sx, (wr.y0 - ir.y0) * sy, (wr.x1 - ir.x0) * sx, (wr.y1 - ir.y0) * sy)
            image_boxes.setdefault(idx, []).append((box, surrogate))
            return


def _redact_images(page: pymupdf.Page, page_model: Page, image_boxes: dict) -> None:
    if not image_boxes:
        return
    replacements = []
    for idx, boxes in image_boxes.items():
        img = page_model.images[idx]
        rect = pymupdf.Rect(img.bbox)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        replacements.append((rect, redact_image(img.png, boxes)))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_REMOVE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    for rect, png in replacements:
        page.insert_image(rect, stream=png)


def _append_legend(pdf: pymupdf.Document, rows: list[list[str]]) -> None:
    margin, line_h, fs = 40.0, 12.0, 8.0
    width, height = pdf[0].rect.width, pdf[0].rect.height
    page, y = None, height
    for i, row in enumerate(rows):
        if y + line_h > height - margin:
            page = pdf.new_page(width=width, height=height)
            page.insert_text((margin, margin), LEGEND_HEADING, fontname="helv", fontsize=14)
            y = margin + 2 * line_h
            if i > 0:
                page.insert_text((margin, y), "  |  ".join(rows[0]), fontname="helv", fontsize=fs)
                y += line_h
        page.insert_text((margin, y), "  |  ".join(row), fontname="helv", fontsize=fs)
        y += line_h
