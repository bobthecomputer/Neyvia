"""Codex adapter for connected sessions.

One long-lived ``codex app-server`` (see ``codex_rpc``) serves every Neyvia
client. Existing Codex threads are listed and read through its paged API, and
continued in place with ``thread/resume`` + ``turn/start``. The Codex desktop
app runs its own app-server; its ownership is detected from the OS writer lock
(bounded rollout tail for legacy stores). A competing turn is refused with
``code == "session_live_elsewhere"`` and can continue as a separate branch.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Sequence

from .codex_items import (
    REQUEST_METHODS, context_from_rollout, iso_from_seconds,
    map_turns, media_refs_of_item, media_token, permission_mode_for, permission_modes,
    plan_from_rollout, public_request, rollout_activity, server_request_result, session_id_for, status_from_thread,
    ordinal_from_seq, strip_extended_prefix, summarize_thread, thread_permission_params, turn_permission_params,
)
from .codex_rpc import AppServerConnection, CodexError, ConnectionLost, RpcError, resolve_command
from .codex_stream import ThreadStream, now_iso
from .codex_writer import active_writer
from .model import ContextUsage, Emit, Item, ItemsPage, LiveOwner, SessionStatus, SessionSummary, TurnOptions
from .plan import latest_plan
from ..proofs_a_providers import checked, check_event, check_goal_note

LIST_PAGE = 100
LIST_MAX = 1000
LIVE_RECENT = 30
LIVE_TTL = 2.0
MAX_PAGE_ITEMS = 200
MAX_INDEX_PAGES = 250
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MEDIA_SCAN_PAGES = 10
LOST_MESSAGE = ("Codex app-server stopped before this turn finished. Neyvia has not resent it; "
                "inspect the chat, then send again if needed.")
OWNER_LABELS = {"app": "the Codex app", "cli": "the Codex CLI", "neyvia": "Neyvia"}
_MISSING = object()


class _TurnIndex:
    """Turn ids of one thread, oldest first; a turn's index is its ordinal."""

    __slots__ = ("ids", "ordinal_of")

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.ordinal_of = {turn_id: n for n, turn_id in enumerate(ids)}


class _Emitter:
    """Serialises a run's events and keeps a failing listener from stopping the run."""

    def __init__(self, target: Callable[[], Emit | None]) -> None:
        self._target = target
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, Any]) -> None:
        check_event("codex", event)
        emit = self._target()
        if emit is None:
            return
        with self._lock:
            try:
                emit(event)
            except Exception:
                pass


class _Pending:
    __slots__ = ("request_id", "server_id", "generation", "method", "params", "public")

    def __init__(self, request_id: str, server_id: Any, generation: int, method: str,
                 params: dict[str, Any], public: dict[str, Any]) -> None:
        self.request_id, self.server_id, self.generation = request_id, server_id, generation
        self.method, self.params, self.public = method, params, public


class _Run:
    def __init__(self, run_id: str, emit: Callable[[], Emit | None], kind: str = "turn") -> None:
        self.run_id = run_id
        self.kind = kind  # "turn" | "compact" | "ambient"
        self.emit = _Emitter(emit)
        self.thread_id = ""
        self.session_id = ""
        self.turn_id: str | None = None
        self.generation = 0
        self.inbox: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.stream: ThreadStream | None = None
        self.state = "queued"
        self.pending: dict[str, _Pending] = {}
        self.interrupt_requested = False
        self.compact_done = False
        self.stop_reason: str | None = None
        self.interrupt_at = 0.0
        self.turn_ready = threading.Event()
        self.lock = threading.RLock()
        self.last_activity = time.monotonic()
        self.context_before: int | None = None

    def set_state(self, state: str | None = None, error: str | None = None, code: str | None = None) -> None:
        with self.lock:
            if state is None:
                waiting = [p.public["kind"] for p in self.pending.values()]
                state = "waiting_input" if "question" in waiting else "waiting_approval" if waiting else "running"
            self.state = state
            pending = next(iter(self.pending.values())).public if self.pending else None
            event: dict[str, Any] = {"type": "run.state", "sessionId": self.session_id, "runId": self.run_id,
                                     "state": state, "pendingRequest": pending, "error": error}
            if code:
                event["code"] = code
            self.emit(event)


