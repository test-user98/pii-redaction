"""Step 8 — entity clustering and deterministic, type-aware surrogates.

cluster_entities(doc)            -> list[Entity]  (also stored on doc.entities)
assign_surrogates(entities, cfg) -> None          (cfg = backends() dict; uses cfg["surrogates"]["salt"])
mention_surrogate(entity, span)  -> str
write_mapping(doc, out_dir)      -> mapping.json + mapping.csv

Names are mapped token by token: each real token gets its own HMAC seed, so
"Hegde" becomes the same fake surname in every entity that contains it.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

from .model import Doc, Entity, Span

HONORIFICS = {"mr", "mrs", "ms", "smt", "shri", "dr", "kum"}
ID_PREFIX = {"PERSON": "P", "ADDRESS": "ADDR"}          # other types use their name
SHAPE_TYPES = {"PHONE", "PAN", "AADHAAR", "CREDIT_CARD", "DIN", "SSN", "GSTIN", "IFSC"}
LENGTH_TRIES = 20

_ORG_SUFFIX = re.compile(
    r"\s*(private limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llp|inc\.?|corporation|corp\.?|plc|"
    r"trust|bank|&\s*co\.?|and co\.?)\s*$", re.IGNORECASE)
_FAKER_SUFFIX = re.compile(r",? (Inc|LLC|PLC|Ltd|Group|and Sons)$")
_TOKEN = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)
_faker = Faker("en_US")


# ---------------------------------------------------------------- normalisation

def _is_honorific(tok: str) -> bool:
    return tok.rstrip(".").casefold() in HONORIFICS


def _is_initial(tok: str) -> bool:
    return re.fullmatch(r"[A-Za-z]\.?", tok) is not None


def _name_tokens(text: str) -> list[str]:
    """Name tokens without honorifics or surrounding punctuation."""
    out = []
    for tok in text.split():
        core = _TOKEN.match(tok).group(2)
        if core and not _is_honorific(core):
            out.append(core)
    return out


def _strip_honorifics(text: str) -> str:
    return " ".join(t for t in text.split() if not _is_honorific(t))


def normalize(type_: str, text: str) -> str:
    if type_ == "PERSON":
        return " ".join(t.casefold() for t in _name_tokens(text))
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


def _pos(span: Span) -> tuple[int, int]:
    return (span.page, min(span.word_ids) if span.word_ids else span.start)


# ---------------------------------------------------------------- clustering

def _subseq(part: list[str], full: list[str]) -> bool:
    """part is an ordered subsequence of full; a one-letter token matches by initial."""
    i = 0
    for tok in part:
        while i < len(full) and not (tok == full[i] or (len(tok) == 1 and full[i].startswith(tok))):
            i += 1
        if i == len(full):
            return False
        i += 1
    return True


def cluster_entities(doc: Doc) -> list[Entity]:
    spans = sorted((s for p in doc.pages for s in p.spans), key=_pos)
    groups: dict[tuple[str, str], Entity] = {}
    for s in spans:
        key = (s.type, normalize(s.type, s.text))
        if not key[1]:
            continue
        groups.setdefault(key, Entity(id="", type=s.type, canonical="")).mentions.append(s)

    # PERSON: link partial mentions (surname, initials, dropped middle name) to a full-name entity.
    persons = [(norm.split(), e, order) for order, ((t, norm), e) in enumerate(groups.items()) if t == "PERSON"]
    targets: list[tuple[list[str], Entity, int]] = []
    linked: list[Entity] = []
    for toks, ent, order in sorted(persons, key=lambda x: (-len(x[0]), x[2])):
        cands = [c for c in targets if len(c[0]) > len(toks) and _subseq(toks, c[0])]
        if cands:
            # prefer a surname match, then the earliest-appearing entity
            best = min(cands, key=lambda c: (c[0][-1] != toks[-1], c[2]))
            best[1].mentions.extend(ent.mentions)
            linked.append(ent)
        elif len(toks) >= 2 and not any(len(t) == 1 for t in toks):
            targets.append((toks, ent, order))

    entities = [e for e in groups.values() if not any(e is x for x in linked)]
    for e in entities:
        e.mentions.sort(key=_pos)
        if e.type == "PERSON":
            longest = max(e.mentions, key=lambda m: (len(_name_tokens(m.text)), -_pos(m)[0], -_pos(m)[1]))
            e.canonical = _strip_honorifics(longest.text)
        else:
            e.canonical = "\n".join(" ".join(line.split()) for line in e.mentions[0].text.split("\n"))
    entities.sort(key=lambda e: _pos(e.mentions[0]))

    counters: dict[str, int] = {}
    for e in entities:
        prefix = ID_PREFIX.get(e.type, e.type)
        counters[prefix] = counters.get(prefix, 0) + 1
        e.id = f"{prefix}{counters[prefix]}"
    doc.entities = entities
    return entities


# ---------------------------------------------------------------- surrogates

def _seed(salt: str, key: str) -> int:
    return int(hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()[:16], 16)


def _length_match(real: str, gen) -> str:
    lo, hi = 0.8 * len(real), 1.2 * len(real)
    best = None
    for _ in range(LENGTH_TRIES):
        cand = gen()
        if lo <= len(cand) <= hi:
            return cand
        if best is None or abs(len(cand) - len(real)) < abs(len(best) - len(real)):
            best = cand
    return best


def _match_case(real: str, fake: str) -> str:
    if len(real) > 1 and real.isupper():
        return fake.upper()
    if real.islower():
        return fake.lower()
    return fake


def _render_person(entity: Entity, text: str) -> str:
    lookup = {k.casefold(): v for k, v in entity.name_tokens.items()}
    out = []
    for tok in text.split():
        pre, core, post = _TOKEN.match(tok).groups()
        if not core or _is_honorific(core):
            out.append(tok)
            continue
        if core.casefold() in lookup:
            fake = lookup[core.casefold()]
        elif _is_initial(core):
            hit = next((v for k, v in lookup.items() if k.startswith(core[0].casefold())), core)
            fake = hit[0] + core[1:]
        else:
            fake = core                         # unseen token: mentions are all known at assign time
        out.append(pre + _match_case(core, fake) + post)
    return " ".join(out)


def _fit(skeleton: str, chars: str) -> str:
    """Drop chars into the alnum slots of skeleton, keeping spaces and punctuation."""
    it = iter(chars)
    return "".join(next(it) if c.isalnum() else c for c in skeleton)


def _alnum(text: str) -> str:
    return "".join(c for c in text if c.isalnum())


def _letters(n: int) -> str:
    return "".join(_faker.random_uppercase_letter() for _ in range(n))


def _digits(n: int) -> str:
    return "".join(str(_faker.random_digit()) for _ in range(n))


def _same_shape(text: str) -> str:
    out = []
    for c in text:
        if c.isdigit():
            out.append(str(_faker.random_digit()))
        elif c.isalpha():
            out.append(_faker.random_uppercase_letter() if c.isupper() else _faker.random_lowercase_letter())
        else:
            out.append(c)
    return "".join(out)


def _luhn_check(digits: str) -> str:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:                      # positions that get doubled once the check digit is appended
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return str((10 - total % 10) % 10)


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_VINV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def _verhoeff_check(digits: str) -> str:
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VD[c][_VP[(i + 1) % 8][int(d)]]
    return str(_VINV[c])


def _pan_compact(holder: str) -> str:
    return _letters(3) + holder + _letters(1) + _digits(4) + _letters(1)


def _gen_pan(text: str) -> str:
    s = _alnum(text).upper()
    if len(s) != 10:
        return _same_shape(text)
    return _fit(text, _pan_compact(s[3]))       # 4th char = holder type (P person, C company); not identifying


def _gen_aadhaar(text: str) -> str:
    if len(_alnum(text)) != 12:
        return _same_shape(text)
    body = str(_faker.random_int(2, 9)) + _digits(10)
    return _fit(text, body + _verhoeff_check(body))


def _gen_card(text: str) -> str:
    n = len(_alnum(text))
    body = _digits(n - 1)
    return _fit(text, body + _luhn_check(body))


def _gen_ssn(text: str) -> str:
    if len(_alnum(text)) != 9:
        return _same_shape(text)
    area = _faker.random_element([x for x in range(1, 900) if x != 666])
    return _fit(text, f"{area:03d}{_faker.random_int(1, 99):02d}{_faker.random_int(1, 9999):04d}")


def _gen_gstin(text: str) -> str:
    s = _alnum(text).upper()
    if len(s) != 15:
        return _same_shape(text)
    pan = _pan_compact(s[5] if s[5] in "ABCFGHLJPT" else "P")
    return _fit(text, s[:2] + pan + s[12] + "Z" + _faker.random_element("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"))


def _gen_ifsc(text: str) -> str:
    if len(_alnum(text)) != 11:
        return _same_shape(text)
    return _fit(text, _letters(4) + "0" + "".join(
        _faker.random_element("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(6)))


def _gen_ip(text: str) -> str:
    if ":" in text:
        return "2001:db8:" + ":".join(f"{_faker.random_int(0, 0xFFFF):x}" for _ in range(6))
    return _faker.random_element(["192.0.2.", "198.51.100.", "203.0.113."]) + str(_faker.random_int(1, 254))


def _gen_phone(text: str) -> str:
    m = re.match(r"\+\s?\d{1,3}", text)          # keep the country code
    keep = m.end() if m else 0
    return text[:keep] + "".join(str(_faker.random_digit()) if c.isdigit() else c for c in text[keep:])


def _gen_org(text: str) -> str:
    m = _ORG_SUFFIX.search(text)
    base, suffix = (text[:m.start()], text[m.start():]) if m and m.start() > 0 else (text, "")
    return _length_match(base, lambda: _FAKER_SUFFIX.sub("", _faker.company())) + suffix


def _gen_address(text: str) -> str:
    n = len(text.split("\n"))
    pieces = [_faker.street_address(), _faker.city(), f"{_faker.state()} {_faker.postcode()}", _faker.country()]
    if n == 1:
        return ", ".join(pieces[:3])
    while len(pieces) < n:
        pieces.append(_faker.street_name())
    return "\n".join(pieces[:n - 1] + [", ".join(pieces[n - 1:])])


def _gen_dob(text: str) -> str:
    m = re.fullmatch(r"(\d{1,2})([/-])(\d{1,2})\2(\d{4})", text.strip())
    if not m:
        return _same_shape(text)
    a, sep, b, y = int(m[1]), m[2], int(m[3]), int(m[4])
    day_first = True
    try:
        date = datetime(y, b, a)
    except ValueError:
        date = datetime(y, a, b)
        day_first = False
    date += timedelta(days=_faker.random_int(30, 400) * _faker.random_element([-1, 1]))
    first, second = (date.day, date.month) if day_first else (date.month, date.day)
    return f"{first:02d}{sep}{second:02d}{sep}{date.year}"


_GENERATORS = {
    "PHONE": _gen_phone, "ORG": _gen_org, "ADDRESS": _gen_address, "DOB": _gen_dob,
    "SSN": _gen_ssn, "CREDIT_CARD": _gen_card, "IP": _gen_ip, "PAN": _gen_pan,
    "AADHAAR": _gen_aadhaar, "DIN": lambda t: _fit(t, _digits(len(_alnum(t)))),
    "GSTIN": _gen_gstin, "IFSC": _gen_ifsc,
}


def _email_from_person(local: str, persons: list[Entity]) -> str | None:
    parts = re.split(r"([^A-Za-z]+)", local)          # alpha parts at even indexes, separators at odd
    alpha = [p.casefold() for p in parts[::2] if p]
    if not alpha:
        return None
    for person in persons:
        lookup = {k.casefold(): v.lower() for k, v in person.name_tokens.items()}
        mapped = {}
        for a in alpha:
            if a in lookup:
                mapped[a] = lookup[a]
            else:
                split = next((k for k in lookup if a.startswith(k) and a[len(k):] in lookup), None)
                if split is None:
                    break
                mapped[a] = lookup[split] + lookup[a[len(split):]]
        if len(mapped) == len(alpha):
            return "".join(mapped[p.casefold()] if i % 2 == 0 and p else p for i, p in enumerate(parts))
    return None


def assign_surrogates(entities: list[Entity], cfg: dict) -> None:
    salt = cfg["surrogates"]["salt"]
    token_fakes: dict[str, str] = {}             # casefolded real token -> fake, shared across entities

    def fake_token(tok: str, last: bool) -> str:
        key = tok.casefold()
        if key not in token_fakes:
            _faker.seed_instance(_seed(salt, "PERSON|token|" + key))
            token_fakes[key] = _length_match(tok, _faker.last_name if last else _faker.first_name)
        return token_fakes[key]

    persons = [e for e in entities if e.type == "PERSON"]
    for e in persons:
        e.name_tokens = {}
        for text in [e.canonical] + [m.text for m in e.mentions]:
            toks = _name_tokens(text)
            for i, tok in enumerate(toks):
                if not _is_initial(tok) and tok.casefold() not in {k.casefold() for k in e.name_tokens}:
                    e.name_tokens[tok] = fake_token(tok, last=(i == len(toks) - 1))
        e.surrogate = _render_person(e, e.canonical)

    for e in entities:
        if e.type == "PERSON":
            continue
        _faker.seed_instance(_seed(salt, e.type + "|" + normalize(e.type, e.canonical)))
        if e.type == "EMAIL":
            local, _, _domain = e.canonical.partition("@")
            derived = _email_from_person(local, persons)
            e.surrogate = (derived or _faker.user_name()) + "@example.com"
        else:
            e.surrogate = _GENERATORS.get(e.type, _same_shape)(e.canonical)


def mention_surrogate(entity: Entity, span: Span) -> str:
    if entity.type == "PERSON":
        return _render_person(entity, span.text)
    if entity.type in SHAPE_TYPES:
        chars = _alnum(entity.surrogate)
        if len(chars) == len(_alnum(span.text)):
            return _fit(span.text, chars)
    return _match_case(span.text, entity.surrogate)


# ---------------------------------------------------------------- mapping files

def write_mapping(doc: Doc, out_dir) -> list[dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in doc.entities:
        rows.append({
            "entity_id": e.id, "type": e.type, "real": e.canonical, "surrogate": e.surrogate,
            "mention_count": len(e.mentions), "pages": sorted({m.page for m in e.mentions}),
            "name_tokens": e.name_tokens,
            "mentions": [{"page": m.page, "text": m.text, "surrogate": mention_surrogate(e, m)} for m in e.mentions],
        })
    with open(out / "mapping.json", "w") as f:
        json.dump({"doc_id": doc.doc_id, "entities": rows}, f, indent=2, ensure_ascii=False)
    with open(out / "mapping.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entity_id", "type", "real", "surrogate", "mention_count", "pages"])
        for r in rows:
            w.writerow([r["entity_id"], r["type"], r["real"], r["surrogate"], r["mention_count"],
                        ";".join(map(str, r["pages"]))])
    return rows
