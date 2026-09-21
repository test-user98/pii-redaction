import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pii_redact.config import backends  # noqa: E402
from pii_redact.review import review_page  # noqa: E402


def _ollama_has_model(cfg):
    try:
        r = requests.get(f"{cfg['llm']['base_url']}/api/tags", timeout=2)
        names = {m["name"] for m in r.json().get("models", [])}
        return cfg["review"]["model"] in names
    except Exception:
        return False


def test_unreachable_returns_error_dict():
    out = review_page("a", "b", [], {"review": {"model": "x", "base_url": "http://localhost:1"}})
    assert "error" in out


def test_smoke_against_ollama():
    cfg = backends()
    if not _ollama_has_model(cfg):
        pytest.skip("Ollama not running or review model not pulled")
    out = review_page("Contact: Shanti Gopalkrishnan", "Contact: Meera Iyer",
                      [{"real": "Shanti Gopalkrishnan", "surrogate": "Meera Iyer", "type": "PERSON"}], cfg)
    assert set(out) == {"leaks", "wrong_replacements", "inconsistent"}, out
    assert all(isinstance(v, list) for v in out.values())
