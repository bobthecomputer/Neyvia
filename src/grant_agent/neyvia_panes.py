"""The new shell's file, artifact and terminal panes (``pane.show``).

User side: POST /api/ui/panes {op, args}, the terminal's output stream at GET /api/ui/panes/terminal,
and sandboxed HTML artifacts at GET /api/ui/artifact/<token>/<path>. Bot side: ``neyvia.pane.show``
opens a pane; ``neyvia.terminal.list`` / ``neyvia.terminal.read`` let a model see what Paul's terminals
show. A model never types into a terminal: ``pane.show {kind: "terminal", target: "<command>"}`` puts the
command on the prompt line and Paul presses Enter.

Files go through the Files app's guard (Home, the workspace, Notes, project folders; the live Neyvia tree
stays protected). Saving needs the hash the editor loaded, so a change made meanwhile by an agent or
another window is never overwritten silently.
"""
from __future__ import annotations

import atexit
import difflib
import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .ui_command_bus import bus_for
from .subprocess_utils import hidden_windows_subprocess_kwargs

TEXT = {"type": "string"}
DEFINITIONS = [
    ("pane.observe", "Read the fresh mounted pane, runtime and content observation acknowledged by the renderer.",
     {"eventId": TEXT}, []),
    ("pane.state", "Read requested pane and actual renderer observation; queued events are unverified.", {}, []),
    ("terminal.list", "List the terminals open in Neyvia's terminal pane: id, folder, shell, alive, last output time.", {}, []),
    ("terminal.read", "Read the recent output of one of Paul's terminals (plain text, last `chars` characters, default 4000). "
                      "To suggest a command, open pane.show {kind: 'terminal', target: '<command>'}: it is typed, Paul presses Enter.",
     {"id": TEXT, "chars": {"type": "integer"}}, ["id"]),
]

MAX_EDIT_BYTES = 2 * 1024 * 1024
MAX_TERMINALS = 8
BUFFER_CHARS = 512 * 1024
TOKENS_KEY = "panes:artifact-tokens"
ARTIFACT_PREFIX = "/api/ui/artifact/"
HTML_EXT = {".html", ".htm"}
MARKDOWN_EXT = {".md", ".markdown", ".mdx"}


def _guard(root, value) -> Path:
    from .neyvia_files_tools import guard
    return guard(root, value)


def _git(cwd: Path, *args, timeout=10) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=timeout, **hidden_windows_subprocess_kwargs())


# ---- files --------------------------------------------------------------------------------------

def _decode(data: bytes):
    """(text, bom, eol) for UTF-8 text, or None for binary."""
    if b"\x00" in data[:8192]:
        return None
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data[3 if bom else 0:].decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            return None
    crlf, lf = text.count("\r\n"), text.count("\n")
    eol = "crlf" if crlf and crlf * 2 >= lf else "lf"
    return text.replace("\r\n", "\n"), bom, eol


