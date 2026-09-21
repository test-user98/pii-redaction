"""Step 4: RapidOCR over Page.images -> Words with source="ocr" (see CONTRACTS.md)."""
from __future__ import annotations

import struct

from rapidocr_onnxruntime import RapidOCR

from .model import Image, Page, Word

_engine: RapidOCR | None = None


def _ocr() -> RapidOCR:
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


def ocr_images(page: Page, cfg: dict) -> list[Word]:
    """One Word per OCR text line (its box is exact; splitting into tokens would
    mean guessing box widths). Each image is its own block; lines number from 0."""
    min_conf = cfg["ocr"]["min_confidence"]
    next_id = max((w.id for w in page.words), default=-1) + 1
    block = max((w.block for w in page.words), default=-1) + 1
    out: list[Word] = []
    for img in page.images:
        if not img.png:
            continue
        result, _elapse = _ocr()(img.png)
        for line_no, (box, text, score) in enumerate(result or []):
            text = text.strip()
            if not text or score < min_conf:
                continue
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            px = (min(xs), min(ys), max(xs), max(ys))
            if img.ref is not None:
                loc = {"image_ref": img.ref, "bbox": px}
            else:
                loc = {"bbox": _to_page(px, img)}
            out.append(Word(id=next_id, page=page.page_no, text=text, loc=loc, source="ocr", block=block, line=line_no))
            next_id += 1
        block += 1
    return out


def _to_page(px: tuple, img: Image) -> tuple[float, float, float, float]:
    """Crop pixels -> page points. Scale comes from the rendered PNG's size over the
    (page-clipped) image bbox, so it is exact even when the image hangs off the page."""
    w, h = struct.unpack(">II", img.png[16:24])  # PNG IHDR width/height
    x0, y0, x1, y1 = img.bbox
    sx, sy = (x1 - x0) / w, (y1 - y0) / h
    return (x0 + px[0] * sx, y0 + px[1] * sy, x0 + px[2] * sx, y0 + px[3] * sy)
