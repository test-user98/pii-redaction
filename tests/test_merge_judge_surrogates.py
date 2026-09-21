"""Hand-built Pages/Spans/Docs; no parser or finder dependency."""
import csv
import re
import sys
import threading

from pii_redact.judge import is_exempt, judge
from pii_redact.merge import merge
from pii_redact.model import Doc, Entity, Page, PageText, Span, Word
from pii_redact.surrogates import assign_surrogates, cluster_entities, mention_surrogate, write_mapping

CFG = {"judge": {"drop_single_finder_below": 0.5, "review_single_finder_below": 0.7},
       "surrogates": {"salt": "salt-A"}}
ORG_CFG = {"name": "ORG", "policy": "redact",
           "allowlist": ["SEBI", "Securities and Exchange Board of India", "BSE", "NSE", "RoC", "Ministry of"]}
TYPES = [{"name": "PERSON", "policy": "redact"}, ORG_CFG, {"name": "PAN", "policy": "redact"}]


def span(text, type_, finder="gliner", conf=0.9, page=1, word_ids=(), start=0):
    return Span(page=page, start=start, end=start + len(text), text=text, type=type_, finder=finder,
                confidence=conf, view="layout", word_ids=list(word_ids))


def doc_with(*spans):
    pages = {}
    for s in spans:
        pages.setdefault(s.page, Page(page_no=s.page, words=[])).spans.append(s)
    return Doc(doc_id="d1", path="x", fmt="pdf", pages=[pages[k] for k in sorted(pages)])


# ---------------------------------------------------------------- merge

def test_merge_keeps_longer_span_and_joins_finders():
    page = Page(page_no=1, words=[])
    page.spans = [span("Hegde", "PERSON", "gliner", 0.6, word_ids=[3]),
                  span("Kushal Subbayya Hegde", "PERSON", "llm", 0.8, word_ids=[1, 2, 3]),
                  span("ABCDE1234F", "PAN", "regex", 1.0, word_ids=[9])]
    out = merge(page)
    assert [s.text for s in out] == ["Kushal Subbayya Hegde", "ABCDE1234F"]
    assert out[0].finder == "gliner+llm" and out[0].confidence == 0.8
    assert out[1].finder == "regex"


def test_merge_maps_word_ids_from_view_and_prefers_validated_regex_type():
    words = [Word(id=i, page=1, text=t, loc={}) for i, t in enumerate(["PAN", "ABCDE1234F"])]
    text = "PAN ABCDE1234F"
    char_word = [0, 0, 0, -1] + [1] * 10
    page = Page(page_no=1, words=words, views={"layout": PageText(1, "layout", text, char_word)})
    page.spans = [span("ABCDE1234F", "PAN", "regex", 1.0, start=4),
                  span("ABCDE1234F", "PERSON", "gliner", 0.95, start=4)]
    out = merge(page)
    assert len(out) == 1 and out[0].word_ids == [1]
    assert out[0].type == "PAN" and out[0].finder == "regex+gliner" and out[0].confidence == 1.0


def test_merge_validated_regex_sets_boundaries_over_longer_llm_span():
    page = Page(page_no=1, words=[])
    page.spans = [span("PAN NBWPS 1951N", "PAN", "llm", 0.8, word_ids=[1, 2, 3]),
                  span("NBWPS 1951N", "PAN", "regex", 1.0, word_ids=[2, 3]),
                  span("Kushal Hegde Ltd", "ORG", "llm", 0.8, word_ids=[7, 8, 9]),
                  span("Kushal Hegde", "PERSON", "gliner", 0.9, word_ids=[7, 8])]
    out = merge(page)
    assert [s.text for s in out] == ["NBWPS 1951N", "Kushal Hegde Ltd"]      # regex wins; else longer wins
    assert out[0].word_ids == [2, 3] and out[0].type == "PAN"
    assert out[0].finder == "regex+llm" and out[0].confidence == 1.0
    assert out[1].type == "PERSON" and out[1].finder == "gliner+llm"   # GLiNER type beats LLM type


# ---------------------------------------------------------------- judge

def test_judge_thresholds():
    page = Page(page_no=1, words=[])
    page.spans = [span("Low", "PERSON", "gliner", 0.3, word_ids=[1]),
                  span("Mid", "PERSON", "gliner", 0.6, word_ids=[2]),
                  span("Both", "PERSON", "gliner+llm", 0.3, word_ids=[3]),
                  span("High", "PERSON", "llm", 0.9, word_ids=[4])]
    kept, review = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == ["Both", "High"]
    assert [s.text for s in review] == ["Mid"]


