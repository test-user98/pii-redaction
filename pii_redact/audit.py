"""One JSONL record per stage per page. Never raise from here."""
from __future__ import annotations

import json
import time
from pathlib import Path


class Audit:
    def __init__(self, out_dir: Path, run_id: str, doc_id: str):
        self.path = Path(out_dir) / "audit.jsonl"
        self.run_id, self.doc_id = run_id, doc_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, stage: str, page: int | None, backend: str, *, confidence=None,
            evidence=None, latency_ms=None, cost_usd=0.0, **extra):
        rec = {"ts": time.time(), "run_id": self.run_id, "doc_id": self.doc_id, "page": page,
               "stage": stage, "backend": backend, "confidence": confidence, "evidence": evidence,
               "latency_ms": latency_ms, "cost_usd": cost_usd, **extra}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
