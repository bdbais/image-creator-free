"""Storico locale delle immagini generate (un file JSON Lines, niente database)."""
from __future__ import annotations

import json
from pathlib import Path

from . import config

MAX_ENTRIES = 500


def path() -> Path:
    return config.data_dir() / "history.jsonl"


def add(entry: dict) -> None:
    try:
        with open(path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load(limit: int = MAX_ENTRIES) -> list[dict]:
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    out.reverse()
    return [e for e in out if Path(e.get("path", "")).exists()]


def clear() -> None:
    try:
        path().unlink(missing_ok=True)
    except OSError:
        pass
