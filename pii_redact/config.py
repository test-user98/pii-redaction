from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f)


def pii_types(enabled_only: bool = True) -> list[dict]:
    types = load_yaml("pii_types.yaml")["types"]
    return [t for t in types if t.get("enabled", True)] if enabled_only else types


def backends() -> dict:
    cfg = load_yaml("backends.yaml")
    # env overrides for secrets only
    cfg.setdefault("surrogates", {})["salt"] = os.environ.get("PII_SALT", cfg["surrogates"].get("salt", "dev-salt"))
    return cfg
