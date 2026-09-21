"""pii-redact <file.pdf|file.docx> [--out out] [--no-llm] [--no-review] [--pages 1-6,128]"""
from __future__ import annotations

import argparse
import json

from .pipeline import run


def _pages(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Redact PII, same format out as in.")
    ap.add_argument("path")
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM finder")
    ap.add_argument("--no-review", action="store_true", help="skip the LLM review pass")
    ap.add_argument("--pages", help="only process these pages, e.g. 1-6,128 (for quick evals)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    summary = run(a.path, a.out, use_llm=not a.no_llm, use_review=not a.no_review,
                  only_pages=_pages(a.pages), workers=a.workers)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
