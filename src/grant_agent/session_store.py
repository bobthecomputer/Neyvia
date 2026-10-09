from __future__ import annotations

import json
import uuid
from pathlib import Path

from .models import TimelineEvent, to_dict, utc_now_iso


class SessionStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, objective: str, parent_session_id: str | None = None) -> Path:
        session_id = f"session_{uuid.uuid4().hex[:10]}"
        session_path = self.base_dir / session_id
        session_path.mkdir(parents=True, exist_ok=False)
        metadata = {
            "session_id": session_id,
            "parent_session_id": parent_session_id,
            "objective": objective,
            "created_at": utc_now_iso(),
        }
        (session_path / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return session_path

    def append_timeline(self, session_path: Path, event: TimelineEvent) -> None:
        line = json.dumps(to_dict(event), ensure_ascii=True)
        timeline_path = session_path / "timeline.jsonl"
        with timeline_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def save_state(self, session_path: Path, state: dict) -> None:
        state_path = session_path / "state.json"
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @staticmethod
    def read_state(session_path: Path) -> dict:
        return json.loads((session_path / "state.json").read_text(encoding="utf-8"))

    def latest_session(self) -> Path | None:
        session_dirs = sorted(
            [p for p in self.base_dir.glob("session_*") if p.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return session_dirs[0] if session_dirs else None

    def get_session_path(self, session_id: str) -> Path | None:
        path = self.base_dir / session_id
        if path.exists() and path.is_dir():
            return path
        return None

    @staticmethod
    def read_metadata(session_path: Path) -> dict:
        return json.loads((session_path / "metadata.json").read_text(encoding="utf-8"))
