from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


CONTEXT_LEDGER_SCHEMA = "neyvia.context_ledger.v1"
CONTEXT_BUNDLE_SCHEMA = "neyvia.context_bundle.v1"
CONTEXT_COMPACTION_SCHEMA = "neyvia.context_compaction_receipt.v1"
MODEL_CONTEXT_SECTIONS = (
    "workingMemory", "collaboration", "decisionChecks", "experienceNotes",
    "runtimeObservation", "workingMemoryRetrieval", "situationRetrieval",
    "adaptiveWork", "qualityObligations",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return set(
        re.findall(
            r"[a-z0-9]+(?:[_.:/-][a-z0-9]+)*",
            str(text).lower(),
        )
    )


def estimate_tokens(text: str) -> int:
    return max(1, (len(str(text)) + 3) // 4)


def _account_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Budget the delivered JSON, including semantic state and metadata.

    Estimates are character based, not provider token counts. Optional ledger
    text may shrink; protected instructions and semantic boundaries never do.
    If those cannot fit, callers must rebudget before model execution.
    """
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def cache_value(value):
        if isinstance(value, dict):
            return {key: cache_value(item) for key, item in value.items() if key != "generatedAt"}
        if isinstance(value, list):
            return [cache_value(item) for item in value]
        return value

    payload["contextBudget"] = {
        "scope": "complete serialized context bundle; excludes provider framing, other prompts and tool schemas",
        "method": "ceil(unicode_characters/4)", "providerTokens": None,
        "exceeded": False, "requiresRebudget": False,
    }
    original_omitted = payload["omitted_count"]
    original_count = len(payload["items"])
    payload["ledger_estimated_tokens"] = 0

    def refresh():
        payload["ledger_estimated_tokens"] = sum(item["estimatedTokens"] for item in payload["items"])
        payload["omitted_count"] = original_omitted + original_count - len(payload["items"])
        selected = {item["eventId"] for item in payload["items"]}
        payload["segments"] = {key: [value for value in values if value in selected]
                               for key, values in payload["segments"].items()}
        # Include semantic revisions/content: a corrected brief invalidates an
        # otherwise unchanged transcript cache.
        material = {key: payload[key] for key in MODEL_CONTEXT_SECTIONS}
        material["items"] = [(item["eventId"], item["includedContentSha256"]) for item in payload["items"]]
        payload["cache_key"] = hashlib.sha256(encoded(cache_value(material)).encode("utf-8")).hexdigest()
        for _ in range(8):
            measured = estimate_tokens(encoded(payload))
            exceeded = measured > payload["token_budget"]
            unchanged = payload["estimated_tokens"] == measured and payload["contextBudget"]["exceeded"] == exceeded
            payload["estimated_tokens"] = measured
            payload["contextBudget"].update(exceeded=exceeded, requiresRebudget=exceeded)
            if unchanged:
                break

    refresh()
    while payload["contextBudget"]["exceeded"]:
        candidates = [item for item in payload["items"] if "required" not in item["reasons"]]
        if not candidates:
            break
        item = max(candidates, key=lambda row: len(row["content"]))
        reduction = (payload["estimated_tokens"] - payload["token_budget"]) * 4 + 64
        marker = f"\n[truncated event={item['eventId']}; retrieve context.search]"
        remaining = len(item["content"]) - reduction - len(marker)
        if remaining >= 80:
            item["content"] = item["content"][:remaining].rstrip() + marker
            item["truncated"] = True
            item["estimatedTokens"] = estimate_tokens(item["content"])
            item["includedContentSha256"] = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        else:
            payload["items"].remove(item)
        refresh()
    stable_ids = set(payload["segments"]["stablePrefix"])
    payload["stable_prefix_cache_key"] = hashlib.sha256(encoded([
        (item["eventId"], item["includedContentSha256"]) for item in payload["items"] if item["eventId"] in stable_ids
    ]).encode("utf-8")).hexdigest()
    refresh()
    return payload


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value).strip()).strip(".-")
    return cleaned[:120] or "context"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class ContextLedgerEvent:
    event_id: str
    sequence: int
    created_at: str
    role: str
    kind: str
    content: str
    tokens: int
    active: bool
    pinned: bool
    importance: float
    source: str
    artifact_path: str
    content_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextBundle:
    session_id: str
    query: str
    token_budget: int
    estimated_tokens: int
    items: list[dict[str, Any]]
    omitted_count: int
    active_event_count: int
    archived_event_count: int
    cache_key: str
    stable_prefix_cache_key: str
    segments: dict[str, list[str]]
    generated_at: str = field(default_factory=_now)
    schema: str = CONTEXT_BUNDLE_SCHEMA


class ContextCompactionStrategy(Protocol):
    strategy_id: str

    def summarize(self, events: list[ContextLedgerEvent], focus: str) -> str:
        ...


class ExtractiveCompactionStrategy:
    strategy_id = "extractive-v1"

    def summarize(self, events: list[ContextLedgerEvent], focus: str) -> str:
        critical = [
            item
            for item in events
            if item.kind != "checkpoint"
            and (item.kind in DurableContextEngine.CRITICAL_KINDS or item.importance >= 0.8)
        ]
        non_checkpoint_events = [item for item in events if item.kind != "checkpoint"]
        sources = critical[-20:] or non_checkpoint_events[-12:]
        lines: list[str] = []
        for item in sources:
            cleaned = re.sub(r"\s+", " ", item.content)[:360]
            lines.append(
                f"- [{item.event_id} {item.kind} sha256={item.content_sha256}] {cleaned}"
            )
        return (
            "[compacted_context]\n"
            f"focus={focus or 'continue the active mission'}\n"
            f"archived_events={len(events)}\n"
            "Durable evidence remains searchable by event id and content hash.\n"
            + ("\n".join(lines) if lines else "No archived facts were selected.")
        )


class DurableContextEngine:
    """Local, dependency-free context ledger with bounded active reconstruction.

    The ledger can grow for the life of a project. Model-visible bundles remain
    finite and are rebuilt from pinned facts, relevant archived evidence, and a
    protected recent tail.
    """

    CRITICAL_KINDS = {
        "goal",
        "contract",
        "decision",
        "blocker",
        "risk",
        "verification",
        "checkpoint",
        "instruction",
        "acceptance",
    }

    # These are task boundaries, not material a summarizer may paraphrase away.
    PROTECTED_KINDS = {"goal", "contract", "instruction", "acceptance"}

    @classmethod
    def _required(cls, event: ContextLedgerEvent) -> bool:
        generated_checkpoint = event.kind == "checkpoint" and event.source == "neyvia-context-engine"
        return event.kind in cls.PROTECTED_KINDS or (event.pinned and not generated_checkpoint)

    def __init__(
        self,
        root: str | Path,
        session_id: str,
        *,
        max_context_tokens: int,
        reserve_tokens: int = 12_000,
        protect_recent_tokens: int = 20_000,
        max_inline_tool_tokens: int = 2_500,
        compactor: ContextCompactionStrategy | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.session_id = _safe_id(session_id)
        self.max_context_tokens = max(8, int(max_context_tokens))
        reserve_limit = max(1, self.max_context_tokens // 3)
        self.reserve_tokens = max(
            1,
            min(int(reserve_tokens), reserve_limit, self.max_context_tokens - 1),
        )
        visible_tokens = max(1, self.max_context_tokens - self.reserve_tokens)
        self.protect_recent_tokens = max(
            1,
            min(int(protect_recent_tokens), visible_tokens),
        )
        self.max_inline_tool_tokens = max(
            1,
            min(int(max_inline_tool_tokens), visible_tokens),
        )
        self.compactor = compactor or ExtractiveCompactionStrategy()
        self.context_root = self.root / ".agent_control" / "context" / self.session_id
        self.db_path = self.context_root / "ledger.sqlite3"
        self.blob_root = self.context_root / "blobs"
        self.receipt_root = self.context_root / "receipts"
        self.context_root.mkdir(parents=True, exist_ok=True)
        # Semantic state lives beside (rather than inside) the transcript.  It
        # remains available after compaction and can be retrieved by identity.
        from .working_memory import WorkingMemoryStore
        self.working_memory = WorkingMemoryStore(self.root, self.session_id)
        from .adaptive_work import AdaptiveWorkStore
        self.adaptive_work = AdaptiveWorkStore(self.root, self.session_id)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS context_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    importance REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    content_sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_context_active_sequence
                    ON context_events(active, sequence);
                CREATE INDEX IF NOT EXISTS idx_context_kind_sequence
                    ON context_events(kind, sequence);
                CREATE TABLE IF NOT EXISTS context_compactions (
                    compaction_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    focus TEXT NOT NULL,
                    archived_count INTEGER NOT NULL,
                    protected_count INTEGER NOT NULL,
                    checkpoint_event_id TEXT NOT NULL,
                    receipt_path TEXT NOT NULL
                );
                """
            )

    def append(
        self,
        role: str,
        content: str,
        *,
        kind: str = "message",
        importance: float = 0.5,
        pinned: bool = False,
        source: str = "",
        metadata: dict[str, Any] | None = None,
        reported_tokens: int | None = None,
    ) -> ContextLedgerEvent:
        raw_content = str(content)
        token_count = max(1, int(reported_tokens or estimate_tokens(raw_content)))
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        artifact_path = ""
        inline_content = raw_content
        normalized_kind = _safe_id(kind).replace("-", "_")
        if normalized_kind == "tool_output" and token_count > self.max_inline_tool_tokens:
            artifact = self.blob_root / f"{content_hash}.txt"
            if not artifact.exists():
                _atomic_text(artifact, raw_content)
            artifact_path = str(artifact)
            head = raw_content[:2400].rstrip()
            tail = raw_content[-800:].lstrip() if len(raw_content) > 3200 else ""
            inline_content = (
                f"[tool_output_archived sha256={content_hash} tokens={token_count} "
                f"path={artifact_path}]\n{head}"
                + (f"\n[... full output archived ...]\n{tail}" if tail else "")
            )
        event_id = f"ctx_{uuid.uuid4().hex[:16]}"
        created_at = _now()
        normalized_importance = max(0.0, min(float(importance), 1.0))
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO context_events (
                    event_id, created_at, role, kind, content, tokens, active,
                    pinned, importance, source, artifact_path, content_sha256,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    created_at,
                    str(role or "system"),
                    normalized_kind,
                    inline_content,
                    token_count,
                    int(bool(pinned)),
                    normalized_importance,
                    str(source or ""),
                    artifact_path,
                    content_hash,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            sequence = int(cursor.lastrowid)
        event = ContextLedgerEvent(
            event_id=event_id,
            sequence=sequence,
            created_at=created_at,
            role=str(role or "system"),
            kind=normalized_kind,
            content=inline_content,
            tokens=token_count,
            active=True,
            pinned=bool(pinned),
            importance=normalized_importance,
            source=str(source or ""),
            artifact_path=artifact_path,
            content_sha256=content_hash,
            metadata=dict(metadata or {}),
        )
        # Only explicit semantic kinds are promoted.  Ordinary prose is kept
        # in the ledger and never guessed to be an authoritative decision.
        try:
            if normalized_kind == "goal":
                self.working_memory.set_objective(raw_content, source=str(source or "context-engine"))
            elif normalized_kind == "decision":
                self.working_memory.record_decision(
                    raw_content, source=str(source or "context-engine"), source_ref=event.event_id
                )
            elif normalized_kind == "observation":
                self.working_memory.record_observation(
                    f"context:{event.event_id}", raw_content, source=str(source or "context-engine")
                )
            elif normalized_kind in {"verification", "artifact"} and artifact_path:
                self.working_memory.add_evidence(
                    artifact_path, sha256=content_hash, source=str(source or "context-engine"), retrieval_path=artifact_path
                )
            elif normalized_kind == "blocker":
                self.working_memory.record_failure(raw_content, attempted="context event", status="open")
                self.adaptive_work.record_problem(raw_content, status="open", source=event.event_id)
        except Exception:
            # A semantic sidecar must never make the durable transcript append
            # fail; the ledger event itself remains authoritative evidence.
            pass
        return event

    @staticmethod
    def _row(row: sqlite3.Row) -> ContextLedgerEvent:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        return ContextLedgerEvent(
            event_id=str(row["event_id"]),
            sequence=int(row["sequence"]),
            created_at=str(row["created_at"]),
            role=str(row["role"]),
            kind=str(row["kind"]),
            content=str(row["content"]),
            tokens=int(row["tokens"]),
            active=bool(row["active"]),
            pinned=bool(row["pinned"]),
            importance=float(row["importance"]),
            source=str(row["source"]),
            artifact_path=str(row["artifact_path"]),
            content_sha256=str(row["content_sha256"]),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _events(self, where: str = "1=1", params: tuple[Any, ...] = ()) -> list[ContextLedgerEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM context_events WHERE {where} ORDER BY sequence ASC",  # noqa: S608
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        events = self._events()
        newest = max((item.sequence for item in events), default=1)
        ranked: list[tuple[float, ContextLedgerEvent]] = []
        for event in events:
            text_tokens = _tokens(
                f"{event.content} {event.kind} {event.source} "
                + " ".join(map(str, event.metadata.get("tags", [])))
            )
            overlap = len(query_tokens & text_tokens) if query_tokens else 0
            if query_tokens and not overlap and not event.pinned:
                continue
            recency = event.sequence / newest
            score = overlap * 5.0 + event.importance * 2.0 + recency
            if event.pinned:
                score += 4.0
            if event.kind in self.CRITICAL_KINDS:
                score += 2.0
            if event.artifact_path:
                score += 4.0
            if query_tokens and event.kind == "checkpoint":
                score -= 5.0
            ranked.append((score, event))
        ranked.sort(key=lambda item: (-item[0], -item[1].sequence))
        return [
            {
                **asdict(event),
                "score": round(score, 4),
            }
            for score, event in ranked[: max(1, min(int(limit), 200))]
        ]

    def build_bundle(self, query: str = "", *, token_budget: int | None = None) -> dict[str, Any]:
        available = max(1, self.max_context_tokens - self.reserve_tokens)
        budget = max(1, min(int(token_budget or available), available))
        all_events = self._events()
        active = [item for item in all_events if item.active]
        archived_count = len(all_events) - len(active)
        required = [item for item in all_events if self._required(item)]
        required_tokens = sum(estimate_tokens(item.content) for item in required)
        if required_tokens > budget:
            raise ValueError(
                f"Protected context requires {required_tokens} estimated tokens, but the bundle budget is {budget}. "
                "Increase the budget or explicitly revise the saved task contract; protected instructions were not truncated."
            )
        selected: dict[str, tuple[ContextLedgerEvent, set[str], float]] = {}

        def select(event: ContextLedgerEvent, reason: str, score: float) -> None:
            current = selected.get(event.event_id)
            if current:
                current[1].add(reason)
                selected[event.event_id] = (event, current[1], max(current[2], score))
            else:
                selected[event.event_id] = (event, {reason}, score)

        for event in all_events:
            if self._required(event):
                select(event, "required", 200.0 + event.importance)
            if event.pinned:
                select(event, "pinned", 100.0 + event.importance)
            elif event.active and event.kind in self.CRITICAL_KINDS:
                select(event, "critical", 50.0 + event.importance)

        if query.strip():
            by_id = {item.event_id: item for item in all_events}
            for row in self.search(query, limit=80):
                event = by_id.get(str(row["event_id"]))
                if event:
                    select(event, "relevant", float(row["score"]))

        recent_tokens = 0
        for event in reversed(active):
            if recent_tokens >= min(self.protect_recent_tokens, max(1, budget // 2)):
                break
            select(event, "recent", 25.0 + event.sequence / max(1, len(all_events)))
            recent_tokens += event.tokens

        ranked = sorted(selected.values(), key=lambda row: ("required" not in row[1], -row[2], -row[0].sequence))
        included: list[tuple[ContextLedgerEvent, set[str], str, int]] = []
        consumed = 0
        for event, reasons, _score in ranked:
            if consumed >= budget:
                break
            remaining = budget - consumed
            content = event.content
            item_tokens = estimate_tokens(content)
            if item_tokens > remaining:
                max_chars = max(1, remaining * 4)
                if max_chars < len(content):
                    marker = f"\n[truncated event={event.event_id}]"
                    if max_chars > len(marker) + 4:
                        content = content[: max_chars - len(marker)].rstrip() + marker
                    else:
                        content = content[:max_chars]
                item_tokens = estimate_tokens(content)
            if item_tokens > remaining:
                continue
            included.append((event, reasons, content, item_tokens))
            consumed += item_tokens

        included.sort(key=lambda row: row[0].sequence)
        items = [
            {
                "eventId": event.event_id,
                "sequence": event.sequence,
                "role": event.role,
                "kind": event.kind,
                "content": content,
                "estimatedTokens": tokens,
                "reasons": sorted(reasons),
                "source": event.source,
                "artifactPath": event.artifact_path,
                "contentSha256": event.content_sha256,
                "includedContentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "truncated": content != event.content,
            }
            for event, reasons, content, tokens in included
        ]
        segments = {
            "stablePrefix": [
                item["eventId"]
                for item in items
                if any(reason in item["reasons"] for reason in ("required", "pinned", "critical"))
            ],
            "retrievedEvidence": [
                item["eventId"] for item in items if "relevant" in item["reasons"]
            ],
            "recentTail": [item["eventId"] for item in items if "recent" in item["reasons"]],
        }
        cache_material = json.dumps(
            [(item["eventId"], item["includedContentSha256"]) for item in items],
            separators=(",", ":"),
        )
        stable_material = json.dumps(
            [
                (item["eventId"], item["includedContentSha256"])
                for item in items
                if item["eventId"] in segments["stablePrefix"]
            ],
            separators=(",", ":"),
        )
        bundle = ContextBundle(
            session_id=self.session_id,
            query=str(query),
            token_budget=budget,
            estimated_tokens=sum(int(item["estimatedTokens"]) for item in items),
            items=items,
            omitted_count=max(0, len(selected) - len(items)),
            active_event_count=len(active),
            archived_event_count=archived_count,
            cache_key=hashlib.sha256(cache_material.encode("utf-8")).hexdigest(),
            stable_prefix_cache_key=hashlib.sha256(stable_material.encode("utf-8")).hexdigest(),
            segments=segments,
        )
        working_memory_budget = max(600, min(1600, max(600, budget // 3)))
        working_memory = self.working_memory.project(query, token_budget=working_memory_budget)
        from .workspace_intelligence import WorkspaceIntelligence
        from .runtime_diagnostics import context_observation
        intelligence = WorkspaceIntelligence(self.root, self.session_id)
        collaboration = intelligence.collaboration_context(max_characters=2400)
        experience_notes = {"scope": self.session_id, "notes": [], "enabled": False}
        if collaboration["preferences"]["learning"]:
            from .experience_learning import ExperienceStore
            experience_notes = {**ExperienceStore(self.root, self.session_id).relevant(query, max_characters=1800), "enabled": True}
        obligations = intelligence.evaluate_obligations(limit=30)
        omitted_obligations=max(0,len(intelligence.snapshot()['obligations'])-len(obligations))
        return _account_bundle({
            **asdict(bundle),
            "protectedContext": {
                "eventIds": [event.event_id for event in required],
                "estimatedTokens": required_tokens,
                "complete": True,
                "policy": "Verbatim task boundaries and explicit pins; preservation does not independently verify their claims.",
            },
            "workingMemory": working_memory,
            "collaboration": collaboration,
            "decisionChecks": intelligence.self_questions(max_characters=1800),
            "experienceNotes": experience_notes,
            "runtimeObservation": context_observation(self.root),
            "workingMemoryRetrieval": working_memory.get("retrieval", {}),
            "situationRetrieval": {"tool":"neyvia.situation", "verb":"recall", "workId":self.session_id,
                                   "policy":"Retrieve the saved task and focus. Saved observations require refresh before action."},
            "adaptiveWork": self.adaptive_work.packet(token_budget=max(600, budget // 3)),
            "qualityObligations": {"checks": obligations,
                                   "needsReview": bool(omitted_obligations) or any(row['status'] != 'verified' for row in obligations),
                                   "omittedCount": omitted_obligations,
                                   "retrievalTool": "intelligence.read", "workId": self.session_id},
        })

    def bundle(self, query: str = "", *, token_budget: int | None = None) -> dict[str, Any]:
        """Return the durable model-visible bundle through the stable facade."""
        result = self.build_bundle(query, token_budget=token_budget)
        from .proofs_a_control import check_bundle
        check_bundle(result)
        return result

    def compact(self, *, focus: str = "", target_ratio: float = 0.25) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute(
                "UPDATE context_events SET pinned = 0 WHERE kind = 'checkpoint' AND pinned = 1 AND source = 'neyvia-context-engine'"
            )
        active = self._events("active = 1")
        if not active:
            return {
                "schema": CONTEXT_COMPACTION_SCHEMA,
                "status": "skipped",
                "reason": "no_active_events",
                "sessionId": self.session_id,
            }
        target_tokens = max(1, int(self.max_context_tokens * max(0.05, min(target_ratio, 0.8))))
        protect_budget = min(self.protect_recent_tokens, target_tokens)
        protected_ids = {item.event_id for item in active if item.pinned or self._required(item)}
        protected_tokens = sum(item.tokens for item in active if item.event_id in protected_ids)
        for event in reversed(active):
            if event.event_id in protected_ids:
                continue
            if protected_tokens >= protect_budget and len(protected_ids) >= 8:
                break
            if len(protected_ids) >= 8 and protected_tokens + event.tokens > protect_budget:
                break
            protected_ids.add(event.event_id)
            protected_tokens += event.tokens

        archived = [item for item in active if item.event_id not in protected_ids]
        summary = self.compactor.summarize(archived, focus)
        summary += f"\nprotected_events={len(protected_ids)}"
        if archived:
            placeholders = ",".join("?" for _ in archived)
            with self._connection() as connection:
                connection.execute(
                    f"UPDATE context_events SET active = 0 WHERE event_id IN ({placeholders})",  # noqa: S608
                    tuple(item.event_id for item in archived),
                )
        checkpoint = self.append(
            "system",
            summary,
            kind="checkpoint",
            importance=1.0,
            pinned=True,
            source="neyvia-context-engine",
            metadata={
                "focus": focus,
                "archivedEventIds": [item.event_id for item in archived],
                "protectedEventIds": sorted(protected_ids),
            },
        )
        compaction_id = f"compact_{uuid.uuid4().hex[:12]}"
        receipt_path = self.receipt_root / f"{compaction_id}.json"
        receipt = {
            "schema": CONTEXT_COMPACTION_SCHEMA,
            "compactionId": compaction_id,
            "sessionId": self.session_id,
            "createdAt": _now(),
            "focus": focus,
            "archivedCount": len(archived),
            "archivedEventIds": [item.event_id for item in archived],
            "protectedCount": len(protected_ids),
            "protectedEventIds": sorted(protected_ids),
            "protectedTokens": protected_tokens,
            "checkpointEventId": checkpoint.event_id,
            "compactionStrategy": self.compactor.strategy_id,
            "ledgerPath": str(self.db_path),
            "receiptPath": str(receipt_path),
        }
        _atomic_text(receipt_path, json.dumps(receipt, indent=2, ensure_ascii=False))
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO context_compactions (
                    compaction_id, created_at, focus, archived_count,
                    protected_count, checkpoint_event_id, receipt_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compaction_id,
                    receipt["createdAt"],
                    focus,
                    len(archived),
                    len(protected_ids),
                    checkpoint.event_id,
                    str(receipt_path),
                ),
            )
        return receipt

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_count,
                    SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS archived_count,
                    COALESCE(SUM(tokens), 0) AS total_tokens,
                    COALESCE(SUM(CASE WHEN active = 1 THEN tokens ELSE 0 END), 0) AS active_tokens,
                    COALESCE(SUM(CASE WHEN artifact_path != '' THEN 1 ELSE 0 END), 0) AS artifact_count
                FROM context_events
                """
            ).fetchone()
            compactions = int(
                connection.execute("SELECT COUNT(*) FROM context_compactions").fetchone()[0]
            )
        return {
            "schema": CONTEXT_LEDGER_SCHEMA,
            "sessionId": self.session_id,
            "ledgerPath": str(self.db_path),
            "totalEvents": int(row["total_count"] or 0),
            "activeEvents": int(row["active_count"] or 0),
            "archivedEvents": int(row["archived_count"] or 0),
            "totalTokensRetained": int(row["total_tokens"] or 0),
            "activeTokens": int(row["active_tokens"] or 0),
            "artifactBackedEvents": int(row["artifact_count"] or 0),
            "compactionCount": compactions,
            "modelVisibleLimit": max(1, self.max_context_tokens - self.reserve_tokens),
            "continuityMode": "durable_unbounded_ledger_bounded_active_window",
            "compactionStrategy": self.compactor.strategy_id,
        }
