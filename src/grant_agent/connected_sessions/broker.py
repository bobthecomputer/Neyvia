"""The live service behind connected sessions.

It hosts the app adapters (Claude Code, Codex, OpenCode), runs one worker thread per turn,
stamps every adapter event with a monotonic cursor into a bounded ring buffer, and serves the
same state to every Neyvia client (desktop, browser, phone) through ``wait_events``. Runs are
durable in ``.agent_control/connected_chats.sqlite3``: a send is idempotent by request id, a
session has at most one active run, and a run whose owner process died is marked
``interrupted`` and never resent.

Adapters are imported lazily; a missing or failing adapter becomes an unavailable source with
a reason, never a crash. Adapters must be thread safe: the broker calls ``interrupt``,
``answer``, ``read`` and ``live_status`` from request threads while ``start_turn`` runs.
"""
from __future__ import annotations

import atexit
import dataclasses
import functools
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from ..chat_run_control import process_started_at
from .events import EventBuffer, bound_event
from .model import SessionSummary, TurnOptions
from .plan import latest_plan
from .registry import (  # AdapterError, FACTORIES and register_adapter are re-exported for adapters and tests
    APP_LABELS, APPS, CATEGORIES, FACTORIES, AdapterError, ConnectedError, Registry, as_connected, bounded, describe,
    jsonable, make_session_id, normalize_app, parallel, parse_session_id, register_adapter,
)
from .runs import ACTIVE_STATES, TERMINAL_STATES, RunStore, iso, public_run, request_fingerprint
from .seen import SeenStore, _epoch
from .. import proofs_a_sessions as _proofs

log = logging.getLogger("neyvia.connected_sessions")

_RUN_STATES = ACTIVE_STATES | TERMINAL_STATES
_STATUS_FOR_RUN = {"queued": "working", "running": "working",
                   "waiting_approval": "waiting_approval", "waiting_input": "waiting_input"}

MAX_MESSAGE_CHARS = 100_000
MAX_IMAGES = 6
MAX_IMAGE_BASE64_CHARS = 12 * 1024 * 1024
MAX_IMAGES_TOTAL_CHARS = 24 * 1024 * 1024
NEW_SESSION_WAIT_SECONDS = 15.0
PAGE_LIMIT = 200
TOOL_OUTPUT_PAGE_CHARS = 8 * 1024
TOOL_OUTPUT_FULL_CHARS = 256 * 1024  # bound for an item carried by a live event
FULL_TOOL_OUTPUT_CHARS = 1_000_000  # bound for "full output on demand"
MAX_SUBSCRIBERS = 64
_OVERLAY_TTL = 10.0
_DEFAULT_IDLE_WATCHDOG_SECONDS = 30 * 60


# -- the broker ---------------------------------------------------------------------------


# Why a source's chats can't be listed right now, in words a person reads. The raw
# error stays in "detail" for the tooltip and logs; the code drives the sidebar's state.
_SOURCE_WORDS = {
    "adapter_busy": ("loading", "{label} is still loading its chats."),
    "adapter_timeout": ("loading", "{label} is still loading its chats."),
    "rpc_timeout": ("loading", "{label} is still loading its chats."),
    "app_server_stopped": ("offline", "{label} isn't responding right now."),
    "app_server_backoff": ("offline", "{label} isn't responding right now."),
    "app_server_start_failed": ("offline", "{label} couldn't start on this PC."),
    "app_server_closed": ("offline", "{label} isn't responding right now."),
    "codex_unavailable": ("missing", "{label} isn't installed on this PC."),
    "local_only": ("off", "{label} is off while Local-only is on."),
}


def source_problem(app: str, error: BaseException | Any) -> dict[str, str]:
    code = str(getattr(error, "code", "") or "error")
    state, words = _SOURCE_WORDS.get(code, ("offline", "{label} couldn't be read right now."))
    return {"code": code, "state": state, "reason": words.format(label=APP_LABELS.get(app, app)), "detail": describe(error)}


class _LiveRun:
    """In-memory side of a run this process owns; ``data`` is the RunRecord being served."""

    def __init__(self, data: dict[str, Any], adapter: Any, kind: str):
        self.data, self.adapter, self.kind = data, adapter, kind
        self.stop_requested = False
        self.terminal = False
        self.last_output = time.monotonic()
        self.io_lock = threading.Lock()
        self.answered: set[str] = set()
        self.edited_files: set[str] = set()
        self.work_claim_ids: set[str] = set()
        self.cwd: str | None = None
        self.intent = "Connected session turn"


