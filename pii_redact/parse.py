"""Step 1: turn a PDF or DOCX into Doc/Page/Word/Image (see CONTRACTS.md)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import docx
import pymupdf
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .model import Doc, Image, Page, Word

RENDER_DPI = 300
DOCX_PARAS_PER_PAGE = 50
EMU_PER_PT = 12700
# A hyperlink target worth scanning: mailto:/tel: schemes, or an email / phone-looking string in the URL.
LINK_PII = re.compile(r"^(mailto|tel):|[\w.+-]+@[\w-]+\.[\w.-]+|\d[\d\s().-]{7,}\d", re.I)


def parse_document(path: str, cfg: dict) -> Doc:
    data = Path(path).read_bytes()
    doc_id = hashlib.sha256(data).hexdigest()[:16]
    fmt = Path(path).suffix.lower().lstrip(".")
    if fmt == "pdf":
        pages = _parse_pdf(path, cfg)
    elif fmt == "docx":
        pages = _parse_docx(path)
    else:
        raise ValueError(f"unsupported format: {path}")
    return Doc(doc_id=doc_id, path=path, fmt=fmt, pages=pages)


# ---------------------------------------------------------------- PDF

def _parse_pdf(path: str, cfg: dict) -> list[Page]:
    pdf = pymupdf.open(path)
    return [_parse_pdf_page(p, cfg["routing"]) for p in pdf]


def _parse_pdf_page(page: pymupdf.Page, routing: dict) -> Page:
    page_no = page.number + 1
    words = [
        Word(id=i, page=page_no, text=text, loc={"bbox": (x0, y0, x1, y1)}, block=block, line=line)
        for i, (x0, y0, x1, y1, text, block, line, _) in enumerate(page.get_text("words"))
    ]

    images = []
    for info in page.get_images(full=True):
        xref = info[0]
        for rect in page.get_image_rects(xref):
            clip = rect & page.rect  # images can hang off the page; OCR coords map from the visible part
            if clip.is_empty:
                continue
            # the same picture placed twice (or two xrefs on the same spot) is one region: OCR it once
            if any(_overlap(clip, pymupdf.Rect(im.bbox)) > 0.9 for im in images):
                continue
            png = page.get_pixmap(clip=clip, dpi=RENDER_DPI).tobytes("png")
            images.append(Image(page=page_no, bbox=tuple(clip), xref=xref, png=png))

    area = page.rect.width * page.rect.height
    signals = {
        "text_density": sum(len(w.text) for w in words) / area,
        "single_letter_ratio": (sum(len(w.text) == 1 for w in words) / len(words)) if words else 0.0,
        "image_area_ratio": sum(pymupdf.Rect(im.bbox).get_area() for im in images) / area,
    }
    hard = (
        signals["text_density"] < routing["min_text_density"]
        or signals["single_letter_ratio"] > routing["max_single_letter_ratio"]
        or signals["image_area_ratio"] > routing["max_image_area_ratio"]
    )
    return Page(page_no=page_no, words=words, images=images, signals=signals, hard=hard)


# ---------------------------------------------------------------- DOCX

def iter_docx_paragraphs(document) -> list[Paragraph]:
    """Every paragraph in document order: body (tables recursed, nested included),
    then each section's header and footer. Parser and writer share this so an
    index means the same paragraph in both."""
    out: list[Paragraph] = []

    def walk(container):
        for item in container.iter_inner_content():
            if isinstance(item, Paragraph):
                out.append(item)
            elif isinstance(item, Table):
                # iter_tcs yields each cell once; table.rows repeats merged cells
                for tc in item._tbl.iter_tcs():
                    walk(_Cell(tc, item))

    walk(document)
    for section in document.sections:
        for part in (section.header, section.footer):
            if not part.is_linked_to_previous:  # linked parts re-expose the previous section's content
                walk(part)
    return out


def iter_docx_runs(paragraph: Paragraph) -> list[Run]:
    """Every run of a paragraph in document order, including runs nested inside
    w:hyperlink (which `Paragraph.runs` skips). Parser and writer share this so a
    run index means the same run in both."""
    out: list[Run] = []
    for item in paragraph.iter_inner_content():
        out.extend(item.runs if isinstance(item, Hyperlink) else [item])
    return out


def _parse_docx(path: str) -> list[Page]:
    paragraphs = iter_docx_paragraphs(docx.Document(path))
    n_pages = max(1, -(-len(paragraphs) // DOCX_PARAS_PER_PAGE))
    pages = [Page(page_no=i + 1, words=[]) for i in range(n_pages)]

    for para_idx, para in enumerate(paragraphs):
        page = pages[para_idx // DOCX_PARAS_PER_PAGE]
        # Tokenize inside each run so every Word sits wholly in one run. Fragments of
        # one whitespace-delimited token (e.g. "Email" + ":" in two runs) share the same
        # `line` number so normalize can glue them back together.
        token_no, prev_ended_in_space = -1, True
        for run_idx, run in enumerate(iter_docx_runs(para)):
            text = run.text
            for m in re.finditer(r"\S+", text):
                if prev_ended_in_space or m.start() > 0:
                    token_no += 1
                page.words.append(Word(
                    id=len(page.words), page=page.page_no, text=m.group(),
                    loc={"para": para_idx, "run": run_idx, "offset": m.start()},
                    block=para_idx, line=token_no,
                ))
            if text:
                prev_ended_in_space = text[-1].isspace()

        # Hyperlink targets (mailto:, tel:, URLs carrying an email/phone) are text too. One Word per
        # link; the writer rewrites the relationship target via loc["rel"].
        for hl in para._p.xpath("./w:hyperlink[@r:id]"):
            rid = hl.get(qn("r:id"))
            rel = para.part.rels[rid]
            if rel.is_external and LINK_PII.search(rel.target_ref):
                target = rel.target_ref
                token_no += 1
                page.words.append(Word(
                    id=len(page.words), page=page.page_no, text=re.sub(r"^(mailto|tel):", "", target, flags=re.I),
                    loc={"para": para_idx, "rel": rid}, block=para_idx, line=token_no,
                ))

        for drawing in para._p.xpath(".//w:drawing"):
            for rid in drawing.xpath(".//a:blip/@r:embed"):
                extent = drawing.xpath(".//wp:extent")
                w = int(extent[0].get("cx")) / EMU_PER_PT if extent else 0.0
                h = int(extent[0].get("cy")) / EMU_PER_PT if extent else 0.0
                # rIds are per part (body, each header/footer); "@<para>" lets the writer resolve the
                # owning part through the shared paragraph traversal.
                page.images.append(Image(
                    page=page.page_no, bbox=(0.0, 0.0, w, h), ref=f"{rid}@{para_idx}",
                    png=para.part.related_parts[rid].blob,
                ))
    return pages


def _overlap(a: "pymupdf.Rect", b: "pymupdf.Rect") -> float:
    """Intersection over the smaller rect: 1.0 when one image lies fully on top of the other."""
    inter = a & b
    if inter.is_empty:
        return 0.0
    return inter.get_area() / min(a.get_area(), b.get_area())