def test_allowlist():
    assert is_exempt("Securities and Exchange Board of India", ORG_CFG)
    assert is_exempt("SEBI", ORG_CFG)
    assert is_exempt("the sebi circular", ORG_CFG)
    assert not is_exempt("ICICI Securities Limited", ORG_CFG)
    assert not is_exempt("Procter & Gamble", ORG_CFG)      # "RoC" must not match inside a word
    page = Page(page_no=1, words=[])
    page.spans = [span("SEBI", "ORG", "gliner+llm", 0.9, word_ids=[1]),
                  span("ICICI Securities Limited", "ORG", "gliner", 0.9, word_ids=[2, 3, 4])]
    kept, review = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == ["ICICI Securities Limited"] and review == []


# ---------------------------------------------------------------- clustering

def person_doc():
    return doc_with(
        span("Kushal Subbayya Hegde", "PERSON", page=1, word_ids=[1, 2, 3]),
        span("KUSHAL SUBBAYYA HEGDE", "PERSON", page=1, word_ids=[10, 11, 12]),
        span("rohan.dey@gmail.com", "EMAIL", "regex", 0.8, page=1, word_ids=[20]),
        span("Mr. Hegde", "PERSON", page=2, word_ids=[1, 2]),
        span("Rajesh Kushal Hegde", "PERSON", page=2, word_ids=[5, 6, 7]),
        span("Rohan Dey", "PERSON", page=3, word_ids=[1, 2]),
        span("+91 81081 14949", "PHONE", "regex", 1.0, page=3, word_ids=[4, 5, 6]),
        span("ABCPE1234F", "PAN", "regex", 1.0, page=3, word_ids=[8]),
        span("ICICI Securities Limited", "ORG", page=3, word_ids=[9, 10, 11]),
    )


def test_clustering_links_partials_and_assigns_ids():
    ents = cluster_entities(person_doc())
    by_id = {e.id: e for e in ents}
    assert [e.id for e in ents] == ["P1", "EMAIL1", "P2", "P3", "PHONE1", "PAN1", "ORG1"]
    assert [m.text for m in by_id["P1"].mentions] == ["Kushal Subbayya Hegde", "KUSHAL SUBBAYYA HEGDE", "Mr. Hegde"]
    assert by_id["P1"].canonical == "Kushal Subbayya Hegde"
    assert by_id["P2"].canonical == "Rajesh Kushal Hegde"
    assert by_id["P3"].canonical == "Rohan Dey"


def assigned(salt="salt-A"):
    doc = person_doc()
    ents = cluster_entities(doc)
    assign_surrogates(ents, {"surrogates": {"salt": salt}})
    return doc, {e.id: e for e in ents}


def test_surrogates_deterministic_and_salt_dependent():
    _, a = assigned()
    _, b = assigned()
    _, c = assigned("salt-B")
    assert [a[k].surrogate for k in a] == [b[k].surrogate for k in b]
    assert [a[k].surrogate for k in a] != [c[k].surrogate for k in c]
    assert all(a[k].surrogate != a[k].canonical for k in a)


def test_concurrent_assign_matches_serial():
    """Two jobs interleaving must not perturb each other: surrogates are a function of (salt, values) only."""
    _, serial = assigned()
    expected = {k: (serial[k].surrogate, serial[k].name_tokens) for k in serial}
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                   # force thread switches inside assign_surrogates
    try:
        for _ in range(20):
            barrier, results = threading.Barrier(2), [None, None]

            def work(i):
                doc = person_doc()
                ents = cluster_entities(doc)
                barrier.wait()
                assign_surrogates(ents, CFG)
                results[i] = {e.id: (e.surrogate, e.name_tokens) for e in ents}

            threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert results[0] == expected and results[1] == expected
    finally:
        sys.setswitchinterval(interval)