def _git_info(path: Path) -> dict:
    """Repository root, the path inside it and its short status; {} outside git."""
    folder = path if path.is_dir() else path.parent
    try:
        top = _git(folder, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return {}
    if top.returncode:
        return {}
    repo = Path(top.stdout.decode("utf-8", "replace").strip()).resolve()
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return {}
    status = _git(repo, "status", "--porcelain=v1", "--", relative)
    code = status.stdout.decode("utf-8", "replace")[:2] if not status.returncode else ""
    head = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD")
    return {"repo": str(repo), "relative": relative, "status": code.strip() or "clean",
            "tracked": code != "??", "hasHead": head.returncode == 0}


def read_file(root, args) -> dict:
    path = _guard(root, args.get("path"))
    if not path.exists():
        return {"ok": False, "status": "missing", "error": "That file doesn't exist any more", "path": str(path)}
    if path.is_dir():
        return {"ok": True, "path": str(path), "kind": "folder", "name": path.name or str(path)}
    info = path.stat()
    from .neyvia_files_tools import open_with
    base = {"ok": True, "path": str(path), "name": path.name, "kind": "file", "size": info.st_size,
            "modified": info.st_mtime, "openWith": open_with(root, path, False)}
    if info.st_size > MAX_EDIT_BYTES:
        return {**base, "editable": False, "reason": "Too big to edit here (over 2 MB)", "git": _git_info(path)}
    data = path.read_bytes()
    decoded = _decode(data)
    if decoded is None:
        return {**base, "editable": False, "binary": True, "reason": "Not a text file", "hash": hashlib.sha256(data).hexdigest()}
    text, bom, eol = decoded
    return {**base, "editable": True, "text": text, "bom": bom, "eol": eol, "hash": hashlib.sha256(data).hexdigest(),
            "git": _git_info(path)}


def write_file(root, args) -> dict:
    path = _guard(root, args.get("path"))
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text is required")
    base_hash = str(args.get("baseHash") or "")
    exists = path.is_file()
    if exists:
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        if current != base_hash:
            return {"ok": False, "status": "conflict", "error": "This file changed on disk since you opened it.",
                    "currentHash": current, "path": str(path)}
    elif base_hash:
        return {"ok": False, "status": "conflict", "error": "This file was moved or deleted since you opened it.", "path": str(path)}
    elif not path.parent.is_dir():
        raise ValueError("The folder doesn't exist")
    body = text.replace("\r\n", "\n")
    if args.get("eol") == "crlf":
        body = body.replace("\n", "\r\n")
    data = (b"\xef\xbb\xbf" if args.get("bom") else b"") + body.encode("utf-8")
    if len(data) > MAX_EDIT_BYTES:
        raise ValueError("Too big to save from here (over 2 MB)")
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.neyvia-save")
    temp.write_bytes(data)
    try:
        if exists:
            shutil.copymode(path, temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    bus_for(root).emit("files.changed", {"op": "save", "by": "ui", "paths": [str(path)]})
    from .neyvia_outputs import publish, failure
    from .neyvia_workspace_tools import workspace_for
    try:
        publication = publish(workspace_for(root), {"path": str(path), "metadata": {"producer": "file-editor"}})
    except (OSError, ValueError) as exc:
        publication = failure("publication_failed", str(exc))
    return {"ok": True, "path": str(path), "hash": digest, "size": len(data), "modified": path.stat().st_mtime,
            "git": _git_info(path), "publication": publication}


def diff_file(root, args) -> dict:
    """Unified diff of the file (or the editor's unsaved text) against the last commit."""
    path = _guard(root, args.get("path"))
    git = _git_info(path)
    if not git:
        return {"ok": True, "path": str(path), "git": {}, "patch": "", "reason": "This file is not in a git repository"}
    old = ""
    if git["tracked"] and git["hasHead"]:
        shown = _git(Path(git["repo"]), "show", f"HEAD:{git['relative']}")
        if shown.returncode == 0:
            decoded = _decode(shown.stdout)
            if decoded is None:
                return {"ok": True, "path": str(path), "git": git, "patch": "", "binary": True, "reason": "Binary file"}
            old = decoded[0]
    if isinstance(args.get("text"), str):
        new = args["text"].replace("\r\n", "\n")
    elif path.is_file():
        decoded = _decode(path.read_bytes())
        if decoded is None:
            return {"ok": True, "path": str(path), "git": git, "patch": "", "binary": True, "reason": "Binary file"}
        new = decoded[0]
    else:
        new = ""
    rel = git["relative"]
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=3))
    header = [f"diff --git a/{rel} b/{rel}"] + (["new file mode 100644"] if not git["tracked"] or not git["hasHead"] else [])
    patch = "\n".join(header + lines) if lines else ""
    return {"ok": True, "path": str(path), "git": git, "patch": patch,
            "against": "the last commit" if git["tracked"] and git["hasHead"] else "nothing (new file)",
            "unsaved": isinstance(args.get("text"), str)}


# ---- artifacts ----------------------------------------------------------------------------------

def open_artifact(root, args) -> dict:
    """What the artifact pane shows for a file an agent produced: html (sandboxed page), markdown, image, pdf or text."""
    path = _guard(root, args.get("path"))
    if not path.is_file():
        return {"ok": False, "status": "missing", "error": "That file doesn't exist", "path": str(path)}
    suffix = path.suffix.lower()
    from .neyvia_files_tools import IMAGE_EXT
    base = {"ok": True, "path": str(path), "name": path.name, "size": path.stat().st_size, "modified": path.stat().st_mtime,
            "version": stat_artifact(root, args)["version"]}
    if suffix in HTML_EXT:
        bus = bus_for(root)
        tokens = dict(bus.get(TOKENS_KEY, {}) or {})
        folder = str(path.parent)
        token = next((key for key, value in tokens.items() if value == folder), None)
        if not token:
            token = secrets.token_urlsafe(18)
            tokens[token] = folder
            tokens = dict(list(tokens.items())[-50:])
            bus.put(TOKENS_KEY, tokens)
        return {**base, "kind": "html", "url": f"{ARTIFACT_PREFIX}{token}/{path.name}"}
    if suffix == ".pdf":
        return {**base, "kind": "pdf"}
    if suffix in IMAGE_EXT:
        return {**base, "kind": "image"}
    if path.stat().st_size > MAX_EDIT_BYTES:
        return {**base, "kind": "other", "reason": "Too big to show here"}
    decoded = _decode(path.read_bytes())
    if decoded is None:
        return {**base, "kind": "other", "reason": "Neyvia can't show this kind of file yet"}
    return {**base, "kind": "markdown" if suffix in MARKDOWN_EXT else "text", "text": decoded[0]}


