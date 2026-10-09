"""Durable, bounded request queue for controlling the local Neyvia desktop.

Only ``desktop_bridge`` calls the poll/complete functions. Remote callers may
enqueue allowlisted backend commands through the authenticated web route.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


QUEUE_LIMIT = 128
MAX_INFLIGHT = 4
RESERVED_CONTROL_INFLIGHT = 1
MAX_CONTROL_PENDING = 4
_PRIORITY_CONTROL_COMMAND = "cancel_agent_chat_command"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
CALLER_TIMEOUT_SECONDS = 3600.0
CHAT_TIMEOUT_MARGIN_SECONDS = 120.0
MAX_EXPLICIT_TIMEOUT_SECONDS = 7200.0
QUEUED_TIMEOUT_SECONDS = 180.0
DESKTOP_STALE_SECONDS = 35.0
POLL_SECONDS = 15.0
HEARTBEAT_SECONDS = 3.0
TERMINAL_RETENTION_SECONDS = 600.0
MAX_IDEMPOTENCY_TOMBSTONES = 4096
RETAINED_RESULTS = 64

# These operations expose or mutate provider credentials and stay on the PC.
_PC_ONLY_COMMANDS = frozenset({
    "get_provider_auth_queue_command", "start_provider_auth_queue_command",
    "advance_provider_auth_queue_command", "skip_provider_auth_queue_item_command",
    "cancel_provider_auth_queue_command", "save_provider_auth_command",
    "get_hermes_anthropic_auth_status_command", "start_hermes_anthropic_oauth_command",
    "delete_provider_auth_command", "set_provider_api_key_command",
    "save_provider_api_key_command", "delete_provider_api_key_command",
})
_FORBIDDEN_COMMANDS = frozenset({
    "desktop_controller_poll_command", "desktop_controller_complete_command",
})
_SAFE_PRESENCE_COMMANDS = frozenset({
    "get_provider_secret_presence_command",
    "has_telegram_bot_token_command",
    "has_openclaw_gateway_token",
})


def _canonical_root(root: Path) -> Path:
    resolved = str(root.expanduser().resolve())
    if os.name == "nt":
        if resolved.startswith("\\\\?\\UNC\\"):
            resolved = "\\\\" + resolved[8:]
        elif resolved.startswith("\\\\?\\"):
            resolved = resolved[4:]
        resolved = os.path.normcase(os.path.normpath(resolved))
    return Path(resolved)


def _db_path(root: Path) -> Path:
    return _canonical_root(root) / ".agent_control" / "desktop_controller.sqlite3"


def _connect(root: Path) -> sqlite3.Connection:
    path = _db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=2000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS controller_sessions (
          root TEXT PRIMARY KEY, session_id TEXT NOT NULL, device_name TEXT NOT NULL,
          process_id INTEGER NOT NULL, process_created TEXT NOT NULL,
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS controller_requests (
          root TEXT NOT NULL, request_id TEXT NOT NULL, content_hash TEXT NOT NULL,
          command TEXT NOT NULL, payload_json TEXT NOT NULL,
          session_id TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
          updated_at REAL NOT NULL, result_json TEXT, error TEXT,
          PRIMARY KEY(root, request_id)
        );
        CREATE INDEX IF NOT EXISTS controller_requests_queue
          ON controller_requests(root, session_id, state, created_at);
    """)
    return db


