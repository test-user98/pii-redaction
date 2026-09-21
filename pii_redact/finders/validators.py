"""Checksum / format validators used by regex_finder. Each takes the matched
string (whitespace already stripped for identifier types) and returns bool."""
from __future__ import annotations

import ipaddress
import re


def luhn(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_V_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_V_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff(s: str) -> bool:
    """Aadhaar: 12 digits, first digit 2-9, Verhoeff checksum."""
    digits = re.sub(r"\D", "", s)
    if len(digits) != 12 or digits[0] in "01":
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _V_D[c][_V_P[i % 8][int(ch)]]
    return c == 0


def pan(s: str) -> bool:
    return re.fullmatch(r"[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]", re.sub(r"\s", "", s)) is not None


def phone(s: str) -> bool:
    """Indian mobile/landline in any spacing. Rejects repeated digits, year lists, round amounts."""
    digits = re.sub(r"\D", "", s)
    if len(set(digits)) == 1:
        return False
    tokens = re.findall(r"\d+", s)
    if sum(len(t) == 4 and t[:2] in ("19", "20") for t in tokens) >= 2:   # "2019 2020 21" year list
        return False
    if digits.endswith("00000"):                                      # "5000000000"
        return False
    n = len(digits)
    if n == 10:
        return digits[0] in "23456789"        # mobile 6-9, or STD code + number without trunk 0
    if n == 11:
        return digits[0] == "0"               # 0 + STD + number, or 0 + mobile
    if n == 12:
        return digits.startswith("91")
    return False


def ssn(s: str) -> bool:
    m = re.fullmatch(r"(\d{3})-(\d{2})-(\d{4})", s)
    if not m:
        return False
    area, group, serial = m.groups()
    return area not in ("000", "666") and area[0] != "9" and group != "00" and serial != "0000"


def ipv4(s: str) -> bool:
    """IPv4 with every octet <= 255. An IPv6 literal (second IP regex) is accepted if parseable."""
    if ":" in s:
        try:
            ipaddress.IPv6Address(s)
            return True
        except ValueError:
            return False
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts)