class ConnectedBroker:
    def __init__(self, root: Path, *, backend: Any = None, adapters: dict[str, Any] | None = None,
                 load_defaults: bool | None = None,
                 ring_events: int = 5000, ring_bytes: int = 24 * 1024 * 1024, max_event_bytes: int = 64 * 1024,
                 list_ttl: float = 3.0, live_poll_seconds: float = 2.0, idle_watchdog_seconds: float | None = None,
                 start_cursor: int | None = None, autostart: bool = True):
        from ..external_chat_inventory import _host

        self.root = Path(root)
        self.db_path = self.root / ".agent_control" / "connected_chats.sqlite3"
        self.host = _host()
        self.token = uuid.uuid4().hex
        self.registry = Registry(self.root, backend, adapters, adapters is None if load_defaults is None else load_defaults)
        self.registry.on_ready = self._adapter_ready
        for name, ready in (adapters or {}).items():
            self._adapter_ready(name, ready)
        self.seen = SeenStore(self.root)
        self.list_ttl, self.live_poll_seconds = list_ttl, live_poll_seconds
        self.events = EventBuffer(self.host["deviceId"], max_events=ring_events, max_bytes=ring_bytes,
                                  max_event_bytes=max_event_bytes, start_cursor=start_cursor)
        if idle_watchdog_seconds is None:
            try:
                configured = float(os.environ.get("NEYVIA_CONNECTED_IDLE_SECONDS") or 0)
            except ValueError:
                configured = 0.0
            idle_watchdog_seconds = max(_DEFAULT_IDLE_WATCHDOG_SECONDS, configured)
        self.idle_watchdog_seconds = idle_watchdog_seconds
        self._autostart = autostart
        self._lock = threading.RLock()
        self._event_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._live: dict[str, _LiveRun] = {}
        self._subscribers: set[str] = set()
        self._last_subscriber = float("-inf")
        self._list_cache: dict[str, tuple[float, list[SessionSummary]]] = {}
        self._summaries: dict[str, SessionSummary] = {}
        self._summary_at: dict[str, float] = {}
        self._live_snapshot: dict[str, dict[str, tuple[str, str | None]]] = {}
        self._live_overlay: dict[str, tuple[str, str | None, str, float]] = {}
        self._latest_seq: dict[str, int] = {}
        self._last_poll = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.store = RunStore(self.db_path, self.token, self._is_live)
        self.recover()
        self.limits = None
        if autostart and adapters is None:
            from .live_limits import service_for
            self.limits = service_for(self.root)
        from ..neyvia_impact import warm
        warm()

    def register_adapter(self, app: str, factory: Callable[[Any], Any]) -> None:
        """Register ``factory(backend) -> Adapter`` for one app on this broker."""
        self.registry.register(app, factory)

    def _adapter_ready(self, app: str, adapter: Any) -> None:
        """Give an adapter that has events of its own (goal turns, renames) a way to publish them."""
        hook = getattr(adapter, "set_event_sink", None)
        if callable(hook):
            hook(lambda event, app=app: self._ambient(app, event))

    def _ambient(self, app: str, event: Any) -> None:
        """Publish an event that belongs to no run this broker started."""
        try:
            if not isinstance(event, dict) or not event.get("type"):
                return
            stamped = dict(event)
            session = stamped.get("session") if isinstance(stamped.get("session"), dict) else {}
            given = self._normalize_session(app, stamped.get("sessionId"))
            if given:
                stamped["sessionId"] = given
            if isinstance(stamped.get("item"), dict):
                item = jsonable(stamped["item"])
                self._tidy_item(str(stamped.get("sessionId") or session.get("id") or ""), item, TOOL_OUTPUT_FULL_CHARS)
                stamped["item"] = item
                if isinstance(item.get("seq"), int) and stamped.get("sessionId"):
                    with self._lock:
                        self._remember_seq(stamped["sessionId"], item["seq"])
            self._publish(stamped)
            if stamped["type"] == "session.updated":
                self._invalidate_lists()
        except Exception:  # noqa: BLE001 - an adapter's stray event must not break it
            log.exception("dropped a malformed %s event", app)

    # -- runs -----------------------------------------------------------------------------

    def _is_live(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._live

    def recover(self, *, session_key: str | None = None, run_id: str | None = None,
                session_keys: list[str] | None = None) -> list[dict[str, Any]]:
        """Mark active runs whose owner is gone as ``interrupted``; they are never resent."""
        filters = {"session_key": session_key, "run_id": run_id}
        if session_keys is not None:
            filters["session_keys"] = session_keys
        recovered = self.store.recover(**filters)
        for data in recovered:
            from ..neyvia_awareness import release_owner
            release_owner(self.root, run_id=data["runId"], session=data.get("sessionId"))
            self._publish({"type": "run.state", "sessionId": data.get("sessionId"), "runId": data["runId"],
                           "state": "interrupted", "pendingRequest": None, "error": data["error"]})
        if recovered:
            self._invalidate_lists()
        _proofs.check_recovered_runs(recovered)
        return recovered

    def _persist(self, run: _LiveRun) -> None:
        with run.io_lock:  # snapshots are taken and written in order, so the row ends on the latest state
            with self._lock:
                data = json.loads(json.dumps(run.data))
            self.store.save(data)

    def _public_run(self, data: dict[str, Any]) -> dict[str, Any]:
        from ..task_feedback import public_feedback
        data["feedback"] = public_feedback(self.root, data["runId"])
        return public_run(data)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            live = self._live.get(run_id)
            if live is not None:
                return self._public_run(json.loads(json.dumps(live.data)))
        self.recover(run_id=run_id)
        data = self.store.load(run_id)
        if data is None:
            raise ConnectedError("run_not_found", "That run was not found.", 404)
        return self._public_run(data)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def latest_run(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            for live in self._live.values():
                if live.data.get("sessionId") == session_id:
                    return self._public_run(json.loads(json.dumps(live.data)))
        self.recover(session_key=session_id)
        data = self.store.latest(session_id)
        return self._public_run(data) if data else None

    def _latest_runs(self, session_ids: list[str], *, recover: bool = True) -> dict[str, dict[str, Any] | None]:
        """Fresh page-scoped run state without one SQLite connection per row."""
        if not session_ids:
            return {}
        selected = set(session_ids)
        with self._lock:
            live_runs = {}
            for live in self._live.values():
                sid = live.data.get("sessionId")
                if sid in selected and sid not in live_runs:
                    live_runs[sid] = public_run(json.loads(json.dumps(live.data)))
        missing = [sid for sid in session_ids if sid not in live_runs]
        if recover:
            self.recover(session_keys=missing)
        stored = self.store.latest_many(missing)
        result = {sid: live_runs.get(sid) or (public_run(stored[sid]) if sid in stored else None)
                  for sid in session_ids}
        for run in result.values():
            _proofs.check_run_record(run)
        return result

    # -- events ---------------------------------------------------------------------------

    def _publish(self, event: dict[str, Any]) -> dict[str, Any]:
        published = self.events.publish(event)
        for listener in tuple(self._event_listeners):
            try:
                listener(published)
            except Exception:
                log.exception("connected event listener failed")
        return published

    def add_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if listener not in self._event_listeners:
                self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

    def head(self) -> int:
        return self.events.head()

    def events_since(self, cursor: int | None) -> tuple[list[dict[str, Any]], int, bool]:
        """(events after ``cursor``, new cursor, resync). Resync when the cursor left the buffer."""
        return self.events.since(cursor)

    def wait_events(self, cursor: int | None, timeout: float) -> tuple[list[dict[str, Any]], int, bool]:
        """Like ``events_since`` but waits up to ``timeout`` seconds for something to deliver."""
        return self.events.wait(cursor, timeout)

    @contextmanager
    def subscription(self):
        """Count a connected client, so live-status polling runs only while someone listens."""
        token = uuid.uuid4().hex
        with self._lock:
            if len(self._subscribers) >= MAX_SUBSCRIBERS:
                raise ConnectedError("too_many_streams", "Too many live connections. Close one and retry.", 429)
            self._subscribers.add(token)
            self._last_subscriber = time.monotonic()
            _proofs.check_subscription(self, token, True)
        self._ensure_thread()
        try:
            yield
        finally:
            with self._lock:
                self._subscribers.discard(token)
                self._last_subscriber = time.monotonic()
                _proofs.check_subscription(self, token, False)

    @property
    def closed(self) -> bool:
        return self.events.closed

    def close(self) -> None:
        """Stop serving; adapters that own a child process (Codex's app-server) shut it down."""
        self._stop.set()
        self.events.close()
        if self.limits is not None:
            self.limits.close()
        for adapter in self.registry.adapters():
            closer = getattr(adapter, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    log.exception("closing an adapter failed")

    # -- summaries ------------------------------------------------------------------------

    def _invalidate_lists(self) -> None:
        with self._lock:
            self._list_cache.clear()

    def _decorate(self, summary: SessionSummary) -> SessionSummary:
        changes: dict[str, Any] = {}
        if not summary.host_device_id:
            changes.update(host_device_id=self.host["deviceId"], host_device_name=self.host["deviceName"])
        with self._lock:
            active = next((live.data for live in self._live.values()
                           if live.data.get("sessionId") == summary.id and live.data["state"] in ACTIVE_STATES), None)
            overlay = self._live_overlay.get(summary.id)
            if active is not None:
                changes.update(status=_STATUS_FOR_RUN[active["state"]], live_owner="neyvia", status_since=active.get("updatedAt"))
                # The broker owns this writer. A stale adapter inventory may
                # still describe the OS lock as belonging to the external app.
                changes["capabilities"] = dataclasses.replace(summary.capabilities,
                    continue_session=True, stop=active["canStop"], steer=active["canSteer"], reason=None)
            # Codex summaries probe OS ownership; a cached overlay must not
            # overwrite a freshly released/acquired writer's status.
            elif summary.app != "codex" and overlay is not None and time.monotonic() - overlay[3] < _OVERLAY_TTL:
                changes.update(status=overlay[0], live_owner=overlay[1], status_since=overlay[2])
        if str(summary.title or '').startswith('<neyvia-memory>'):
            source = active or self.store.latest(summary.id)
            if source and source.get('taskText'):
                from ..memory_recall import visible_chat_text
                text = visible_chat_text(source['taskText']).strip()
                if text:
                    changes['title'] = text.splitlines()[0][:160]
        return dataclasses.replace(summary, **changes) if changes else summary

    def _fetch_lists(self, apps: list[str], *, ttl: float, include_running: bool = False) -> tuple[dict[str, list[SessionSummary]], dict[str, str]]:
        """Per-app session lists, reusing any taken less than ``ttl`` seconds ago."""
        now, lists, problems, calls = time.monotonic(), {}, {}, {}
        for app in apps:
            with self._lock:
                cached = self._list_cache.get(app + (":running" if include_running else ""))
            if cached and now - cached[0] < ttl:
                lists[app] = cached[1]
                continue
            adapter = self.registry.get(app)[0]
            def inventory(adapter=adapter):
                rows = adapter.list_sessions(include_archived=True)
                extra = getattr(adapter, "running_sessions", None)
                if include_running and callable(extra):
                    rows = list({row.id: row for row in [*rows, *extra()]}.values())
                return rows
            calls[app] = inventory
        if calls:
            for app, (ok, value) in parallel(calls, 20, guard="list").items():
                if ok:
                    lists[app] = list(value or [])
                    with self._lock:
                        self._list_cache[app + (":running" if include_running else "")] = (time.monotonic(), lists[app])
                else:
                    problems[app] = source_problem(app, value)
                    with self._lock:
                        stale = self._list_cache.get(app + (":running" if include_running else ""))
                    if stale:
                        lists[app] = stale[1]
        for app in calls:
            for summary in lists.get(app, []):
                self._remember(summary)
        return lists, problems

    def _remember(self, summary: SessionSummary) -> None:
        """Index a summary for lookups, never replacing one the app updated more recently."""
        with self._lock:
            known = self._summaries.get(summary.id)
            if known is None or _sort_key(summary.updated_at) >= _sort_key(known.updated_at):
                self._summaries[summary.id] = summary
                self._summary_at[summary.id] = time.monotonic()

    def find_summary(self, session_id: str, *, refresh: bool = True) -> SessionSummary | None:
        """The session's current summary; an index entry older than the list cache is refreshed first."""
        parsed = parse_session_id(session_id)
        if parsed is None:
            return None
        if refresh:
            with self._lock:
                known = self._summaries.get(session_id)
                age = time.monotonic() - self._summary_at.get(session_id, 0.0)
            if known is None or age >= self.list_ttl:
                adapter, ok, _ = self.registry.availability(parsed[0])
                if adapter is not None and ok:
                    # A session the cache has never heard of may just have been created.
                    self._fetch_lists([parsed[0]], ttl=1.0 if known is None else self.list_ttl)
        with self._lock:
            summary = self._summaries.get(session_id)
        if refresh and summary:
            adapter = self._adapter(parsed[0])
            hook = getattr(adapter, "refresh_summary", None)
            if callable(hook):
                summary = hook(session_id)
                self._remember(summary)
        return self._decorate(summary) if summary else None

    def list_sessions(self, *, query: str = "", app: str = "", category: str = "", include_archived: bool = False,
                      include_harness: bool = False, limit: int = 100, offset: int = 0,
                      force: bool = False, observe: bool = True, include_running: bool = False) -> dict[str, Any]:
        selected = normalize_app(app)
        if selected and selected not in APPS:
            raise ConnectedError("invalid_app", "Choose one of: " + ", ".join(APPS) + ".")
        wanted = str(category or "").strip().lower()
        if wanted and wanted not in CATEGORIES:
            raise ConnectedError("invalid_category", "Choose one of: " + ", ".join(CATEGORIES) + ".")
        sources, usable = [], []
        for name in APPS:
            adapter, ok, reason = self.registry.availability(name)
            sources.append({"app": name, "available": ok, "reason": reason,
                            **({} if ok else {"state": "offline" if "could not be checked" in str(reason or "") else "missing"})})
            if adapter is not None and ok and selected in ("", name):
                usable.append(name)
        lists, problems = self._fetch_lists(usable, ttl=0.0 if force else self.list_ttl, include_running=include_running)
        for source in sources:
            if source["app"] in problems:
                source.update(problems[source["app"]])
                source["available"] = source["available"] and source["app"] in lists
        rows = [self._decorate(summary) for name in usable for summary in lists.get(name, [])]
        if include_running:
            # Detached conductor workers own separate brokers. Their active rows
            # are authoritative even if a native inventory caps old history.
            self.recover()
            indexed = {row.id: row for row in rows}
            for run in self.store.active():
                sid = run.get("sessionId")
                parsed = parse_session_id(sid)
                if not parsed or parsed[1] != self.host["deviceId"] or selected and parsed[0] != selected:
                    continue
                row = indexed.get(sid) or self.find_summary(sid, refresh=False)
                if row is None:
                    row = SessionSummary(id=sid, app=parsed[0], title="Running " + APP_LABELS[parsed[0]],
                                         updated_at=run.get("updatedAt"), model=run.get("model"))
                indexed[sid] = dataclasses.replace(row, status=_STATUS_FOR_RUN[run["state"]], live_owner="neyvia",
                                                  status_since=run.get("startedAt"))
            rows = list(indexed.values())
        observed_rows = list(rows)
        self.seen.baseline((summary.id, summary.updated_at) for summary in rows)
        if not include_archived:
            rows = [row for row in rows if not row.archived]
        if not include_harness:
            rows = [row for row in rows if row.origin != "neyvia-harness"]
        if wanted:
            rows = [row for row in rows if row.category == wanted]
        needle = " ".join(str(query or "").casefold().split())
        if needle:
            rows = [row for row in rows if needle in " ".join(
                str(part or "") for part in (row.title, row.project, row.cwd, row.git_branch, APP_LABELS.get(row.app))).casefold()]
        rows.sort(key=lambda row: (_sort_key(row.updated_at), row.id), reverse=True)
        bounded = max(1, min(int(limit or 100), 500))
        start = max(0, int(offset or 0))
        page = rows[start:start + bounded]
        with self._lock:
            latest = dict(self._latest_seq)
        sessions = []
        from .sidebar_cleanup import SidebarSafetyObserver
        from ..ui_command_bus import bus_for
        observer = SidebarSafetyObserver(bus_for(self.root).get("projects", {}).values())
        runs = self._latest_runs([row.id for row in page]) if observe else None
        for row in page:
            item = row.public()
            if observe:  # a bulk caller (sidebar tidy) observes only the rows it needs
                item.update(self.sidebar_observation(row, observer=observer, cached=True, runs=runs))
            item["unread"] = self.seen.unread(row.id, row.updated_at, latest.get(row.id))
            sessions.append(item)
        result = {"sessions": sessions, "sources": sources,
                "host": {"deviceId": self.host["deviceId"], "deviceName": self.host["deviceName"]},
                "total": len(rows), "nextOffset": start + bounded if start + bounded < len(rows) else None,
                "cursor": self.head()}
        _proofs.check_broker_list(self, observed_rows, sources, result, query=query, category=wanted,
                                  archived=include_archived, harness=include_harness, limit=limit, offset=offset)
        return result

    def sidebar_observation(self, summary: SessionSummary, *, observer=None, cached: bool = False,
                            runs: dict[str, dict[str, Any] | None] | None = None) -> dict[str, Any]:
        """Display snapshots or fresh archive safety; no adapter-provided guesses."""
        from .sidebar_cleanup import SidebarSafetyObserver
        from ..ui_command_bus import bus_for
        observer = observer or SidebarSafetyObserver(bus_for(self.root).get("projects", {}).values())
        observation = observer.observe_cached(summary.cwd) if cached else observer.observe(summary.cwd)
        run = runs.get(summary.id) if cached and runs is not None else self.latest_run(summary.id)
        if summary.status in {"working", "waiting_approval", "waiting_input"} or run and run.get("state") in ACTIVE_STATES:
            observation["has_running_jobs"] = True
        return observation

    def session_cwd(self, session_id: str) -> str | None:
        self._host_check(session_id)
        summary = self.find_summary(session_id)
        if summary is None:
            raise ConnectedError("session_not_found", "That session was not found on this PC.", 404)
        return summary.cwd

    def mark_seen(self, session_id: str, seq: Any) -> dict[str, Any]:
        if parse_session_id(session_id) is None:
            raise ConnectedError("invalid_session", "That is not a connected session id.")
        try:
            number = int(seq)
        except (TypeError, ValueError) as exc:
            raise ConnectedError("invalid_request", "seq must be a number.") from exc
        summary = self.find_summary(session_id)
        self.seen.mark(session_id, number, summary.updated_at if summary else None)
        return {"ok": True}

    # -- live status ----------------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if not self._autostart or self.events.closed:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._tick_loop, name="connected-sessions-tick", daemon=True)
            self._thread.start()

    def _tick_loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive one bad tick
                log.exception("connected sessions tick failed")

    def tick(self, now: float | None = None) -> None:
        """One maintenance pass: idle watchdog, and live-status polling while clients listen."""
        now = time.monotonic() if now is None else now
        self._watchdog(now)
        with self._lock:
            listening = bool(self._subscribers) or now - self._last_subscriber < 5.0
            due = now - self._last_poll >= self.live_poll_seconds
        if listening and due:
            self.poll_live_status(now)

    def poll_live_status(self, now: float | None = None) -> int:
        """Emit ``session.updated`` for sessions the apps report changed; returns the number emitted."""
        from ..local_network_policy import enabled
        if enabled():
            return 0
        now = time.monotonic() if now is None else now
        with self._lock:
            self._last_poll = now
        calls = {}
        for app in APPS:
            adapter, ok, _ = self.registry.availability(app)
            if adapter is not None and ok:
                calls[app] = adapter.live_status
        emitted = 0
        for app, (ok, value) in parallel(calls, 10, guard="live").items():
            if not ok or not isinstance(value, dict):
                continue
            current = {str(key): (str(item[0]), item[1] if len(item) > 1 else None) for key, item in value.items()
                       if isinstance(item, (tuple, list)) and item}
            with self._lock:
                previous = self._live_snapshot.get(app)
                self._live_snapshot[app] = current
            stamp, since = time.monotonic(), iso(time.time())
            with self._lock:
                self._live_overlay = {key: row for key, row in self._live_overlay.items() if stamp - row[3] < 600}
            for sid, (status, owner) in current.items():
                changed = previous is not None and previous.get(sid) != (status, owner)
                with self._lock:
                    old = self._live_overlay.get(sid)
                    self._live_overlay[sid] = (status, owner, since if changed or old is None else old[2], stamp)
                if changed:
                    emitted += self._emit_session_updated(sid)
            for sid in (previous or {}):
                if sid not in current:
                    with self._lock:
                        self._live_overlay[sid] = ("idle", None, since, stamp)
                    emitted += self._emit_session_updated(sid)
        return emitted

    def _emit_session_updated(self, session_id: str) -> int:
        with self._lock:
            owned = any(live.data.get("sessionId") == session_id for live in self._live.values())
            summary = self._summaries.get(session_id)
        if owned or summary is None:
            return 0
        adapter = self._adapter(summary.app)
        hook = getattr(adapter, "refresh_summary", None)
        if callable(hook):
            summary = hook(session_id)
            self._remember(summary)
        self._publish({"type": "session.updated", "session": self._decorate(summary).public()})
        return 1

    def _watchdog(self, now: float) -> None:
        """Stop a turn that has produced no output for the idle limit; waiting turns are exempt."""
        with self._lock:
            observed = [(live, live.data["state"], live.stop_requested, live.last_output) for live in self._live.values()]
            idle = [live for live in self._live.values() if live.data["state"] in ("queued", "running")
                    and not live.stop_requested and now - live.last_output >= self.idle_watchdog_seconds]
            _proofs.check_watchdog_selection(self, observed, now, idle)
            for live in idle:
                live.stop_requested = True
        for live in idle:
            minutes = max(1, int(self.idle_watchdog_seconds // 60))
            self._set_state(live, "interrupted", error=f"No output for {minutes} minutes, so Neyvia stopped this turn.")
            threading.Thread(target=self._quiet_interrupt, args=(live,), name="connected-idle-stop", daemon=True).start()

    @staticmethod
    def _quiet_interrupt(live: _LiveRun) -> None:
        try:
            live.adapter.interrupt(live.data["runId"])
        except Exception:  # noqa: BLE001
            log.exception("interrupt after idle watchdog failed")

    # -- turns ----------------------------------------------------------------------------

    def _adapter(self, app: str, *, for_start: bool = False) -> Any:
        adapter, ok, reason = self.registry.availability(app, for_start=True) if for_start else self.registry.availability(app)
        if adapter is None or not ok:
            raise ConnectedError("adapter_unavailable", reason or f"{APP_LABELS[app]} is not available.", 503)
        return adapter

    def _host_check(self, session_id: str) -> tuple[str, str]:
        parsed = parse_session_id(session_id)
        if parsed is None:
            raise ConnectedError("invalid_session", "That is not a connected session id.")
        if parsed[1] != self.host["deviceId"]:
            raise ConnectedError("wrong_device", "This session belongs to another device.", 404)
        return parsed[0], parsed[2]

    @staticmethod
    def _validate_send(message: Any, request_id: Any, *, has_images: bool = False) -> tuple[str, str]:
        if not isinstance(message, str) or (not message.strip() and not has_images) or len(message) > MAX_MESSAGE_CHARS:
            raise ConnectedError("invalid_message", "Send text or attach an image. Text may contain up to 100,000 characters.")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 160:
            raise ConnectedError("invalid_request_id", "A stable request ID of 8 to 160 characters is required.")
        return message, request_id

    @staticmethod
    def _with_files(message: Any, options: Any) -> Any:
        """Save attached files on this PC and name them in the message (see ``attachments``)."""
        from .attachments import AttachmentError, save_files, with_files

        raw = options.get("files") if isinstance(options, dict) else None
        if not raw:
            return message
        try:
            paths = save_files(raw)
        except AttachmentError as exc:
            raise ConnectedError(exc.code, exc.message, 413 if "large" in exc.code or "many" in exc.code else 400) from exc
        return with_files(message if isinstance(message, str) else "", paths)

    @staticmethod
    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_turn_options(args[0], result))
    def _turn_options(raw: Any) -> TurnOptions:
        raw = raw if isinstance(raw, dict) else {}
        images = raw.get("images") if isinstance(raw.get("images"), list) else []
        if len(images) > MAX_IMAGES:
            raise ConnectedError("too_many_images", f"Attach at most {MAX_IMAGES} images.", 413)
        clean = []
        if sum(len(image.get("data") or "") for image in images if isinstance(image, dict)) > MAX_IMAGES_TOTAL_CHARS:
            raise ConnectedError("image_too_large", "The attached images are too large together.", 413)
        for image in images:
            if not isinstance(image, dict) or not isinstance(image.get("data"), str) or not image["data"].strip():
                raise ConnectedError("invalid_image", "Each image needs base64 data.")
            if len(image["data"]) > MAX_IMAGE_BASE64_CHARS:
                raise ConnectedError("image_too_large", "An attached image is too large.", 413)
            clean.append({"mime": str(image.get("mime") or "")[:100], "data": image["data"], "name": str(image.get("name") or "")[:200]})

        def text(*keys: str) -> str | None:
            for key in keys:
                if isinstance(raw.get(key), str) and raw[key].strip():
                    return raw[key].strip()[:200]
            return None

        transport = text("transport")
        if transport not in (None, "print", "terminal"):
            raise ConnectedError("invalid_option", "Choose how the app should run: print or terminal.")
        return TurnOptions(model=text("model"), effort=text("effort"),
                           permission_mode=text("permissionMode", "permission_mode"), images=clean, transport=transport,
                           fork_from=text("forkFrom", "fork_from"))

    def _preflight(self, adapter: Any, session_id: str | None) -> None:
        """Refuse a turn the app says cannot start (a hook named ``preflight`` or ``check_send``), else use live_status."""
        check = getattr(adapter, "preflight", None) or (getattr(adapter, "check_send", None) if session_id else None)
        if callable(check):
            try:
                bounded(lambda: check(session_id), 20, "preflight")
                return
            except Exception as exc:  # noqa: BLE001
                refusal = as_connected(exc, "check_failed")
                if refusal.code != "check_failed":
                    raise refusal from exc
        if session_id is None:
            return
        try:
            live = bounded(adapter.live_status, 10, "live_status") or {}
        except Exception:  # noqa: BLE001 - if the app cannot say, do not block the user
            return
        entry = live.get(session_id)
        owner = entry[1] if isinstance(entry, (tuple, list)) and len(entry) > 1 else None
        if owner in ("app", "cli"):
            where = "a terminal (CLI) on this PC" if owner == "cli" else "the app on this PC"
            raise ConnectedError(
                "session_live_elsewhere",
                f"This session is running in {where} right now. Let it finish or stop it there before continuing it here.",
                409, owner=owner)

    def _replay(self, run_id: str, fingerprint: str) -> dict[str, Any] | None:
        return self.get_run(run_id) if self.store.has_request(run_id, fingerprint) else None

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_broker_request(kwargs, result))
    def send(self, session_id: str, message: Any, request_id: Any, options: Any = None, *, memory_owner: str | None = None) -> dict[str, Any]:
        from ..prompt_amplifier import service_for as amplifier_for
        if isinstance(options, dict) and options.get("amplificationId"):
            message = amplifier_for(self.root).consume(options, message, session_id, emit=self._publish)
        message = self._with_files(message, options)
        turn_options = self._turn_options(options)
        message, request_id = self._validate_send(message, request_id, has_images=bool(turn_options.images))
        app, _ = self._host_check(session_id)
        fingerprint = request_fingerprint("send", session_id, message, turn_options)
        replay = self._replay(request_id, fingerprint)
        if replay is not None:
            return replay
        adapter = self._adapter(app)
        summary = self.find_summary(session_id)
        if summary is None:
            raise ConnectedError("session_not_found", "That session was not found on this PC.", 404)
        memory_context = self._memory_context(memory_owner, summary.cwd, message, request_id)
        if memory_context:
            from ..cue_memory import CueMemoryStore
            if not CueMemoryStore(memory_context).session_valid(session_id):
                raise ConnectedError('memory_context_revoked', 'Memory changed since this chat received it. Start a new chat to use fresh memory.', 409)
        if not summary.capabilities.continue_session:
            raise ConnectedError("cannot_continue", summary.capabilities.reason or "This session cannot be continued from Neyvia.", 409)
        from ..neyvia_runtime import enforce
        enforce(self.root, app, turn_options)
        self._preflight(adapter, session_id)
        return self._start("turn", app, adapter, session_id, message, turn_options, summary.cwd,
                           request_id, fingerprint, summary.capabilities.stop, summary.capabilities.steer, memory_context=memory_context)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_broker_request(kwargs, result))
    def new(self, app: Any, cwd: Any, message: Any, request_id: Any, options: Any = None, *, memory_owner: str | None = None) -> dict[str, Any]:
        from ..prompt_amplifier import service_for as amplifier_for
        if isinstance(options, dict) and options.get("amplificationId"):
            message = amplifier_for(self.root).consume(options, message, emit=self._publish)
        message = self._with_files(message, options)
        turn_options = self._turn_options(options)
        message, request_id = self._validate_send(message, request_id, has_images=bool(turn_options.images))
        name = normalize_app(app)
        if name not in APPS:
            raise ConnectedError("invalid_app", "Choose one of: " + ", ".join(APPS) + ".")
        if not isinstance(cwd, str) or not cwd.strip() or not os.path.isdir(cwd):
            raise ConnectedError("invalid_cwd", "Choose an existing folder on this PC for the new session.")
        if turn_options.fork_from:
            if name not in ("claude-code", "codex"):
                raise ConnectedError("unsupported", "This app cannot continue chats as a branch.", 400)
            self._host_check(turn_options.fork_from)
        fingerprint = request_fingerprint("new", [name, os.path.normcase(os.path.abspath(cwd))], message, turn_options)
        replay = self._replay(request_id, fingerprint)
        if replay is not None:
            return replay
        from ..neyvia_runtime import enforce
        enforce(self.root, name, turn_options)
        adapter = self._adapter(name, for_start=True)
        hook = getattr(adapter, "can_start_new", None)
        if callable(hook):
            allowed, reason = hook()
            if not allowed:
                raise ConnectedError("cannot_start", reason or f"{APP_LABELS[name]} cannot start sessions from Neyvia.", 409)
        self._preflight(adapter, None)
        started = self._start("turn", name, adapter, None, message, turn_options, os.path.abspath(cwd),
                              request_id, fingerprint, True, callable(getattr(adapter, "steer", None)),
                              memory_context=self._memory_context(memory_owner, cwd, message, request_id))
        return self._await_session(started["runId"]) if not started.get("sessionId") else started

    def _memory_context(self, owner, cwd, message, request_id):
        if not owner or not cwd:
            return None
        from ..neyvia_memory_tools import chat_context
        return chat_context(self.root, owner, cwd, message, request_id)

    def _await_session(self, run_id: str, timeout: float = NEW_SESSION_WAIT_SECONDS) -> dict[str, Any]:
        """Give a new session up to ``timeout`` seconds to be named, so the client can open it."""
        deadline = time.monotonic() + timeout
        while not self.events.closed:
            cursor = self.events.head()
            with self._lock:
                live = self._live.get(run_id)
                ready = live is None or live.data.get("sessionId") or live.data["state"] in TERMINAL_STATES
            remaining = deadline - time.monotonic()
            if ready or remaining <= 0:
                break
            self.events.wait(cursor, remaining)  # wakes on the next event, which is how a session gets named
        return self.get_run(run_id)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def compact(self, session_id: str, options: Any = None, instructions: Any = None) -> dict[str, Any]:
        """Compact a chat. ``options`` (transport, model...) are the ones a message would use; ``instructions`` is what follows ``/compact``."""
        turn_options = self._turn_options({k: v for k, v in options.items() if k not in ("images", "files", "forkFrom", "fork_from")}
                                          if isinstance(options, dict) else None)
        extra = " ".join(str(instructions).split())[:2000] if isinstance(instructions, str) else ""
        app, _ = self._host_check(session_id)
        adapter = self._adapter(app)
        summary = self.find_summary(session_id)
        if summary is None:
            raise ConnectedError("session_not_found", "That session was not found on this PC.", 404)
        if not callable(getattr(adapter, "compact", None)) and not summary.capabilities.compact:
            raise ConnectedError("not_supported", f"{APP_LABELS[app]} cannot compact this session from Neyvia.", 409)
        self._preflight(adapter, session_id)
        run_id = f"compact-{uuid.uuid4().hex}"
        return self._start("compact", app, adapter, session_id, f"/compact {extra}".strip(), turn_options, summary.cwd, run_id,
                           hashlib.sha256(f"compact\0{session_id}\0{run_id}".encode()).hexdigest(),
                           summary.capabilities.stop, False)

    def goal(self, session_id: str, action: Any, text: Any = None) -> dict[str, Any]:
        app, _ = self._host_check(session_id)
        adapter = self._adapter(app)
        if action not in ("get", "set", "clear"):
            raise ConnectedError("invalid_request", "action must be get, set or clear.")
        hook = getattr(adapter, "goal", None)
        if not callable(hook):
            if action == "get":
                return {"goal": None, "supported": False}
            raise ConnectedError("not_supported", f"{APP_LABELS[app]} does not report goals for Neyvia.", 409)
        if action == "set" and (not isinstance(text, str) or not text.strip() or len(text) > 4000):
            raise ConnectedError("invalid_request", "A goal of 1 to 4,000 characters is required.")
        try:
            result = bounded(lambda: hook(session_id, action, text), 30, "goal")
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "goal_failed", "The app could not change the goal:") from exc
        projected = {"goal": jsonable(result) if result else None, "supported": True}
        _proofs.check_control_projection(result, projected, "goal")
        return projected

    def provider_options(self, app: Any, session_id: Any = None) -> dict[str, Any]:
        name = normalize_app(app)
        if name not in APPS:
            raise ConnectedError("invalid_app", "Choose one of: " + ", ".join(APPS) + ".")
        adapter = self._adapter(name)
        if session_id:
            self._host_check(str(session_id))
        try:
            raw = bounded(lambda: adapter.options(str(session_id) if session_id else None), 30, "options")
            result = jsonable(raw)
            _proofs.check_control_projection(raw, result, "options")
            return result
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "options_failed", "The app could not list its options:") from exc

    def release_for_update(self, app: str) -> bool:
        """Let an app's CLI be updated: a running adapter that holds it open lets go if it is idle.

        True when nothing of this app is held open by Neyvia any more (or never was).
        """
        adapter = self.registry.loaded(app)
        release = getattr(adapter, "release_for_update", None)
        if adapter is None or not callable(release):
            return True
        try:
            return bool(release())
        except Exception:  # noqa: BLE001 - a failed release only postpones the update
            return False

    def app_auth(self, app: Any, *, sign_in: bool = False) -> dict[str, Any]:
        """How an app is signed in on this PC, or start the app's own sign-in (``sign_in``)."""
        name = normalize_app(app)
        if name not in APPS:
            raise ConnectedError("invalid_app", "Choose one of: " + ", ".join(APPS) + ".")
        adapter = self._adapter(name)
        method = getattr(adapter, "sign_in" if sign_in else "auth", None)
        if not callable(method):
            raise ConnectedError("unsupported", "Neyvia can't start a sign-in for this app.", 400)
        try:
            return jsonable(bounded(lambda: method() if sign_in else method(force=True), 30, "auth"))
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "auth_failed", "The app could not report its sign-in:") from exc

    def app_sign_in_code(self, app: Any, code: Any) -> dict[str, Any]:
        """Finish an app's own sign-in with the code its sign-in page showed (Claude Code)."""
        name = normalize_app(app)
        if name not in APPS:
            raise ConnectedError("invalid_app", "Choose one of: " + ", ".join(APPS) + ".")
        method = getattr(self._adapter(name), "finish_sign_in", None)
        if not callable(method):
            raise ConnectedError("unsupported", "This app's sign-in doesn't take a code.", 400)
        try:
            return jsonable(bounded(lambda: method(code), 60, "auth"))
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "sign_in_failed", "The sign-in could not finish:") from exc

    def read(self, session_id: str, *, cursor: Any = None, before_seq: Any = None, limit: Any = PAGE_LIMIT) -> dict[str, Any]:
        app, _ = self._host_check(session_id)
        adapter = self._adapter(app)
        try:
            count = max(1, min(int(limit or PAGE_LIMIT), PAGE_LIMIT))
            before = int(before_seq) if before_seq not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ConnectedError("invalid_request", "limit and beforeSeq must be numbers.") from exc
        try:
            page = bounded(lambda: adapter.read(session_id, cursor=str(cursor) if cursor not in (None, "") else None,
                                                 before_seq=before, limit=count), 30, "read")
        except (FileNotFoundError, KeyError) as exc:
            raise ConnectedError("session_not_found", "That session was not found on this PC.", 404) from exc
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "read_failed", "The app could not read this session:") from exc
        data = jsonable(dataclasses.asdict(page) if dataclasses.is_dataclass(page) and not isinstance(page, type) else page)
        fresh = getattr(page, "session", None)
        if isinstance(fresh, SessionSummary):
            self._remember(fresh)
            data["session"] = jsonable(self._decorate(fresh).public())
        for item in data.get("items") or []:
            self._tidy_item(session_id, item, TOOL_OUTPUT_PAGE_CHARS)
        # The agent's checklist: what the adapter folded over the whole session, else this page's own.
        # An older page or a "what changed" page that found none says nothing, so the client keeps its own.
        if data.get("plan") is None:
            data["plan"] = latest_plan(data.get("items") or [])
        if before is not None or (data["plan"] is None and cursor not in (None, "")):
            data.pop("plan", None)
        with self._lock:
            seqs = [item.get("seq") for item in data.get("items") or [] if isinstance(item.get("seq"), int)]
            if seqs:
                self._remember_seq(session_id, max(seqs))
        data["run"] = self.latest_run(session_id)
        if app == "claude-code":
            from ..claude_code_activity import settle_subagents
            data["items"] = settle_subagents(data.get("items") or [], data["run"] or data.get("session") or {})
        _proofs.check_broker_page(session_id, data, data["run"])
        return data

    def tool_output(self, session_id: str, item_id: Any) -> dict[str, Any]:
        """The full output of one tool item; pages carry at most 8 KB of it."""
        app, _ = self._host_check(session_id)
        adapter = self._adapter(app)
        hook = getattr(adapter, "tool_output", None)
        if not callable(hook):
            raise ConnectedError("not_supported", f"{APP_LABELS[app]} does not keep full tool output for Neyvia.", 409)
        if not isinstance(item_id, str) or not item_id or len(item_id) > 500:
            raise ConnectedError("invalid_request", "itemId is required.")
        try:
            output = bounded(lambda: hook(session_id, item_id), 30, "tool_output")
        except (FileNotFoundError, KeyError) as exc:
            raise ConnectedError("session_not_found", "That session was not found on this PC.", 404) from exc
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "tool_output_failed", "The app could not read that output:") from exc
        if output is None:
            raise ConnectedError("item_not_found", "That tool call was not found in this session.", 404)
        text = str(output)
        result = {"itemId": item_id, "output": text[:FULL_TOOL_OUTPUT_CHARS], "truncated": len(text) > FULL_TOOL_OUTPUT_CHARS}
        _proofs.check_full_output(item_id, output, result)
        return result

    def _remember_seq(self, session_id: str, seq: int) -> None:
        if seq > self._latest_seq.get(session_id, -1):
            self._latest_seq[session_id] = seq
            while len(self._latest_seq) > 2000:
                self._latest_seq.pop(next(iter(self._latest_seq)))

    @staticmethod
    def _tidy_item(session_id: str, item: dict[str, Any], output_cap: int) -> None:
        """Bound tool output and turn attachment references into safe, served URLs."""
        data = item.get("data") if isinstance(item.get("data"), dict) else None
        if data is None:
            return
        original = {**item, "data": {**data, "attachments": [dict(value) if isinstance(value, dict) else value for value in data.get("attachments") or []]}}
        if item.get('kind') == 'user':
            from ..memory_recall import visible_chat_text
            data['text'] = visible_chat_text(data.get('text'))
        output = data.get("output")
        if isinstance(output, str) and len(output) > output_cap:
            data["output"], data["outputTruncated"] = output[:output_cap], True
        for attachment in data.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            url = str(attachment.get("url") or "")
            if not url.startswith(("/api/connected/media", "/api/connected-chat-media")):
                ident = attachment.get("id")
                attachment["url"] = (f"/api/connected/media?session={quote(session_id, safe='')}&media={quote(str(ident), safe='')}"
                                     if ident else None)
            label = attachment.get("label")
            if isinstance(label, str) and ("/" in label or "\\" in label):
                attachment["label"] = Path(label.replace("\\", "/")).name
        _proofs.check_tidy_item(session_id, original, item, output_cap)

    def media(self, session_id: str, media_id: str) -> tuple[bytes, str, str]:
        app, _ = self._host_check(session_id)
        adapter = self._adapter(app)
        hook = getattr(adapter, "media", None) or getattr(adapter, "read_media", None)
        missing = ConnectedError("media_not_found", "That attachment is not available.", 404)
        try:
            if callable(hook):
                found = bounded(lambda: hook(session_id, media_id), 60, "media")
            else:
                from ..connected_chat_media import read_media
                found = read_media(session_id, media_id)
        except (FileNotFoundError, ValueError, KeyError, OSError) as exc:
            raise missing from exc
        except Exception as exc:  # noqa: BLE001
            refusal = as_connected(exc, "media_not_found", "", 404)
            raise (refusal if refusal.status != 502 else missing) from exc
        if not found:
            raise missing
        _proofs.check_media_result(found)
        return found

    def _start(self, kind: str, app: str, adapter: Any, session_id: str | None, message: str, options: TurnOptions,
               cwd: str | None, run_id: str, fingerprint: str, can_stop: Any, can_steer: Any, *, memory_context=None) -> dict[str, Any]:
        key = session_id or f"new:{run_id}"
        self.recover(session_key=key)
        now = time.time()
        started = process_started_at(os.getpid())
        run = _LiveRun({"runId": run_id, "sessionId": session_id, "app": app, "state": "queued", "startedAt": iso(now),
                        "updatedAt": iso(now), "pendingRequest": None, "error": None,
                        "canStop": True if can_stop is None else bool(can_stop), "canSteer": bool(can_steer),
                        "_ownerStartedAt": started, "model": options.model, "effort": options.effort,
                        "permissionMode": options.permission_mode, "promptCharacters": len(message),
                        "taskText": message, "workspaceRoot": cwd}, adapter, kind)
        from ..model_usage import CodexUsage, ZERO
        run.usage_tracker = CodexUsage(ZERO if session_id is None else None)
        run.memory_context = memory_context
        claimed = self.store.claim(
            run.data, fingerprint, started,
            is_free=lambda other: self._run_is_over(other),
            register=lambda: self._live.__setitem__(run_id, run),
            unregister=lambda: self._live.pop(run_id, None))
        if not claimed:
            return self.get_run(run_id)
        # Replay inputs belong to admission, before a provider can edit them.
        # Unmapped external/native tasks remain honest quarantined frontier.
        try:
            from ..lesson_replay import capture_task_manifest
            from ..lesson_evolver import service_for as lesson_service
            manifest = capture_task_manifest(cwd, message)
            if manifest:
                lesson_service(self.root).register_replay(run_id, manifest)
        except (ValueError, OSError):
            log.warning("C9 replay inputs unavailable for run %s", run_id)
        with self._lock:
            self._publish_run_state(run)
        thread = threading.Thread(target=self._worker, args=(run, message, options, cwd), daemon=True,
                                  name=f"connected-session-run-{run_id}")
        try:
            thread.start()
        except RuntimeError:
            self._set_state(run, "interrupted", error="Neyvia could not start this turn. It was not sent.")
            self._retire(run)
        self._invalidate_lists()
        self._ensure_thread()
        return self.get_run(run_id)

    def _run_is_over(self, run_id: str) -> bool:
        """A run that just ended in memory frees its session before its row catches up."""
        with self._lock:
            return run_id in self._live and self._live[run_id].terminal

    def _publish_run_state(self, run: _LiveRun) -> None:
        data = run.data
        self._publish({"type": "run.state", "sessionId": data.get("sessionId"), "runId": data["runId"],
                       "state": data["state"], "pendingRequest": data.get("pendingRequest"), "error": data.get("error"),
                       "impact": data.get("impact")})

    def _set_state(self, run: _LiveRun, state: str, *, error: str | None = None, pending: dict[str, Any] | None = None,
                   flags: dict[str, Any] | None = None) -> bool:
        if state in TERMINAL_STATES and not run.terminal:
            from ..task_feedback import capture_outputs
            outputs, snapshots, warnings = capture_outputs(run.data.get("workspaceRoot"), run.edited_files)
            run.data.update(outputs=outputs, outputSnapshots=snapshots, evidenceWarnings=warnings)
        if state in TERMINAL_STATES and not run.terminal and getattr(run, "edited_files", None):
            from ..neyvia_impact import REPO, impact
            paths = []
            for raw in sorted(run.edited_files):
                try:
                    Path(raw).resolve().relative_to(REPO.resolve())
                    paths.append(raw)
                except ValueError:
                    continue
            if paths:
                try:
                    run.data["impact"] = impact(paths, gaps=False)
                except Exception as exc:
                    run.data["impact"] = {"ok": False, "error": describe(exc)}
        with self._lock:
            if run.terminal:
                return False
            run.data.update(state=state, updatedAt=iso(time.time()), pendingRequest=pending if state in ("waiting_approval", "waiting_input") else None)
            run.data["error"] = error if state in TERMINAL_STATES or error else None
            for name in ("canStop", "canSteer"):
                if flags and name in flags:
                    run.data[name] = bool(flags[name])
            run.terminal = state in TERMINAL_STATES
            _proofs.check_state_transition(run, state, error, pending, flags)
            if run.terminal:
                from ..neyvia_awareness import release
                for identity in list(run.work_claim_ids):
                    try:
                        release(self.root, {"id": identity})
                        run.work_claim_ids.discard(identity)
                    except ValueError:
                        run.work_claim_ids.discard(identity)  # the mod's end hook already released it
                    except OSError:
                        log.exception("could not release work claim %s", identity)
                from ..neyvia_awareness import release_owner
                try:
                    release_owner(self.root, run_id=run.data["runId"], session=run.data.get("sessionId"))
                except (OSError, TimeoutError):
                    log.exception("could not release run claims %s; persisted terminal state expires them", run.data["runId"])
            self._publish_run_state(run)
            summary = self._summaries.get(run.data.get("sessionId") or "")
            if summary is not None:
                self._publish({"type": "session.updated", "session": self._decorate(summary).public()})
        self._persist(run)
        self._invalidate_lists()
        return True

    def _retire(self, run: _LiveRun) -> None:
        with self._lock:
            self._live.pop(run.data["runId"], None)
        self._invalidate_lists()

    def _normalize_session(self, app: str, value: Any) -> str | None:
        if not value or not isinstance(value, str):
            return None
        return value if parse_session_id(value) else make_session_id(app, self.host["deviceId"], value)

    def _learn_session(self, run: _LiveRun, value: Any) -> None:
        """Adopt the session id of a new session once the adapter names it; never replace a known one."""
        session_id = self._normalize_session(run.data["app"], value)
        if session_id is None:
            return
        with self._lock:
            if run.data.get("sessionId"):
                return
            run.data["sessionId"] = session_id
            if getattr(run, 'memory_context', None) and getattr(run, 'memory_generation', None) is not None:
                from ..cue_memory import CueMemoryStore
                CueMemoryStore(run.memory_context).mark_session(session_id, run.memory_generation)
            # A newly adopted session was started in a folder chosen by the
            # person. Persist that placement before announcing its id, even
            # when the provider hasn't populated gitInfo yet.
            cwd = run.data.get("workspaceRoot")
            if cwd:
                from ..ui_command_bus import bus_for
                bus = bus_for(self.root)
                bus.update("projects", {cwd: {"name": Path(cwd).name, "path": cwd}})
                saved = bus.get("sessions", {}).get(session_id, {})
                bus.update("sessions", {session_id: {**saved, "project": cwd}})
                bus.emit("session.moved", {"id": session_id, "project": cwd})
            self._publish_run_state(run)
        self._persist(run)

    def _worker(self, run: _LiveRun, message: str, options: TurnOptions, cwd: str | None) -> None:
        final, error = "completed", None
        watch_stop = threading.Event()
        run.cwd = cwd
        run.intent = next((line.strip()[:300] for line in message.splitlines() if line.strip()), run.intent)

        def emit(event: dict[str, Any]) -> None:
            try:
                if getattr(run, 'memory_context', None) and getattr(run, 'memory_generation', None) is not None:
                    from ..cue_memory import CueMemoryStore
                    if CueMemoryStore(run.memory_context).generation() != run.memory_generation:
                        run.stop_requested = True
                        run.memory_revoked = True
                        run.adapter.interrupt(run.data['runId'])
                        return
                self._on_event(run, event)
            except Exception:  # noqa: BLE001 - a bad event must not break the adapter's turn
                log.exception("dropped a malformed event from %s", run.data["app"])

        def watch_memory():
            # Cancellation does not depend on another provider output event.
            from ..cue_memory import CueMemoryStore
            watch_store = CueMemoryStore(run.memory_context)
            while not watch_stop.wait(.1):
                try:
                    if watch_store.generation() != run.memory_generation:
                        run.stop_requested = True
                        run.memory_revoked = True
                        run.adapter.interrupt(run.data['runId'])
                        return
                except Exception:
                    run.stop_requested = True
                    run.memory_revoked = True
                    run.adapter.interrupt(run.data['runId'])
                    return

        try:
            if run.stop_requested:
                final = "cancelled"
            else:
                self._set_state(run, "running")
                if run.kind == "compact" and callable(getattr(run.adapter, "compact", None)):
                    result = run.adapter.compact(run.data["sessionId"], run_id=run.data["runId"], emit=emit)
                else:
                    if getattr(run, 'memory_context', None):
                        from ..cue_memory import CueMemoryStore
                        from ..neyvia_memory_tools import ingest_teaching
                        from ..memory_recall import recall
                        teaching = ingest_teaching(run.memory_context, message)
                        store = CueMemoryStore(run.memory_context)
                        if run.data.get('sessionId') and not store.session_valid(run.data['sessionId']):
                            raise ConnectedError('memory_context_revoked', 'Memory was updated; this chat has older context. Start a fresh chat.', 409)
                        packet = recall(run.memory_context, {'intent': message, 'app': run.data['app']}, destination='provider', write_receipt=teaching)
                        run.data['memoryRecall'] = {key: packet[key] for key in ('selected', 'generation', 'route', 'reason', 'tokens', 'generationTokens', 'latencyMs')}
                        if teaching:
                            run.data['memoryWrite'] = teaching
                        if packet['selected'] or teaching:
                            run.memory_generation = packet['generation']
                            store.mark_session('pending:' + run.data['runId'], packet['generation'])
                            if run.data.get('sessionId'):
                                store.mark_session(run.data['sessionId'], packet['generation'])
                            threading.Thread(target=watch_memory, name='memory-revocation-' + run.data['runId'], daemon=True).start()
                        # Context is prepared after admission and never saved as taskText.
                        # With the Neyvia mod loaded in Claude Code, recall travels as mod context (the mod adds it as a
                        # model-only note), so the person's message stays exactly what they typed.
                        from ..claude_code_mods import mod_active
                        from ..connected_sessions.claude_items import parse_identity
                        try:
                            raw = parse_identity(run.data.get('sessionId') or '')
                        except ValueError:
                            raw = None
                        from ..claude_code_host import mod_loaded
                        via_mod = run.data['app'] == 'claude-code' and mod_active() and mod_loaded(self.root, raw)
                        side = []
                        if packet['section']:
                            if via_mod:
                                side.append(packet['section'])
                            else:
                                message = packet['section'] + '\n' + message
                        if teaching:
                            # The scoped host already committed this command.
                            # Avoid a duplicate provider write or approval request.
                            from ..memory_recall import ACKNOWLEDGEMENT_GUIDANCE
                            if via_mod:
                                side.append(ACKNOWLEDGEMENT_GUIDANCE.strip())
                            else:
                                message += ACKNOWLEDGEMENT_GUIDANCE
                        if side:
                            from ..claude_code_host import note_memory
                            note_memory(run.data['runId'], '\n'.join(side))
                        self._persist(run)
                    result = run.adapter.start_turn(run.data.get("sessionId"), message, options, cwd=cwd,
                                                    run_id=run.data["runId"], emit=emit)
                self._learn_session(run, result)
        except Exception as exc:  # noqa: BLE001 - the turn failed; report it on the run
            if run.stop_requested:
                final = "cancelled"
            else:
                final, error = "failed", describe(exc)
                log.warning("turn %s failed: %s", run.data["runId"], error, exc_info=True)
        finally:
            watch_stop.set()
            try:
                if getattr(run, 'memory_revoked', False):
                    final, error = 'cancelled', 'Memory changed while this turn was running. Start a fresh chat.'
                self._set_state(run, "cancelled" if run.stop_requested and final == "completed" else final, error=error)
                if getattr(run, 'memory_context', None) and final == 'completed' and not run.stop_requested:
                    try:
                        from ..neyvia_memory_tools import capture_outcome
                        candidate = capture_outcome(run.memory_context, run.data)
                        if candidate:
                            run.data['memoryCandidate'] = candidate
                            self._persist(run)
                    except (ValueError, OSError):
                        log.warning('Verified outcome memory candidate unavailable for run %s', run.data['runId'])
            finally:
                self._retire(run)

    def _on_event(self, run: _LiveRun, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        run.last_output = time.monotonic()
        kind = event.get("type")
        if kind == "completion.receipt":
            with self._lock:
                run.data["doneStatus"] = event.get("doneStatus")
                run.data["skillReceipts"] = jsonable(event.get("skillReceipts") or {})
                run.edited_files.update(str(path) for path in event.get("outputPaths", []) if isinstance(path, str))
            self._persist(run)
            return
        session = event.get("session") if isinstance(event.get("session"), dict) else {}
        self._learn_session(run, event.get("sessionId") or session.get("id"))
        if kind in {"usage.updated", "usage.baseline"}:
            from ..model_usage import record_run_usage
            with self._lock:
                if not record_run_usage(run, event):
                    return
            self._persist(run)
            self._publish({"type": "usage.updated", "sessionId": run.data.get("sessionId"),
                           "runId": run.data["runId"], "usage": run.data["usage"]})
            return
        if kind == "run.state":
            state = event.get("state")
            if state not in _RUN_STATES:
                return
            pending = bound_event(event["pendingRequest"], 32 * 1024) if isinstance(event.get("pendingRequest"), dict) else None
            if pending is not None:
                pending.setdefault("kind", "question" if state == "waiting_input" else "approval")
                pending["requestId"] = str(pending.get("requestId") or pending.get("id") or uuid.uuid4().hex)
            error = str(event["error"])[:500] if event.get("error") else None
            self._set_state(run, state, error=error, pending=pending, flags=event)
            return
        stamped = dict(event)
        stamped["sessionId"] = (self._normalize_session(run.data["app"], stamped.get("sessionId"))
                                or run.data.get("sessionId"))
        item = stamped.get("item") if isinstance(stamped.get("item"), dict) else None
        if item is not None:
            item = jsonable(item)
            with self._lock:
                from .work_board import edited_paths
                from ..neyvia_awareness import claim
                paths = [] if run.terminal else edited_paths(item, run.cwd)
                if paths:
                    run.edited_files.update(paths)
                    record = claim(self.root, {"agent": APP_LABELS[run.data["app"]],
                        "chat": run.data.get("sessionId") or run.data["runId"], "app": run.data["app"], "runId": run.data["runId"],
                        "files": paths[:100], "intent": run.intent})
                    run.work_claim_ids.add(record["claim"]["id"])
            self._tidy_item(str(stamped.get("sessionId") or ""), item, TOOL_OUTPUT_FULL_CHARS)
            stamped["item"] = item
            if isinstance(item.get("seq"), int) and stamped.get("sessionId"):
                with self._lock:
                    self._remember_seq(stamped["sessionId"], item["seq"])
        self._publish(stamped)

    # -- control --------------------------------------------------------------------------

    def _active_live(self, run_id: str) -> _LiveRun | None:
        self.recover(run_id=run_id)
        with self._lock:
            return self._live.get(run_id)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def stop(self, run_id: str) -> dict[str, Any]:
        record = self.get_run(str(run_id or ""))
        live = self._active_live(record["runId"])
        if record["state"] not in ACTIVE_STATES or live is None:
            return self.get_run(record["runId"])
        live.stop_requested = True
        try:
            bounded(lambda: live.adapter.interrupt(record["runId"]), 15, "stop")
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "stop_failed", "The app could not stop this turn:") from exc
        return self.get_run(record["runId"])

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def steer(self, run_id: str, message: Any, options: Any = None) -> dict[str, Any]:
        """Add a message to the turn that is running, for apps that can take one."""
        record = self.get_run(str(run_id or ""))
        live = self._active_live(record["runId"])
        if live is None or record["state"] not in ACTIVE_STATES:
            raise ConnectedError("run_not_active", "That turn is not running any more.", 409)
        hook = getattr(live.adapter, "steer", None)
        if not record["canSteer"] or not callable(hook):
            raise ConnectedError("not_supported", f"{APP_LABELS[record['app']]} cannot take a message into a running turn.", 409)
        message = self._with_files(message, options)
        images = self._turn_options(options).images
        if not isinstance(message, str) or (not message.strip() and not images) or len(message) > MAX_MESSAGE_CHARS:
            raise ConnectedError("invalid_message", "Send a message between 1 and 100,000 characters.")
        try:
            bounded(lambda: hook(record["runId"], message, images) if images else hook(record["runId"], message), 45, "steer")
        except Exception as exc:  # noqa: BLE001
            raise as_connected(exc, "steer_failed", "The app could not take that message:") from exc
        return self.get_run(record["runId"])

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_run_record(result))
    def answer(self, run_id: str, request_id: str, response: Any) -> dict[str, Any]:
        record = self.get_run(str(run_id or ""))
        live = self._active_live(record["runId"])
        pending = record.get("pendingRequest")
        if live is None or not isinstance(pending, dict) or pending.get("requestId") != request_id:
            raise ConnectedError("request_not_pending", "This request is no longer waiting. Refresh the session to see its current state.", 409)
        if not isinstance(response, dict) or response.get("decision") not in ("approve", "deny", "cancel"):
            raise ConnectedError("invalid_response", "Choose approve, deny or cancel.")
        choices = pending.get("choices")
        if (response["decision"] != "cancel" and isinstance(choices, list) and choices
                and all(isinstance(choice, str) for choice in choices) and response["decision"] not in choices):
            raise ConnectedError("invalid_response", "That choice is not available for this request.")
        answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
        clean = {"decision": response["decision"], "answers": {str(key)[:200]: str(value)[:20_000] for key, value in list(answers.items())[:50]}}
        with self._lock:
            if request_id in live.answered:
                raise ConnectedError("request_already_answered", "This request already has an answer.", 409)
            live.answered.add(request_id)
        try:
            bounded(lambda: live.adapter.answer(record["runId"], request_id, clean), 15, "answer")
        except Exception as exc:
            with self._lock:
                live.answered.discard(request_id)
            raise as_connected(exc, "answer_failed", "The app could not take that answer:") from exc
        with self._lock:
            current = live.data.get("pendingRequest")
            if not live.terminal and isinstance(current, dict) and current.get("requestId") == request_id:
                live.data.update(state="running", pendingRequest=None, updatedAt=iso(time.time()))
                self._publish_run_state(live)
                changed = True
            else:
                changed = False
        if changed:
            self._persist(live)
        return self.get_run(record["runId"])


def _sort_key(value: str | None) -> float:
    return _epoch(value) or 0.0


_BROKERS: dict[str, ConnectedBroker] = {}
_BROKERS_LOCK = threading.Lock()


def broker_for(root: Path, backend: Any = None) -> ConnectedBroker:
    """The one broker of this process for a state root; ``backend`` reaches adapters that need it."""
    key = os.path.normcase(str(Path(root).resolve()))
    with _BROKERS_LOCK:
        broker = _BROKERS.get(key)
        if broker is None or broker.closed:
            broker = _BROKERS[key] = ConnectedBroker(Path(root).resolve(), backend=backend)
            atexit.register(broker.close)  # never leave an adapter's child process behind
        return broker
