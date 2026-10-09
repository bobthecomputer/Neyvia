from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _cache_path(root: Path, cache_name: str) -> Path:
    slug = str(cache_name or "snapshot").strip().replace("\\", "_").replace("/", "_")
    return root / ".agent_control" / "cache" / f"{slug}.json"


def load_persistent_snapshot_cache(
    root: Path,
    cache_name: str,
    ttl_seconds: float,
) -> Any | None:
    path = _cache_path(root.resolve(), cache_name)
    if not path.exists():
        return None
    try:
        if ttl_seconds > 0:
            age_seconds = time.time() - path.stat().st_mtime
            if age_seconds > ttl_seconds:
                return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_persistent_snapshot_cache(root: Path, cache_name: str, payload: Any) -> None:
    path = _cache_path(root.resolve(), cache_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == serialized:
                os.utime(path, None)
                return
        except OSError:
            pass
    path.write_text(serialized, encoding="utf-8")


def invalidate_persistent_snapshot_cache(root: Path, cache_name: str) -> None:
    path = _cache_path(root.resolve(), cache_name)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