def _payload_object(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Desktop controller payload must be an object.")
    nested = payload.get("payload")
    return nested if isinstance(nested, dict) else payload


def _request_wait_timeout_seconds(command: str, payload: dict[str, Any]) -> float | None:
    """Return an opt-in caller budget; active chats have no default deadline."""
    if command == "send_agent_chat_command":
        raw_requested = payload.get("runtimeTimeoutSeconds")
        if raw_requested is None:
            raw_requested = payload.get("runtime_timeout_seconds")
        if raw_requested is None:
            return None
        try:
            requested = float(raw_requested)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(requested) or requested <= 0:
            return None
        return max(15.0, requested) + CHAT_TIMEOUT_MARGIN_SECONDS
    try:
        requested = float(payload.get("timeoutSeconds") or payload.get("timeout_seconds") or 0)
    except (TypeError, ValueError):
        requested = 0.0
    if requested > 0:
        return min(MAX_EXPLICIT_TIMEOUT_SECONDS, max(30.0, requested)) + CHAT_TIMEOUT_MARGIN_SECONDS
    return CALLER_TIMEOUT_SECONDS


def _json(value: Any, limit: int, label: str) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        size = len(encoded.encode("utf-8", errors="strict"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Desktop controller {label} is not valid JSON data.") from exc
    if size > limit:
        raise ValueError(f"Desktop controller {label} exceeds the size limit.")
    return encoded


def _contains_sensitive_keys(value: Any) -> bool:
    sensitive = {
        "apikey", "providerapikey", "accesstoken", "refreshtoken", "idtoken",
        "oauthaccesstoken", "oauthrefreshtoken", "providertoken", "bearertoken",
        "clientsecret", "providersecret", "secret", "credential", "credentials",
        "password", "authorization", "privatekey", "signingkey",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in sensitive or _contains_sensitive_keys(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_keys(item) for item in value)
    return False


def _compact_terminal_rows(db: sqlite3.Connection, root_key: str, now: float) -> None:
    """Keep recent result data small while retaining replay hashes for ten minutes."""
    db.execute("UPDATE controller_requests SET state='expired',payload_json='',result_json=NULL,error=NULL,updated_at=? "
               "WHERE root=? AND state='queued' AND updated_at<?",
               (now, root_key, now - QUEUED_TIMEOUT_SECONDS))
    # Active chats have no automatic elapsed-time expiry. Explicit finite runtime
    # budgets remain opt-in; other claimed operations retain their existing bound.
    claimed_rows = db.execute(
        "SELECT request_id, command, payload_json, updated_at FROM controller_requests "
        "WHERE root=? AND state='claimed'",
        (root_key,),
    ).fetchall()
    for row in claimed_rows:
        try:
            stored_payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            stored_payload = {}
        request_payload = _payload_object(stored_payload) if isinstance(stored_payload, dict) else {}
        budget = _request_wait_timeout_seconds(str(row["command"]), request_payload)
        if budget is not None and now - float(row["updated_at"]) > budget:
            db.execute(
                "UPDATE controller_requests SET state='expired',payload_json='',result_json=NULL,error=NULL,updated_at=? "
                "WHERE root=? AND request_id=? AND state='claimed'",
                (now, root_key, row["request_id"]),
            )
    db.execute("DELETE FROM controller_requests WHERE root=? AND state IN ('done','failed','expired') AND updated_at<?",
               (root_key, now - TERMINAL_RETENTION_SECONDS))
    rows = db.execute("SELECT request_id FROM controller_requests WHERE root=? AND state IN ('done','failed') "
                      "ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                      (root_key, RETAINED_RESULTS)).fetchall()
    for row in rows:
        db.execute("UPDATE controller_requests SET state='expired',payload_json='',result_json=NULL,error=NULL,updated_at=? "
                   "WHERE root=? AND request_id=?", (now, root_key, row["request_id"]))


def _windows_parent_identity() -> dict[str, Any]:
    """Find the actual Neyvia Tauri parent and bind to PID plus creation time."""
    if os.name != "nt":
        raise RuntimeError("The desktop controller is available only to the Windows Neyvia desktop.")

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260),
        ]

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle_t = ctypes.c_void_p
    bool_t = ctypes.c_int
    dword_t = ctypes.c_ulong
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.CreateToolhelp32Snapshot.argtypes = [dword_t, dword_t]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [dword_t, bool_t, dword_t]
    kernel.Process32FirstW.argtypes = [handle_t, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32FirstW.restype = bool_t
    kernel.Process32NextW.argtypes = [handle_t, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.restype = bool_t
    kernel.CloseHandle.argtypes = [handle_t]
    kernel.CloseHandle.restype = bool_t
    kernel.GetProcessTimes.argtypes = [handle_t, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel.GetProcessTimes.restype = bool_t
    kernel.QueryFullProcessImageNameW.argtypes = [handle_t, dword_t, ctypes.POINTER(ctypes.c_wchar), ctypes.POINTER(dword_t)]
    kernel.QueryFullProcessImageNameW.restype = bool_t
    snap = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snap or snap == invalid:
        raise RuntimeError("Could not inspect the Neyvia desktop process tree.")
    parents: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), str(entry.szExeFile))
            ok = kernel.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snap)

    pid = os.getppid()
    seen: set[int] = set()
    candidates: list[tuple[int, str]] = []
    while pid and pid not in seen:
        seen.add(pid)
        parent, image = parents.get(pid, (0, ""))
        if image.lower() == "neyvia-desktop.exe":
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                raise RuntimeError("Could not validate the Neyvia desktop process.")
            try:
                image_buffer = ctypes.create_unicode_buffer(32768)
                image_length = dword_t(len(image_buffer))
                if not kernel.QueryFullProcessImageNameW(handle, 0, image_buffer, ctypes.byref(image_length)):
                    raise RuntimeError("Could not validate the Neyvia desktop executable path.")
                executable_path = str(Path(image_buffer.value).resolve())
                if Path(executable_path).name.lower() != "neyvia-desktop.exe":
                    raise RuntimeError("The parent process image does not match the Neyvia desktop executable.")
                creation, exit_time, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
                if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                    raise RuntimeError("Could not validate the Neyvia desktop process start time.")
                started = (int(creation.high) << 32) | int(creation.low)
            finally:
                kernel.CloseHandle(handle)
            candidates.append((pid, executable_path, str(started)))
        pid = parent
    if candidates:
        install_roots = [os.environ.get("LOCALAPPDATA", "") and str(Path(os.environ["LOCALAPPDATA"]) / "Programs"),
                         os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
        install_roots = [os.path.normcase(os.path.abspath(path)) for path in install_roots if path]
        def is_installed(path: str, base: str) -> bool:
            try:
                return os.path.commonpath([os.path.normcase(path), base]) == base
            except ValueError:
                return False
        installed = [item for item in candidates if any(is_installed(item[1], base) for base in install_roots)]
        selected = installed[0] if installed else candidates[0]
        return {"processId": selected[0], "processCreated": selected[2], "deviceName": socket.gethostname()}
    raise RuntimeError("This controller request did not originate from the Neyvia desktop process.")


def _identity_for_test(root: Path, process_id: int, process_created: str, device_name: str = "test-device") -> dict[str, Any]:
    """Explicit test seam; production entry points never accept caller identity."""
    return {"processId": int(process_id), "processCreated": str(process_created), "deviceName": str(device_name)}


def _windows_process_is_alive(process_id: int, process_created: str) -> bool:
    if os.name != "nt":
        return False

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle_t, dword_t, bool_t = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int
    kernel.OpenProcess.argtypes = [dword_t, bool_t, dword_t]
    kernel.OpenProcess.restype = handle_t
    kernel.GetProcessTimes.argtypes = [handle_t, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel.GetProcessTimes.restype = bool_t
    kernel.GetExitCodeProcess.argtypes = [handle_t, ctypes.POINTER(dword_t)]
    kernel.GetExitCodeProcess.restype = bool_t
    kernel.CloseHandle.argtypes = [handle_t]
    kernel.CloseHandle.restype = bool_t
    handle = kernel.OpenProcess(0x1000, False, int(process_id))
    if not handle:
        return False
    try:
        creation, exit_time, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        exit_code = dword_t()
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return False
        started = str((int(creation.high) << 32) | int(creation.low))
        return started == str(process_created) and bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and int(exit_code.value) == 259
    finally:
        kernel.CloseHandle(handle)


def _session(root: Path, identity: dict[str, Any], now: float) -> str:
    root = _canonical_root(root)
    root_key = str(root)
    db = _connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM controller_sessions WHERE root=?", (root_key,)).fetchone()
        same_process = bool(row and int(row["process_id"]) == int(identity["processId"]) and row["process_created"] == str(identity["processCreated"]))
        if same_process and now - float(row["updated_at"]) <= DESKTOP_STALE_SECONDS:
            sid = str(row["session_id"])
        else:
            sid = str(uuid.uuid4())
            if row:
                db.execute("UPDATE controller_requests SET state='failed',payload_json='',error='Desktop controller session expired.',updated_at=? WHERE root=? AND session_id=? AND state IN ('queued','claimed')",
                           (now, root_key, row["session_id"]))
        db.execute("""INSERT INTO controller_sessions(root,session_id,device_name,process_id,process_created,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(root) DO UPDATE SET session_id=excluded.session_id,
          device_name=excluded.device_name,process_id=excluded.process_id,
          process_created=excluded.process_created,updated_at=excluded.updated_at""",
          (root_key, sid, str(identity["deviceName"]), int(identity["processId"]), str(identity["processCreated"]), now))
        db.commit()
        return sid
    finally:
        db.close()


def _poll_with_identity(root: Path, payload: dict[str, Any] | None, identity: dict[str, Any], poll_seconds: float = POLL_SECONDS) -> dict[str, Any]:
    root = _canonical_root(root)
    started = time.monotonic()
    deadline = started + max(0.0, min(float(poll_seconds), POLL_SECONDS))
    next_heartbeat = started
    root_key = str(root)
    session_id = _session(root, identity, time.time())
    while True:
        now = time.time()
        db = _connect(root)
        try:
            db.execute("BEGIN IMMEDIATE")
            if time.monotonic() >= next_heartbeat:
                db.execute("UPDATE controller_sessions SET updated_at=? WHERE root=? AND session_id=?", (now, root_key, session_id))
                next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            _compact_terminal_rows(db, root_key, now)
            control_inflight = int(db.execute(
                "SELECT COUNT(*) FROM controller_requests WHERE root=? AND session_id=? AND state='claimed' AND command=?",
                (root_key, session_id, _PRIORITY_CONTROL_COMMAND),
            ).fetchone()[0])
            regular_inflight = int(db.execute(
                "SELECT COUNT(*) FROM controller_requests WHERE root=? AND session_id=? AND state='claimed' AND command<>?",
                (root_key, session_id, _PRIORITY_CONTROL_COMMAND),
            ).fetchone()[0])

            # Stop must still be deliverable when all ordinary slots are busy
            # with long-running chats. Give this exact control command one
            # reserved slot and claim it before regular queued work.
            row = None
            if control_inflight < RESERVED_CONTROL_INFLIGHT:
                row = db.execute(
                    "SELECT * FROM controller_requests WHERE root=? AND session_id=? AND state='queued' AND command=? ORDER BY created_at LIMIT 1",
                    (root_key, session_id, _PRIORITY_CONTROL_COMMAND),
                ).fetchone()
            if row is None and regular_inflight < MAX_INFLIGHT:
                row = db.execute(
                    "SELECT * FROM controller_requests WHERE root=? AND session_id=? AND state='queued' AND command<>? ORDER BY created_at LIMIT 1",
                    (root_key, session_id, _PRIORITY_CONTROL_COMMAND),
                ).fetchone()
            if row:
                db.execute("UPDATE controller_requests SET state='claimed',updated_at=? WHERE root=? AND request_id=? AND state='queued'", (now, root_key, row["request_id"]))
                db.commit()
                return {"sessionId": session_id, "deviceName": str(identity["deviceName"]), "requests":[{
                    "requestId": row["request_id"], "command": row["command"], "payload": json.loads(row["payload_json"])
                }]}
            db.commit()
        finally:
            db.close()
        if time.monotonic() >= deadline:
            return {"sessionId": session_id, "deviceName": str(identity["deviceName"]), "requests": []}
        pause = min(0.25, max(0.02, deadline - time.monotonic()))
        time.sleep(pause)


def desktop_poll(root: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Trusted bridge-only poll; a Python subprocess must descend from Tauri."""
    _payload_object(payload)
    return _poll_with_identity(root, payload, _windows_parent_identity())


def _complete_with_identity(root: Path, payload: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    args = _payload_object(payload)
    session_id = str(args.get("sessionId") or "")
    request_id = str(args.get("requestId") or "")
    if not session_id or not request_id or not isinstance(args.get("ok"), bool):
        raise ValueError("Desktop completion requires sessionId, requestId, and boolean ok.")
    if args.get("ok") and _contains_sensitive_keys(args.get("data")):
        args = {**args, "ok": False, "data": None,
                "error": "Desktop result blocked because it contained credential fields."}
    data_json = _json(args.get("data"), MAX_RESULT_BYTES, "result") if args.get("ok") else None
    error = str(args.get("error") or "Desktop command failed.") if not args.get("ok") else None
    if error and len(error.encode("utf-8", errors="replace")) > 16_384:
        error = error[:16_384]
    root = _canonical_root(root)
    root_key = str(root)
    now = time.time()
    db = _connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        session = db.execute("SELECT * FROM controller_sessions WHERE root=? AND session_id=?", (root_key, session_id)).fetchone()
        if not session or int(session["process_id"]) != int(identity["processId"]) or session["process_created"] != str(identity["processCreated"]):
            raise RuntimeError("Desktop controller session is expired or belongs to another process.")
        row = db.execute("SELECT * FROM controller_requests WHERE root=? AND request_id=?", (root_key, request_id)).fetchone()
        if not row or row["session_id"] != session_id or row["state"] != "claimed":
            raise RuntimeError("Desktop controller request is unknown, already completed, or not claimed by this session.")
        db.execute("UPDATE controller_requests SET state=?,updated_at=?,payload_json='',result_json=?,error=? WHERE root=? AND request_id=?",
                   ("done" if args["ok"] else "failed", now, data_json, error, root_key, request_id))
        _compact_terminal_rows(db, root_key, now)
        db.commit()
        return {"requestId": request_id, "ok": bool(args["ok"]), "data": args.get("data") if args["ok"] else None, "error": error}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def desktop_complete(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Trusted bridge-only completion bound to the original Tauri process."""
    return _complete_with_identity(root, payload, _windows_parent_identity())


def _controller_status(root: Path, process_alive: Any) -> dict[str, Any]:
    root = _canonical_root(root)
    now = time.time()
    db = _connect(root)
    try:
        row = db.execute("SELECT * FROM controller_sessions WHERE root=?", (str(root),)).fetchone()
        if not row:
            return {"online": False, "deviceName": None, "sessionId": None, "root": str(root), "processId": None, "updatedAt": None}
        online = now - float(row["updated_at"]) <= DESKTOP_STALE_SECONDS and bool(process_alive(int(row["process_id"]), str(row["process_created"])))
        if not online:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE controller_requests SET state='expired',payload_json='',result_json=NULL,error=NULL,updated_at=? "
                       "WHERE root=? AND session_id=? AND state IN ('queued','claimed')",
                       (now, str(root), row["session_id"]))
            _compact_terminal_rows(db, str(root), now)
            db.commit()
        return {"online": online, "deviceName": row["device_name"] if online else None,
                "sessionId": row["session_id"] if online else None, "root": str(root),
                "processId": int(row["process_id"]) if online else None, "updatedAt": float(row["updated_at"])}
    finally:
        db.close()


def controller_status(root: Path) -> dict[str, Any]:
    return _controller_status(root, _windows_process_is_alive)


def _controller_status_for_test(root: Path) -> dict[str, Any]:
    return _controller_status(root, lambda _pid, _created: True)


def _submit_controller_request(root: Path, command: str, payload: dict[str, Any], request_id: str, process_alive: Any) -> Any:
    """Queue one idempotent remote request and wait for the real desktop result."""
    root = _canonical_root(root)
    command = str(command or "").strip()
    request_id = str(request_id or "").strip()
    if not command or command in _FORBIDDEN_COMMANDS or command in _PC_ONLY_COMMANDS:
        raise ValueError("This desktop command is not available through remote control.")
    command_lower = command.lower()
    if command not in _SAFE_PRESENCE_COMMANDS and any(term in command_lower for term in ("token", "secret", "credential", "api_key", "api-key", "provider_auth")):
        raise ValueError("Credential and token management commands are available on the PC only.")
    if len(request_id) < 8 or len(request_id) > 128:
        raise ValueError("Desktop controller requestId must contain 8 to 128 characters.")
    if not isinstance(payload, dict):
        raise ValueError("Desktop controller payload must be an object.")
    if _contains_sensitive_keys(payload):
        raise ValueError("Credential and token fields are available on the PC only.")
    request_limit = 29 * 1024 * 1024 if command == "inspect_skill_import_command" else MAX_REQUEST_BYTES
    payload_json = _json(payload, request_limit, "request")
    content_hash = hashlib.sha256((command + "\n" + payload_json).encode("utf-8")).hexdigest()
    root_key = str(root)
    wait_budget = _request_wait_timeout_seconds(command, payload)
    deadline = time.monotonic() + wait_budget if wait_budget is not None else None
    now = time.time()
    db = _connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        _compact_terminal_rows(db, root_key, now)
        row = db.execute("SELECT * FROM controller_requests WHERE root=? AND request_id=?", (root_key, request_id)).fetchone()
        if row:
            if row["content_hash"] != content_hash:
                raise ValueError("Desktop controller requestId was already used with different content.")
            session_id = row["session_id"]
        else:
            if command == _PRIORITY_CONTROL_COMMAND:
                pending_control = int(db.execute(
                    "SELECT COUNT(*) FROM controller_requests WHERE root=? AND state IN ('queued','claimed') AND command=?",
                    (root_key, _PRIORITY_CONTROL_COMMAND),
                ).fetchone()[0])
                if pending_control >= MAX_CONTROL_PENDING:
                    raise RuntimeError("Desktop controller cancellation queue is full.")
            else:
                regular_count = int(db.execute(
                    "SELECT COUNT(*) FROM controller_requests WHERE root=? AND state IN ('queued','claimed') AND command<>?",
                    (root_key, _PRIORITY_CONTROL_COMMAND),
                ).fetchone()[0])
                if regular_count >= QUEUE_LIMIT:
                    raise RuntimeError("Desktop controller queue is full.")
            tombstones = int(db.execute("SELECT COUNT(*) FROM controller_requests WHERE root=? AND state='expired'", (root_key,)).fetchone()[0])
            if tombstones >= MAX_IDEMPOTENCY_TOMBSTONES:
                raise RuntimeError("Desktop controller idempotency retention is full; retry after older request IDs expire.")
            session = db.execute("SELECT * FROM controller_sessions WHERE root=?", (root_key,)).fetchone()
            if not session or now - float(session["updated_at"]) > DESKTOP_STALE_SECONDS or not process_alive(int(session["process_id"]), str(session["process_created"])):
                raise RuntimeError("The Neyvia desktop controller is offline or expired.")
            session_id = str(session["session_id"])
            db.execute("INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?, 'queued',?,?)",
                       (root_key, request_id, content_hash, command, payload_json, session_id, now, now))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    while deadline is None or time.monotonic() < deadline:
        now = time.time()
        db = _connect(root)
        try:
            session = db.execute("SELECT * FROM controller_sessions WHERE root=? AND session_id=?", (root_key, session_id)).fetchone()
            row = db.execute("SELECT * FROM controller_requests WHERE root=? AND request_id=?", (root_key, request_id)).fetchone()
            if not row:
                raise RuntimeError("Desktop controller request expired before completion.")
            if row["state"] == "done":
                return json.loads(row["result_json"] or "null")
            if row["state"] == "failed":
                raise RuntimeError(str(row["error"] or "Desktop command failed."))
            if row["state"] == "expired":
                raise RuntimeError("Desktop controller result expired; this requestId will not be re-executed.")
            if not session or now - float(session["updated_at"]) > DESKTOP_STALE_SECONDS or not process_alive(int(session["process_id"]), str(session["process_created"])):
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE controller_requests SET state='expired',payload_json='',result_json=NULL,error=NULL,updated_at=? "
                           "WHERE root=? AND session_id=? AND state IN ('queued','claimed')",
                           (now, root_key, session_id))
                db.commit()
                raise RuntimeError("The Neyvia desktop controller expired before completing the request.")
        finally:
            db.close()
        # A bounded sleep keeps the open-ended chat relay responsive to completion
        # and liveness changes without spinning on SQLite while the model works.
        time.sleep(0.25 if deadline is None else 0.15)
    raise TimeoutError("Desktop controller timed out; request outcome may still be pending.")


def submit_controller_request(root: Path, command: str, payload: dict[str, Any], request_id: str) -> Any:
    return _submit_controller_request(root, command, payload, request_id, _windows_process_is_alive)


def _submit_for_test(root: Path, command: str, payload: dict[str, Any], request_id: str) -> Any:
    return _submit_controller_request(root, command, payload, request_id, lambda _pid, _created: True)