def stat_artifact(root, args) -> dict:
    """A cheap change marker for the live preview: no file content is read or sent.

    An HTML page also changes when a stylesheet, script or image next to it does, so its marker
    covers the files in its folder (and one level of subfolders), bounded."""
    path = _guard(root, args.get("path"))
    if not path.is_file():
        return {"ok": False, "status": "missing", "error": "That file doesn't exist", "path": str(path)}
    info = path.stat()
    newest, size, count = info.st_mtime_ns, info.st_size, 1
    if path.suffix.lower() in HTML_EXT:
        seen = 0
        for entry in path.parent.iterdir():
            if entry.name.startswith(".") or entry.name == "node_modules":
                continue
            candidates = [entry]
            if entry.is_dir():
                candidates = [child for child in list(entry.iterdir())[:100] if child.is_file()]
            for item in candidates:
                if not item.is_file() or item == path:
                    continue
                seen += 1
                if seen > 300:
                    break
                try:
                    detail = item.stat()
                except OSError:
                    continue
                newest, size, count = max(newest, detail.st_mtime_ns), size + detail.st_size, count + 1
            if seen > 300:
                break
    return {"ok": True, "path": str(path), "version": f"{newest}-{size}-{count}", "modified": newest / 1e9, "size": size}


def serve_artifact(root, handler, parsed) -> None:
    """GET /api/ui/artifact/<token>/<path>: an HTML artifact and the files next to it, in an opaque origin."""
    rest = parsed.path[len(ARTIFACT_PREFIX):]
    token, _, relative = rest.partition("/")
    folder = (bus_for(root).get(TOKENS_KEY, {}) or {}).get(token)
    if not folder or not Path(folder).is_dir():
        return _send(handler, 404, b"This artifact link is not valid any more. Open it again from Neyvia.", "text/plain; charset=utf-8")
    base = Path(folder).resolve()
    target = (base / unquote(relative)).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return _send(handler, 403, b"Outside the artifact's folder", "text/plain")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return _send(handler, 404, b"Not found", "text/plain")
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    kind = {".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm"}.get(target.suffix.lower(), kind)
    if kind.startswith("text/") and "charset" not in kind:
        kind += "; charset=utf-8"
    return _send(handler, 200, target.read_bytes(), kind)


def _send(handler, status_code, body: bytes, kind: str) -> None:
    handler.send_response(status_code)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    # Opaque origin: the page keeps its scripts, never Neyvia's cookies, storage or API.
    handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.close_connection = True
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(body)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass


# ---- terminals ----------------------------------------------------------------------------------

def default_shell() -> list[str]:
    if os.name == "nt":
        for name, args in (("pwsh", ["-NoLogo"]), ("powershell", ["-NoLogo"]), ("cmd", [])):
            found = shutil.which(name)
            if found:
                return [found, *args]
        return ["cmd.exe"]
    return [os.environ.get("SHELL") or "/bin/bash", "-l"]


