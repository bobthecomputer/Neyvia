"""One long-lived ``codex app-server`` JSON-RPC connection over stdio.

The connection starts lazily, runs with no visible window, and restarts with a
short backoff after a crash. A reader thread routes responses to the waiting
caller by id, notifications to ``on_notification`` and server-initiated
requests to ``on_server_request``. Nothing here knows about sessions or runs:
the adapter owns that. A request that was in flight when the process died is
failed with ``ConnectionLost`` and is never sent again.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from ..subprocess_utils import hidden_windows_subprocess_kwargs
from ..proofs_a_providers import checked, check_process

Trace = Callable[[str, dict[str, Any]], None]

MAX_ERROR_CHARS = 300
READ_ONLY_METHODS = frozenset({"thread/list", "thread/read", "thread/loaded/list", "account/read",
                               "config/read", "model/list", "skills/list", "plugin/installed",
                               "mcpServerStatus/list", "app/list"})


class CodexError(RuntimeError):
    """A Codex operation failed. ``code`` is stable; ``str()`` is safe to show."""

    def __init__(self, code: str, message: str, *, owner: str | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.owner = owner
        self.data = data


class RpcTimeout(CodexError):
    def __init__(self, method: str, seconds: float):
        super().__init__("rpc_timeout", f"Codex did not answer {method} within {seconds:g}s.")


class ConnectionLost(CodexError):
    def __init__(self, message: str = "Codex app-server stopped before confirming this request. It was not resent."):
        super().__init__("app_server_stopped", message)


class RpcError(CodexError):
    def __init__(self, method: str, error: Any):
        rpc_code = error.get("code") if isinstance(error, dict) else None
        raw = str(error.get("message") if isinstance(error, dict) else error or "")
        # Some failures embed a whole HTML error page; never relay that.
        message = " ".join(re.split(r"<\s*(?:!doctype|html|head|body)", raw, maxsplit=1, flags=re.I)[0].split())[:MAX_ERROR_CHARS] or "request failed"
        super().__init__("rpc_error", f"Codex {method} failed: {message}",
                         data=error.get("data") if isinstance(error, dict) else None)
        self.rpc_code = rpc_code
        self.method = method
        self.raw_message = raw


def resolve_command(override: Sequence[str] | None = None) -> list[str] | None:
    """The argv that starts app-server, or None when Codex is not installed."""
    if override:
        command = list(override)
        return command if shutil.which(command[0]) else None
    configured = str(os.environ.get("NEYVIA_CODEX_APP_SERVER_COMMAND") or "").strip()
    if configured:
        return [configured, "app-server", "--stdio"] if shutil.which(configured) else None
    found = next((item for item in (shutil.which(name) for name in ("codex.exe", "codex.cmd", "codex")) if item), None)
    if found and Path(found).suffix.lower() in {'.cmd', '.bat', '.ps1'}:
        # Use the same installed npm entry as bounded Codex judgements. Batch
        # shims are not executable images for hidden CreateProcess launches.
        entry = Path(found).parent / 'node_modules/@openai/codex/bin/codex.js'
        node = shutil.which('node')
        if node and entry.is_file():
            return [node, str(entry), 'app-server', '--stdio']
    return [found, "app-server", "--stdio"] if found else None


def kill_process_tree(process: subprocess.Popen) -> None:
    """Stop the process and its children (the npm shim spawns node, which spawns codex)."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           timeout=10, check=False, **hidden_windows_subprocess_kwargs())
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


class _Pending:
    __slots__ = ("method", "event", "result", "error")

    def __init__(self, method: str) -> None:
        self.method = method
        self.event = threading.Event()
        self.result: Any = None
        self.error: CodexError | None = None


