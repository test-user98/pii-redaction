"""Precision rules: structured-type shape gate, short spans, single-token ORG context, verify needles,
DIN context carried over from the previous page, slash-joined names, LLM JSON fences."""
import pytest

from pii_redact.config import pii_types
from pii_redact.finders import llm_finder, regex_finder
from pii_redact.judge import judge, shape_ok
from pii_redact.model import Page, Span, Word
from pii_redact.normalize import build_views
from pii_redact.verify import _needle_ok

TYPES = pii_types()
BY_NAME = {t["name"]: t for t in TYPES}
CFG = {"judge": {"drop_single_finder_below": 0.5, "review_single_finder_below": 0.7}}


def span(text, type_, finder="llm", conf=0.8, page=1, word_ids=(1,), view="layout", start=0):
    return Span(page=page, start=start, end=start + len(text), text=text, type=type_, finder=finder,
                confidence=conf, view=view, word_ids=list(word_ids))


def text_page(text: str, page_no: int = 1) -> Page:
    """One Word per whitespace token, all on one line, so views are just the text."""
    words = [Word(id=i, page=page_no, text=t, loc={"bbox": (i * 10.0, 0.0, i * 10.0 + 9.0, 5.0)})
             for i, t in enumerate(text.split())]
    page = Page(page_no=page_no, words=words)
    page.views = build_views(page)
    return page


# ---------------------------------------------------------------- 1. judge shape gate

@pytest.mark.parametrize("text,type_", [
    ("5,587.12", "CREDIT_CARD"), ("19,282.93", "CREDIT_CARD"), ("53.97%", "SSN"), ("100", "PHONE"),
    ("Telephone", "PHONE"), ("Three-month period ended June 30, 2025", "DOB"), ("PAN", "PAN"), ("PAT", "PAN"),
    ("M-140388", "PAN"), ("116417W", "DIN"), ("July 30, 1979", "DOB"), ("189 178 168 161", "PHONE"),
])
def test_structured_junk_is_dropped_whoever_found_it(text, type_):
    assert not shape_ok(span(text, type_), BY_NAME[type_])
    page = Page(page_no=1, words=[])
    page.spans = [span(text, type_, finder="gliner+llm", conf=0.95)]      # even with two finders
    kept, review = judge(page, TYPES, CFG)
    assert kept == [] and review == []


@pytest.mark.parametrize("text,type_", [
    ("0013507 0", "DIN"), ("05293084", "DIN"), ("+ 91 20\n45053237", "PHONE"), ("+91 22 4009 4400", "PHONE"),
    ("NBWPS1951N", "PAN"), ("PAN NBWPS 1951N", "PAN"), ("Email: ksh@icicisecurities.com", "EMAIL"),
    ("06/05/2000", "DOB"), ("4111 1111 1111 1111", "CREDIT_CARD"),
])
def test_real_identifiers_pass_the_shape_gate(text, type_):
    assert shape_ok(span(text, type_), BY_NAME[type_])
    page = Page(page_no=1, words=[])
    page.spans = [span(text, type_, finder="llm", conf=0.8)]
    kept, _ = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == [text]


def test_short_and_letterless_spans_are_dropped():
    page = Page(page_no=1, words=[])
    page.spans = [span("mer", "ADDRESS"), span("Sup", "ORG", "gliner+llm", 0.9), span("Al", "PERSON", "gliner+llm", 0.9),
                  span("26,570 1.36", "ADDRESS", "gliner", 0.9), span("I-Sec Limited", "ORG", "gliner+llm", 0.9)]
    kept, review = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == ["I-Sec Limited"] and review == []


def test_single_token_org_needs_corporate_context():
    page = text_page("Legal Counsel to our Company as to Indian Law Trilegal One World Centre . "
                     "expansion at our Supa Facility ; Mega Volt-Amperes ; Reliance on customers")
    t = page.views["layout"].text

    def at(word, type_="ORG", finder="gliner", conf=0.9):
        i = t.index(word)
        return span(word, type_, finder, conf, start=i, word_ids=page.views["layout"].word_ids(i, i + len(word)))

    page.spans = [at("Trilegal"), at("Supa"), at("Mega", finder="propagate"), at("Reliance", finder="gliner+propagate"),
                  at("Supa Facility")]
    kept, review = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == ["Trilegal", "Supa Facility"]        # "Counsel" nearby; two tokens
    assert [s.text for s in review] == ["Supa", "Mega", "Reliance"]       # propagate is not a second finder
    page.spans = [at("Supa", finder="gliner+llm")]
    kept, review = judge(page, TYPES, CFG)
    assert [s.text for s in kept] == ["Supa"]                             # two real finders agree: kept


