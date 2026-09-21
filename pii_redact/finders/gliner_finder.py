"""GLiNER2-PII finder. Runs on the layout view, chunked at ~1500 chars with 200-char overlap."""
from __future__ import annotations

import threading

from pii_redact.model import Page, Span
from pii_redact.finders.regex_finder import make_span

DEFAULT_MODEL = "fastino/gliner2-privacy-filter-PII-multi"
CHUNK_CHARS = 1500
OVERLAP_CHARS = 200

_model = None
_model_name = None
_lock = threading.Lock()   # one forward pass at a time: parallel torch calls on CPU are ~10x slower


def get_model(name: str = DEFAULT_MODEL):
    """Load once per process (lazy). Prints a config banner on first load; that is expected."""
    global _model, _model_name
    if _model is None or _model_name != name:
        from gliner2 import GLiNER2
        _model = GLiNER2.from_pretrained(name)
        _model_name = name
    return _model


def chunk_text(text: str, size: int, overlap: int):
    """Yield (offset, chunk). Cuts prefer a newline or sentence end in the last third of the window."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start + size * 2 // 3:end]
            cut = max(window.rfind("\n"), window.rfind(". "))
            if cut >= 0:
                end = start + size * 2 // 3 + cut + 1
        yield start, text[start:end]
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def find(page: Page, types: list[dict], cfg: dict) -> list[Span]:
    view = page.views.get("layout") or page.views.get("raw")
    if view is None or not view.text.strip():
        return []
    label_to_type = {lab: t["name"] for t in types for lab in t.get("ner_labels", [])}
    if not label_to_type:
        return []
    ner = cfg.get("ner", {})
    model = get_model(ner.get("model", DEFAULT_MODEL))
    threshold = ner.get("threshold", 0.4)
    labels = list(label_to_type)
    best: dict[tuple, Span] = {}
    for offset, chunk in chunk_text(view.text, CHUNK_CHARS, OVERLAP_CHARS):
        with _lock:
            result = model.extract_entities(chunk, labels, threshold=threshold,
                                            include_confidence=True, include_spans=True)
        for label, ents in result.get("entities", {}).items():
            for e in ents:
                s, en = offset + e["start"], offset + e["end"]
                key = (s, en, label_to_type[label])
                if key not in best or e["confidence"] > best[key].confidence:
                    best[key] = make_span(page, view.view, s, en, label_to_type[label], "gliner", float(e["confidence"]))
    return sorted(best.values(), key=lambda sp: (sp.start, sp.end, sp.type))