class AppServerConnection:
    """Thread-safe JSON-RPC client for one supervised app-server process."""

    def __init__(
        self,
        command: Callable[[], Sequence[str] | None],
        *,
        on_notification: Callable[[int, str, dict[str, Any]], None],
        on_server_request: Callable[[int, Any, str, dict[str, Any]], None],
        on_lost: Callable[[int], None] | None = None,
        trace: Trace | None = None,
        client_name: str = "neyvia-connected-sessions",
        client_version: str = "1.0",
        initialize_timeout: float = 30.0,
        backoff: Sequence[float] = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0),
        max_start_wait: float = 2.5,
        initialize_params: dict[str, Any] | None = None,
        initialized_notification: bool = True,
        jsonrpc: bool = False,
        environment: dict[str, str] | None = None,
        idle_guard: Callable[[], bool] | None = None,
    ) -> None:
        self._command = command
        self._on_notification = on_notification
        self._on_server_request = on_server_request
        self._on_lost = on_lost
        self._trace = trace
        self._client = (client_name, client_version)
        self._initialize_timeout = initialize_timeout
        self._backoff = tuple(backoff)
        self._max_start_wait = max_start_wait
        self._initialize_params = initialize_params
        self._initialized_notification = initialized_notification
        self._jsonrpc, self._environment = jsonrpc, environment
        self._idle_guard = idle_guard
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[str, _Pending] = {}
        self._process: subprocess.Popen[str] | None = None
        self._generation = 0
        self._alive = False
        self._closing = threading.Event()
        self._failures = 0
        self._started_at = 0.0
        self._next_start_at = 0.0
        self._stderr: list[str] = []
        self.server_info: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def generation(self) -> int:
        return self._generation

    def last_stderr(self) -> list[str]:
        return list(self._stderr)

    def ensure_started(self) -> int:
        """Start (or restart) the process if needed and return its generation."""
        from ..local_network_policy import enabled, LocalOnlyError, register_idle_child
        if enabled():
            raise CodexError("local_only", "Local-only is on. Turn it off in Settings to use Codex.")
        if self._alive:
            return self._generation
        with self._start_lock:
            if self._alive:
                return self._generation
            if self._closing.is_set():
                raise CodexError("app_server_closed", "The Codex connection was closed.")
            wait = self._next_start_at - time.monotonic()
            if wait > self._max_start_wait:
                raise CodexError("app_server_backoff", "Codex app-server keeps stopping; retrying shortly.")
            if wait > 0 and self._closing.wait(wait):
                raise CodexError("app_server_closed", "The Codex connection was closed.")
            argv = self._command()
            if not argv:
                raise CodexError("codex_unavailable", "Codex CLI is not installed on this host.")
            options: dict[str, Any] = {
                "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1,
                "start_new_session": os.name != "nt",
            }
            options.update(hidden_windows_subprocess_kwargs(new_process_group=True))
            check_process(options)
            try:
                process = subprocess.Popen(list(argv), env=self._environment if self._environment is not None else dict(os.environ), **options)
            except LocalOnlyError as exc:
                raise CodexError("local_only", "Local-only is on. Turn it off in Settings to use Codex.") from exc
            except OSError as exc:
                self._register_failure()
                raise CodexError("app_server_start_failed", "Codex app-server could not start. Check the Codex CLI install.") from exc
            with self._lock:
                self._generation += 1
                generation = self._generation
                self._process = process
                self._started_at = time.monotonic()
            if self._idle_guard is not None:
                register_idle_child(process, kind="Codex app server", busy=self.busy,
                                    stop=self.stop_idle)
            threading.Thread(target=self._read_stdout, args=(generation, process), daemon=True,
                             name=f"codex-app-server-out-{generation}").start()
            threading.Thread(target=self._read_stderr, args=(process,), daemon=True,
                             name=f"codex-app-server-err-{generation}").start()
            try:
                info = self._request_on(generation, "initialize", self._initialize_params if self._initialize_params is not None else {
                    "clientInfo": {"name": self._client[0], "title": None, "version": self._client[1]},
                    "capabilities": {"experimentalApi": True, "requestAttestation": False},
                }, self._initialize_timeout)
                if self._initialized_notification:
                    self._write(generation, {"method": "initialized", "params": {}})
            except CodexError:
                self._register_failure()
                kill_process_tree(process)
                raise
            with self._lock:
                self._alive = True
                self.server_info = info if isinstance(info, dict) else {}
            return generation

    def busy(self) -> bool:
        return (bool(self._process is not None and not self._alive)
                or any(p.method not in READ_ONLY_METHODS for p in tuple(self._pending.values()))
                or bool(self._idle_guard and self._idle_guard()))

    def stop_idle(self) -> bool:
        # A pending request or active turn must never be silently interrupted.
        with self._lock:
            if self.busy():
                return False
            process, self._process = self._process, None
            self._alive = False
        if process is not None:
            from ..local_network_policy import stop_child
            stopped = stop_child(process)
            self._fail_pending(ConnectionLost("Local-only is on. The idle Codex app server was stopped."))
            return stopped
        return True

    def close(self) -> None:
        self._closing.set()
        with self._lock:
            process, self._process = self._process, None
            self._alive = False
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        kill_process_tree(process)
        self._fail_pending(ConnectionLost("The Codex connection was closed."))

    def kill(self) -> None:
        """Drop a wedged process; the next request restarts it."""
        with self._lock:
            process = self._process
        if process is not None:
            kill_process_tree(process)

    @checked("providers.rpc.backoff")
    def _register_failure(self) -> None:
        self._failures += 1
        delay = self._backoff[min(self._failures - 1, len(self._backoff) - 1)] if self._backoff else 0.0
        self._next_start_at = time.monotonic() + delay

    # -- requests ----------------------------------------------------------

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = 30.0) -> Any:
        generation = self.ensure_started()
        return self._request_on(generation, method, params or {}, timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write(self.ensure_started(), {"method": method, "params": params or {}})

    @checked("providers.rpc.response")
    def respond(self, generation: int, request_id: Any, result: dict[str, Any]) -> None:
        self._write(generation, {"id": request_id, "result": result})

    def reject(self, generation: int, request_id: Any, message: str, code: int = -32601) -> None:
        self._write(generation, {"id": request_id, "error": {"code": code, "message": message}})

    def _request_on(self, generation: int, method: str, params: dict[str, Any], timeout: float | None) -> Any:
        # Client ids are strings so they can never collide with the numeric
        # ids the server uses for its own requests.
        request_id = f"nv-{next(self._ids)}"
        pending = _Pending(method)
        from ..local_network_policy import transition
        with transition(False):
            with self._lock:
                if generation != self._generation or self._process is None or self._process.poll() is not None:
                    raise ConnectionLost()
                self._pending[request_id] = pending
        try:
            self._write(generation, {"id": request_id, "method": method, "params": params})
        except CodexError:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise RpcTimeout(method, timeout or 0)
        if pending.error is not None:
            raise pending.error
        return pending.result

    def _write(self, generation: int, message: dict[str, Any]) -> None:
        with self._lock:
            process = self._process
            current = self._generation
        if process is None or generation != current or process.poll() is not None or process.stdin is None:
            raise ConnectionLost()
        line = json.dumps({"jsonrpc": "2.0", **message} if self._jsonrpc else message)
        if self._trace:
            self._trace("out", message)
        try:
            with self._write_lock:
                process.stdin.write(line + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise ConnectionLost() from exc

    # -- reader ------------------------------------------------------------

    def _read_stdout(self, generation: int, process: subprocess.Popen) -> None:
        try:
            for raw in process.stdout or ():
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self._route(generation, message)
        except (OSError, ValueError):
            pass
        finally:
            self._handle_exit(generation, process)

    def _read_stderr(self, process: subprocess.Popen) -> None:
        try:
            for raw in process.stderr or ():
                text = raw.strip()
                if text:
                    self._stderr.append(text[-MAX_ERROR_CHARS:])
                    del self._stderr[:-20]
        except (OSError, ValueError):
            pass

    def _route(self, generation: int, message: dict[str, Any]) -> None:
        if self._trace:
            self._trace("in", message)
        method = message.get("method")
        message_id = message.get("id")
        if method is None and message_id is not None:
            with self._lock:
                pending = self._pending.pop(str(message_id), None)
            if pending is None:
                return
            if "error" in message:
                pending.error = RpcError(pending.method, message["error"])
            else:
                pending.result = message.get("result")
            pending.event.set()
            return
        if not isinstance(method, str):
            return
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            if message_id is not None:
                self._on_server_request(generation, message_id, method, params)
            else:
                self._on_notification(generation, method, params)
        except Exception:  # a bad handler must not kill the reader
            if message_id is not None:
                try:
                    self.reject(generation, message_id, "Neyvia could not handle this request.", -32603)
                except CodexError:
                    pass

    def _handle_exit(self, generation: int, process: subprocess.Popen) -> None:
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            kill_process_tree(process)
        with self._lock:
            current = generation == self._generation
            was_alive = current and self._alive
            if current:
                self._alive = False
        if not current:
            return
        lifetime = time.monotonic() - self._started_at
        # A failed start is accounted for by ensure_started itself.
        if was_alive and not self._closing.is_set():
            if lifetime >= 60:
                self._failures = 0
                self._next_start_at = 0.0
            else:
                self._register_failure()
        self._fail_pending(ConnectionLost())
        if was_alive and self._on_lost and not self._closing.is_set():
            try:
                self._on_lost(generation)
            except Exception:
                pass

    def _fail_pending(self, error: CodexError) -> None:
        with self._lock:
            pending, self._pending = list(self._pending.values()), {}
        for item in pending:
            item.error = error
            item.event.set()
