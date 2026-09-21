"""Entity propagation: after the first mention of a PERSON/ORG/EMAIL/PHONE is confirmed, string-search
every page's views for its variants. Whole-word matches only; single tokens that are ordinary
English words are gated (DESIGN step 8b)."""
from __future__ import annotations

import re

from pii_redact.model import Doc, Span
from pii_redact.finders.regex_finder import make_span

PROPAGATED_TYPES = {"PERSON", "ORG", "EMAIL", "PHONE"}
HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "smt", "shri", "sh", "dr", "prof", "kumari", "master"}
ORG_GENERIC = {"family", "trust", "limited", "ltd", "private", "pvt", "llp", "inc", "company", "co",
               "group", "holdings", "industries", "international", "enterprises", "corporation", "corp",
               "foundation", "bank", "and", "&", "sons", "brothers", "associates", "partners", "ventures"}

# Ordinary English words that are also names. Single-token variants in this set are gated.
COMMON_WORDS = set("""
a able about above act action add after again age air all also always among angel apple april area arm art
ash at august autumn back bank bar base bay beach bear beauty bell belle berry best bill bird bishop black
blade blaze bliss block blue board bold bond book boost boss bow box boy bridge bright broad brook brown
buck bud bull burn bush by call candy cap card care carol case cash castle cat chance chase cherry chip
church city clay clear cliff close cloud coal coast cold cool cost country court cross crown crystal cut dale
dawn day dean deep dell den destiny dew diamond dice dish dock dove down draw dream drew dust earl early
earth east ease ember end even ever everest fair faith fall fame fancy far fast fawn fern field fine fire
first fish flag flint flood flower ford forest fox frank free frost fry gale garden gate gay gem general
gentle gift glen glory gold grace grant gray green grey grove guy hail hall harbor hardy harmony harper
hart haven hay hazel heart heath heaven hedge herb hill holly home honey hope hunt hunter ice iris ivory
ivy jack jade jasmine jay jazz jet jewel joy judge june just kay kid king knight lace lake lane lark last
lead leaf lee level light lily line link lion little lock long love luck main major man march marina mark
marsh mason may meadow mercy merry mild mill miller mint miss mist moon more moss mount myrtle nash neat
nice night noble north oak ocean olive orange page paige palm park patience pearl penny pepper pike pine
plain plant plum poppy port price pride prince prior quick rain rainbow ray reed rich ridge ring river
road robin rock rose ruby rush rust sage sail saint sand scout sea sean seed serene shade shadow shark
sharp shine shore short silver skip sky slate smart smith snow soft solid song south spark speed spring
star steel stone storm strong summer sun sunny sweet swift tag tan tank temple thorn tide top tower town
trace trust twin vale valley van vine violet wade wall ward water wave way weather web well west white
wild will win wind winter wise wolf wood woods worth wren yard year young zip
rakhi sandesh anand bijlee
""".split())


def _tokens(s: str) -> list[str]:
    return s.split()


def _strip_honorific(tokens: list[str]) -> list[str]:
    while tokens and tokens[0].rstrip(".").lower() in HONORIFICS:
        tokens = tokens[1:]
    return tokens


def variants(span: Span) -> set[str]:
    """Variant strings for one confirmed span (searched case-insensitively)."""
    text = " ".join(_tokens(span.text))
    out = {text}
    if span.type == "PERSON":
        toks = _strip_honorific(_tokens(text))
        if toks:
            out.add(" ".join(toks))
            if len(toks) >= 2:
                out.add(toks[-1])                                              # surname alone
                inits = [t[0] + "." for t in toks[:-1]]
                out.add(" ".join(inits + [toks[-1]]))                          # K. S. Hegde
                out.add("".join(inits) + " " + toks[-1])                       # K.S. Hegde
    elif span.type == "ORG":
        toks = _tokens(text)
        core = [t for t in toks if t.lower().strip(".,") not in ORG_GENERIC]
        if core and len(core) < len(toks):
            out.add(" ".join(core))                                            # "Broad" from "Broad Family Trust"
    return {v for v in out if v}


def _pattern(variant: str, whitespace_free: bool) -> re.Pattern:
    if whitespace_free:   # PHONE: digits may be spaced differently on other pages
        body = r"\s*".join(re.escape(c) for c in variant if not c.isspace())
    else:
        body = r"\s+".join(re.escape(t) for t in _tokens(variant))
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)


def is_common(token: str) -> bool:
    return token.lower() in COMMON_WORDS


def _gate_ok(text: str, s: int, e: int, known_tokens: set[str]) -> bool:
    """Common-word single token: must be Title-case AND (honorific before OR adjacent known name token)."""
    if not text[s:e].istitle():
        return False
    before = re.findall(r"[A-Za-z][A-Za-z.]*", text[max(0, s - 40):s])
    after = re.findall(r"[A-Za-z][A-Za-z.]*", text[e:e + 40])
    prev = before[-1] if before else ""
    nxt = after[0] if after else ""
    if prev.rstrip(".").lower() in HONORIFICS:
        return True
    return prev.lower() in known_tokens or nxt.lower() in known_tokens


def find(doc: Doc, confirmed: list[Span], types: list[dict], cfg: dict) -> list[Span]:
    enabled = {t["name"] for t in types} & PROPAGATED_TYPES
    confirmed = [c for c in confirmed if c.type in enabled]
    if not confirmed:
        return []
    gated = cfg.get("judge", {}).get("common_word_names_gated", True)

    known_tokens = set()
    for c in confirmed:
        if c.type in ("PERSON", "ORG"):
            known_tokens |= {t.lower() for t in _strip_honorific(_tokens(c.text)) if len(t) > 1 and not is_common(t)}

    searches = []   # (type, pattern, single_common, confidence)
    seen_variant = set()
    for c in confirmed:
        for v in variants(c):
            key = (c.type, v.lower())
            if key in seen_variant:
                continue
            seen_variant.add(key)
            single = len(_tokens(v)) == 1
            common = single and c.type in ("PERSON", "ORG") and is_common(v) and gated
            searches.append((c.type, _pattern(v, c.type == "PHONE"), common, 0.6 if common else 0.9))

    out = []
    for page in doc.pages:
        for view_name, view in page.views.items():
            taken = {w for c in confirmed if c.page == page.page_no for w in c.word_ids}
            found = set()
            for typ, pat, common, conf in searches:
                for m in pat.finditer(view.text):
                    s, e = m.span()
                    if (s, e, typ) in found or taken & set(view.word_ids(s, e)):   # already confirmed
                        continue
                    if common and not _gate_ok(view.text, s, e, known_tokens):
                        continue
                    found.add((s, e, typ))
                    out.append(make_span(page, view_name, s, e, typ, "propagate", conf))
    return sorted(out, key=lambda sp: (sp.page, sp.view, sp.start, sp.end))
