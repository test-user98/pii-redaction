"""LLM finder (ollama | anthropic). The model returns verbatim substrings + type; we locate them
in the layout view by exact, then whitespace-insensitive search. Unlocatable items are appended
to `unlocated` for the caller to audit as `llm_unlocated`."""
from __future__ import annotations

import json
import re

from pii_redact.model import Page, Span
from pii_redact.finders.regex_finder import make_span
from pii_redact.finders.gliner_finder import chunk_text

LLM_CONFIDENCE = 0.8
unlocated: list[dict] = []   # {"page", "text", "type"}

SYSTEM = (
    "You are a PII detection engine for financial and legal documents. "
    "Find every span of personally identifiable information in the user's text. "
    "Return ONLY a JSON object of the form {\"items\": [{\"text\": \"...\", \"type\": \"...\"}]}. "
    "Each \"text\" must be copied VERBATIM from the input, character for character, including its spacing "
    "(the input may contain spaced-out letters like 'K U S H A L' or line breaks inside an address). "
    "Never invent, correct, or paraphrase. Use only these types:\n"
)


def build_system(types: list[dict]) -> str:
    return SYSTEM + "\n".join(f"- {t['name']}: {t.get('llm_hint', t['name'])}" for t in types)


def locate(text: str, needle: str) -> list[tuple[int, int]]:
    """All (start, end) of needle in text: exact first, else whitespace-insensitive. [] if not found."""
    needle = needle.strip()
    if not needle:
        return []
    hits, i = [], text.find(needle)
    while i >= 0:
        hits.append((i, i + len(needle)))
        i = text.find(needle, i + 1)
    if hits:
        return hits
    pat = r"\s*".join(re.escape(c) for c in needle if not c.isspace())
    return [m.span() for m in re.finditer(pat, text)]


def _parse_json(s: str) -> dict:
    """Take the outermost {...} of the reply: models (Haiku in particular) wrap it in ```json fences
    and may add prose before or after. Raises ValueError when there is no object at all."""
    s = re.sub(r"```(?:json)?", "", s)
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < a:
        raise ValueError(f"no JSON object in LLM reply: {s[:120]!r}")
    return json.loads(s[a:b + 1])


def _call_ollama(system: str, user: str, llm: dict) -> dict:
    import requests
    r = requests.post(f"{llm.get('base_url', 'http://localhost:11434')}/api/chat",
                      json={"model": llm["model"], "format": "json", "stream": False,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                      timeout=llm.get("timeout_s", 120))
    r.raise_for_status()
    return _parse_json(r.json()["message"]["content"])


def _call_anthropic(system: str, user: str, llm: dict) -> dict:
    from anthropic import Anthropic   # optional dependency
    resp = Anthropic().messages.create(model=llm.get("model") or "claude-haiku-4-5", max_tokens=4096,
                                       system=system, messages=[{"role": "user", "content": user}])
    return _parse_json("".join(b.text for b in resp.content if b.type == "text"))


PROVIDERS = {"ollama": _call_ollama, "anthropic": _call_anthropic}


def call_llm(system: str, user: str, llm: dict) -> dict:
    """One retry; raises on the second failure so the caller can audit llm_skipped."""
    fn = PROVIDERS[llm["provider"]]
    try:
        return fn(system, user, llm)
    except Exception:
        return fn(system, user, llm)


def find(page: Page, types: list[dict], cfg: dict) -> list[Span]:
    llm = cfg.get("llm", {})
    if llm.get("provider", "none") not in PROVIDERS:
        return []
    view = page.views.get("layout") or page.views.get("raw")
    if view is None or not view.text.strip():
        return []
    system = build_system(types)
    type_names = {t["name"] for t in types}
    seen: dict[tuple, Span] = {}
    for offset, chunk in chunk_text(view.text, llm.get("chunk_chars", 4000), llm.get("overlap_chars", 300)):
        data = call_llm(system, chunk, llm)
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            text, typ = str(item.get("text", "")), str(item.get("type", "")).upper().strip()
            if not text.strip() or typ not in type_names:
                continue
            hits = locate(chunk, text)
            if not hits:
                unlocated.append({"page": page.page_no, "text": text, "type": typ})
                continue
            for s, e in hits:
                key = (offset + s, offset + e, typ)
                seen.setdefault(key, make_span(page, view.view, offset + s, offset + e, typ, "llm", LLM_CONFIDENCE))
    return sorted(seen.values(), key=lambda sp: (sp.start, sp.end, sp.type))
