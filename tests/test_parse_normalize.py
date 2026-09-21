import copy
import random
import time
from pathlib import Path

import docx
import pytest

from pii_redact.config import backends
from pii_redact.normalize import build_views
from pii_redact.ocr import ocr_images
from pii_redact.parse import iter_docx_paragraphs, parse_document

ROOT = Path(__file__).resolve().parent.parent
PDF = str(ROOT / "samples" / "rhp.pdf")
DOCX = str(ROOT / "samples" / "rhp.docx")


@pytest.fixture(scope="module")
def cfg():
    return backends()


@pytest.fixture(scope="module")
def pdf_doc(cfg):
    doc = parse_document(PDF, cfg)
    for page in doc.pages:
        page.views = build_views(page)
    return doc


@pytest.fixture(scope="module")
def docx_doc(cfg):
    doc = parse_document(DOCX, cfg)
    for page in doc.pages:
        page.views = build_views(page)
    return doc


# ---------------------------------------------------------------- PDF parse

def test_pdf_doc_shape(pdf_doc):
    assert pdf_doc.fmt == "pdf"
    assert len(pdf_doc.doc_id) == 16
    assert len(pdf_doc.pages) == 128
    assert [p.page_no for p in pdf_doc.pages] == list(range(1, 129))


def test_pdf_words_and_images(pdf_doc):
    p1 = pdf_doc.pages[0]
    assert [w.id for w in p1.words] == list(range(len(p1.words)))
    assert all(w.source == "text" and len(w.loc["bbox"]) == 4 for w in p1.words)
    assert len(p1.images) == 2
    assert all(im.xref and im.png.startswith(b"\x89PNG") for im in p1.images)
    assert len(pdf_doc.pages[127].images) == 1  # the card is embedded twice on the same spot; deduped


def test_signals_and_hard_flag(pdf_doc):
    for page in pdf_doc.pages[:6] + [pdf_doc.pages[127]]:
        assert set(page.signals) == {"text_density", "single_letter_ratio", "image_area_ratio"}
    assert pdf_doc.pages[0].hard is False
    assert pdf_doc.pages[1].hard is True  # vertical single-letter cells
    assert pdf_doc.pages[1].signals["single_letter_ratio"] > 0.15
    assert pdf_doc.pages[127].hard is True  # image page, no text layer
    assert pdf_doc.pages[127].signals["text_density"] < 0.0005


# ---------------------------------------------------------------- views

def test_layout_collapses_spaced_letters(pdf_doc):
    page = pdf_doc.pages[1]
    assert "Promoter" in page.views["layout"].text
    assert "Promoter" not in page.views["raw"].text


def test_layout_rejoins_wrapped_email(pdf_doc):
    page = pdf_doc.pages[0]
    assert "cs.connect@kshinternational.com" in page.views["layout"].text
    assert "cs.connect@kshinternational.com" not in page.views["raw"].text


def test_layout_rejoins_hyphenated_word(pdf_doc):
    assert "Non-Institutional" in pdf_doc.pages[4].views["layout"].text


def test_char_word_map_is_exact(pdf_doc):
    for page in pdf_doc.pages[:6]:
        words = {w.id: w for w in page.words}
        for view in page.views.values():
            assert len(view.text) == len(view.char_word)
            for ch, wid in zip(view.text, view.char_word):
                assert wid >= 0 or ch.isspace()
                if wid >= 0:
                    assert ch in words[wid].text


def test_char_word_round_trip_random_spans(pdf_doc):
    rng = random.Random(0)
    for page in pdf_doc.pages[:6]:
        words = {w.id: w for w in page.words}
        for view in page.views.values():
            cw = view.char_word
            for _ in range(30):
                start = rng.randrange(len(view.text))
                end = min(len(view.text), start + rng.randrange(5, 60))
                # snap to word boundaries so edge words are wholly inside the span
                while start > 0 and cw[start] >= 0 and cw[start - 1] == cw[start]:
                    start -= 1
                while end < len(cw) and cw[end] >= 0 and cw[end - 1] == cw[end]:
                    end += 1
                span_text = view.text[start:end]
                ids = view.word_ids(start, end)
                assert ids == sorted(ids)
                for wid in ids:
                    assert words[wid].text in span_text


# ---------------------------------------------------------------- OCR

def test_ocr_pan_card_page(pdf_doc, cfg):
    page = pdf_doc.pages[127]
    words = ocr_images(page, cfg)
    assert words and all(w.source == "ocr" for w in words)
    assert words[0].id == len(page.words)
    assert [w.id for w in words] == list(range(words[0].id, words[0].id + len(words)))
    texts = " ".join(w.text for w in words)
    assert "VISHAL" in texts
    assert "NBWPS1951N" in texts
    for w in words:
        x0, y0, x1, y1 = w.loc["bbox"]
        assert 0 <= x0 < x1 <= 596.2 and 0 <= y0 < y1 <= 842.1
    page = copy.copy(page)  # keep the module-scoped fixture untouched
    page.words = page.words + words
    views = build_views(page)
    assert "NBWPS1951N" in views["layout"].text
    assert views["layout"].char_word[views["layout"].text.index("NBWPS1951N")] >= words[0].id


# ---------------------------------------------------------------- DOCX

def test_docx_parse_reindexes_through_iter_docx_paragraphs(docx_doc):
    assert docx_doc.fmt == "docx"
    paragraphs = iter_docx_paragraphs(docx.Document(DOCX))
    assert len(docx_doc.pages) == -(-len(paragraphs) // 50)
    runs = {}
    n = 0
    for page in docx_doc.pages:
        for w in page.words:
            loc = w.loc
            if loc["para"] not in runs:
                runs[loc["para"]] = paragraphs[loc["para"]].runs
            assert runs[loc["para"]][loc["run"]].text[loc["offset"]:].startswith(w.text)
            assert page.page_no == loc["para"] // 50 + 1
            n += 1
    assert n > 50000


def test_docx_layout_glues_run_fragments(docx_doc):
    layout = docx_doc.pages[0].views["layout"].text
    assert "Email: cs.connect@kshinternational.com" in layout


def test_docx_images(docx_doc):
    images = [im for page in docx_doc.pages for im in page.images]
    assert len(images) == 10
    assert all(im.ref.startswith("rId") and im.png and im.xref is None for im in images)


# ---------------------------------------------------------------- perf

def test_full_pdf_parse_and_views_under_30s(cfg):
    t = time.perf_counter()
    doc = parse_document(PDF, cfg)
    for page in doc.pages:
        build_views(page)
    assert time.perf_counter() - t < 30