class CodexAdapter:
    app = "codex"

    def __init__(self, *, state_root: str | Path | None = None, command: Sequence[str] | None = None, trace: Callable[[str, dict[str, Any]], None] | None = None,
                 rpc_timeout: float = 30.0, idle_watchdog_seconds: float | None = None, list_ttl: float = 3.0,
                 device: dict[str, str] | None = None) -> None:
        self._command = list(command) if command else None
        self.state_root = Path(state_root).resolve() if state_root is not None else None
        self._rpc_timeout = rpc_timeout
        self._watchdog = idle_watchdog_seconds
        self._list_ttl = list_ttl
        self._device_override = device
        self._lock = threading.RLock()
        self._runs: dict[str, _Run] = {}
        self._thread_runs: dict[str, str] = {}
        self._threads: dict[str, dict[str, Any]] = {}
        self._contexts: dict[str, ContextUsage] = {}
        self._goals: dict[str, dict[str, Any]] = {}
        self._goal_expect: dict[str, tuple[str, float]] = {}
        self._since: dict[str, str] = {}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._turn_cursors: OrderedDict[str, OrderedDict[int, str | None]] = OrderedDict()
        self._turn_indexes: OrderedDict[str, _TurnIndex] = OrderedDict()
        self._sink: Emit | None = None
        self._plugin_index: dict[str, dict[str, Any]] = {}
        self._conn = AppServerConnection(
            lambda: resolve_command(self._command), on_notification=self._on_notification,
            on_server_request=self._on_server_request, on_lost=self._on_lost, trace=trace,
            idle_guard=lambda: bool(self._runs) or any(goal.get("status") == "active" for goal in tuple(self._goals.values())))

    # -- basics ------------------------------------------------------------

    @checked("providers.codex.available")
    def available(self) -> tuple[bool, str | None]:
        from ..local_network_policy import enabled
        if enabled():
            return False, "Local-only is on. Turn it off in Settings to use Codex."
        if resolve_command(self._command):
            return True, None
        return False, "Codex CLI is not installed on this host."

    def close(self) -> None:
        self._conn.close()

    def set_event_sink(self, emit: Emit | None) -> None:
        """Receive events that belong to no run Neyvia started (a goal's own turns, thread renames)."""
        self._sink = emit

    def _device(self) -> dict[str, str]:
        if self._device_override:
            return self._device_override
        from ..external_chat_inventory import _host
        return _host()

    def _thread_id(self, session_id: str) -> str:
        parts = str(session_id or "").split(":", 3)
        if len(parts) != 4 or parts[0] != "external" or parts[1] != "codex":
            raise CodexError("invalid_session", "Expected a Codex chat id.")
        if parts[2] != self._device()["deviceId"]:
            raise CodexError("invalid_session", "This Codex chat belongs to another device.")
        from urllib.parse import unquote
        thread_id = unquote(parts[3])
        if not thread_id or len(thread_id) > 200 or any(ch in thread_id for ch in "\\/\x00"):
            raise CodexError("invalid_session", "Invalid Codex thread id.")
        return thread_id

    def _sid(self, thread_id: str) -> str:
        return session_id_for(thread_id, self._device()["deviceId"])

    @checked("providers.codex.wire")
    def _rpc(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        try:
            return self._conn.request(method, params, timeout=self._rpc_timeout if timeout is None else timeout)
        except RpcError as exc:
            # A writer can acquire the lock between preflight and resume. Translate
            # this race too, including compact/goal paths; never expose JSON-RPC.
            if "already has an active writer" in exc.raw_message.lower():
                thread = self._threads.get(str((params or {}).get("threadId")), {})
                owner = self._owner_of(thread)
                raise CodexError("session_live_elsewhere", self._writer_reason(owner), owner=owner) from exc
            raise

    def _supports_fork(self) -> bool:
        # These paginated app-server versions ship thread/fork. Do not advertise
        # it for an unidentified/older server whose protocol we cannot establish.
        version = re.search(r"/(\d+)\.(\d+)\.(\d+)", str(self._conn.server_info.get("userAgent") or ""))
        return bool(version and tuple(map(int, version.groups())) >= (0, 153, 0))

    def _writer_reason(self, owner: str) -> str:
        branch = " Or choose Continue as a branch from the + menu." if self._supports_fork() else ""
        return (f"This chat is working elsewhere in {OWNER_LABELS[owner]}. "
                f"Let it finish or close it there; Neyvia will check again automatically.{branch}")

    def _cached(self, key: str, ttl: float, produce: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = produce()
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def _drop_cache(self, *prefixes: str) -> None:
        with self._lock:
            for key in [k for k in self._cache if any(k.startswith(p) for p in prefixes)]:
                del self._cache[key]

    # -- listing -----------------------------------------------------------

    def _projects(self, *, fetch: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            hit = self._cache.get("projects")
        # Project names are decoration: never start or wait on the process for them.
        if hit and (time.monotonic() - hit[0] < 30.0 or not fetch or not self._conn.alive):
            return hit[1]
        if not fetch or not self._conn.alive:
            return []
        found: list[dict[str, Any]] = []
        cursor = None
        try:
            for _ in range(10):
                params: dict[str, Any] = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                page = self._rpc("project/list", params)
                found += [p for p in page.get("data") or [] if isinstance(p, dict)]
                cursor = page.get("nextCursor")
                if not cursor:
                    break
        except CodexError:
            return hit[1] if hit else []
        with self._lock:
            self._cache["projects"] = (time.monotonic(), found)
        return found

    def _list_threads(self, *, archived: bool, cap: int | None) -> list[dict[str, Any]]:
        def load() -> list[dict[str, Any]]:
            threads: list[dict[str, Any]] = []
            cursor = None
            cursors: set[str] = set()
            while cap is None or len(threads) < cap:
                # useStateDbOnly skips the rollout scan; without it one page of 100 took ~30 s.
                params: dict[str, Any] = {"limit": LIST_PAGE if cap is None else min(LIST_PAGE, cap - len(threads)), "sortKey": "updated_at",
                                          "sortDirection": "desc", "useStateDbOnly": True}
                if archived:
                    params["archived"] = True
                if cursor:
                    params["cursor"] = cursor
                page = self._rpc("thread/list", params)
                threads += [t for t in page.get("data") or [] if isinstance(t, dict) and t.get("id")]
                cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
                if not cursor or not page.get("data"):
                    break
                if cursor in cursors:
                    raise CodexError("inventory_paging_failed", "Codex inventory paging did not advance.")
                cursors.add(cursor)
            return threads
        threads = self._cached(f"threads:{archived}:{cap}", self._list_ttl if cap is None or cap > LIVE_RECENT else LIVE_TTL, load)
        with self._lock:
            for thread in threads:
                self._threads[str(thread["id"])] = thread
        return threads

    @checked("providers.codex.summary")
    def _summary(self, thread: dict[str, Any], *, archived: bool = False, live: dict[str, tuple[str, str | None]] | None = None,
                 since: str | None = None, fetch: bool = True) -> SessionSummary:
        available, reason = self._cached("available", 30.0, self.available)
        summary = summarize_thread(thread, device=self._device(), projects=self._projects(fetch=fetch),
                                   available=available, reason=reason, archived=archived)
        entry = (live or {}).get(summary.id)
        if entry:
            summary.status, summary.live_owner = entry[0], entry[1]  # type: ignore[assignment]
            summary.status_since = since or self._since.get(summary.id)
        if summary.capabilities.continue_session:
            summary.capabilities.fork = self._supports_fork()
            if summary.live_owner in ("app", "cli"):
                summary.capabilities.continue_session = False
                summary.capabilities.compact = False
                summary.capabilities.goal = False
                summary.capabilities.steer = False
                summary.capabilities.stop = False
                summary.capabilities.reason = self._writer_reason(summary.live_owner)
        return summary

    @checked("providers.codex.list")
    def list_sessions(self, *, include_archived: bool = False, limit: int = LIST_MAX) -> list[SessionSummary]:
        cap = max(1, min(int(limit or LIST_MAX), LIST_MAX))
        threads = self._list_threads(archived=False, cap=cap)
        live = self._live()
        rows = [self._summary(t, live=live) for t in threads]
        if include_archived:
            rows += [self._summary(t, archived=True) for t in self._list_threads(archived=True, cap=min(cap, 200))]
        rows.sort(key=lambda row: row.updated_at or "", reverse=True)
        return rows

    # -- live status -------------------------------------------------------

    def _owner_of(self, thread: dict[str, Any]) -> str:
        return "cli" if thread.get("source") in ("cli", "exec") else "app"

    def _ours(self) -> dict[str, tuple[str, str | None]]:
        with self._lock:
            runs = [(run.thread_id, run.state) for run in self._runs.values() if run.thread_id]
        status = {"running": "working", "queued": "working", "waiting_approval": "waiting_approval", "waiting_input": "waiting_input"}
        return {self._sid(tid): (status.get(state, "working"), "neyvia") for tid, state in runs if state in status}

    @checked("providers.codex.writer")
    def _elsewhere(self, thread: dict[str, Any]) -> dict[str, Any] | None:
        """OS ownership outlives rollout activity, including idle app/CLI writers."""
        locked = active_writer(str(thread.get("id") or ""), thread.get("path"))
        if locked is False:
            return None  # completed/crashed writer; an unfinished rollout is not a lock
        activity = rollout_activity(thread.get("path"))
        if locked is True:
            return {"owner": self._owner_of(thread), "since": activity.get("since")}
        if not activity["inProgress"]:
            return None
        return {"owner": self._owner_of(thread), "since": activity.get("since"), "ageSeconds": activity.get("ageSeconds")}

    def _live(self) -> dict[str, tuple[str, str | None]]:
        def compute() -> dict[str, tuple[str, str | None]]:
            elsewhere: dict[str, tuple[str, str | None]] = {}
            since: dict[str, str] = {}
            try:
                recent = self._list_threads(archived=False, cap=LIVE_RECENT)
            except CodexError:
                return elsewhere
            for thread in recent:
                found = self._elsewhere(thread)
                if found:
                    sid = self._sid(str(thread["id"]))
                    elsewhere[sid] = ("working", self._owner_of(thread))
                    if found.get("since"):
                        since[sid] = found["since"]
            with self._lock:
                self._since = since
            return elsewhere
        # What another process is doing is cached ~2 s; what Neyvia itself is running is always current.
        return {**self._cached("live", LIVE_TTL, compute), **self._ours()}

    @checked("providers.codex.live")
    def live_status(self) -> dict[str, tuple[SessionStatus, LiveOwner | None]]:
        return self._live()  # type: ignore[return-value]

    def running_sessions(self) -> list[SessionSummary]:
        """Every current writer, even when its chat falls outside the sidebar history.

        Modern Codex exposes OS writer locks, so discovery needs no rollout scan.
        Legacy stores use complete RPC history pages and the existing activity probe.
        Neither path attaches to, resumes, or starts an externally owned thread.
        """
        directory = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "thread-writer-locks"
        live = self._ours()
        threads: dict[str, dict[str, Any]] = {}
        if directory.is_dir():
            candidates = {path.stem for path in directory.glob("*.lock")
                          if active_writer(path.stem, None) is True}
            candidates.update(self._thread_id(sid) for sid in live)
            for thread_id in candidates:
                threads[thread_id] = self._thread_meta(thread_id)
        else:
            for thread in self._list_threads(archived=False, cap=None):
                threads[str(thread["id"])] = thread
        found = []
        for thread in threads.values():
            sid = self._sid(str(thread["id"]))
            owner = self._elsewhere(thread)
            if owner:
                live.setdefault(sid, ("working", owner["owner"]))
            if sid in live:
                found.append(self._summary(thread, live=live, since=(owner or {}).get("since")))
        return found

    # -- reading -----------------------------------------------------------

    @checked("providers.codex.thread")
    def _thread_meta(self, thread_id: str) -> dict[str, Any]:
        try:
            result = self._rpc("thread/read", {"threadId": thread_id, "includeTurns": False})
        except RpcError as exc:
            if re.search(r"not loaded|not found|no rollout|invalid thread id|unknown thread|does not exist", exc.raw_message, re.I):
                raise CodexError("session_not_found", "Codex has no chat with this id on this device.") from exc
            raise
        thread = result.get("thread") if isinstance(result, dict) else None
        if not isinstance(thread, dict) or str(thread.get("id") or "") != thread_id:
            raise CodexError("session_not_found", "Codex has no chat with this id on this device.")
        with self._lock:
            self._threads[thread_id] = thread
        return thread

    def _remember_cursor(self, thread_id: str, ordinal: int, cursor: str | None) -> None:
        """Remember the cursor that fetches the turn with this ordinal (None: the newest turn)."""
        if ordinal < 0:
            return
        with self._lock:
            table = self._turn_cursors.setdefault(thread_id, OrderedDict())
            self._turn_cursors.move_to_end(thread_id)
            table[ordinal] = cursor
            while len(table) > 2000:
                table.popitem(last=False)
            while len(self._turn_cursors) > 40:
                self._turn_cursors.popitem(last=False)

    def _index_turns(self, thread_id: str, *, force: bool = False) -> _TurnIndex:
        """Every turn id of the thread, oldest first. Metadata only, so a long thread costs a few small requests.

        A turn's ordinal (its position in this list) is what makes seq stable. The list is
        reused while the newest turn is unchanged.
        """
        with self._lock:
            cached = self._turn_indexes.get(thread_id)
        if cached is not None and not force:
            head = self._rpc("thread/turns/list", {"threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded"})
            data = [t for t in head.get("data") or [] if isinstance(t, dict)]
            newest = str(data[0].get("id")) if data else None
            if newest == (cached.ids[-1] if cached.ids else None):
                return cached
        newest_first: list[str] = []
        boundaries: dict[int, str] = {}
        cursor: str | None = None
        for _ in range(MAX_INDEX_PAGES):
            params: dict[str, Any] = {"threadId": thread_id, "limit": 100, "sortDirection": "desc", "itemsView": "notLoaded"}
            if cursor:
                params["cursor"] = cursor
            page = self._rpc("thread/turns/list", params, timeout=60)
            data = [t for t in page.get("data") or [] if isinstance(t, dict)]
            newest_first += [str(t.get("id")) for t in data]
            cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
            if not data or not cursor:
                break
            boundaries[len(newest_first)] = cursor  # fetches the turn at this distance from the newest
        index = _TurnIndex(newest_first[::-1])
        total = len(index.ids)
        self._remember_cursor(thread_id, total - 1, None)
        for distance, boundary in boundaries.items():
            self._remember_cursor(thread_id, total - 1 - distance, boundary)
        with self._lock:
            self._turn_indexes[thread_id] = index
            self._turn_indexes.move_to_end(thread_id)
            while len(self._turn_indexes) > 40:
                self._turn_indexes.popitem(last=False)
        return index

    def _ordinal_of_turn(self, thread_id: str, turn_id: str, *, fetch: bool) -> int:
        """Ordinal of a turn; a turn not persisted yet (the one starting now) is the next one."""
        try:
            index = self._index_turns(thread_id) if fetch else self._turn_indexes.get(thread_id)
        except CodexError:
            index = self._turn_indexes.get(thread_id)
        if index is None:
            return 0
        found = index.ordinal_of.get(turn_id)
        return found if found is not None else len(index.ids)

    def _cursor_at(self, thread_id: str, target: int, total: int) -> str | None:
        """Cursor that fetches the turn with ordinal ``target``, walking down from the nearest one known."""
        with self._lock:
            table = dict(self._turn_cursors.get(thread_id, {}))
        if target >= total - 1:
            return None
        if target in table:
            return table[target]
        ordinal = min((o for o in table if o > target), default=total - 1)
        cursor = table.get(ordinal)
        while ordinal > target:
            page = self._rpc("thread/turns/list", {"threadId": thread_id, "limit": 1, "sortDirection": "desc",
                                                   "itemsView": "notLoaded", **({"cursor": cursor} if cursor else {})}, timeout=60)
            following = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
            ordinal -= 1
            if not following and ordinal > target:
                raise CodexError("thread_changed", "This chat changed while it was being read. Try again.")
            cursor = following
            self._remember_cursor(thread_id, ordinal, following)
        return cursor

    def _load_turns(self, thread_id: str, cwd: str | None, limit: int, before_seq: int | None,
                    stop_ordinal: int | None) -> tuple[list[Item], bool, int | None]:
        """Whole turns newest-first, one request each so every turn has a resumable cursor.

        Returns (items oldest-first, has_earlier, ordinal of the newest turn).
        """
        for attempt in range(2):
            found = self._read_turns(thread_id, cwd, limit, before_seq, stop_ordinal, self._index_turns(thread_id, force=attempt > 0))
            if found is not None:
                return found
        raise CodexError("thread_changed", "This chat changed while it was being read. Try again.")

    def _read_turns(self, thread_id: str, cwd: str | None, limit: int, before_seq: int | None,
                    stop_ordinal: int | None, index: _TurnIndex) -> tuple[list[Item], bool, int | None] | None:
        total = len(index.ids)
        if total == 0:
            return [], False, None
        ordinal = total - 1 if before_seq is None else min(ordinal_from_seq(before_seq), total - 1)
        cursor = self._cursor_at(thread_id, ordinal, total)
        chunks: list[list[Item]] = []
        count = 0
        more = False
        while ordinal >= 0:
            params: dict[str, Any] = {"threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "full"}
            if cursor:
                params["cursor"] = cursor
            page = self._rpc("thread/turns/list", params, timeout=120)
            data = [t for t in page.get("data") or [] if isinstance(t, dict)]
            if not data:
                break
            turn = data[0]
            if str(turn.get("id")) != index.ids[ordinal]:
                return None  # the thread changed under us; the caller re-indexes
            with self._lock:
                locations = getattr(self, "_output_turns", None)
                if locations is None:
                    self._output_turns = locations = OrderedDict()
                for raw in turn.get("items") or []:
                    if isinstance(raw, dict) and raw.get("type") in {"commandExecution", "mcpToolCall", "dynamicToolCall", "functionCallOutput"}:
                        locations[(thread_id, str(raw.get("id")))] = str(turn["id"])
                while len(locations) > 4096:
                    locations.popitem(last=False)
            following = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
            self._remember_cursor(thread_id, ordinal - 1, following)
            mapped = map_turns([turn], index.ordinal_of, cwd=cwd)
            if before_seq is not None:
                mapped = [item for item in mapped if item.seq < before_seq]
            chunks.append(mapped)
            count += len(mapped)
            if stop_ordinal is not None and ordinal <= stop_ordinal:
                break
            ordinal -= 1
            cursor = following
            more = ordinal >= 0 and following is not None
            if not more or count >= limit:
                break
        items = [item for chunk in reversed(chunks) for item in chunk]
        if len(items) > limit:
            items, more = items[-limit:], True
        return items, more, total - 1

    def _context(self, thread_id: str, thread: dict[str, Any]) -> ContextUsage:
        with self._lock:
            cached = self._contexts.get(thread_id)
        # While a run streams, its numbers are newest; otherwise the persisted ones are, since
        # the Codex app may have continued this chat since Neyvia last ran a turn in it.
        context = cached if cached is not None and self._run_for(thread_id) else None
        if context is None:
            context = context_from_rollout(thread.get("path")) or cached or ContextUsage()
        if context.auto_compact_tokens is None:
            context = ContextUsage(context.used_tokens, context.window_tokens, self._auto_compact_tokens(),
                                   context.source, context.updated_at)
        return context

    def _auto_compact_cached(self) -> int | None:
        with self._lock:
            hit = self._cache.get("auto-compact")
        return hit[1] if hit else None

    def _auto_compact_tokens(self) -> int | None:
        def load() -> int | None:
            try:
                config = self._rpc("config/read", {}).get("config") or {}
            except CodexError:
                return None
            value = config.get("model_auto_compact_token_limit")
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
        return self._cached("auto-compact", 300.0, load)

    @checked("providers.codex.page")
    def read(self, session_id: str, *, cursor: str | None = None, before_seq: int | None = None,
             limit: int = MAX_PAGE_ITEMS) -> ItemsPage:
        thread_id = self._thread_id(session_id)
        limit = max(1, min(int(limit or MAX_PAGE_ITEMS), MAX_PAGE_ITEMS))
        thread = self._thread_meta(thread_id)
        cwd = strip_extended_prefix(thread.get("cwd")) or None
        stop_ordinal = None
        if cursor and str(cursor).startswith("t2:") and str(cursor)[3:].isdigit():
            stop_ordinal = int(str(cursor)[3:])
        items, has_earlier, newest = self._load_turns(thread_id, cwd, limit, before_seq, stop_ordinal)
        if stop_ordinal is not None:
            has_earlier = False
        run = self._run_for(thread_id)
        if run and run.stream and before_seq is None:
            by_id = {item.id: item for item in items}
            for live in run.stream.live_items():
                by_id[live.id] = live
            items = sorted(by_id.values(), key=lambda item: item.seq)
        next_cursor = f"t2:{newest}" if newest is not None else None
        summary = self._live_summary(thread)
        plan = latest_plan(items)
        if plan is None and cursor is None and before_seq is None:
            # Codex keeps update_plan out of its thread items; the rollout has the call itself.
            plan = plan_from_rollout(thread.get("path"))
            if plan is not None:
                plan["throughSeq"] = max((item.seq for item in items), default=0)
        return ItemsPage(session=summary, items=items, context=self._context(thread_id, thread),
                         cursor=next_cursor, has_earlier=has_earlier, plan=plan)

    def _live_summary(self, thread: dict[str, Any]) -> SessionSummary:
        sid = self._sid(str(thread["id"]))
        live = dict(self._ours())
        since = None
        if sid not in live:
            loaded = status_from_thread(thread.get("status"))
            elsewhere = None if loaded in ("working", "waiting_approval", "waiting_input") else self._elsewhere(thread)
            if loaded in ("working", "waiting_approval", "waiting_input"):
                live[sid] = (loaded, "neyvia")  # loaded and running in this process
            elif elsewhere:
                live[sid] = ("working", elsewhere["owner"])
                since = elsewhere.get("since")
        return self._summary(thread, archived=self._is_archived(thread), live=live, since=since)

    def refresh_summary(self, session_id: str) -> SessionSummary:
        """Refresh capabilities without hydrating history, including writer release."""
        return self._live_summary(self._thread_meta(self._thread_id(session_id)))

    def _is_archived(self, thread: dict[str, Any]) -> bool:
        return "archived_sessions" in strip_extended_prefix(thread.get("path")).replace("\\", "/")

    def tool_output(self, session_id: str, item_id: str) -> str | None:
        """Read native output on demand; the broker applies its explicit response cap."""
        from .codex_items import _text_of_content, map_thread_item
        thread_id = self._thread_id(session_id)
        cursor = None
        with self._lock:
            turn_id = getattr(self, "_output_turns", {}).get((thread_id, item_id))
        for _ in range(20):
            params = {"threadId": thread_id, "limit": 10, "sortDirection": "desc", "itemsView": "full"}
            if cursor:
                params["cursor"] = cursor
            if turn_id:
                item_page = self._rpc("thread/items/list", {"threadId": thread_id, "turnId": turn_id, "limit": 200, "cursor": cursor}, timeout=20)
                page = {"data": [{"items": [entry["item"] for entry in item_page.get("data") or [] if isinstance(entry, dict) and isinstance(entry.get("item"), dict)]}], "nextCursor": item_page.get("nextCursor")}
            else:
                page = self._rpc("thread/turns/list", params, timeout=20)
            for turn in page.get("data") or []:
                for raw in turn.get("items") or []:
                    if not isinstance(raw, dict) or raw.get("id") != item_id:
                        continue
                    if raw.get("type") == "commandExecution":
                        return str(raw.get("aggregatedOutput") or "")
                    if raw.get("type") == "mcpToolCall":
                        return _text_of_content((raw.get("result") or {}).get("content")) or str((raw.get("error") or {}).get("message") or "")
                    if raw.get("type") == "dynamicToolCall":
                        return _text_of_content(raw.get("contentItems"))
                    if raw.get("type") == "functionCallOutput":
                        return _text_of_content(raw.get("output"))
                    mapped = map_thread_item(raw, seq=0, at=None)
                    return next((str(item.data.get("output") or "") for item in mapped if item.kind == "tool"), None)
            cursor = page.get("nextCursor")
            if not cursor:
                break
        run = self._run_for(thread_id)
        item = run.stream.items.get(item_id) if run and run.stream else None
        return str(item.data.get("output") or "") if item and item.kind == "tool" else None

    @checked("providers.codex.media")
    def read_media(self, session_id: str, media_id: str) -> tuple[bytes, str, str]:
        """Bytes of an image referenced by a message, found through the same paged API."""
        thread_id = self._thread_id(session_id)
        if not re.fullmatch(r"[0-9a-f]{64}", str(media_id or "")):
            raise CodexError("invalid_media", "Invalid media id.")
        cursor: str | None = None
        for _ in range(MEDIA_SCAN_PAGES):
            params: dict[str, Any] = {"threadId": thread_id, "limit": 100, "sortDirection": "desc"}
            if cursor:
                params["cursor"] = cursor
            page = self._rpc("thread/items/list", params, timeout=60)
            for entry in page.get("data") or []:
                for ref in media_refs_of_item(entry.get("item") or {}):
                    if media_token(ref) == media_id:
                        return _load_media(ref)
            cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
            if not cursor:
                break
        raise CodexError("media_not_found", "That image is not in this chat's recent history.")

    # -- runs --------------------------------------------------------------

    def _run_for(self, thread_id: str | None) -> _Run | None:
        if not thread_id:
            return None
        with self._lock:
            run_id = self._thread_runs.get(thread_id)
            return self._runs.get(run_id) if run_id else None

    def _register(self, run: _Run) -> None:
        with self._lock:
            self._runs[run.run_id] = run
            if run.thread_id:
                self._thread_runs[run.thread_id] = run.run_id

    def _unregister(self, run: _Run) -> None:
        with self._lock:
            self._runs.pop(run.run_id, None)
            if self._thread_runs.get(run.thread_id) == run.run_id:
                del self._thread_runs[run.thread_id]
        self._drop_cache("live")

    def check_send(self, session_id: str) -> None:
        """Raise ``CodexError`` (code ``session_live_elsewhere`` / ``session_busy``) if a turn cannot start."""
        self._check_thread(self._thread_id(session_id))

    def _check_thread(self, thread_id: str, *, own_run_ok: bool = False) -> dict[str, Any]:
        own = self._run_for(thread_id)
        if own and not own_run_ok:
            raise CodexError("session_busy", "Neyvia is already running a turn in this chat. Steer it or stop it first.", owner="neyvia")
        thread = self._thread_meta(thread_id)
        elsewhere = None if own else self._elsewhere(thread)
        if elsewhere:
            owner = elsewhere["owner"]
            raise CodexError("session_live_elsewhere", self._writer_reason(owner), owner=owner)
        return thread

    def _new_run(self, run_id: str, emit: Emit, kind: str) -> _Run:
        return _Run(run_id, lambda: emit, kind)

    @checked("providers.codex.lifecycle")
    def start_turn(self, session_id: str | None, message: str, options: TurnOptions, *, cwd: str | None,
                   run_id: str, emit: Emit) -> str:
        text = str(message or "").strip()
        images = list(options.images or [])
        if not text and not images:
            raise CodexError("empty_message", "Write a message or attach an image.")
        user_input = _build_input(text, images)
        thread_id: str | None = None
        if session_id:
            thread_id = self._thread_id(session_id)
            self._check_thread(thread_id)
        else:
            folder = Path(str(cwd or "")).expanduser()
            if not cwd or not folder.is_dir():
                raise CodexError("cwd_missing", "Choose an existing folder to start a Codex chat in.")
        run = self._new_run(run_id, emit, "turn")
        with self._lock:
            if run_id in self._runs:
                raise CodexError("run_exists", "This run id is already in use.")
            if thread_id and thread_id in self._thread_runs:
                raise CodexError("session_busy", "Neyvia is already running a turn in this chat. Steer it or stop it first.", owner="neyvia")
            self._runs[run_id] = run
            if thread_id:
                run.thread_id = thread_id
                run.session_id = self._sid(thread_id)
                self._thread_runs[thread_id] = run_id
        try:
            run.generation = self._conn.ensure_started()
            if thread_id is None:
                method = "thread/fork" if options.fork_from else "thread/start"
                # The person started this chat, as in the Codex app: the app lists only threads whose
                # source says so, so without it Neyvia's chats never show up there.
                params = {"cwd": str(cwd), "threadSource": "user", **({"model": options.model} if options.model else {}),
                          **thread_permission_params(options.permission_mode)}
                from ..cua_launch import codex_config
                cua = codex_config(session_id or ("codex-run:" + run_id))
                params["config"] = {**(cua or {}), "model_reasoning_summary": "detailed", "show_raw_agent_reasoning": True}
                if options.fork_from:
                    params.update(threadId=self._thread_id(options.fork_from), excludeTurns=True)
                from ..neyvia_intent_plan import codex_thread_params
                params.update(codex_thread_params())  # multi-ask messages get an intent checklist (update_plan)
                from ..neyvia_parallel_codex import thread_tools
                params.update(thread_tools(cwd))
                from .work_board import turn_note as work_note
                awareness = work_note(self.state_root, cwd)
                if awareness:
                    params["developerInstructions"] += "\n\n" + awareness
                started = self._rpc(method, params, timeout=60)
                thread = started["thread"]
                thread_id = str(thread["id"])
            else:
                from ..cua_launch import codex_config
                cua = codex_config(session_id)
                from ..neyvia_intent_plan import codex_thread_params
                from .work_board import turn_note as work_note
                known_cwd = cwd or self._threads.get(thread_id, {}).get("cwd")
                instructions = codex_thread_params()
                awareness = work_note(self.state_root, known_cwd, session_id)
                if awareness:
                    instructions["developerInstructions"] += "\n\n" + awareness
                resumed = self._rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True,
                    **instructions,
                    "config": {**(cua or {}), "model_reasoning_summary": "detailed", "show_raw_agent_reasoning": True}}, timeout=60)
                thread = resumed.get("thread") if isinstance(resumed.get("thread"), dict) else {}
            self._attach(run, thread_id, thread)
            run.set_state("running")
            self._announce(run, thread, working=True)
            params: dict[str, Any] = {"threadId": thread_id, "input": user_input, "summary": "detailed", **turn_permission_params(options.permission_mode)}
            if options.model:
                params["model"] = options.model
            if options.effort:
                params["effort"] = options.effort
            if cwd and session_id:
                params["cwd"] = str(cwd)
            if session_id:
                # Resume updates thread configuration, but an existing history retains its old
                # developer message. Carry the observed snapshot in a separate input block too.
                from .work_board import turn_note as work_note
                awareness = work_note(self.state_root, cwd or thread.get("cwd"), session_id)
                if awareness:
                    params["input"] = [*user_input, {"type": "text", "text":
                        "Neyvia observed coordination state (not a new user request):\n" + awareness,
                        "text_elements": []}]
            response = self._rpc("turn/start", params, timeout=60)
            turn = response.get("turn") if isinstance(response, dict) and isinstance(response.get("turn"), dict) else {}
            self._set_turn(run, str(turn.get("id") or ""), turn)
        except ConnectionLost:
            self._finish(run, "interrupted", LOST_MESSAGE, code="app_server_stopped")
            return run.session_id or str(session_id or "")
        except CodexError as exc:
            self._finish(run, "failed", str(exc), code=exc.code)
            return run.session_id or str(session_id or "")
        state, error = self._drive(run)
        self._finish(run, state, error)
        return run.session_id

    def _attach(self, run: _Run, thread_id: str, thread: dict[str, Any]) -> None:
        run.thread_id = thread_id
        run.session_id = self._sid(thread_id)
        from ..neyvia_cua import bind_chat
        bind_chat("codex-run:" + run.run_id, run.session_id)
        with self._lock:
            if thread:
                self._threads[thread_id] = {**self._threads.get(thread_id, {}), **thread}
            self._thread_runs[thread_id] = run.run_id
            cwd = strip_extended_prefix(self._threads.get(thread_id, {}).get("cwd")) or None
        # A run's stream is only driven from its own thread, so it may ask the server for a turn's ordinal.
        run.stream = ThreadStream(run.session_id, thread_id, run.emit, cwd=cwd, on_context=lambda c: self._store_context(thread_id, c, run),
                                  auto_compact_tokens=self._auto_compact_tokens,
                                  ordinal_of_turn=lambda turn_id: self._ordinal_of_turn(thread_id, turn_id, fetch=True))
        self._drop_cache("live")

    def _set_turn(self, run: _Run, turn_id: str, turn: dict[str, Any]) -> None:
        if not turn_id:
            return
        run.turn_id = turn_id
        if run.stream:
            run.stream.begin_turn(turn or {"id": turn_id})
        run.turn_ready.set()
        if run.interrupt_requested:
            self._send_interrupt(run)

    def _announce(self, run: _Run, thread: dict[str, Any], *, working: bool) -> None:
        with self._lock:
            data = dict(self._threads.get(run.thread_id) or thread or {"id": run.thread_id})
        live = {run.session_id: ("working", "neyvia")} if working else None
        summary = self._summary(data, live=live)
        if not working:
            elsewhere = self._elsewhere(data)
            summary = self._summary(data, live={run.session_id: ("working", elsewhere["owner"])}) if elsewhere else summary
            if not elsewhere:
                summary.status, summary.live_owner = "idle", None
        run.emit({"type": "session.updated", "session": summary.public()})

    def _store_context(self, thread_id: str, context: ContextUsage, run: _Run | None = None) -> None:
        with self._lock:
            self._contexts[thread_id] = context
        target = run.emit if run else self._sink_emit
        target({"type": "context.updated", "sessionId": self._sid(thread_id), "context": asdict(context)})

    def _sink_emit(self, event: dict[str, Any]) -> None:
        sink = self._sink
        if sink is not None:
            try:
                sink(event)
            except Exception:
                pass

    def _finish(self, run: _Run, state: str, error: str | None = None, *, code: str | None = None) -> None:
        with run.lock:
            run.pending.clear()
        run.set_state(state, error=error, code=code)
        self._unregister(run)
        self._hand_over(run)
        if run.thread_id:
            with self._lock:
                goal_active = (self._goals.get(run.thread_id) or {}).get("status") == "active"
            if not goal_active and self._conn.alive and self._conn.generation == run.generation:
                try:
                    self._rpc("thread/unsubscribe", {"threadId": run.thread_id}, timeout=10)
                except CodexError:
                    pass
            self._announce(run, {}, working=False)

    def _hand_over(self, run: _Run) -> None:
        """Notifications that reached a finished run's inbox but belong to the turn a goal started next."""
        leftover = []
        while True:
            try:
                leftover.append(run.inbox.get_nowait())
            except queue.Empty:
                break
        starts = [n for n, e in enumerate(leftover) if e[0] == "note" and e[1] == "turn/started"
                  and str((e[2].get("turn") or {}).get("id") or "") != str(run.turn_id or "")]
        if not starts or self._sink is None or not run.thread_id:
            return
        first = starts[0]
        self._adopt(run.thread_id, run.generation, leftover[first][2])
        adopted = self._run_for(run.thread_id)
        if adopted is not None:
            for entry in leftover[first + 1:]:
                adopted.inbox.put(entry)

    def _drive(self, run: _Run) -> tuple[str, str | None]:
        """Consume this run's notifications until the turn ends. No overall time limit."""
        while True:
            try:
                entry = run.inbox.get(timeout=0.5)
            except queue.Empty:
                if not self._conn.alive or self._conn.generation != run.generation:
                    return "interrupted", LOST_MESSAGE
                if run.compact_done and time.monotonic() - run.last_activity > 2.0:
                    return "completed", None
                if run.interrupt_at and time.monotonic() - run.interrupt_at > 45:
                    return "interrupted", "Stopped. Codex did not confirm the stop."
                if (self._watchdog and not run.pending and not run.interrupt_requested
                        and time.monotonic() - run.last_activity > self._watchdog):
                    # Stop it the normal way and wait for Codex to confirm, so the next send finds the thread free.
                    run.stop_reason = f"No output from Codex for {max(1, round(self._watchdog / 60))} min; the turn was stopped."
                    self.interrupt(run.run_id)
                continue
            run.last_activity = time.monotonic()
            if entry[0] == "lost":
                return "interrupted", LOST_MESSAGE
            if entry[0] == "request":
                self._on_run_request(run, *entry[1:])
                continue
            outcome = self._on_run_note(run, entry[1], entry[2])
            if outcome:
                return outcome

    def _on_run_note(self, run: _Run, method: str, params: dict[str, Any]) -> tuple[str, str | None] | None:
        stream = run.stream
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        turn_id = str(params.get("turnId") or turn.get("id") or "")
        if method == "turn/started":
            if run.turn_id is None or run.turn_id == turn_id:
                self._set_turn(run, turn_id, turn)
            return None
        if method == "serverRequest/resolved":
            self._resolve_pending(run, params.get("requestId"))
            return None
        if turn_id and run.turn_id and turn_id != run.turn_id and method.startswith(("turn/", "item/")):
            return None  # another turn on this thread
        if method == "thread/name/updated":
            self._announce(run, {"name": params.get("threadName")}, working=True)
            return None
        if method == "turn/completed":
            if stream:
                stream.end_turn(turn)
            status = str(turn.get("status") or "completed")
            error = turn.get("error") if isinstance(turn.get("error"), dict) else {}
            if status == "failed":
                return "failed", " ".join(str(error.get("message") or "The turn failed.").split())[:600]
            return ("interrupted", run.stop_reason) if status == "interrupted" else ("completed", None)
        if stream:
            stream.handle(method, params)
        if run.kind == "compact":
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            if method == "thread/compacted" or (method == "item/completed" and item.get("type") == "contextCompaction"):
                run.compact_done = True  # the turn should close right after; do not wait forever if it does not
        if run.kind == "compact" and method == "error" and not params.get("willRetry"):
            error = params.get("error") if isinstance(params.get("error"), dict) else {}
            return "failed", " ".join(str(error.get("message") or "Compaction failed.").split())[:600]
        return None

    def _on_run_request(self, run: _Run, generation: int, server_id: Any, method: str, params: dict[str, Any]) -> None:
        if method == 'item/tool/call' and str(params.get('tool') or '').startswith('neyvia_parallel_'):
            # Do not block provider notifications while the native action sends an inbox message.
            def execute_parallel():
                try:
                    from ..neyvia_parallel_codex import call
                    cwd = self._threads.get(run.thread_id, {}).get('cwd')
                    value = call(self.state_root, cwd, params['tool'], params.get('arguments') or {})
                    reply = {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(value)}]}
                except Exception as exc:
                    reply = {'success': False, 'contentItems': [{'type': 'inputText', 'text': str(exc)}]}
                self._conn.respond(generation, server_id, reply)
            threading.Thread(target=execute_parallel, name='parallel-codex-tool', daemon=True).start()
            return
        request_id = f"{generation}:{server_id}"
        public = public_request(method, params, request_id)
        pending = _Pending(request_id, server_id, generation, method, params, public)
        with run.lock:
            run.pending[request_id] = pending
        if run.stream:
            run.stream.add_request_item(public)
        run.set_state()

    def _resolve_pending(self, run: _Run, server_id: Any) -> None:
        with run.lock:
            match = next((p for p in run.pending.values() if str(p.server_id) == str(server_id)), None)
            if match:
                del run.pending[match.request_id]
        if match:
            if run.stream:
                run.stream.resolve_request_item(match.request_id, {"decision": "resolved"})
            run.set_state()

    def _send_interrupt(self, run: _Run) -> None:
        if not run.turn_id:
            return
        try:
            self._rpc("turn/interrupt", {"threadId": run.thread_id, "turnId": run.turn_id}, timeout=15)
        except CodexError:
            pass  # already finished, or the connection is gone and the run will notice

    def interrupt(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            return
        run.interrupt_requested = True
        run.interrupt_at = time.monotonic()
        with run.lock:
            pending = list(run.pending.values())
        for item in pending:
            try:
                result = server_request_result(item.method, item.params, {"decision": "cancel"})
                self._conn.respond(item.generation, item.server_id, result)
            except CodexError:
                pass
        if run.kind == "compact" and not run.turn_id:
            return
        self._send_interrupt(run)

    def steer(self, run_id: str, message: str, images: list[dict[str, Any]] | None = None) -> None:
        """Add a message to the turn that is running (``turn/steer``)."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or run.state not in ("running", "waiting_approval", "waiting_input"):
            raise CodexError("run_not_active", "That run is not active any more.")
        text = str(message or "").strip()
        if not text and not images:
            raise CodexError("empty_message", "Write a message or attach an image.")
        if not run.turn_ready.wait(10):
            raise CodexError("turn_not_ready", "Codex has not started the turn yet. Try again in a moment.")
        try:
            self._rpc("turn/steer", {"threadId": run.thread_id, "expectedTurnId": run.turn_id,
                                     "input": _build_input(text, list(images or []))}, timeout=30)
        except RpcError as exc:
            if "steer" in exc.raw_message.lower() or "activeturn" in exc.raw_message.lower().replace("_", ""):
                raise CodexError("turn_not_steerable", "This turn cannot take extra messages right now.") from exc
            raise

    @checked("providers.codex.answer")
    def answer(self, run_id: str, request_id: str, response: dict[str, Any]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise CodexError("run_not_active", "That run is not active any more.")
        with run.lock:
            pending = run.pending.get(request_id)
            if pending is None:
                raise CodexError("request_not_pending", "This request is no longer waiting. Refresh the chat to see its state.")
            decision = str((response or {}).get("decision") or "")
            if decision not in ("approve", "deny", "cancel"):
                raise CodexError("invalid_decision", "Choose approve, deny or cancel.")
            choices = pending.public.get("choices")
            if choices and decision not in choices:
                raise CodexError("invalid_decision", "That choice is not available for this request.")
            if pending.method == "item/tool/requestUserInput" and decision == "approve":
                answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
                if not any(str(v).strip() for v in answers.values()):
                    raise CodexError("answers_required", "Answer the question, or stop the turn.")
            result = server_request_result(pending.method, pending.params, response)
            try:
                self._conn.respond(pending.generation, pending.server_id, result)
            except ConnectionLost as exc:
                raise CodexError("request_expired", "Codex stopped before this answer could be delivered.") from exc
            run.pending.pop(request_id, None)
        if run.stream:
            run.stream.resolve_request_item(request_id, response)
        run.set_state()
        if decision == "cancel" and pending.public["kind"] == "question":
            self._send_interrupt(run)

    # -- compaction and goals ---------------------------------------------

    def compact(self, session_id: str, *, run_id: str | None = None, emit: Emit | None = None) -> dict[str, Any]:
        """Run ``thread/compact/start`` and emit compaction items until it finishes."""
        thread_id = self._thread_id(session_id)
        thread = self._check_thread(thread_id)
        before = self._context(thread_id, thread).used_tokens
        run = self._new_run(run_id or f"compact-{thread_id}", emit or self._sink_emit, "compact")
        with self._lock:
            self._runs[run.run_id] = run
        try:
            run.generation = self._conn.ensure_started()
            resumed = self._rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True}, timeout=60)
            self._attach(run, thread_id, resumed.get("thread") if isinstance(resumed.get("thread"), dict) else {})
            run.context_before = before
            if run.stream:
                run.stream._last_used = run.context_before
                run.stream.begin_turn(turn_id=f"compact-{int(time.time() * 1000)}")
            run.set_state("running")
            self._announce(run, {}, working=True)
            self._rpc("thread/compact/start", {"threadId": thread_id}, timeout=60)
        except ConnectionLost:
            self._finish(run, "interrupted", LOST_MESSAGE, code="app_server_stopped")
            return {"state": "failed", "error": LOST_MESSAGE}
        except CodexError as exc:
            self._fail_compaction(run, str(exc))
            self._finish(run, "failed", str(exc), code=exc.code)
            return {"state": "failed", "error": str(exc)}
        state, error = self._drive(run)
        if state != "completed":
            self._fail_compaction(run, error or "Compaction did not finish.")
        self._finish(run, state, error)
        with self._lock:
            after = self._contexts.get(thread_id)
        return {"state": "completed" if state == "completed" else "failed", "error": error,
                "beforeTokens": run.context_before, "afterTokens": after.used_tokens if after else None}

    def _fail_compaction(self, run: _Run, message: str) -> None:
        stream = run.stream
        if stream is None:
            return
        open_items = [i for i in stream.items.values() if i.kind == "compaction" and i.data.get("state") == "started"]
        if not open_items:
            item = Item(f"compaction:{run.run_id}", int(time.time() * 1000), "compaction", now_iso(),
                        {"state": "failed", "beforeTokens": run.context_before, "afterTokens": None, "error": message})
            stream._added(item)
            return
        for item in open_items:
            item.data.update(state="failed", error=message)
            stream._updated(item)

    @checked("providers.codex.goal")
    def goal(self, session_id: str, action: str, text: str | None = None) -> dict[str, Any] | None:
        thread_id = self._thread_id(session_id)
        if action == "get":
            goal = self._rpc("thread/goal/get", {"threadId": thread_id}).get("goal")
        elif action == "set":
            objective = str(text or "").strip()
            if not objective:
                raise CodexError("goal_required", "Write the goal first.")
            # A goal keeps starting turns by itself, so the thread must be loaded here for them to stream.
            self._check_thread(thread_id, own_run_ok=True)
            self._ensure_loaded(thread_id)
            self._goal_expect[thread_id] = ("set", time.monotonic())
            goal = self._rpc("thread/goal/set", {"threadId": thread_id, "objective": objective}).get("goal")
        elif action == "clear":
            # Works while a goal turn is running (that is when it is needed) and on an unloaded thread.
            self._check_thread(thread_id, own_run_ok=True)
            self._goal_expect[thread_id] = ("clear", time.monotonic())
            cleared = self._rpc("thread/goal/clear", {"threadId": thread_id}).get("cleared")
            if not cleared:
                self._goal_expect.pop(thread_id, None)
            goal = None
        else:
            raise CodexError("invalid_action", "Goal action must be get, set or clear.")
        with self._lock:
            if goal:
                # Notifications can arrive before the RPC response, including a
                # subsequent clear. Do not resurrect that already-cleared goal.
                if action == "get" or thread_id in self._goal_expect:
                    self._goals.setdefault(thread_id, goal)
            else:
                self._goals.pop(thread_id, None)
        return _goal_public(goal)

    def _ensure_loaded(self, thread_id: str) -> None:
        self._rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True}, timeout=60)

    # -- thread housekeeping ----------------------------------------------

    def archive(self, session_id: str) -> None:
        thread_id = self._thread_id(session_id)
        self._check_thread(thread_id)
        self._rpc("thread/archive", {"threadId": thread_id})
        self._drop_cache("threads")

    def unarchive(self, session_id: str) -> None:
        self._rpc("thread/unarchive", {"threadId": self._thread_id(session_id)})
        self._drop_cache("threads")

    def rename(self, session_id: str, name: str) -> None:
        self._rpc("thread/name/set", {"threadId": self._thread_id(session_id), "name": " ".join(str(name).split())[:160]})
        self._drop_cache("threads")

    # -- notifications from the connection --------------------------------

    def _on_lost(self, generation: int) -> None:
        with self._lock:
            runs = [run for run in self._runs.values() if run.generation == generation]
            self._contexts.clear()
        self._drop_cache("live", "threads")
        for run in runs:
            run.inbox.put(("lost",))

    def _on_notification(self, generation: int, method: str, params: dict[str, Any]) -> None:
        if method in ("account/login/completed", "account/updated"):
            self._drop_cache("auth")
            return
        if method in ("skills/changed",):
            self._drop_cache("skills")
            return
        if method in ("mcpServer/startupStatus/updated", "mcpServer/oauthLogin/completed", "app/list/updated"):
            self._drop_cache("plugins", "mcp", "apps")
            return
        thread = params.get("thread") if isinstance(params.get("thread"), dict) else {}
        thread_id = str(params.get("threadId") or thread.get("id") or "")
        if not thread_id:
            return
        if method in ("thread/goal/updated", "thread/goal/cleared"):
            params = self._note_goal(thread_id, method, params)
        elif method == "thread/name/updated" and params.get("threadName"):
            with self._lock:
                self._threads[thread_id] = {**self._threads.get(thread_id, {"id": thread_id}), "name": params["threadName"]}
            self._drop_cache("threads")
        run = self._run_for(thread_id)
        if run is not None:
            run.inbox.put(("note", method, params))
            return
        if method == "turn/started" and self._sink is not None:
            self._adopt(thread_id, generation, params)
            return
        self._ambient(thread_id, method, params)

    def _note_goal(self, thread_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Track a thread's goal and decide whether this notification is a change worth showing.

        Codex repeats the goal state whenever a thread is resumed, and updates its
        token counters while a goal runs; only a set, a clear, or a change of
        objective or status becomes a transcript item.
        """
        with self._lock:
            previous = self._goals.get(thread_id)
            kind, stamp = self._goal_expect.get(thread_id, ("", 0.0))
            expected = kind if time.monotonic() - stamp < 15 else ""
            # A resumed thread can deliver its old goal snapshot after a goal
            # command's RPC reply. Only the matching notification acknowledges
            # that command; the stale opposite snapshot must not consume it.
            if expected and ((method == "thread/goal/cleared") != (expected == "clear")):
                check_goal_note(method, params, previous, expected, False)
                return {**params, "_neyvia": {"emit": False}}
            self._goal_expect.pop(thread_id, None)
            if method == "thread/goal/cleared":
                emit = previous is not None or expected == "clear"
                self._goals.pop(thread_id, None)
            else:
                goal = params.get("goal") if isinstance(params.get("goal"), dict) else {}
                self._goals[thread_id] = goal
                changed = previous is not None and (previous.get("objective"), previous.get("status")) != (goal.get("objective"), goal.get("status"))
                emit = expected == "set" or changed
        check_goal_note(method, params, previous, expected, emit)
        return {**params, "_neyvia": {"emit": emit}}

    def _ambient(self, thread_id: str, method: str, params: dict[str, Any]) -> None:
        """Thread-level events with no run: goal changes, renames, context.

        Runs on the connection's reader thread, so it must never wait on an RPC.
        """
        if method == "thread/name/updated":
            with self._lock:
                thread = dict(self._threads.get(thread_id) or {"id": thread_id})
            if self._sink is not None:
                threading.Thread(target=lambda: self._sink_emit(
                    {"type": "session.updated", "session": self._summary(thread, fetch=False).public()}), daemon=True).start()
            return
        if self._sink is None:
            return
        if method in ("thread/goal/updated", "thread/goal/cleared", "thread/tokenUsage/updated", "thread/compacted"):
            stream = ThreadStream(self._sid(thread_id), thread_id, self._sink_emit,
                                  on_context=lambda c: self._store_context(thread_id, c),
                                  auto_compact_tokens=self._auto_compact_cached,
                                  ordinal_of_turn=lambda turn_id: self._ordinal_of_turn(thread_id, turn_id, fetch=False))
            stream.handle(method, params)

    def _adopt(self, thread_id: str, generation: int, params: dict[str, Any]) -> None:
        """A turn Neyvia did not start (a goal continuing on its own): stream it like any run."""
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        run = self._new_run(f"codex-turn-{turn.get('id') or int(time.time() * 1000)}", self._sink_emit, "ambient")
        run.generation = generation
        self._attach(run, thread_id, {})
        self._register(run)
        run.inbox.put(("note", "turn/started", params))
        threading.Thread(target=self._drive_adopted, args=(run,), daemon=True, name=f"codex-{run.run_id}").start()

    def _drive_adopted(self, run: _Run) -> None:
        run.set_state("running")
        state, error = self._drive(run)
        self._finish(run, state, error)

    def _on_server_request(self, generation: int, server_id: Any, method: str, params: dict[str, Any]) -> None:
        if method == "currentTime/read":
            self._conn.respond(generation, server_id, {"currentTimeAt": int(time.time())})
            return
        run = self._run_for(str(params.get("threadId") or ""))
        if method in REQUEST_METHODS or (method == 'item/tool/call' and str(params.get('tool') or '').startswith('neyvia_parallel_')):
            if run is not None:
                run.inbox.put(("request", generation, server_id, method, params))
                return
            # Nobody is watching this thread: never approve on the user's behalf.
            self._conn.respond(generation, server_id, server_request_result(method, params, {"decision": "cancel"}))
            return
        self._conn.reject(generation, server_id, f"Neyvia does not handle {method}.")

    # -- options -----------------------------------------------------------

    @checked("providers.codex.options")
    def options(self, session_id: str | None = None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        cwd = None
        thread: dict[str, Any] = {}
        if session_id:
            try:
                thread = self._thread_meta(self._thread_id(session_id))
                cwd = strip_extended_prefix(thread.get("cwd")) or None
            except CodexError as exc:
                errors["session"] = str(exc)
        result: dict[str, Any] = {"models": [], "permissionModes": permission_modes(), "skills": [], "plugins": [], "mcpServers": []}
        # The requests are independent and some take a second; ask them side by side.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codex-options") as pool:
            models = pool.submit(self._models)
            skills = pool.submit(self._skills, cwd)
            integrations = pool.submit(self._integrations)
            defaults = pool.submit(self._defaults, thread)
            try:
                result["models"] = models.result()
            except CodexError as exc:
                errors["models"] = str(exc)
            try:
                result["skills"] = skills.result()
            except CodexError as exc:
                errors["skills"] = str(exc)
            try:
                plugins, servers, notes = integrations.result()
                result["plugins"], result["mcpServers"] = plugins, servers
                errors.update(notes)
            except CodexError as exc:
                errors["plugins"] = str(exc)
            result["defaults"] = defaults.result()
        result["auth"] = self.auth()
        if errors:
            result["errors"] = errors
        return result

    def release_for_update(self) -> bool:
        """Stop this adapter's app-server while idle so the Codex CLI can be updated.

        Nothing is lost: the connection starts again on the next request. Refused while a turn
        runs or a thread (a goal or a chat) is still loaded in the app-server.
        """
        with self._lock:
            if self._runs:
                return False
        try:
            loaded = (self._rpc("thread/loaded/list", {}, timeout=10) or {}).get("data") or []
        except CodexError:
            loaded = []
        if loaded:
            return False
        self._conn.kill()
        return True

    # -- sign-in -----------------------------------------------------------

    _PLANS = {"plus": "Plus", "pro": "Pro", "prolite": "Pro Lite", "promax": "Pro Max", "go": "Go", "free": "Free",
              "team": "Team", "business": "Business", "enterprise": "Enterprise", "edu": "Edu"}

    @checked("providers.codex.auth")
    def auth(self, force: bool = False) -> dict[str, Any]:
        """Who Codex is signed in as, from the app server's ``account/read`` (the plan only: no email, never a token)."""
        def load() -> dict[str, Any]:
            reply = self._rpc("account/read", {}) or {}
            account = reply.get("account") if isinstance(reply.get("account"), dict) else None
            if account is None:
                if reply.get("requiresOpenaiAuth") is False:
                    return {"kind": "none-required", "label": "a model provider that needs no sign-in"}
                return {"kind": "signed-out", "label": "no sign-in"}
            if account.get("type") == "chatgpt":
                plan = self._PLANS.get(str(account.get("planType") or ""))
                return {"kind": "subscription", "label": f"your ChatGPT {plan} plan" if plan else "your ChatGPT account"}
            if account.get("type") == "apiKey":
                return {"kind": "api-key", "label": "an OpenAI API key"}
            return {"kind": "other", "label": "Amazon Bedrock" if account.get("type") == "amazonBedrock" else "another provider"}

        if force:
            self._drop_cache("auth")
        try:
            return self._cached("auth", 60.0, load)
        except CodexError:
            return {"kind": "unknown", "label": "an unknown setup"}

    @checked("providers.codex.login")
    def sign_in(self) -> dict[str, Any]:
        """Start Codex's own ChatGPT sign-in with a one-time code, which works from any device."""
        current = self.auth(force=True)
        if current.get("kind") == "subscription":
            return {"state": "signed-in", "auth": current}
        reply = self._rpc("account/login/start", {"type": "chatgptDeviceCode"}) or {}
        url, code = str(reply.get("verificationUrl") or ""), str(reply.get("userCode") or "")
        if not url.startswith("https://") or not code:
            raise CodexError("sign_in_failed", "Codex did not return a sign-in code. Try again, or run `codex login` on the PC.")
        return {"state": "code", "method": "device-code", "verificationUrl": url, "userCode": code, "auth": current,
                "message": "Open the link on any device, sign in to ChatGPT, and enter the code. Neyvia never sees your password."}

    def _defaults(self, thread: dict[str, Any]) -> dict[str, Any]:
        try:
            config = self._cached("config", 60.0, lambda: self._rpc("config/read", {}).get("config") or {})
        except CodexError:
            config = {}
        return {"model": thread.get("model") or config.get("model"),
                "effort": thread.get("reasoningEffort") or config.get("model_reasoning_effort"),
                "permissionMode": permission_mode_for(config.get("approval_policy"), config.get("sandbox_mode"))}

    def _models(self) -> list[dict[str, Any]]:
        def load() -> list[dict[str, Any]]:
            models: list[dict[str, Any]] = []
            cursor = None
            for _ in range(10):
                params: dict[str, Any] = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                page = self._rpc("model/list", params)
                for entry in page.get("data") or []:
                    if not isinstance(entry, dict) or entry.get("hidden"):
                        continue
                    efforts = [e.get("reasoningEffort") for e in entry.get("supportedReasoningEfforts") or [] if isinstance(e, dict)]
                    models.append({"id": entry.get("model") or entry.get("id"), "label": entry.get("displayName") or entry.get("model"),
                                   "efforts": [e for e in efforts if e], "defaultEffort": entry.get("defaultReasoningEffort"),
                                   "default": bool(entry.get("isDefault")), "description": str(entry.get("description") or "")[:200],
                                   "images": "image" in (entry.get("inputModalities") or [])})
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            return models
        return self._cached("models", 300.0, load)

    def _skills(self, cwd: str | None) -> list[dict[str, Any]]:
        folder = cwd or os.getcwd()

        def load() -> list[dict[str, Any]]:
            found: dict[str, dict[str, Any]] = {}
            for entry in self._rpc("skills/list", {"cwds": [folder]}).get("data") or []:
                for skill in entry.get("skills") or []:
                    if not isinstance(skill, dict) or not skill.get("name"):
                        continue
                    interface = skill.get("interface") if isinstance(skill.get("interface"), dict) else {}
                    found.setdefault(skill["name"], {
                        "name": skill["name"], "label": interface.get("displayName") or skill["name"],
                        "description": str(interface.get("shortDescription") or skill.get("description") or "")[:200],
                        "enabled": bool(skill.get("enabled", True)), "scope": skill.get("scope"), "pluginId": skill.get("pluginId")})
            return sorted(found.values(), key=lambda s: str(s["name"]).lower())
        return self._cached(f"skills:{folder}", 60.0, load)

    def _integrations(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
        return self._cached("plugins", 60.0, self._load_integrations)

    def _load_integrations(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
        notes: dict[str, str] = {}
        installed = self._rpc("plugin/installed", {}, timeout=60)
        servers_raw: list[dict[str, Any]] = []
        cursor = None
        for _ in range(5):
            params: dict[str, Any] = {"limit": 100, "detail": "toolsAndAuthOnly"}
            if cursor:
                params["cursor"] = cursor
            try:
                page = self._rpc("mcpServerStatus/list", params, timeout=60)
            except CodexError as exc:
                notes["mcpServers"] = str(exc)
                break
            servers_raw += [s for s in page.get("data") or [] if isinstance(s, dict)]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        apps: list[dict[str, Any]] = []
        try:
            apps = [a for a in self._rpc("app/list", {"limit": 100}, timeout=30).get("data") or [] if isinstance(a, dict)]
        except CodexError as exc:
            notes["apps"] = str(exc)
        plugins, servers, index = build_integrations(installed, servers_raw, apps)
        with self._lock:
            self._plugin_index = index
        return plugins, servers, notes

    @checked("providers.codex.plugin_login")
    def plugin_login(self, plugin_id: str) -> dict[str, Any]:
        """Start the sign-in for a plugin, app or MCP server; returns the URL to open."""
        self._integrations()
        with self._lock:
            entry = self._plugin_index.get(str(plugin_id))
        if entry is None:
            raise CodexError("plugin_unknown", "Codex does not list that plugin.")
        server = entry.get("loginServer")
        if server:
            result = self._rpc("mcpServer/oauth/login", {"name": server}, timeout=60)
            url = str(result.get("authorizationUrl") or "")
            if url.startswith(("https://", "http://")):
                self._drop_cache("plugins")
                return {"ok": True, "id": plugin_id, "authUrl": url, "server": server}
            raise CodexError("login_unavailable", "Codex did not return a sign-in link.")
        if str(entry.get("installUrl") or "").startswith(("https://", "http://")):
            return {"ok": True, "id": plugin_id, "authUrl": entry["installUrl"], "server": None}
        return {"ok": False, "id": plugin_id, "authUrl": None,
                "message": "Connect this in Codex: Settings, Plugins. Neyvia cannot start its sign-in."}


# -- helpers ---------------------------------------------------------------

def _goal_public(goal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not goal:
        return None
    return {"text": str(goal.get("objective") or ""), "state": str(goal.get("status") or "active"),
            "tokenBudget": goal.get("tokenBudget"), "tokensUsed": goal.get("tokensUsed"),
            "timeUsedSeconds": goal.get("timeUsedSeconds"), "updatedAt": iso_from_seconds(goal.get("updatedAt"))}


@checked("providers.codex.input")
def _build_input(text: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text, "text_elements": []})
    for image in images:
        mime = str(image.get("mime") or "")
        data = str(image.get("data") or "")
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"} or not data:
            raise CodexError("invalid_image", "An attached image is not readable.")
        if len(data) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise CodexError("image_too_large", "An attached image is too large.")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CodexError("invalid_image", "An attached image is not readable.") from exc
        if not decoded:
            raise CodexError("invalid_image", "An attached image is not readable.")
        if len(decoded) > MAX_IMAGE_BYTES:
            raise CodexError("image_too_large", "An attached image is too large.")
        parts.append({"type": "image", "url": f"data:{mime};base64,{data}"})
    return parts


def _load_media(ref: str) -> tuple[bytes, str, str]:
    from ..connected_chat_media import MAX_MEDIA_BYTES, TYPES
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)", ref)
    if match:
        if len(match[2]) > MAX_MEDIA_BYTES * 4 // 3 + 16:
            raise CodexError("media_too_large", "That image is too large.")
        try:
            return base64.b64decode(re.sub(r"\s+", "", match[2]), validate=True), match[1], "image"
        except (binascii.Error, ValueError) as exc:
            raise CodexError("media_invalid", "That image could not be decoded.") from exc
    if ref.startswith(("http://", "https://", "data:")):
        raise CodexError("media_remote", "Remote images are not fetched by Neyvia.")
    path = Path(strip_extended_prefix(ref))
    content_type = TYPES.get(path.suffix.lower())
    if not path.is_absolute() or not content_type or not path.is_file() or path.stat().st_size > MAX_MEDIA_BYTES:
        raise CodexError("media_not_found", "That file is missing, too large or not an image.")
    return path.read_bytes(), content_type, path.name


@checked("providers.codex.integrations")
def build_integrations(installed: dict[str, Any], servers: list[dict[str, Any]], apps: list[dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Merge plugin/installed, mcpServerStatus/list and app/list into option entries.

    A plugin is "connected" only when Codex shows evidence of it: its own MCP
    servers are up, or its connector's tools are exposed by ``codex_apps``.
    """
    connectors: dict[str, str] = {}  # lower-case connector name -> connector id
    server_entries: list[dict[str, Any]] = []
    for server in servers:
        name = str(server.get("name") or "")
        runtime, auth = server.get("runtimeStatus"), server.get("authStatus")
        if runtime in ("authenticationRequired",) or auth == "notLoggedIn":
            state = "needs_sign_in"
        elif runtime == "failed":
            state = "error"
        elif runtime == "disabled":
            state = "disabled"
        elif runtime in ("starting", "notStarted") and auth not in ("unsupported",):
            state = "starting"
        else:
            state = "connected"
        entry = {"name": name, "state": state, "authStatus": auth, "pluginId": server.get("pluginId"),
                 "toolCount": len(server.get("tools") or {})}
        server_entries.append(entry)
        for tool in (server.get("tools") or {}).values():
            meta = tool.get("_meta") if isinstance(tool, dict) and isinstance(tool.get("_meta"), dict) else {}
            if meta.get("connector_name"):
                connectors[str(meta["connector_name"]).lower()] = str(meta.get("connector_id") or "")
    app_by_name = {str(a.get("name") or "").lower(): a for a in apps}
    plugins: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    claimed_servers: set[str] = set()
    for marketplace in installed.get("marketplaces") or []:
        for plugin in marketplace.get("plugins") or []:
            if not isinstance(plugin, dict) or not plugin.get("installed"):
                continue
            interface = plugin.get("interface") if isinstance(plugin.get("interface"), dict) else {}
            label = str(interface.get("displayName") or plugin.get("name") or plugin.get("id"))
            own = [s for s in server_entries if s["pluginId"] == plugin.get("id")]
            claimed_servers.update(s["name"] for s in own)
            app = app_by_name.get(label.lower())
            remote = bool(plugin.get("remotePluginId")) or (plugin.get("source") or {}).get("type") == "remote" \
                or str(marketplace.get("name") or "").endswith("remote")
            login_server = next((s["name"] for s in own if s["state"] == "needs_sign_in"), None)
            if not plugin.get("enabled") or plugin.get("availability") != "AVAILABLE":
                state = "disabled"
            elif any(s["state"] == "error" for s in own):
                state = "error"
            elif login_server:
                state = "needs_sign_in"
            elif any(s["state"] == "starting" for s in own):
                state = "starting"
            elif own and all(s["state"] == "disabled" for s in own):
                state = "disabled"
            elif own:
                state = "connected"
            elif label.lower() in connectors:
                state = "connected"
            elif app is not None and app.get("isEnabled") is False:
                state = "disabled"
            elif app is not None and not app.get("isAccessible"):
                state = "needs_sign_in"
            elif remote and plugin.get("authPolicy") == "ON_INSTALL":
                state = "needs_sign_in"
            else:
                state = "connected"
            entry = {"id": f"plugin:{plugin.get('id')}", "label": label, "state": state, "kind": "plugin",
                     "description": str(interface.get("shortDescription") or "")[:200]}
            plugins.append(entry)
            index[entry["id"]] = {"loginServer": login_server, "installUrl": (app or {}).get("installUrl")}
    known_labels = {p["label"].lower() for p in plugins}
    for server in server_entries:
        if server["name"] in claimed_servers or server["name"] == "codex_apps" or server["authStatus"] == "unsupported" and server["state"] == "connected" and not server["toolCount"]:
            continue
        entry = {"id": f"mcp:{server['name']}", "label": server["name"], "state": server["state"], "kind": "mcp"}
        plugins.append(entry)
        index[entry["id"]] = {"loginServer": server["name"] if server["state"] == "needs_sign_in" else None}
    for name, connector_id in connectors.items():
        if name in known_labels:
            continue
        app = app_by_name.get(name) or {}
        plugins.append({"id": f"app:{connector_id or name}", "label": str(app.get("name") or name.title()), "state": "connected", "kind": "app"})
    return plugins, [{k: v for k, v in s.items() if k != "pluginId" or v} for s in server_entries], index
