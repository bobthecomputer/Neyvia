from __future__ import annotations

import json
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def build_lineage_timeline(base_dir: Path, lineage: list[str]) -> list[dict]:
    events: list[dict] = []
    for session_id in lineage:
        timeline_path = base_dir / session_id / "timeline.jsonl"
        rows = _load_jsonl(timeline_path)
        for row in rows:
            row["session_id"] = session_id
            events.append(row)
    return events


from .proofs_d_runtime import checked as _checked
build_lineage_timeline = _checked("d.runtime.lineage.source", build_lineage_timeline)
