"""Neyvia's own conversations (Native and Hybrid) as connected sessions.

The adapter reads the conversation store and sends turns through the same backend commands the
classic UI uses, so a Neyvia chat looks and streams like a Claude Code or Codex session in the
redesigned UI. It is built by ``create_adapter(backend)``, which the broker calls with the web
backend (``broker._build`` passes ``backend=``).

Category rule (``conversation_runtime`` and ``classify``). The runtime is the first of: the runtime
recorded on the conversation's latest turn (``runtimeId``), the conversation's route metadata, its
agent nodes' runtimes (orchestrations only). Then:

* ``neyvia-agent`` (also ``neyvia``, ``own``) is native;
* any other runtime (Codex, Claude Code, Hermes, ``fluxio-hybrid``, ...) is hybrid, and disagreeing
  routes are hybrid with no single runtime;
* a conversation that recorded no runtime anywhere is native with ``runtime=None``, so it always
  appears. (The classic UI files such a conversation under "unknown"; that is why Native chats
  without route metadata were missing from the browser.)

Session ids are ``external:neyvia:<deviceId>:<conversationId>``, the shape the broker routes on;
``neyvia:<conversationId>`` is accepted as an alias. Item ids and sequence numbers are described in
``neyvia_items``. Orchestration conversations are listed and readable, not continuable here.
"""
from __future__ import annotations

import base64
import binascii
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..chat_stream import read_chat_stream
from ..external_chat_inventory import _host
from .broker import ConnectedError, make_session_id, parse_session_id
from .model import Capabilities, ContextUsage, Emit, Item, ItemsPage, SessionSummary, TurnOptions
from .neyvia_items import LiveTurn, TEXT_SLOT, ordinal_of, seq_for, turn_items
from .neyvia_options import (DEFAULT_PERMISSION_MODE, NATIVE_RUNTIME, is_native, model_rows, normalize_runtime,
                             parse_route_id, permission_mode_rows, route_id, runtime_permission_modes, runtime_rows)
from .. import proofs_a_sessions as _proofs
from .. import proofs_a_native_sessions as _native_proofs

ORCHESTRATION_REASON = ("Orchestration plans run from Neyvia's orchestration workspace. "
                        "Here they can be read but not continued.")
_POLL_SECONDS = 0.25
_TURNS_PER_PAGE = 40
_HISTORY_TURNS = 8
_FOREIGN_WINDOW_SECONDS = 300.0  # clock skew allowed between a saved user turn and its chat run
_RECENT_RUN_SECONDS = 24 * 3600
_HARNESS_SOURCES = frozenset({"neyvia-harness", "harness", "proof"})
_TERMINAL_STATUS = {"failed": "failed", "stopped": "interrupted", "cancelled": "interrupted", "canceled": "interrupted"}
_DEFAULT_PROVIDERS = {"claude-code": "claude-code", "kimi-code": "kimi-code", "grok-build": "grok-build"}
_IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# -- category ----------------------------------------------------------------------------------


def _ids_of(routes: Any) -> list[str]:
    rows = routes if isinstance(routes, list) else list(routes.values()) if isinstance(routes, dict) else []
    found: list[str] = []
    for row in rows:
        value = next((row.get(key) for key in ("runtimeId", "runtime_id", "runtime", "harnessId", "harness_id")
                      if isinstance(row, dict) and row.get(key)), "")
        if value and normalize_runtime(value) not in found:
            found.append(normalize_runtime(value))
    return found


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_runtime(args[0], result))
def conversation_runtime(row: dict[str, Any]) -> str:
    """The runtime a conversation used; '' when nothing recorded one, 'mixed-routes' when they disagree."""
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    route = next((item for item in (metadata.get("routeSelection"), metadata.get("route")) if isinstance(item, dict)), {})
    for source in (row, metadata, route):
        for key in ("runtimeId", "runtime_id", "runtime", "harnessId", "harness_id"):
            if source.get(key) and isinstance(source.get(key), str):
                return normalize_runtime(source[key])
    ids = _ids_of(metadata.get("routeSnapshot"))
    return ids[0] if len(ids) == 1 else "mixed-routes" if ids else ""


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_category(args[0], result))
def classify(runtime: str) -> tuple[str, str | None]:
    """(category, runtime) for a conversation's runtime; see the module docstring."""
    if not runtime:
        return "native", None
    if is_native(runtime):
        return "native", NATIVE_RUNTIME
    return "hybrid", None if runtime == "mixed-routes" else normalize_runtime(runtime)


# -- runs --------------------------------------------------------------------------------------