# ---------------------------------------------------------------- 2. verify needles

def test_verify_needles_skip_junk_but_keep_real_values():
    phone_generic = {w.lower() for w in BY_NAME["PHONE"]["generic_words"]}
    for junk in ["PAN", "mer", "Supa", "2025", "100", "Telephone", "Tel. No."]:
        assert not _needle_ok(junk, phone_generic), junk
    for real in ["Sarthak Malvadkar", "+91 20 4505 3237", "4505 3237", "NBWPS1951N", "0529308 4", "I-Sec"]:
        assert _needle_ok(real, phone_generic), real


# ---------------------------------------------------------------- 3. DIN context from the previous page

def test_din_context_carries_over_from_previous_page():
    cfg = dict(CFG)
    p110 = text_page("Name Designation DIN Address", 110)
    p111 = text_page("Indu Jacob Independent Director 05293084 A29 Pashan Road", 111)
    p112 = text_page("Some other table 05293085 with no header before it", 112)
    lonely = text_page("Some other table 05293086 with no header anywhere", 200)
    for p in (p110, p111, p112, lonely):
        p.spans = regex_finder.find(p, TYPES, cfg)                       # parallel in the pipeline
    assert not [s for s in p111.spans if s.type == "DIN"]                # parked, not returned
    assert cfg["_doc_context_seen"][110] == {"din"}
    for p in (p110, p111, p112, lonely):                                 # judge runs in page order
        kept, _ = judge(p, TYPES, cfg)
        p.spans = kept
    assert [s.text for s in p111.spans if s.type == "DIN"] == ["05293084"]
    assert p111.spans[0].finder == "regex" and p111.spans[0].confidence == 1.0
    assert not [s for s in p112.spans if s.type == "DIN"]                # 111 showed no header
    assert not [s for s in lonely.spans if s.type == "DIN"]
    assert not cfg["_doc_context_pending"]                               # everything was consumed


# ---------------------------------------------------------------- 4. slash-joined names

def test_slash_joined_names_become_separate_words():
    page = Page(page_no=6, words=[Word(0, 6, "Person:", {"bbox": (0, 0, 30, 5)}),
                                  Word(1, 6, "Kishan", {"bbox": (30, 0, 60, 5)}),
                                  Word(2, 6, "Rastogi/Abhijit", {"bbox": (60, 0, 210, 5)}),
                                  Word(3, 6, "Diwan", {"bbox": (210, 0, 240, 5)}),
                                  Word(4, 6, "and/or", {"bbox": (0, 10, 60, 15)}, block=1),
                                  Word(5, 6, "www.x.in/a/b", {"bbox": (0, 20, 60, 25)}, block=2),
                                  Word(6, 6, "997/8", {"bbox": (0, 30, 60, 35)}, block=3)])
    views = build_views(page)
    assert views["layout"].text == "Person: Kishan Rastogi/ Abhijit Diwan\nand/ or\nwww.x.in/a/b\n997/8"
    assert [w.text for w in page.words] == ["Person:", "Kishan", "Rastogi/", "Abhijit", "Diwan", "and/", "or", "www.x.in/a/b", "997/8"]
    assert [w.id for w in page.words] == list(range(9))
    assert page.words[2].loc["bbox"] == (60.0, 0, 140.0, 5) and page.words[3].loc["bbox"] == (140.0, 0, 210.0, 5)
    t = views["layout"].text
    assert views["layout"].word_ids(t.index("Kishan"), t.index("Rastogi/") + 8) == [1, 2]
    assert views["layout"].word_ids(t.index("Abhijit"), t.index("Diwan") + 5) == [3, 4]
    assert build_views(page)["layout"].text == t                          # idempotent


# ---------------------------------------------------------------- 5. LLM JSON with fences / prose

@pytest.mark.parametrize("reply", [
    '{"items": [{"text": "a", "type": "PERSON"}]}',
    '```json\n{"items": [{"text": "a", "type": "PERSON"}]}\n```',
    'Here you go:\n```json\n{"items": [{"text": "a", "type": "PERSON"}]}\n```\nLet me know if you need more.',
])
def test_parse_json_strips_fences_and_prose(reply):
    assert llm_finder._parse_json(reply) == {"items": [{"text": "a", "type": "PERSON"}]}


def test_parse_json_without_object_raises():
    with pytest.raises(ValueError):
        llm_finder._parse_json("no entities found")
