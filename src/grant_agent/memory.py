from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import utc_now_iso
from .durability import file_transaction as _mutation


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass
class MemoryItem:
    id: str
    created_at: str
    source_session_id: str
    objective: str
    content: str
    tags: list[str]
    kind: str


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        # An open reader can deny atomic replacement on Windows. Share the
        # writer's lock while loading an existing store; absent stores stay pure.
        if path.exists():
            with _mutation(path):
                self.items = self._load(path)
        else:
            self.items = []
        self._persisted = [asdict(item) for item in self.items]

    @staticmethod
    def _load(path: Path) -> list[MemoryItem]:
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        items: list[MemoryItem] = []
        for raw in payload:
            items.append(
                MemoryItem(
                    id=raw["id"],
                    created_at=raw["created_at"],
                    source_session_id=raw["source_session_id"],
                    objective=raw["objective"],
                    content=raw["content"],
                    tags=raw.get("tags", []),
                    kind=raw.get("kind", "note"),
                )
            )
        return items

    def save(self) -> None:
        with _mutation(self.path):
            if [asdict(item) for item in self._load(self.path)] != self._persisted:
                raise RuntimeError("Memory changed after observation; reload before replacing the saved snapshot")
            self._commit()

    def _commit(self) -> None:
        from .durability import atomic_write_json
        atomic_write_json(self.path, [asdict(item) for item in self.items])
        from .proofs_c_runtime import check_memory_saved
        check_memory_saved(self)
        self._persisted = [asdict(item) for item in self.items]

    def add(self, source_session_id: str, objective: str, content: str, tags: list[str], kind: str) -> MemoryItem:
        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            created_at=utc_now_iso(),
            source_session_id=source_session_id,
            objective=objective,
            content=content,
            tags=tags,
            kind=kind,
        )
        with _mutation(self.path):
            self.items = self._load(self.path)
            self.items.append(item)
            try:
                self._commit()
            except BaseException:
                self.items.pop()
                raise
        return item

    def recent(self, limit: int = 10) -> list[MemoryItem]:
        return sorted(self.items, key=lambda item: item.created_at, reverse=True)[:limit]

    def search(self, query: str, limit: int = 8) -> list[MemoryItem]:
        query_tokens = _tokens(query)
        if not query_tokens:
            result = self.recent(limit=limit)
            from .proofs_c_runtime import check_memory_search
            check_memory_search(self, query, limit, result)
            return result

        def score(item: MemoryItem) -> tuple[int, int]:
            text_tokens = _tokens(item.content + " " + " ".join(item.tags) + " " + item.objective)
            overlap = len(query_tokens & text_tokens)
            return overlap, len(item.tags)

        ranked = sorted(self.items, key=score, reverse=True)
        positive = [item for item in ranked if score(item)[0] > 0]
        result = positive[:limit] if positive else self.recent(limit=limit)
        from .proofs_c_runtime import check_memory_search
        check_memory_search(self, query, limit, result)
        return result


def ingest_state_into_memory(memory: MemoryStore, session_id: str, state: dict) -> list[str]:
    # Reload and append the bounded batch under one store transaction. Other
    # writers may not interleave rows or erase the ingestion's prior snapshot.
    with _mutation(memory.path):
        memory.items = memory._load(memory.path)
        return _ingest_locked(memory, session_id, state)


def _ingest_locked(memory: MemoryStore, session_id: str, state: dict) -> list[str]:
    previous = list(memory.items)
    objective = state.get("objective", "")
    inserted_ids: list[str] = []

    for decision in state.get("decisions", [])[-3:]:
        item = _append_ingested(memory,
            source_session_id=session_id,
            objective=objective,
            content=decision,
            tags=["decision", "autonomy"],
            kind="decision",
        )
        inserted_ids.append(item.id)

    for risk in state.get("risks", [])[-2:]:
        item = _append_ingested(memory,
            source_session_id=session_id,
            objective=objective,
            content=risk,
            tags=["risk", "safety"],
            kind="risk",
        )
        inserted_ids.append(item.id)

    for action in state.get("next_actions", [])[:2]:
        item = _append_ingested(memory,
            source_session_id=session_id,
            objective=objective,
            content=action,
            tags=["next_action", "resume"],
            kind="next_action",
        )
        inserted_ids.append(item.id)

    try:
        memory._commit()
    except BaseException:
        memory.items = previous
        raise
    from .proofs_c_runtime import check_ingested
    check_ingested(memory, session_id, state, previous, inserted_ids)
    return inserted_ids


def _append_ingested(memory: MemoryStore, **values) -> MemoryItem:
    item = MemoryItem(id=f"mem_{uuid.uuid4().hex[:10]}", created_at=utc_now_iso(), **values)
    memory.items.append(item)
    return item
