"""Adapter registry for connected sessions, and the small calls around it.

The registry builds Claude Code, Codex, OpenCode and Neyvia adapters lazily (a module import or a
registered factory) and turns a missing or failing one into an unavailable source with a reason.
``parallel`` and ``bounded`` run adapter calls on daemon threads with a deadline, so one stuck
app never blocks the service. ``ConnectedError`` is the refusal type the whole package raises.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote

from .. import proofs_a_sessions as _proofs

log = logging.getLogger("neyvia.connected_sessions")

APPS = ("claude-code", "codex", "opencode", "neyvia")
CATEGORIES = ("connected", "native", "hybrid")
APP_LABELS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "neyvia": "Neyvia"}
_APP_MODULES = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "neyvia": "neyvia"}
_APP_ALIASES = {"claude": "claude-code", "claude_code": "claude-code", "open-code": "opencode", "open_code": "opencode"}
_CLASS_NAMES = {"claude-code": ("ClaudeAdapter", "ClaudeCodeAdapter"), "codex": ("CodexAdapter",),
                "opencode": ("OpenCodeAdapter",), "neyvia": ("NeyviaAdapter",)}
_REQUIRED_METHODS = ("available", "list_sessions", "live_status", "read", "options", "start_turn", "interrupt", "answer")

_AVAILABILITY_TTL = 15.0
_ADAPTER_RETRY_SECONDS = 30.0
START_AVAILABILITY_SECONDS = 45.0


class ConnectedError(Exception):
    """A refused request with a stable machine code. Adapters may raise it too."""

    def __init__(self, code: str, message: str, status: int = 400, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra

    def public(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "error": self.message, "message": self.message, **self.extra}


AdapterError = ConnectedError


def normalize_app(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _APP_ALIASES.get(text, text)


def make_session_id(app: str, device_id: str, native_id: Any) -> str:
    return f"external:{app}:{device_id}:{quote(str(native_id), safe='-_.~')}"


def parse_session_id(value: Any) -> tuple[str, str, str] | None:
    parts = str(value or "").split(":", 3)
    if len(parts) != 4 or parts[0] != "external" or parts[1] not in APPS or not parts[3]:
        return None
    return parts[1], parts[2], unquote(parts[3])


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return str(value)


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def describe(exc: BaseException) -> str:
    message = getattr(exc, "message", None) if isinstance(getattr(exc, "code", None), str) else None
    text = str(message or exc).strip().splitlines()
    return (text[0] if text else type(exc).__name__)[:500]


_STATUS_BY_CODE = {"local_only": 403, "session_live_elsewhere": 409, "session_busy": 409, "request_not_pending": 409, "request_expired": 409,
                   "run_not_active": 409, "turn_not_steerable": 409, "turn_not_ready": 409, "rpc_timeout": 504}


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_adapter_refusal(kwargs, result))
def as_connected(exc: BaseException, fallback_code: str, fallback_message: str = "", fallback_status: int = 502) -> ConnectedError:
    """Turn an adapter exception into a refusal: a coded one (``exc.code``) keeps its code."""
    if isinstance(exc, ConnectedError):
        return exc
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        status = _STATUS_BY_CODE.get(code) or (
            404 if "not_found" in code else 400 if any(word in code for word in ("invalid", "required", "empty", "missing")) else fallback_status)
        owner, extra = getattr(exc, "owner", None), {}
        if isinstance(owner, str) and owner:
            extra["owner"] = owner
        elif isinstance(owner, dict) and owner.get("owner"):
            extra.update(owner=str(owner["owner"]), ownerDetail=jsonable(owner))
        return ConnectedError(code, describe(exc), status, **extra)
    return ConnectedError(fallback_code, (fallback_message + " " if fallback_message else "") + describe(exc), fallback_status)


def _build(factory: Callable[..., Any], app: str, root: Path, backend: Any) -> Any:
    """Call an adapter factory. The Neyvia adapter gets the web backend, the others the state root."""
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return factory()
    if "backend" in params:
        return factory(**{"backend": backend})
    positional = any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params.values())
    if app == "neyvia" and positional:
        return factory(backend)
    for name in ("root", "state_root", "workspace_root", "base_dir"):
        if name in params:
            return factory(**{name: root})
    return factory(root) if positional else factory()


def _instantiate(module: Any, app: str, root: Path, backend: Any) -> Any:
    for name in ("create_adapter", "build_adapter", "get_adapter", "make_adapter"):
        factory = getattr(module, name, None)
        if callable(factory):
            return _build(factory, app, root, backend)
    for name in (*_CLASS_NAMES[app], "Adapter"):
        cls = getattr(module, name, None)
        if inspect.isclass(cls):
            return _build(cls, app, root, backend)
    for name in ("ADAPTER", "adapter"):
        value = getattr(module, name, None)
        if value is not None and not inspect.ismodule(value) and hasattr(value, "list_sessions"):
            return value
    raise LookupError("it exposes no create_adapter(root) function or adapter class")


_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Thread] = {}


def parallel(calls: dict[str, Callable[[], Any]], timeout: float, guard: str | None = None) -> dict[str, tuple[bool, Any]]:
    """Run adapter calls on daemon threads; a call that overruns ``timeout`` reports a timeout.

    With ``guard``, a call whose previous run is still stuck is not started again.
    """
    results: dict[str, tuple[bool, Any]] = {}
    started: dict[str, threading.Thread] = {}
    for key, fn in calls.items():
        slot = f"{guard}:{key}" if guard else None
        with _INFLIGHT_LOCK:
            if slot and _INFLIGHT.get(slot) is not None and _INFLIGHT[slot].is_alive():
                results[key] = (False, ConnectedError("adapter_busy", "The app is still answering an earlier request.", 503))
                continue

            def target(key: str = key, fn: Callable[[], Any] = fn) -> None:
                try:
                    results[key] = (True, fn())
                except BaseException as exc:  # noqa: BLE001 - reported to the caller
                    results[key] = (False, exc)

            thread = threading.Thread(target=target, name=f"connected-{guard or 'call'}-{key}", daemon=True)
            started[key] = thread
            if slot:
                _INFLIGHT[slot] = thread
        thread.start()
    deadline = time.monotonic() + timeout
    for key, thread in started.items():
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            results[key] = (False, ConnectedError("adapter_timeout", "The app did not answer in time.", 504))
    return results


def bounded(fn: Callable[[], Any], timeout: float, label: str) -> Any:
    ok, value = parallel({"call": fn}, timeout, guard=None)["call"]
    if ok:
        return value
    if isinstance(value, ConnectedError) and value.code == "adapter_timeout":
        raise ConnectedError("adapter_timeout", f"The app did not answer ({label}) in time.", 504)
    raise value


FACTORIES: dict[str, Callable[[Any], Any]] = {}


def register_adapter(app: str, factory: Callable[[Any], Any]) -> None:
    """Register ``factory(backend) -> Adapter`` for every broker of this process.

    It is called lazily, the first time the app is needed; if it raises, the app becomes an
    unavailable source with that reason. ``ConnectedBroker.register_adapter`` does the same
    for one broker.
    """
    FACTORIES[app] = factory


class Registry:
    def __init__(self, root: Path, backend: Any, adapters: dict[str, Any] | None, load_defaults: bool):
        self._root, self._backend = root, backend
        self._adapters: dict[str, Any] = dict(adapters or {})
        self._factories: dict[str, Callable[[Any], Any]] = {}
        self.on_ready: Callable[[str, Any], None] | None = None
        self._load_defaults = load_defaults
        self._failed: dict[str, tuple[float, str]] = {}
        self._availability: dict[str, tuple[float, bool, str | None]] = {}
        self._lock = threading.RLock()

    def register(self, app: str, factory: Callable[[Any], Any]) -> None:
        with self._lock:
            self._factories[app] = factory
            self._failed.pop(app, None)
            self._availability.pop(app, None)

    def loaded(self, app: str) -> Any | None:
        """The adapter if it is already running, without starting it."""
        with self._lock:
            return self._adapters.get(app)

    def get(self, app: str) -> tuple[Any | None, str | None]:
        with self._lock:
            if app in self._adapters:
                return self._adapters[app], None
            factory = self._factories.get(app) or (FACTORIES.get(app) if self._load_defaults else None)
            if factory is None and not self._load_defaults:
                return None, f"No {APP_LABELS[app]} adapter is registered."
            failed = self._failed.get(app)
            if failed and time.monotonic() - failed[0] < _ADAPTER_RETRY_SECONDS:
                return None, failed[1]
            adapter, reason = self._create(app, factory) if factory else self._load(app)
            if adapter is None:
                self._failed[app] = (time.monotonic(), reason or "The adapter could not be loaded.")
                return None, reason
            self._adapters[app] = adapter
            if self.on_ready is not None:
                try:
                    self.on_ready(app, adapter)
                except Exception:  # noqa: BLE001 - wiring an optional hook must not lose the adapter
                    log.exception("could not connect the %s adapter's event sink", app)
            return adapter, None

    def _create(self, app: str, factory: Callable[[Any], Any]) -> tuple[Any | None, str | None]:
        label = APP_LABELS[app]
        try:
            adapter = factory(self._backend)
        except Exception as exc:  # noqa: BLE001
            return None, f"The {label} adapter could not start: {describe(exc)}"
        return self._check(app, adapter)

    @staticmethod
    @_proofs.checked_result(lambda args, kwargs, result: _proofs.check_registry_adapter(kwargs, result))
    def _check(app: str, adapter: Any) -> tuple[Any | None, str | None]:
        label = APP_LABELS[app]
        missing = [method for method in _REQUIRED_METHODS if not callable(getattr(adapter, method, None))]
        if missing:
            return None, f"The {label} adapter is incomplete (missing {', '.join(missing)})."
        if getattr(adapter, "app", app) != app:
            return None, f"The {label} adapter reports a different app ({getattr(adapter, 'app', None)})."
        return adapter, None

    def adapters(self) -> list[Any]:
        with self._lock:
            return list(self._adapters.values())

    def _load(self, app: str) -> tuple[Any | None, str | None]:
        label, name = APP_LABELS[app], _APP_MODULES[app]
        module_name = f"{__package__}.{name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                return None, f"The {label} adapter is not part of this build."
            return None, f"The {label} adapter could not load: {exc}"
        except Exception as exc:  # noqa: BLE001 - a broken adapter must not stop the service
            return None, f"The {label} adapter failed to load: {describe(exc)}"
        try:
            adapter = _instantiate(module, app, self._root, self._backend)
        except Exception as exc:  # noqa: BLE001
            return None, f"The {label} adapter could not start: {describe(exc)}"
        return self._check(app, adapter)

    def availability(self, app: str, *, for_start: bool = False) -> tuple[Any | None, bool, str | None]:
        adapter, reason = self.get(app)
        if adapter is None:
            return None, False, reason
        with self._lock:
            cached = self._availability.get(app)
            if cached and time.monotonic() - cached[0] < _AVAILABILITY_TTL and (cached[1] or not for_start):
                return adapter, cached[1], cached[2]
        # Discovery stays short. Explicit Claude starts tolerate a loaded PC,
        # with two bounded attempts; never retry a session-creation operation.
        startup = for_start and app == 'claude-code'
        for attempt in range(2 if startup else 1):
            try:
                ok, why = bounded(adapter.available, START_AVAILABILITY_SECONDS if startup else 10, "available")
                ok, why = bool(ok), (None if ok else (why or f"{APP_LABELS[app]} is not available on this PC."))
                break
            except Exception as exc:  # noqa: BLE001
                ok, why = False, f"{APP_LABELS[app]} could not be checked: {describe(exc)}"
                if not startup or attempt or getattr(exc, 'code', None) != 'adapter_timeout':
                    break
        with self._lock:
            self._availability[app] = (time.monotonic(), ok, why)
        return adapter, ok, why

    def forget_availability(self) -> None:
        with self._lock:
            self._availability.clear()
