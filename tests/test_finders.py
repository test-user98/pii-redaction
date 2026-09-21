"""Finder tests. Pages are built by hand (no parse.py dependency)."""
from __future__ import annotations

import re
import time

import pytest
import requests

from pii_redact.config import backends, pii_types
from pii_redact.model import Doc, Page, PageText, Span, Word
from pii_redact.finders import validators, regex_finder, propagate, llm_finder

TYPES = pii_types()
CFG = backends()
BY_NAME = {t["name"]: t for t in TYPES}


def make_page(page_no: int, text: str) -> Page:
    words, char_word = [], [-1] * len(text)
    for m in re.finditer(r"\S+", text):
        wid = len(words)
        words.append(Word(id=wid, page=page_no, text=m.group(0), loc={"bbox": (0, 0, 0, 0)}))
        for i in range(m.start(), m.end()):
            char_word[i] = wid
    page = Page(page_no=page_no, words=words)
    page.views = {v: PageText(page_no, v, text, list(char_word)) for v in ("raw", "layout")}
    return page


def found(spans, type_, view="layout"):
    return [s.text for s in spans if s.type == type_ and s.view == view]


# ---------------- validators ----------------

def test_validators_accept_known_good():
    assert validators.luhn("4111 1111 1111 1111")
    assert validators.verhoeff("2234 5678 9018")          # 223456789018 is Verhoeff-valid
    assert validators.pan("NBWPS1951N")
    assert validators.phone("+ 91 20 4505 3237")
    assert validators.phone("9876543210")
    assert validators.phone("020-2561 8211")
    assert validators.phone("2025 618211")                 # STD 20 + number, no trunk zero
    assert validators.ssn("123-45-6789")
    assert validators.ipv4("192.168.1.255")
    assert validators.ipv4("2001:0db8:85a3:0000:0000:8a2e:0370:7334")


def test_validators_reject_known_bad():
    assert not validators.luhn("4111 1111 1111 1112")
    assert not validators.verhoeff("2234 5678 9019")
    assert not validators.verhoeff("1234 5678 9012")       # starts with 1
    assert not validators.pan("NBWXS1951N")                # 4th char not a holder code
    assert not validators.pan("NBWPS19510")
    assert not validators.phone("1111111111")
    assert not validators.phone("2019 2020 21")
    assert not validators.phone("5000000000")
    assert not validators.phone("1234567890")              # 10 digits starting with 1
    assert not validators.phone("123456")                  # wrong length
    assert not validators.ssn("000-45-6789")
    assert not validators.ssn("666-45-6789")
    assert not validators.ssn("912-45-6789")
    assert not validators.ipv4("192.168.1.256")
    assert not validators.ipv4("1.2.3")


# ---------------- regex finder ----------------

def test_regex_finds_spaced_email_phone_pan():
    page = make_page(1, "Tel: + 91 20 4505 3237 Email: cs.connect@kshinternational.com PAN: NBWPS 1951N")
    spans = regex_finder.find(page, TYPES, CFG)
    assert "cs.connect@kshinternational.com" in found(spans, "EMAIL")
    assert "+ 91 20 4505 3237" in found(spans, "PHONE")
    assert "NBWPS 1951N" in found(spans, "PAN")
    pan = next(s for s in spans if s.type == "PAN" and s.view == "layout")
    assert pan.confidence == 1.0 and pan.word_ids == page.views["layout"].word_ids(pan.start, pan.end)
    assert page.words[pan.word_ids[0]].text == "NBWPS"


def test_regex_drops_failed_validator():
    page = make_page(1, "Phone 1111 111 111 and card 4111 1111 1111 1112 here")
    spans = regex_finder.find(page, TYPES, CFG)
    assert not found(spans, "PHONE") and not found(spans, "CREDIT_CARD")


def test_dob_regex_requires_context():
    with_ctx = make_page(1, "Date of Birth: 12/05/1985. " + "The offer opens and closes as per the schedule set out below. "
                            "Filing date 01/01/2024 for the offer.")
    spans = regex_finder.find(with_ctx, TYPES, CFG)
    assert found(spans, "DOB") == ["12/05/1985"]
    no_ctx = make_page(2, "The meeting was held on 12/05/1985 in Pune.")
    assert not found(regex_finder.find(no_ctx, TYPES, CFG), "DOB")


# ---------------- GLiNER ----------------

SAMPLE = ("Our Company Secretary and Compliance Officer is Mr. Sarthak Malvadkar. Investors may contact him at "
          "cs.connect@kshinternational.com or on +91 20 4505 3237 for any pre-offer or post-offer related "
          "grievances. Our registered office is at Gat No. 1234, Village Kuruli, Taluka Khed, Pune 410501.")


