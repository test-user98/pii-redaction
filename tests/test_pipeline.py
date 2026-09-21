"""End-to-end and failure-path tests. GLiNER loads once (~20 s); no LLM calls."""
from __future__ import annotations

import csv
import json

import pymupdf
import pytest

from pii_redact import pipeline
from pii_redact.config import backends

TEXT = [
    "Contact Person: Sarthak Malvadkar, Company Secretary",
    "Telephone: +91 20 4505 3237  E-mail: sarthak.malvadkar@kshinternational.com",
    "Registered Office: 11/3, Village Birdewadi, Chakan Taluka - Khed, Pune – 410 501, Maharashtra, India",
    "Our Promoters: Kushal Subbayya Hegde and Rajesh Kushal Hegde. Mr. Hegde chairs the Board.",
    "Bankers: HDFC Bank Limited. Regulator: Securities and Exchange Board of India (SEBI).",
    "PAN: NBWPS1951N   Date of Birth: 06/05/2000   Offer closes on December 18, 2025.",
    "A broad range of products. Sarthak Malvadkar signed.",
]


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("doc") / "sample.pdf"
    d = pymupdf.open()
    page = d.new_page()
    y = 72
    for line in TEXT:
        page.insert_text((40, y), line, fontsize=9)
        y += 18
    d.save(path)
    return path


def _rows(out_dir):
    return list(csv.DictReader(open(out_dir / "spans.csv")))


def test_end_to_end_pdf(sample_pdf, tmp_path):
    summary = pipeline.run(str(sample_pdf), str(tmp_path), use_llm=False, use_review=False)
    out = tmp_path / summary["doc_id"]
    assert summary["verify"]["ok"], summary["verify"]["leaks"]

    redacted = pymupdf.open(summary["output"])[0].get_text()
    for real in ("Sarthak Malvadkar", "kshinternational.com", "4505 3237", "NBWPS1951N", "06/05/2000", "Birdewadi"):
        assert real not in redacted
    assert "December 18, 2025" in redacted            # an offer date is not PII
    assert "Securities and Exchange Board of India" in redacted   # regulator is allowlisted
    assert "broad range" in redacted                  # common word not treated as a name

    rows = _rows(out)
    by_text = {r["text"]: r for r in rows}
    # same person twice -> same surrogate; partial mention shares the surname surrogate
    s1 = by_text["Sarthak Malvadkar"]["surrogate"]
    assert all(r["surrogate"] == s1 for r in rows if r["text"] == "Sarthak Malvadkar")
    hegde_full = next(r for r in rows if r["text"] == "Kushal Subbayya Hegde")["surrogate"]
    hegde_alone = next(r for r in rows if r["text"] == "Hegde")["surrogate"]   # "Mr. Hegde" -> honorific kept
    assert hegde_alone == hegde_full.split()[-1]
    # email follows the person's surrogate tokens
    email = next(r for r in rows if r["type"] == "EMAIL")["surrogate"]
    assert email.endswith("@example.com") and email.split("@")[0].replace(".", " ").lower() == s1.lower()

    mapping = json.load(open(out / "mapping.json"))
    assert mapping and (out / "mapping.csv").exists() and (out / "audit.jsonl").exists()
    assert (out / "sample.redacted.docx").exists()    # docx copy for a pdf input


def test_unsupported_format(tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError):
        pipeline.run(str(bad), str(tmp_path))


def test_llm_down_does_not_kill_page(sample_pdf, tmp_path, monkeypatch):
    cfg = backends()
    cfg["llm"].update(provider="ollama", base_url="http://127.0.0.1:1", timeout_s=2)
    cfg["routing"]["llm_easy_page_sample"] = 1.0        # force the LLM on this page
    monkeypatch.setattr(pipeline, "backends", lambda: cfg)
    summary = pipeline.run(str(sample_pdf), str(tmp_path), use_llm=True, use_review=False)
    audit = [json.loads(l) for l in open(tmp_path / summary["doc_id"] / "audit.jsonl")]
    assert any(r["stage"] == "llm_failed" for r in audit)
    assert summary["verify"]["ok"]                       # regex + GLiNER still redacted everything


def test_blank_page(tmp_path):
    path = tmp_path / "blank.pdf"
    d = pymupdf.open()
    d.new_page()
    d.save(path)
    summary = pipeline.run(str(path), str(tmp_path), use_llm=False, use_review=False)
    assert summary["spans"] == 0 and summary["verify"]["ok"]


def test_corrupt_pdf(tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(Exception):
        pipeline.run(str(path), str(tmp_path), use_llm=False, use_review=False)
