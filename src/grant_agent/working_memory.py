"""Durable, bounded working memory for long-running Neyvia missions.

Working memory is deliberately separate from the context transcript.  It stores
small semantic records and emits a faithful projection: records may be omitted
from the projection for a token budget, but their stable ids, hashes, and local
retrieval paths remain visible so a later model can recover the full truth.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .durability import append_jsonl_durable, atomic_write_json

WORKING_MEMORY_SCHEMA = "neyvia.working_memory.v1"
WORKING_MEMORY_EVENT_SCHEMA = "neyvia.working_memory.event.v1"

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_id(value: object) -> str:
    original = str(value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", original).strip(".-")
    if not text:
        return f"memory-{uuid.uuid4().hex[:12]}"
    # Keep distinct logical ids distinct after filesystem sanitisation.
    if text == original:
        return text[:160]
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:10]
    return f"{text[:145]}-{digest}"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tokens(value: object) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:[_.:/-][a-z0-9]+)*", str(value).lower()))


def _observation_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()).casefold()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class WorkingMemoryStore:
    """Persistent semantic state for one mission/session.

    The state file is atomically replaced after every mutation and a compact
    event journal provides an auditable append-only trail.  ``project`` is the
    model-facing API; ``retrieve`` is the explicit path for omitted detail.
    """

    @classmethod
    def has_state(cls, root: str | Path, memory_id: str) -> bool:
        """Check for an existing ledger without creating an empty one."""
        return (Path(root).expanduser().resolve() / ".agent_control" / "working_memory"
                / f"{_safe_id(memory_id)}.json").is_file()

    def __init__(self, root: str | Path, memory_id: str, *, max_records: int = 2000) -> None:
        self.root = Path(root).expanduser().resolve()
        self.memory_id = _safe_id(memory_id)
        self.base = self.root / ".agent_control" / "working_memory"
        self.path = self.base / f"{self.memory_id}.json"
        self.events_path = self.base / f"{self.memory_id}.events.jsonl"
        self.max_records = max(32, int(max_records))
        self.base.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)
        with self._lock:
            if not self.path.exists():
                self._write(self._empty())

    @contextmanager
    def _file_lock(self):
        """Serialize writers across processes without requiring a dependency."""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        deadline = time.monotonic() + 20.0
        while True:
            try:
                descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, str(os.getpid()).encode("ascii"))
                os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Working memory writer lock timed out: {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": WORKING_MEMORY_SCHEMA,
            "memoryId": self.memory_id,
            "revision": 0,
            "updatedAt": _now(),
            "objective": {"text": "", "updatedAt": None, "source": ""},
            "decisions": [],
            "observations": [],
            "evidence": [],
            "hypotheses": [],
            "failures": [],
            "retrieval": {"statePath": str(self.path), "eventsPath": str(self.events_path)},
        }

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = self._empty()
        if not isinstance(raw, dict) or raw.get("schema") != WORKING_MEMORY_SCHEMA:
            raise ValueError(f"Invalid working memory state: {self.path}")
        for key in ("decisions", "observations", "evidence", "hypotheses", "failures"):
            raw.setdefault(key, [])
        raw.setdefault("objective", {"text": "", "updatedAt": None, "source": ""})
        raw.setdefault("retrieval", {"statePath": str(self.path), "eventsPath": str(self.events_path)})
        return raw

    def _write(self, state: dict[str, Any]) -> None:
        atomic_write_json(self.path, state)

    def _mutate(self, event: str, payload: dict[str, Any], fn) -> dict[str, Any]:
        with self._lock, self._file_lock():
            state = self._read()
            fn(state)
            state["revision"] = int(state.get("revision") or 0) + 1
            state["updatedAt"] = _now()
            state["integritySha256"] = _sha({k: v for k, v in state.items() if k != "integritySha256"})
            self._write(state)
            append_jsonl_durable(self.events_path, {
                "schema": WORKING_MEMORY_EVENT_SCHEMA,
                "eventId": f"wme_{uuid.uuid4().hex[:16]}",
                "memoryId": self.memory_id,
                "revision": state["revision"],
                "createdAt": state["updatedAt"],
                "event": event,
                "payload": payload,
            })
            return copy.deepcopy(state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._read())

    def set_objective(self, text: str, *, source: str = "user") -> dict[str, Any]:
        value = str(text).strip()
        def apply(state):
            state["objective"] = {"text": value, "updatedAt": _now(), "source": source}
        return self._mutate("objective_set", {"text": value, "source": source}, apply)

    def _append(self, bucket: str, record: dict[str, Any], event: str) -> dict[str, Any]:
        record = copy.deepcopy(record)
        record.setdefault("recordId", f"wm_{uuid.uuid4().hex[:16]}")
        record.setdefault("createdAt", _now())
        record.setdefault("status", "active")
        record["recordSha256"] = _sha({k: v for k, v in record.items() if k != "recordSha256"})
        def apply(state):
            rows = state[bucket]
            rows.append(record)
            if len(rows) > self.max_records:
                del rows[:-self.max_records]
        return self._mutate(event, {"bucket": bucket, "recordId": record["recordId"]}, apply)

    def record_decision(self, text: str, *, source: str = "user", scope: str = "", source_ref: str = "") -> dict[str, Any]:
        return self._append("decisions", {"text": str(text), "source": source, "scope": scope, "sourceRef": source_ref}, "decision_recorded")

    def record_observation(self, key: str, value: Any, *, source: str = "", freshness: str = "current", observed_at: str | None = None,
                           source_ref: str = "", evidence_ids: Iterable[str] = ()) -> dict[str, Any]:
        """Keep conflicting claims; supersede only a newer comparable observation."""
        normalized = _canonical(value)
        record = {"key": str(key), "value": value, "valueSha256": _sha(value), "source": source,
                  "freshness": freshness, "observedAt": observed_at or _now(),
                  "sourceRef": source_ref, "evidenceIds": list(evidence_ids)}
        new_time = _observation_time(record["observedAt"])
        def apply(state):
            for prior in state["observations"]:
                if prior.get("key") != key or prior.get("status") != "active":
                    continue
                if _canonical(prior.get("value")) != normalized:
                    prior.setdefault("conflictsWith", []).append(record["recordId"])
                    record.setdefault("conflictsWith", []).append(prior["recordId"])
                    prior_time = _observation_time(prior.get("observedAt"))
                    if (source and source == prior.get("source") and freshness == "current"
                            and prior.get("freshness") == "current" and new_time and prior_time
                            and new_time > prior_time):
                        prior["status"] = "stale"
                        prior["staleReason"] = "superseded_by_newer_same_source_observation"
                        prior["contradictedBy"] = record["recordId"]
                        record.setdefault("supersedes", []).append(prior["recordId"])
                    prior["recordSha256"] = _sha({k: v for k, v in prior.items() if k != "recordSha256"})
            record["recordSha256"] = _sha({k: v for k, v in record.items() if k != "recordSha256"})
            state["observations"].append(record)
            if len(state["observations"]) > self.max_records:
                del state["observations"][:-self.max_records]
        record["recordId"] = f"wm_{uuid.uuid4().hex[:16]}"
        record["createdAt"] = _now()
        record["status"] = "active"
        record["recordSha256"] = _sha({k: v for k, v in record.items() if k != "recordSha256"})
        return self._mutate("observation_recorded", {"key": key, "recordId": record["recordId"]}, apply)

    def add_evidence(self, identity: str, *, sha256: str | None = None, source: str = "", retrieval_path: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        evidence = {"identity": str(identity), "sha256": str(sha256 or ""), "source": source,
                    "retrievalPath": retrieval_path or str(identity), "metadata": metadata or {}}
        evidence["identityHash"] = _sha({"identity": evidence["identity"], "sha256": evidence["sha256"]})
        return self._append("evidence", evidence, "evidence_added")

    def record_hypothesis(self, text: str, *, confidence: float = 0.5, status: str = "open", evidence_ids: Iterable[str] = ()) -> dict[str, Any]:
        return self._append("hypotheses", {"text": str(text), "confidence": max(0.0, min(1.0, float(confidence))), "status": status, "evidenceIds": list(evidence_ids)}, "hypothesis_recorded")

    def record_failure(self, signature: str, *, diagnosis: str = "", attempted: str = "", recovery: str = "", status: str = "open") -> dict[str, Any]:
        return self._append("failures", {"signature": str(signature), "diagnosis": diagnosis, "attempted": attempted, "recovery": recovery, "status": status}, "failure_recorded")

    def retrieve(self, record_id: str) -> dict[str, Any] | None:
        state = self.snapshot()
        if record_id == "objective":
            return state["objective"]
        for bucket in ("decisions", "observations", "evidence", "hypotheses", "failures"):
            for row in state[bucket]:
                if row.get("recordId") == record_id:
                    return row
        return None

    def find(self, query: str, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        """Return bounded, ranked record handles without exposing the whole ledger."""
        state = self.snapshot()
        query = str(query or "")[:512]
        offset = max(0, min(int(offset), self.max_records * 5))
        terms = _tokens(query)
        rows = []
        for bucket in ("decisions", "observations", "evidence", "hypotheses", "failures"):
            for row in state[bucket]:
                matches = len(terms & _tokens(_canonical(row))) if terms else 0
                if terms and not matches:
                    continue
                rows.append((matches, row.get("createdAt", ""), bucket, row))
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        page = rows[offset:offset + max(1, min(limit, 20))]
        return {"schema": "neyvia.working_memory_find.v1", "memoryId": self.memory_id,
                "revision": state["revision"], "query": query, "total": len(rows),
                "offset": offset, "handles": [
                    {"recordId": row.get("recordId"), "bucket": bucket,
                     "recordSha256": row.get("recordSha256"), "status": row.get("status"),
                     "createdAt": row.get("createdAt"), "score": score}
                    for score, _, bucket, row in page]}

    def project(self, query: str = "", *, token_budget: int = 1800) -> dict[str, Any]:
        """Return bounded faithful state; omitted records retain ids and paths."""
        state = self.snapshot()
        budget = max(180, int(token_budget))
        terms = _tokens(query)
        rows: list[tuple[str, dict[str, Any], float]] = []
        for bucket in ("decisions", "observations", "evidence", "hypotheses", "failures"):
            for row in state[bucket]:
                text = _canonical(row)
                score = (len(terms & _tokens(text)) * 10) if terms else 0
                score += 4 if row.get("status") == "active" else 0
                score += 2 if bucket in ("decisions", "observations") else 0
                # Explicit user decisions are continuity boundaries; retain
                # them ahead of diagnostic observations during projection.
                if bucket == "decisions":
                    score += 1000
                rows.append((bucket, row, score))
        rows.sort(key=lambda item: (item[2], item[1].get("createdAt", "")), reverse=True)
        included: dict[str, list[dict[str, Any]]] = {k: [] for k in ("decisions", "observations", "evidence", "hypotheses", "failures")}
        used = len(_canonical(state["objective"])) // 4 + 80
        for bucket, row, _score in rows:
            cost = max(1, len(_canonical(row)) // 4)
            if used + cost <= budget:
                included[bucket].append(copy.deepcopy(row))
                used += cost
        included_ids = {row["recordId"] for values in included.values() for row in values}
        omitted = []
        for bucket in included:
            for row in state[bucket]:
                if row.get("recordId") not in included_ids:
                    omitted.append({"recordId": row.get("recordId"), "bucket": bucket, "recordSha256": row.get("recordSha256"), "retrievalPath": f"{self.path}#{row.get('recordId')}"})
        # Omitted detail is represented by a bounded page of handles plus a
        # manifest path; the projection itself must remain bounded even when
        # the durable ledger contains thousands of records.
        handle_limit = min(3, len(omitted))
        page = omitted[:handle_limit]
        projection = {"schema": "neyvia.working_memory_projection.v1", "memoryId": self.memory_id, "revision": state["revision"],
                "objective": copy.deepcopy(state["objective"]), "records": included, "omitted": page,
                "omittedCount": len(omitted),
                "omittedManifest": {"count": len(omitted), "statePath": str(self.path), "api": "semantic.memory.find then semantic.memory.retrieve", "sha256": _sha(omitted)},
                "retrieval": {"statePath": str(self.path), "eventsPath": str(self.events_path), "api": "semantic.memory.retrieve", "findApi": "semantic.memory.find"},
                "integritySha256": state.get("integritySha256"), "generatedAt": _now()}
        # Keep serialized output within the caller's approximate token budget.
        limit = max(720, budget * 4)
        while len(_canonical(projection)) > limit and projection["omitted"]:
            projection["omitted"].pop()
        while len(_canonical(projection)) > limit and any(projection["records"].values()):
            removable = [key for key, values in projection["records"].items() if values and key != "decisions"]
            if not removable:
                break
            bucket = max(removable, key=lambda key: len(projection["records"][key]))
            if projection["records"][bucket]:
                removed = projection["records"][bucket].pop()
                projection["omittedCount"] += 1
        if len(_canonical(projection)) > limit:
            projection["objective"]["text"] = projection["objective"].get("text", "")[: max(80, budget)]
            projection["objective"]["truncated"] = True
            projection["objective"]["retrievalPath"] = str(self.path)
        if len(_canonical(projection)) > limit:
            projection["retrieval"] = {"statePath": str(self.path)}
            projection["omittedManifest"] = {"count": len(omitted), "statePath": str(self.path)}
        selected_ids = {row["recordId"] for bucket in projection["records"].values() for row in bucket}
        omitted_rows = [{"recordId": row.get("recordId"), "recordSha256": row.get("recordSha256")}
                        for _, row, _ in rows if row.get("recordId") not in selected_ids]
        projection["omittedCount"] = len(omitted_rows)
        projection["omittedManifest"] = {"count": len(omitted_rows), "sha256": _sha(omitted_rows), "statePath": str(self.path)}
        if len(_canonical(projection)) > limit:
            projection = {"schema": "neyvia.working_memory_projection.v1", "memoryId": self.memory_id,
                          "revision": state["revision"], "integritySha256": state.get("integritySha256"),
                          "records": {}, "omitted": [], "omittedCount": len(rows),
                          "objective": {"truncated": True, "retrievalPath": str(self.path)},
                          "retrieval": {"statePath": str(self.path)}}
        if len(_canonical(projection)) > limit:
            projection = {"memoryId": self.memory_id, "revision": state["revision"], "omittedCount": len(rows),
                          "retrieval": {"statePath": str(self.path)}, "budgetExceeded": True}
        return projection


WorkingMemory = WorkingMemoryStore

__all__ = ["WORKING_MEMORY_SCHEMA", "WORKING_MEMORY_EVENT_SCHEMA", "WorkingMemoryStore", "WorkingMemory"]
