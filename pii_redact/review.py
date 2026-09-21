"""Step 10b: LLM re-reads one redacted page and flags problems. Flag-only; never raises."""
from __future__ import annotations

import json

import requests

SYSTEM = (
    "You are a redaction reviewer. You get the ORIGINAL page, the REDACTED page and the list of "
    "EXPECTED replacements (real value -> surrogate) for this page. Report:\n"
    '(a) "leaks": real PII from the ORIGINAL (names, emails, phones, addresses, dates of birth, '
    "PAN/DIN/Aadhaar numbers, private company names) whose exact value still appears in the REDACTED "
    "text. Check every expected replacement: if its real value is still present, it is a leak. "
    "A value that was replaced by its surrogate is NOT a leak;\n"
    '(b) "wrong_replacements": replacements that look wrong, e.g. a regulator or exchange name '
    "(SEBI, BSE, NSE, RBI), a statute, or a common word was replaced;\n"
    '(c) "inconsistent": the same original value replaced by two different surrogates.\n'
    "Page numbers, CIN, SEBI registration numbers, filing/offer dates and website URLs are NOT PII.\n"
    'Answer with JSON only: {"leaks": [], "wrong_replacements": [], "inconsistent": []}. '
    "Each list item is a short string naming the text and the problem. Empty lists if nothing is wrong."
)
KEYS = ("leaks", "wrong_replacements", "inconsistent")


def review_page(original_text: str, redacted_text: str, page_mapping: list[dict], cfg: dict) -> dict:
    rc = cfg.get("review", {})
    base = (rc.get("base_url") or cfg.get("llm", {}).get("base_url") or "http://localhost:11434").rstrip("/")
    model = rc.get("model") or cfg.get("llm", {}).get("model")
    timeout = rc.get("timeout_s") or cfg.get("llm", {}).get("timeout_s") or 120
    if not model:
        return {"error": "no review model configured (cfg['review']['model'])"}
    expected = "\n".join(f"- {m.get('real', '')} -> {m.get('surrogate', '')} ({m.get('type', '')})" for m in page_mapping) or "- (none)"
    user = (f"ORIGINAL PAGE:\n{original_text}\n\nREDACTED PAGE:\n{redacted_text}\n\n"
            f"EXPECTED REPLACEMENTS:\n{expected}\n\nReturn the JSON object.")
    if rc.get("provider") == "anthropic":
        return _anthropic(model, user)
    body = {"model": model, "format": "json", "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    try:
        r = requests.post(f"{base}/api/chat", json=body, timeout=timeout)
        if r.status_code == 404:
            return {"error": f"model '{model}' not found on Ollama at {base}"}
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "")
        data = json.loads(content)
    except requests.exceptions.ConnectionError:
        return {"error": f"Ollama unreachable at {base}"}
    except (requests.exceptions.RequestException, ValueError, TypeError) as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if not isinstance(data, dict):
        return {"error": f"unexpected response shape: {content[:200]}"}
    out = {}
    for k in KEYS:
        v = data.get(k, [])
        out[k] = [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in (v if isinstance(v, list) else [v])]
    return out


def _anthropic(model: str, user: str) -> dict:
    """Same review through the Claude API (provider: anthropic in config/backends.yaml)."""
    try:
        from anthropic import Anthropic
        from .finders.llm_finder import _parse_json
        r = Anthropic().messages.create(model=model, max_tokens=1024, system=SYSTEM,
                                        messages=[{"role": "user", "content": user}])
        data = _parse_json("".join(b.text for b in r.content if getattr(b, "type", "") == "text"))
    except Exception as e:                      # flag-only stage: never raise
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {k: [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
                for x in (data.get(k, []) if isinstance(data.get(k, []), list) else [data.get(k)])] for k in KEYS}