@dataclass
class _Run:
    run_id: str
    conversation_id: str
    turn_id: str  # the assistant turn id: it names the chat stream and the chat run
    live: LiveTurn
    stop: bool = False
    cancel_sent: float = 0.0
    cancel_ok: bool = False


@dataclass
class _Context:
    active: dict[str, str] = field(default_factory=dict)  # conversation id -> live owner
    pending: set[str] = field(default_factory=set)  # conversations with a question waiting for an answer
    workspaces: dict[str, dict[str, Any]] = field(default_factory=dict)


class NeyviaAdapter:
    app = "neyvia"

    def __init__(self, backend: Any):
        self._backend = backend
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()

    # -- backend access -------------------------------------------------------------------------

    def _root(self) -> Path:
        return Path(self._backend.root)

    def _store(self) -> Any:
        if hasattr(type(self._backend), "conversation_store"):
            return self._backend.conversation_store
        return self._backend.neyvia_mcp.conversations

    def _dispatch(self, command: str, payload: dict[str, Any]) -> Any:
        return self._backend.dispatch(command, payload)

    def available(self) -> tuple[bool, str | None]:
        if not callable(getattr(self._backend, "dispatch", None)):
            return False, "The Neyvia adapter is not attached to the Neyvia backend on this PC."
        try:
            self._store()
        except Exception as exc:  # noqa: BLE001 - reported as the reason the source is unavailable
            return False, f"Neyvia conversations could not be opened: {str(exc)[:200]}"
        return True, None

    @staticmethod
    def _sid(conversation_id: str) -> str:
        return make_session_id("neyvia", _host()["deviceId"], conversation_id)

    @staticmethod
    def _conversation_id(session_id: str) -> str:
        parsed = parse_session_id(session_id)
        if parsed and parsed[0] == "neyvia":
            return parsed[2]
        if str(session_id).startswith("neyvia:") and len(str(session_id)) > 7:
            return str(session_id)[7:]
        raise FileNotFoundError(str(session_id))

    def _query(self, sql: str, args: tuple = ()) -> list[Any]:
        # The store offers no call for these narrow reads, and loading whole turns (their metadata
        # can be megabytes) to answer them would make every list and send slow.
        with self._store()._connection() as connection:
            return connection.execute(sql, args).fetchall()

    def _turn_ids(self, conversation_id: str) -> list[str]:
        return [row[0] for row in self._query(
            "SELECT turn_id FROM conversation_turns WHERE conversation_id = ? ORDER BY created_at, turn_id", (conversation_id,))]

    def _last_route(self, conversation_id: str) -> tuple[str, str, str, str] | None:
        rows = self._query(
            "SELECT json_extract(metadata_json, '$.runtimeResult.runtime', '$.runtimeResult.route.provider', "
            "'$.runtimeResult.route.model', '$.runtimeResult.route.effort') FROM conversation_turns "
            "WHERE conversation_id = ? AND json_extract(metadata_json, '$.runtimeResult.runtime') IS NOT NULL "
            "ORDER BY created_at DESC, turn_id DESC LIMIT 1", (conversation_id,))
        values = json.loads(rows[0][0]) if rows and rows[0][0] else None
        return tuple(str(value or "") for value in values) if values else None  # type: ignore[return-value]

    def _history(self, conversation_id: str) -> list[dict[str, str]]:
        rows = self._query(
            "SELECT role, content FROM conversation_turns WHERE conversation_id = ? AND meaningful = 1 "
            "AND role IN ('user', 'assistant') AND turn_kind = 'dialogue' ORDER BY created_at DESC, turn_id DESC LIMIT ?",
            (conversation_id, _HISTORY_TURNS))
        return [{"role": role, "text": content} for role, content in reversed(rows) if str(content).strip()]

    def _workspaces(self) -> dict[str, dict[str, Any]]:
        try:
            rows = json.loads((self._root() / ".agent_control" / "workspaces.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(row["workspace_id"]): row for row in rows if isinstance(row, dict) and row.get("workspace_id")}

    # -- list -----------------------------------------------------------------------------------

    def _pending_questions(self) -> set[str]:
        from ..agent_questions import list_questions

        try:
            rows = list_questions(self._root())
        except (OSError, ValueError):
            return set()
        return {str(row.get(key)) for row in rows for key in ("conversationId", "sessionId") if row.get(key)}

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_foreign(kwargs, result))
    def _foreign_runs(self) -> dict[str, str]:
        """Chat runs started elsewhere (the classic UI, a phone), attributed to their conversation.

        A chat run records its turn id and start time, not its conversation, so a running run is
        matched to the conversation whose newest saved turn is a user turn awaiting its reply and
        whose request time is closest to the run's start (within ``_FOREIGN_WINDOW_SECONDS``).
        """
        from ..chat_run_control import chat_run_status

        folder = self._root() / ".agent_control" / "chat_runs"
        with self._lock:
            own = {run.turn_id for run in self._runs.values()}
        runs: list[tuple[str, float]] = []
        for path in folder.glob("*.json"):
            if path.stem in own:
                continue
            try:
                if time.time() - path.stat().st_mtime >= _RECENT_RUN_SECONDS:
                    continue
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("state") == "running" and chat_run_status(self._root(), path.stem).get("status") == "running":
                    runs.append((path.stem, float(state.get("startedAt") or 0)))
            except (OSError, ValueError, TypeError):
                continue
        if not runs:
            return {}
        waiting = self._query(
            "SELECT c.conversation_id, t.created_at FROM conversations c JOIN conversation_turns t ON t.turn_id = "
            "(SELECT turn_id FROM conversation_turns WHERE conversation_id = c.conversation_id AND meaningful = 1 "
            "ORDER BY created_at DESC, turn_id DESC LIMIT 1) WHERE c.deleted_at IS NULL AND c.kind = 'chat' "
            "AND t.role = 'user' AND c.last_meaningful_activity_at >= ?",
            (datetime.fromtimestamp(time.time() - _RECENT_RUN_SECONDS * 2, timezone.utc).isoformat(),))
        pairs = sorted((abs((_epoch(created) or 0) - started), turn, cid) for turn, started in runs for cid, created in waiting
                       if _epoch(created) and abs((_epoch(created) or 0) - started) <= _FOREIGN_WINDOW_SECONDS)
        matched: dict[str, str] = {}
        used: set[str] = set()
        for _, turn, cid in pairs:
            if turn not in used and cid not in matched:
                matched[cid] = turn
                used.add(turn)
        return matched

    def _context(self) -> _Context:
        with self._lock:
            active = {run.conversation_id: "neyvia" for run in self._runs.values()}
        for cid in self._foreign_runs():
            active.setdefault(cid, "app")
        return _Context(active=active, pending=self._pending_questions(), workspaces=self._workspaces())

    def _node_runtimes(self, conversation_ids: list[str]) -> dict[str, str]:
        if not conversation_ids:
            return {}
        marks = ",".join("?" for _ in conversation_ids)
        found: dict[str, list[str]] = {}
        for cid, runtime in self._query(
                f"SELECT conversation_id, runtime FROM agent_nodes WHERE runtime != '' AND conversation_id IN ({marks})",
                tuple(conversation_ids)):
            found.setdefault(cid, [])
            if normalize_runtime(runtime) not in found[cid]:
                found[cid].append(normalize_runtime(runtime))
        return {cid: ids[0] if len(ids) == 1 else "mixed-routes" for cid, ids in found.items()}

    def _status(self, row: dict[str, Any], context: _Context) -> tuple[str, str | None]:
        cid = row["conversationId"]
        if cid in context.active:
            return "working", context.active[cid]
        if row.get("settledAt"):
            return "idle", None  # a settled conversation is done, whatever it once asked
        reasons = self._store()._blocking_attention_reasons(row)
        if "approval-required" in reasons:
            return "waiting_approval", None
        if "answer-required" in reasons or cid in context.pending:
            return "waiting_input", None
        return _TERMINAL_STATUS.get(str(row.get("status") or "").lower(), "idle"), None

    def _capabilities(self, row: dict[str, Any], category: str, runtime: str | None) -> Capabilities:
        if row["kind"] != "chat":
            return Capabilities(reason=ORCHESTRATION_REASON)
        return Capabilities(continue_session=True, new_session=True, stop=True, images=True,
                            goal=category == "native" and is_native(runtime or NATIVE_RUNTIME),
                            model_choice=True, effort_choice=True, permission_choice=True)

    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_summary(args[0], args[1], args[2], args[3], result))
    def _summary(self, row: dict[str, Any], context: _Context, node_runtime: str = "") -> SessionSummary:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        category, runtime = classify(conversation_runtime(row) or node_runtime)
        workspace = context.workspaces.get(str(row.get("workspaceId") or ""), {})
        cwd = next((str(value) for value in (metadata.get("workspacePath"), metadata.get("executionRoot"), workspace.get("root_path"))
                    if isinstance(value, str) and value.strip()), None)
        project = row.get("projectId") or workspace.get("name") or (Path(cwd).name if cwd else None) or None
        status, owner = self._status(row, context)
        host = _host()
        origin = "neyvia-harness" if metadata.get("origin") == "neyvia-harness" or metadata.get("harness") is True \
            or metadata.get("source") in _HARNESS_SOURCES else "user"
        return SessionSummary(
            id=self._sid(row["conversationId"]), app="neyvia", title=str(row.get("title") or "Conversation"),
            updated_at=row.get("lastMeaningfulActivityAt") or row.get("updatedAt"), created_at=row.get("createdAt"),
            cwd=cwd, project=project, git_branch=row.get("branch") or None, status=status,  # type: ignore[arg-type]
            status_since=row.get("updatedAt") if status != "idle" else None, live_owner=owner,  # type: ignore[arg-type]
            origin=origin, host_device_id=host["deviceId"], host_device_name=host["deviceName"],  # type: ignore[arg-type]
            archived=bool(row.get("archivedAt")), capabilities=self._capabilities(row, category, runtime),
            category=category, runtime=runtime)  # type: ignore[arg-type]

    def list_sessions(self, *, include_archived: bool = False) -> list[SessionSummary]:
        rows = self._store().list_conversations(include_archived=True, limit=1000)
        if not include_archived:
            rows = [row for row in rows if not row.get("archivedAt")]
        context = self._context()
        unlabeled = [row["conversationId"] for row in rows if row["kind"] == "orchestration" and not conversation_runtime(row)]
        nodes = self._node_runtimes(unlabeled)
        return [self._summary(row, context, nodes.get(row["conversationId"], "")) for row in rows]

    def live_status(self) -> dict[str, tuple[str, str | None]]:
        return {self._sid(cid): ("working", owner) for cid, owner in self._context().active.items()}

    def running_sessions(self) -> list[SessionSummary]:
        """Active and waiting conversations without the normal 1,000-history-row cap."""
        context = self._context()
        store = self._store()
        # Read the light conversation records, never their transcript or semantic payloads.
        rows = [store._conversation_from_row(row) for row in self._query(
            "SELECT * FROM conversations WHERE deleted_at IS NULL "
            "ORDER BY last_meaningful_activity_at DESC, conversation_id")]
        active = [row for row in rows if self._status(row, context)[0] in
                  ("working", "waiting_approval", "waiting_input")]
        unlabeled = [row["conversationId"] for row in active if row["kind"] == "orchestration"
                     and not conversation_runtime(row)]
        nodes = self._node_runtimes(unlabeled)
        found = []
        for row in active:
            route = self._last_route(row["conversationId"])
            if route:
                row["runtimeId"] = route[0]
            found.append(self._summary(row, context, nodes.get(row["conversationId"], "")))
        return found

    # -- read -----------------------------------------------------------------------------------

    def _row(self, conversation_id: str) -> dict[str, Any]:
        row = self._store().get_conversation(conversation_id)  # KeyError when it does not exist
        if row.get("deletedAt"):
            raise KeyError(conversation_id)
        route = self._last_route(conversation_id)
        row["runtimeId"] = route[0] if route else ""
        return row

    def _window(self, conversation_id: str, ids: list[str], upper: int, count: int) -> tuple[list[dict[str, Any]], int]:
        """The ``count`` turns before ordinal ``upper`` (plus one earlier, as a route baseline) and their first ordinal."""
        boundary = ids[upper] if upper < len(ids) else ""
        page = self._store().get_conversation_page(conversation_id, turn_limit=count + 1, before_turn_id=boundary)
        turns = page["turns"]
        return turns, upper - len(turns)

    def read(self, session_id: str, *, cursor: str | None = None, before_seq: int | None = None,
             limit: int = 200) -> ItemsPage:
        cid = self._conversation_id(session_id)
        try:
            row = self._row(cid)
        except KeyError as exc:
            raise FileNotFoundError(session_id) from exc
        ids = self._turn_ids(cid)
        budget = max(1, min(int(limit or 200), 200))
        after = None
        if cursor not in (None, ""):
            try:
                after = int(cursor)
            except ValueError:
                after = 0
        upper = len(ids) if before_seq is None else min(len(ids), ordinal_of(int(before_seq)) + 1)
        floor = max(0, ordinal_of(after)) if after is not None else 0
        items: list[Item] = []
        first_ordinal = upper
        while upper > floor and not items:
            count = min(_TURNS_PER_PAGE, upper - floor)
            turns, first_ordinal = self._window(cid, ids, upper, count)
            if not turns:
                break
            baseline = len(turns) > count  # the extra earliest turn only tells us what route came before
            previous = None
            for offset, turn in enumerate(turns):
                if not turn.get("meaningful", True):
                    continue
                built, previous = turn_items(turn, first_ordinal + offset, previous)
                if not (baseline and offset == 0):
                    items.extend(built)
            if before_seq is not None:
                items = [item for item in items if item.seq < int(before_seq)]
            if after is not None:
                items = [item for item in items if item.seq > after]
            upper = first_ordinal + (1 if baseline else 0)
        trimmed = len(items) > budget
        items = items[-budget:]
        run = self._run_for(cid) if before_seq is None else None
        if run is not None:
            seen = {item.id for item in items}
            items += [item for item in list(run.live.items.values())
                      if item.id not in seen and (after is None or item.seq > after)]
            items.sort(key=lambda item: item.seq)
        earliest = ordinal_of(items[0].seq) if items else first_ordinal
        newest = max([item.seq for item in items] + ([after] if after is not None else []), default=0)
        context = run.live.context if run is not None and run.live.context else self._last_context_usage(cid)
        summary = self._summary(row, self._context())
        page = ItemsPage(session=summary, items=items, context=context, cursor=str(newest),
                         has_earlier=trimmed or earliest > 0)
        # The native plan owner also publishes directly to the existing UI bus,
        # without creating a provider tool item. A current connected read must
        # project that explicit owner state just as it projects recorded items.
        if before_seq is None:
            from ..ui_command_bus import bus_for
            missing = object()
            bus = bus_for(self._root())
            published = bus.get('plan:' + summary.id, missing)
            if published is missing and session_id != summary.id:
                published = bus.get('plan:' + session_id, missing)
            if published is not missing:
                # An explicit clear must not resurrect a historical item plan
                # through the broker's fallback for an absent page.plan.
                page.plan = published if published is not None else {
                    'items': [], 'source': 'neyvia-intent', 'explanation': None,
                    'updatedAt': None, 'throughSeq': None}
        _proofs.check_native_page(page, after=after, before=before_seq, budget=budget, earliest=earliest, trimmed=trimmed)
        return page

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_context(kwargs, result))
    def _last_context_usage(self, conversation_id: str) -> ContextUsage:
        """The last provider-reported prompt size, from the newest turns' recorded streams."""
        from ..chat_stream import last_stream_event

        with self._store()._connection() as connection:
            turn_ids = [row[0] for row in connection.execute(
                "SELECT turn_id FROM conversation_turns WHERE conversation_id = ? AND role = 'assistant' "
                "ORDER BY created_at DESC, turn_id DESC LIMIT 3", (conversation_id,))]
        for turn_id in turn_ids:
            # From the end of the stream: a long turn's last round is its context now.
            try:
                event = last_stream_event(self._root(), turn_id, "context.usage")
            except (OSError, ValueError):
                continue
            if event is not None:
                data = event["data"]
                used = data.get("inputTokens")
                if isinstance(used, int) and not isinstance(used, bool):
                    window, trigger = data.get("contextTokens"), data.get("triggerTokens")
                    return ContextUsage(
                        used_tokens=used,
                        window_tokens=window if isinstance(window, int) and window > 0 else None,
                        auto_compact_tokens=trigger if isinstance(trigger, int) and trigger > 0 else None,
                        source="provider-usage", updated_at=str(event.get("at") or "") or None)
        return ContextUsage()

    def _run_for(self, conversation_id: str) -> _Run | None:
        with self._lock:
            return next((run for run in self._runs.values() if run.conversation_id == conversation_id), None)

    # -- options --------------------------------------------------------------------------------

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_options(kwargs, result))
    def options(self, session_id: str | None = None) -> dict[str, Any]:
        rows = model_rows(self._root())
        runtimes = runtime_rows()
        for runtime in runtimes:  # a runtime without a model list is still selectable, on its own default
            if not any(row["runtime"] == runtime["id"] for row in rows):
                rows.append({"id": route_id(runtime["id"], "", ""), "label": "Default model", "runtime": runtime["id"],
                             "provider": "", "model": "", "group": runtime["label"], "efforts": [],
                             "defaultEffort": None, "default": False})
        preferred = NATIVE_RUNTIME, "openai-codex", next((r["defaultModel"] for r in runtimes if r["id"] == NATIVE_RUNTIME), "") or ""
        try:
            last = self._last_route(self._conversation_id(session_id)) if session_id else None
        except FileNotFoundError:
            last = None  # an unknown session gets the defaults
        if last:
            preferred = last[0], last[1], last[2]
        # The session's last route may name a provider the picker lists differently, so fall back to
        # the same model, then the same runtime, then Neyvia Native.
        chosen = (next((row for row in rows if (row["runtime"], row["provider"], row["model"]) == preferred), None)
                  or next((row for row in rows if (row["runtime"], row["model"]) == (preferred[0], preferred[2])), None)
                  or next((row for row in rows if row["runtime"] == preferred[0]), None)
                  or next((row for row in rows if row["runtime"] == NATIVE_RUNTIME), rows[0] if rows else None))
        if chosen is not None:
            chosen["default"] = True
        return {"models": rows, "runtimes": runtimes, "permissionModes": permission_mode_rows(),
                "defaultPermissionMode": DEFAULT_PERMISSION_MODE, "skills": [], "plugins": [], "mcpServers": []}

    def can_start_new(self) -> tuple[bool, str | None]:
        ok, reason = self.available()
        return ok, reason

    # -- turns ----------------------------------------------------------------------------------

    @staticmethod
    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_attachments(args[0], result))
    def _attachments(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from ..web_backend import ChatAttachmentValidationError, _decode_chat_attachments

        rows = []
        for number, image in enumerate(images, 1):
            encoded = str(image.get("data") or "")
            # The shared decoder checks the encoded bound before allocating bytes.
            size = len(encoded) // 4 * 3 - len(encoded) + len(encoded.rstrip("="))
            mime = str(image.get("mime") or "application/octet-stream")
            rows.append({"name": str(image.get("name") or f"image-{number}{_IMAGE_EXTENSIONS.get(mime, '.bin')}"),
                         "mime": mime, "size": size, "dataBase64": encoded})
        try:
            _decode_chat_attachments(rows)
        except ChatAttachmentValidationError as exc:
            raise ConnectedError("invalid_image", str(exc)) from exc
        _native_proofs.admitted_attachments()
        return rows

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_route(kwargs, result))
    def _route(self, conversation_id: str, options: TurnOptions) -> tuple[str, str, str, str]:
        """(runtime, provider, model, effort): the picked route, else the conversation's last one, else Native's default."""
        last = self._last_route(conversation_id) if conversation_id else None
        picked = parse_route_id(options.model)
        if picked:
            runtime, provider, model = picked
        else:
            runtime, provider, model = (last[0], last[1], options.model or last[2]) if last else (NATIVE_RUNTIME, "", options.model or "")
        runtime = normalize_runtime(runtime) or NATIVE_RUNTIME
        if not provider:
            provider = (last[1] if last and last[0] == runtime else "") or _DEFAULT_PROVIDERS.get(runtime, "openai-codex")
        if not model and runtime == NATIVE_RUNTIME and not picked:
            model = next((r["defaultModel"] for r in runtime_rows() if r["id"] == NATIVE_RUNTIME), "") or ""
        return runtime, provider, model, options.effort or "default"

    @staticmethod
    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_permission(kwargs, result))
    def _permission_mode(options: TurnOptions, runtime: str) -> str:
        from ..native_access import PERMISSION_MODES

        mode = options.permission_mode or DEFAULT_PERMISSION_MODE
        if mode not in PERMISSION_MODES:
            raise ConnectedError("invalid_permission_mode", "Choose read-only, workspace or full-access.")
        allowed = runtime_permission_modes(runtime)
        if mode not in allowed:
            raise ConnectedError("permission_not_supported",
                                 f"{runtime} cannot run in {mode} mode here. Choose one of: {', '.join(allowed)}.")
        return mode

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_payload(kwargs, result))
    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_payload(kwargs, result))
    def _payload(self, conversation_id: str, message: str, mode: str, attachments: list[dict[str, Any]],
                 route: tuple[str, str, str, str], cwd: str | None, row: dict[str, Any],
                 ids: tuple[str, str], started: str) -> dict[str, Any]:
        """The ``send_agent_chat_command`` payload, with the fields the classic composer sends."""
        runtime, provider, model, effort = route
        metadata = row.get("metadata") or {}
        workspace = self._workspaces().get(str(row.get("workspaceId") or ""), {})
        path = cwd or metadata.get("workspacePath") or metadata.get("executionRoot") or workspace.get("root_path") or ""
        context = [line for line in (f"Workspace: {workspace['name']}." if workspace.get("name") else "",
                                     f"Workspace path: {path}." if path else "") if line]
        return {
            "message": message, "attachments": attachments, "permissionMode": mode,
            "workspaceToolsAllowed": mode != "read-only", "runtime": runtime,
            "route": {"runtimeId": runtime, "provider": provider, "model": model, "effort": effort, "role": "executor"},
            "workspaceId": str(row.get("workspaceId") or ""), "workspacePath": str(path),
            "history": self._history(conversation_id), "sessionId": conversation_id, "conversationId": conversation_id,
            "userTurnId": ids[0], "assistantTurnId": ids[1], "systemContext": "\n".join(context),
            "requestStartedAt": started,
        }

    def _create(self, cwd: str | None) -> dict[str, Any]:
        _native_proofs.before_conversation_mutation()
        workspace_id = ""
        if cwd:
            same = str(Path(cwd).resolve()).casefold()
            workspace_id = next((key for key, row in self._workspaces().items()
                                 if str(Path(str(row.get("root_path") or "-")).resolve()).casefold() == same), "")
        return self._dispatch("create_neyvia_conversation_command", {
            "workspaceId": workspace_id, "kind": "chat", "title": "", "titleMode": "automatic",
            "metadata": {"source": "connected-sessions", **({"workspacePath": cwd} if cwd else {})}})

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_cancel(kwargs, result))
    def _cancel(self, run: _Run) -> None:
        result = self._dispatch("cancel_agent_chat_command", {"turnId": run.turn_id}) or {}
        run.cancel_sent = time.monotonic()
        run.cancel_ok = result.get("status") in ("stop_requested", "already_finished", "interrupted")
        _native_proofs.check_cancel_result(run, result)

    @_native_proofs.turn_contract
    def start_turn(self, session_id: str | None, message: str, options: TurnOptions, *, cwd: str | None,
                   run_id: str, emit: Emit) -> str:
        ok, reason = self.available()
        if not ok:
            raise ConnectedError("adapter_unavailable", reason or "Neyvia is not available.", 503)
        store = self._store()
        existing = ""
        if session_id is not None:
            try:
                existing = self._conversation_id(session_id)
                row = self._row(existing)
            except (FileNotFoundError, KeyError) as exc:
                raise ConnectedError("session_not_found", "That conversation was not found.", 404) from exc
            if row["kind"] != "chat":
                raise ConnectedError("cannot_continue", ORCHESTRATION_REASON, 409)
        # Refuse a bad request before anything is created or restored.
        route = self._route(existing, options)
        mode = self._permission_mode(options, route[0])
        attachments = self._attachments(options.images)
        if session_id is None:
            cid = str(self._create(cwd)["conversationId"])
        else:
            cid = existing
            if row.get("archivedAt"):
                _native_proofs.before_conversation_mutation()
                store.restore_conversation(cid)  # sending is the request to bring it back
        row = self._row(cid)
        sid = self._sid(cid)
        previous = self._last_route(cid)
        stamp = int(time.time() * 1000)
        ids = (f"chat-turn-{stamp}-{uuid.uuid4().hex[:6]}", f"chat-turn-{stamp}-{uuid.uuid4().hex[:6]}")
        started = _now()
        payload = self._payload(cid, message, mode, attachments, route, cwd, row, ids, started)
        ordinal = len(self._turn_ids(cid))
        run = _Run(run_id, cid, ids[1], LiveTurn(sid, ids[1], ordinal + 1))
        with self._lock:
            self._runs[run_id] = run
        try:
            if session_id is None:
                emit({"type": "session.updated", "session": self._summary(row, self._context()).public()})
            shown = [{"id": "", "kind": "image" if a["mime"].startswith("image/") else "file", "label": a["name"],
                      "url": None, "mime": a["mime"]} for a in attachments]
            user = Item(id=ids[0], seq=seq_for(ordinal, TEXT_SLOT), kind="user", at=started,
                        data={"text": message, "attachments": shown})
            emit({"type": "item.added", "sessionId": sid, "item": user.public()})
            outcome = self._follow(run, payload, emit)
            self._reconcile(run, ids[1], ordinal + 1, previous, emit)
            failure = self._finish(run, outcome, emit)
            emit({"type": "session.updated", "session": self._summary(self._row(cid), self._context()).public()})
            if failure is not None:
                raise failure
        finally:
            with self._lock:
                self._runs.pop(run_id, None)
        return sid

    def _follow(self, run: _Run, payload: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Run ``send_agent_chat_command`` on a worker thread and relay its chat stream until the run ends."""
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["result"] = self._dispatch("send_agent_chat_command", payload)
            except BaseException as exc:  # noqa: BLE001 - handed to the calling thread
                box["error"] = exc

        worker = threading.Thread(target=work, name=f"neyvia-chat-{run.turn_id}", daemon=True)
        worker.start()
        cursor = 0
        while True:
            finished = not worker.is_alive()
            snapshot = read_chat_stream(self._root(), run.turn_id, cursor)
            events = snapshot.get("events") or []
            cursor = int(snapshot.get("cursor") or cursor)
            for event in run.live.apply(events):
                emit(event)
            if run.stop and not run.cancel_ok and not finished and time.monotonic() - run.cancel_sent >= 1.0:
                self._cancel(run)  # the run may not have registered when the first request came
            if finished and not events:
                return box
            if not events:
                worker.join(_POLL_SECONDS)

    def _reconcile(self, run: _Run, turn_id: str, ordinal: int, previous: Any, emit: Emit) -> None:
        """Replace the live rows with the saved turn's, so the client shows exactly what a later read would."""
        try:
            turn = self._store().get_turn(turn_id, hydrate=False)
        except KeyError:
            return  # the run failed before it saved a reply
        from .neyvia_items import receipt_of
        receipt = receipt_of(turn.get("metadata")) or {}
        result = (turn.get("metadata") or {}).get("runtimeResult") or {}
        completion = result.get("clCompletion") or (result.get("raw") or {}).get("clCompletion")
        if isinstance(completion, dict):
            emit({"type": "completion.receipt", "sessionId": run.live.session_id,
                  "doneStatus": completion.get("doneStatus"), "skillReceipts": completion.get("skillReceipts") or {},
                  "outputPaths": completion.get("outputPaths", [])})
        usage = (result.get("raw") or {}).get("usage") or receipt.get("usage")
        if isinstance(usage, dict):
            emit({"type": "usage.updated", "sessionId": run.live.session_id, "usage": usage})
        if not turn.get("meaningful", True):
            return
        items, _ = turn_items(turn, ordinal, tuple(previous[:3]) if previous else None)
        for item in items:
            kind = "item.updated" if item.id in run.live.items else "item.added"
            emit({"type": kind, "sessionId": run.live.session_id, "item": item.public()})

    @staticmethod
    @_native_proofs.finish_contract
    def _finish(run: _Run, outcome: dict[str, Any], emit: Emit) -> ConnectedError | None:
        """Report how the run ended; returns the error the broker should record, if the run itself failed."""
        error = outcome.get("error")
        if error is not None:
            return error if isinstance(error, ConnectedError) else ConnectedError(
                "send_failed", str(error)[:500] or type(error).__name__, 502)
        result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
        status = str(result.get("status") or "completed").lower()
        state, text = None, None
        if status == "cancelled":
            state = "cancelled"
        elif status == "stop_unconfirmed":
            state, text = "interrupted", result.get("error") or "Stop was requested, but the runtime could not be confirmed stopped."
        elif status in ("failed", "error", "timeout") or result.get("ok") is False:
            state, text = "failed", result.get("error") or "The runtime failed before a readable reply."
        if state:
            emit({"type": "run.state", "sessionId": run.live.session_id, "runId": run.run_id, "state": state,
                  "pendingRequest": None, "error": str(text)[:500] if text else None})
        return None

    def interrupt(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            return
        run.stop = True
        self._cancel(run)

    @_native_proofs.unsupported_contract
    def answer(self, run_id: str, request_id: str, response: dict[str, Any]) -> None:
        raise ConnectedError("not_supported", "Neyvia asks a question at the end of a turn. Answer it by sending your reply.", 409)

    @_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_goal(kwargs, result))
    @_native_proofs.goal_contract
    @_native_proofs.unsupported_contract
    def goal(self, session_id: str, action: str, text: str | None = None) -> dict[str, Any] | None:
        """Goal mode is a per-chat switch that makes Native keep working against its goal; ``text`` is not stored."""
        cid = self._conversation_id(session_id)
        row = self._row(cid)
        category, runtime = classify(conversation_runtime(row))
        if row["kind"] != "chat" or category != "native":
            raise ConnectedError("not_supported", "Goal mode is a Neyvia Native chat feature.", 409)
        if action in ("set", "clear"):
            row = self._store().set_goal_mode(cid, action == "set")
        enabled = (row.get("metadata") or {}).get("goalMode") is True
        return {"state": "set", "text": None, "goalMode": True} if enabled else None


@_proofs.checked_result(lambda args, kwargs, result: _native_proofs.check_factory(kwargs, result))
def create_adapter(backend: Any = None) -> NeyviaAdapter:
    return NeyviaAdapter(backend)