def test_token_consistency_across_entities_and_mentions():
    _, e = assigned()
    p1, p2 = e["P1"], e["P2"]
    fake_surname = p1.name_tokens["Hegde"]
    assert p2.name_tokens["Hegde"] == fake_surname
    assert p2.name_tokens["Kushal"] == p1.name_tokens["Kushal"]
    assert p1.surrogate.split() == [p1.name_tokens["Kushal"], p1.name_tokens["Subbayya"], fake_surname]
    assert p2.surrogate.split() == [p2.name_tokens["Rajesh"], p1.name_tokens["Kushal"], fake_surname]
    mr = p1.mentions[2]
    assert mention_surrogate(p1, mr) == f"Mr. {fake_surname}"
    upper = p1.mentions[1]
    assert mention_surrogate(p1, upper) == p1.surrogate.upper()
    initials = span("K. S. Hegde", "PERSON")
    assert mention_surrogate(p1, initials) == f"{p1.name_tokens['Kushal'][0]}. {p1.name_tokens['Subbayya'][0]}. {fake_surname}"


def test_email_follows_person_surrogate():
    _, e = assigned()
    rohan = e["P3"]
    expected = f"{rohan.name_tokens['Rohan'].lower()}.{rohan.name_tokens['Dey'].lower()}@example.com"
    assert e["EMAIL1"].surrogate == expected


def test_phone_pan_org_surrogates():
    _, e = assigned()
    phone = e["PHONE1"].surrogate
    assert phone.startswith("+91 ") and len(phone) == len("+91 81081 14949")
    assert re.fullmatch(r"\+91 \d{5} \d{5}", phone) and phone != "+91 81081 14949"
    dashed = span("+91-81081-14949", "PHONE")
    assert mention_surrogate(e["PHONE1"], dashed) == phone.replace(" ", "-")
    pan = e["PAN1"].surrogate
    assert re.fullmatch(r"[A-Z]{3}[ABCFGHLJPTK][A-Z][0-9]{4}[A-Z]", pan) and pan != "ABCPE1234F"
    org = e["ORG1"].surrogate
    assert org.endswith(" Limited") and org != "ICICI Securities Limited"


def test_structured_and_address_surrogates():
    doc = doc_with(span("1234 5678 9012", "AADHAAR", "regex", 1.0, word_ids=[1]),
                   span("4111 1111 1111 1111", "CREDIT_CARD", "regex", 1.0, word_ids=[2]),
                   span("27ABCPE1234F1Z5", "GSTIN", "regex", 0.8, word_ids=[3]),
                   span("HDFC0001234", "IFSC", "regex", 0.8, word_ids=[4]),
                   span("12/05/1985", "DOB", "regex", 0.8, word_ids=[5]),
                   span("Plot 12, MG Road\nPune 411001", "ADDRESS", "gliner", 0.9, word_ids=[6]),
                   span("192.168.1.10", "IP", "regex", 1.0, word_ids=[7]))
    ents = cluster_entities(doc)
    assign_surrogates(ents, CFG)
    s = {e.type: e.surrogate for e in ents}
    assert re.fullmatch(r"\d{4} \d{4} \d{4}", s["AADHAAR"]) and s["AADHAAR"] != "1234 5678 9012"
    assert re.fullmatch(r"\d{4} \d{4} \d{4} \d{4}", s["CREDIT_CARD"])
    assert re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", s["GSTIN"])
    assert re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", s["IFSC"])
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", s["DOB"]) and s["DOB"] != "12/05/1985"
    assert s["ADDRESS"].count("\n") == 1
    assert s["IP"].startswith(("192.0.2.", "198.51.100.", "203.0.113."))


def test_name_length_matching():
    ents = [Entity(id="P1", type="PERSON", canonical="Kushal Subbayya Hegde",
                   mentions=[span("Kushal Subbayya Hegde", "PERSON", word_ids=[1, 2, 3])])]
    for salt in ["a", "b", "c", "d", "e"]:
        assign_surrogates(ents, {"surrogates": {"salt": salt}})
        for real, fake in ents[0].name_tokens.items():
            assert 0.8 * len(real) <= len(fake) <= 1.2 * len(real), (salt, real, fake)
        assert 0.8 * 21 <= len(ents[0].surrogate) <= 1.2 * 21


def test_write_mapping(tmp_path):
    doc, e = assigned()
    write_mapping(doc, tmp_path)
    rows = list(csv.DictReader(open(tmp_path / "mapping.csv")))
    assert len(rows) == len(e) == 7
    p1 = next(r for r in rows if r["entity_id"] == "P1")
    assert p1["mention_count"] == "3" and p1["pages"] == "1;2" and p1["surrogate"] == e["P1"].surrogate
    assert (tmp_path / "mapping.json").exists()
