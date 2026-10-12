"""Tiny JSON cache so a re-run never repeats successful (paid / rate-limited) API calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint(*parts: str | bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:24]


class Cache:
    def __init__(self, folder: Path, enabled: bool = True):
        self.folder, self.enabled = folder, enabled
        if enabled:
            folder.mkdir(parents=True, exist_ok=True)

    def get(self, name: str, key: str):
        path = self.folder / f"{name}.json"
        if not self.enabled or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data.get("value") if data.get("key") == key else None

    def put(self, name: str, key: str, value) -> None:
        if self.enabled:
            (self.folder / f"{name}.json").write_text(
                json.dumps({"key": key, "value": value}, ensure_ascii=False), encoding="utf-8")