def test_gliner_finds_person_and_email():
    from pii_redact.finders import gliner_finder
    gliner_finder.get_model(CFG["ner"]["model"])   # exclude load time from the timing below
    page = make_page(1, (SAMPLE + " ") * 10)        # ~2900 chars -> 2+ chunks, exercises offset shifting
    t = time.time()
    spans = gliner_finder.find(page, TYPES, CFG)
    print(f"\nGLiNER latency for {len(page.views['layout'].text)} chars: {time.time() - t:.2f}s")
    assert "Sarthak Malvadkar" in found(spans, "PERSON")
    assert "cs.connect@kshinternational.com" in found(spans, "EMAIL")
    for s in spans:
        assert page.views["layout"].text[s.start:s.end] == s.text and s.word_ids


def test_gliner_chunking_covers_text_with_overlap():
    from pii_redact.finders.gliner_finder import chunk_text
    text = "Sentence number one. " * 200
    chunks = list(chunk_text(text, 1500, 200))
    assert chunks[0][0] == 0 and chunks[-1][0] + len(chunks[-1][1]) == len(text)
    for (o1, c1), (o2, _) in zip(chunks, chunks[1:]):
        assert o2 < o1 + len(c1)                       # overlap
        assert text[o1:o1 + len(c1)] == c1


# ---------------- propagate ----------------

def test_propagate_surname_but_not_common_word():
    p1 = make_page(1, "Our Promoter is Mr. Kushal Subbayya Hegde. The Broad Family Trust holds 10% of shares.")
    p2 = make_page(2, "Mr. Hegde has a broad range of experience. Broad Family Trust and Mr. Broad agree. "
                      "HEGDE was appointed in 2019.")
    doc = Doc(doc_id="x", path="x", fmt="pdf", pages=[p1, p2])
    v1 = p1.views["layout"]
    confirmed = []
    for text, typ in (("Mr. Kushal Subbayya Hegde", "PERSON"), ("Broad Family Trust", "ORG")):
        s = v1.text.index(text)
        confirmed.append(Span(1, s, s + len(text), text, typ, "gliner", 0.9, "layout", v1.word_ids(s, s + len(text))))
    spans = propagate.find(doc, confirmed, TYPES, CFG)
    p2_persons = [(s.text, s.confidence) for s in spans if s.page == 2 and s.type == "PERSON" and s.view == "layout"]
    assert ("Hegde", 0.9) in p2_persons and ("HEGDE", 0.9) in p2_persons
    p2_orgs = [(s.text, s.confidence) for s in spans if s.page == 2 and s.type == "ORG" and s.view == "layout"]
    assert ("Broad Family Trust", 0.9) in p2_orgs
    assert ("Broad", 0.6) in p2_orgs                   # "Mr. Broad": honorific before -> gated hit
    assert all("broad" != t for t, _ in p2_orgs)       # "a broad range" untouched
    assert not [s for s in spans if s.page == 1 and s.type == "PERSON"]   # confirmed mention is not re-emitted


def test_propagate_variants():
    v = propagate.variants(Span(1, 0, 0, "Mr. Kushal Subbayya Hegde", "PERSON", "gliner", 1.0, "layout"))
    assert {"Kushal Subbayya Hegde", "Hegde", "K. S. Hegde", "K.S. Hegde"} <= v


# ---------------- LLM ----------------

def test_llm_locate_whitespace_broken():
    text = "Promoter: K U S H A L\nS U B B A Y Y A HEGDE, Pune"
    assert llm_finder.locate(text, "KUSHAL SUBBAYYA HEGDE") == [(10, 43)]
    assert text[10:43] == "K U S H A L\nS U B B A Y Y A HEGDE"
    assert llm_finder.locate("a b a b", "a b") == [(0, 3), (4, 7)]
    assert llm_finder.locate(text, "nowhere") == []


def test_llm_unlocatable_item_is_recorded(monkeypatch):
    monkeypatch.setattr(llm_finder, "call_llm", lambda *a: {"items": [{"text": "Nobody Here", "type": "PERSON"}]})
    llm_finder.unlocated.clear()
    assert llm_finder.find(make_page(1, "Some text without that name."), TYPES, CFG) == []
    assert llm_finder.unlocated == [{"page": 1, "text": "Nobody Here", "type": "PERSON"}]


def _ollama_ready() -> bool:
    try:
        tags = requests.get(f"{CFG['llm']['base_url']}/api/tags", timeout=2).json()
        return any(m["name"].startswith(CFG["llm"]["model"]) for m in tags.get("models", []))
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason=f"Ollama model {CFG['llm']['model']} not available yet")
def test_llm_finder_ollama_live():
    if CFG["llm"]["provider"] != "ollama":
        pytest.skip("llm.provider is not ollama")
    page = make_page(1, SAMPLE)
    spans = llm_finder.find(page, TYPES, CFG)
    texts = {s.type: s.text for s in spans}
    assert any("Malvadkar" in s.text for s in spans if s.type == "PERSON"), texts
    assert "cs.connect@kshinternational.com" in [s.text for s in spans if s.type == "EMAIL"], texts