class Terminal:
    def __init__(self, cwd: Path, cols: int, rows: int):
        from .private_conpty import PrivateConPTY
        self.id = uuid.uuid4().hex[:12]
        self.cwd = str(cwd)
        self.argv = default_shell()
        self.shell = Path(self.argv[0]).stem
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        env.pop("NEYVIA_UI_BACKEND_URL", None)
        self.proc = PrivateConPTY.spawn(self.argv, cwd=self.cwd, env=env, dimensions=(rows, cols))
        self.created = time.time()
        self.last_output = self.created
        self.chunks: list[str] = []
        self.start = 0  # output offset of chunks[0]
        self.total = 0
        self.alive = True
        self.exit_code = None
        self.cond = threading.Condition()
        self.target = ""
        self.typed = ""  # a command typed on the prompt line for Paul, never run by Neyvia
        threading.Thread(target=self._pump, name=f"neyvia-terminal-{self.id}", daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = self.proc.read(8192)
            except (EOFError, OSError):
                break
            except Exception:  # noqa: BLE001 - a broken pty ends this terminal, never the backend
                break
            if data:
                self._append(data)
        with self.cond:
            self.alive = False
            try:
                self.exit_code = self.proc.exitstatus
            except Exception:  # noqa: BLE001
                self.exit_code = None
            self.cond.notify_all()

    def _append(self, data: str):
        with self.cond:
            self.chunks.append(data)
            self.total += len(data)
            self.last_output = time.time()
            size = self.total - self.start
            while size > BUFFER_CHARS and len(self.chunks) > 1:
                dropped = self.chunks.pop(0)
                self.start += len(dropped)
                size -= len(dropped)
            self.cond.notify_all()

    def since(self, cursor: int) -> tuple[str, int, bool]:
        """Output after ``cursor``; ``reset`` when part of it already left the buffer."""
        with self.cond:
            reset = cursor < self.start
            text = "".join(self.chunks)
            begin = max(0, cursor - self.start)
            return text[begin:], self.total, reset

    def write(self, data: str):
        if not self.alive:
            raise ValueError("This terminal has ended")
        self.proc.write(data)

    def resize(self, cols: int, rows: int):
        if self.alive:
            self.proc.setwinsize(rows, cols)

    def close(self):
        try:
            if self.proc.isalive():
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001
            pass

    def summary(self) -> dict:
        return {"id": self.id, "cwd": self.cwd, "target": self.target, "typed": self.typed, "shell": self.shell, "alive": self.alive, "exitCode": self.exit_code,
                "created": self.created, "lastOutput": self.last_output, "cursor": self.total}


_terminals: dict[str, Terminal] = {}
_terminal_lock = threading.Lock()


def _close_all():
    for terminal in list(_terminals.values()):
        terminal.close()


atexit.register(_close_all)


def terminal(identity: str) -> Terminal:
    found = _terminals.get(str(identity or ""))
    if not found:
        raise ValueError("That terminal is closed. Open a new one.")
    return found


def _size(args):
    cols = int(args.get("cols") or 100)
    rows = int(args.get("rows") or 30)
    return max(20, min(cols, 400)), max(5, min(rows, 200))


def open_terminal(root, args) -> dict:
    if os.name != "nt":
        raise ValueError("Terminals are only built for Windows hosts so far")
    # The pane's target is a folder to start in, or a command to type there (cwd, else the workspace).
    target = str(args.get("target") or "").strip()
    command = str(args.get("command") or "").strip()
    if target and not command:
        try:
            folder = Path(os.path.expandvars(target.strip('"'))).expanduser()
            is_folder = folder.is_absolute() and folder.is_dir()
        except (OSError, ValueError):
            is_folder = False
        if is_folder:
            args = {**args, "cwd": str(folder)}
        else:
            command = target
    cwd = _guard(root, args.get("cwd") or str(bus_for(root).root))
    if not cwd.is_dir():
        cwd = cwd.parent
    with _terminal_lock:
        for identity in [key for key, value in _terminals.items() if not value.alive]:
            _terminals.pop(identity, None)
        if len(_terminals) >= MAX_TERMINALS:
            raise ValueError(f"{MAX_TERMINALS} terminals are already open. Close one first.")
        cols, rows = _size(args)
        created = Terminal(cwd, cols, rows)
        created.target = target
        created.typed = command
        _terminals[created.id] = created
    if command:
        # Typed on the prompt line, never run: Paul reads it and presses Enter.
        threading.Thread(target=_type_later, args=(created, command.replace("\r", " ").replace("\n", " ")), daemon=True).start()
    return {"ok": True, **created.summary()}


def _type_later(created: Terminal, command: str):
    deadline = time.time() + 8
    while time.time() < deadline and created.alive and created.total == 0:
        time.sleep(0.1)
    time.sleep(0.6)  # let the first prompt paint
    if created.alive:
        created.write(command)


def call_panes(root, op: str, args: dict) -> dict:
    if op == "file.read":
        return read_file(root, args)
    if op == "file.write":
        return write_file(root, args)
    if op == "file.diff":
        return diff_file(root, args)
    if op == "artifact.open":
        return open_artifact(root, args)
    if op == "artifact.stat":
        return stat_artifact(root, args)
    if op == "terminal.open":
        return open_terminal(root, args)
    if op == "terminal.list":
        return {"ok": True, "terminals": [value.summary() for value in _terminals.values()]}
    if op == "terminal.input":
        data = args.get("data")
        if not isinstance(data, str) or len(data) > 64 * 1024:
            raise ValueError("data must be text up to 64 KB")
        terminal(args.get("id")).write(data)
        return {"ok": True}
    if op == "terminal.resize":
        terminal(args.get("id")).resize(*_size(args))
        return {"ok": True}
    if op == "terminal.takeover":
        from .claude_code_cli import set_takeover
        return set_takeover(args.get("id"), bool(args.get("on")))
    if op == "claude.open":
        # The "Open CLI" button: the person's click is the authority (fromClick), the tool refuses without it.
        from .neyvia_workspace_tools import workspace_for
        from .claude_code_cli import open_cli
        return open_cli(workspace_for(root), {**args, "fromClick": True})
    if op == "claude.message":
        # The message box on a Claude Code row: the person's words go to that session (mid-turn, or at its next turn).
        from .neyvia_workspace_tools import workspace_for
        from .claude_code_activity import message
        return message(workspace_for(root), {"to": args.get("session"), "text": args.get("text"), "from": "the person"})
    if op == "terminal.close":
        found = _terminals.pop(str(args.get("id") or ""), None)
        if found:
            found.close()
        return {"ok": True, "closed": bool(found)}
    raise ValueError("Unknown pane action")


def call_tool(service, name: str, args: dict) -> dict:
    """neyvia.terminal.list / neyvia.terminal.read (read only)."""
    if name == "pane.state":
        pane = service.bus.get("pane", {})
        if pane.get("kind") == "browser":
            from .neyvia_browser import service_for
            runtime = service_for(service.bus.root)
            state = runtime.view()
            tab = next((row for row in state["tabs"] if row["id"] == pane.get("target")), None)
            if not state["headless"].get("connected") or not tab or not tab.get("live"):
                return {"ok": True, "pane": pane, "status": "unavailable", "verified": False}
            try:
                runtime.request("observe", {"tabId": pane["target"]})
            except Exception as error:
                return {"ok": True, "pane": pane, "status": "unavailable", "verified": False,
                        "observation": {"error": str(error)}}
            browser = runtime.view()
            ack = browser["paneAcknowledgements"].get(pane.get("target"), {})
            verified = ack.get("status") == "observed" and ack.get("sessionId") == pane.get("runtimeSessionId")
            return {"ok": True, "pane": pane, "status": "observed" if verified else "queued", "verified": verified, "observation": ack}
        return {"ok": True, "pane": pane, "status": "queued", "verified": False}
    if name == "terminal.list":
        return call_panes(service.bus.root, "terminal.list", {})
    if name == "terminal.read":
        found = terminal(args.get("id"))
        chars = max(200, min(int(args.get("chars") or 4000), 50_000))
        text, cursor, _ = found.since(max(0, found.total - chars))
        from .connected_sessions.claude_terminal import _ANSI
        clean = _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
        return {"ok": True, **found.summary(), "text": clean[-chars:]}
    raise ValueError("Unknown terminal action")


def stream_terminal(handler, parsed) -> None:
    """SSE: {data, cursor, reset?} frames, then {ended, exitCode} when the shell exits."""
    from .connected_sessions.api import _client_gone
    from .web_backend import _apply_security_headers, _send_cors_headers
    query = parse_qs(parsed.query)
    found = terminal((query.get("id") or [""])[0])
    cursor = int(handler.headers.get("Last-Event-ID") or (query.get("cursor") or ["0"])[0])
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(b": connected\n\n")
    handler.wfile.flush()
    heartbeat = time.monotonic()
    while not _client_gone(handler):
        text, total, reset = found.since(cursor)
        if text or reset:
            frame = {"data": text, "cursor": total, **({"reset": True} if reset else {})}
            handler.wfile.write(f"id: {total}\ndata: {json.dumps(frame)}\n\n".encode())
            cursor = total
            heartbeat = time.monotonic()
        elif not found.alive:
            handler.wfile.write(f"data: {json.dumps({'ended': True, 'exitCode': found.exit_code, 'cursor': cursor})}\n\n".encode())
            handler.wfile.flush()
            return
        elif time.monotonic() - heartbeat >= 15:
            handler.wfile.write(b": heartbeat\n\n")
            heartbeat = time.monotonic()
        handler.wfile.flush()
        with found.cond:
            if found.total == cursor and found.alive:
                found.cond.wait(1)
