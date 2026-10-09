"""Notes app: a folder of Markdown notes (default ~/Neyvia Notes) shared by Paul and models.

The user side (Notes in the Documents suite) and the bot side (neyvia.notes.*) call the same
functions here, so both read and write the same files. Pins live in the folder itself
(`.neyvia-notes.json`) so they travel with it.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path

from .ui_command_bus import bus_for

TEXT = {"type": "string"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 500}
DEFINITIONS = [
    ("list", "List notes: pinned first, then most recently changed. Filter by text (title and body) or #tag. "
             "Also returns the notes folder and every tag with its count.", {"query": TEXT, "tag": TEXT, "limit": LIMIT}, []),
    ("read", "Read one note's Markdown, title, tags and `modified` (pass it back as expectedModified when writing).",
     {"path": TEXT}, ["path"]),
    ("write", "Create or change a note. No path = new note named from title. mode=append adds to the end "
              "(good for dictation). expectedModified refuses to overwrite a note changed since you read it.",
     {"path": TEXT, "title": TEXT, "body": TEXT, "mode": {"type": "string", "enum": ["replace", "append"]},
      "expectedModified": TEXT}, ["body"]),
    ("search", "Search note titles and bodies; every word must match. Returns snippets.", {"query": TEXT, "limit": LIMIT}, ["query"]),
    ("open", "Show a note to Paul in the Notes app.", {"path": TEXT}, ["path"]),
    ("pin", "Pin or unpin a note (pinned notes list first).", {"path": TEXT, "pinned": {"type": "boolean"}}, ["path"]),
    ("folder", "Read the notes folder, or move Notes to another folder with `folder` (created if missing; files are not moved).",
     {"folder": TEXT}, []),
]
READ = {"list", "read", "search"}
NOTE_EXT = {".md", ".markdown", ".txt"}
MAX_NOTES = 3000
MAX_BYTES = 2 * 1024 * 1024
META = ".neyvia-notes.json"
TAG = re.compile(r"(?<![\w&/#'\"=])#([^\W\d_][\w-]{0,48})")
FENCE = re.compile(r"```.*?(```|\Z)|`[^`\n]*`", re.S)
HEADING = re.compile(r"^#{1,2}\s+(.+?)\s*#*\s*$")
_folder_locks = {}
_folder_locks_guard = threading.Lock()
_held = threading.local()


@contextmanager
def _notes_lock(root):
    """Serialize cooperating writers across threads/processes, including observers.

    The hidden lock file persists: unlinking it can split waiters across two inodes.
    The OS releases its byte lock on process exit, including interrupted runs.
    """
    folder = notes_folder(root)
    key = os.path.normcase(str(folder))
    with _folder_locks_guard:
        lock = _folder_locks.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_held, "folders", set())
        if key in held:
            yield
            return
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ".neyvia-notes.lock").open("a+b") as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Notes folder is busy; retry the action") from None
                    time.sleep(0.01)
            _held.folders = held | {key}
            try:
                yield
            finally:
                _held.folders = held
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _serialized(action):
    @wraps(action)
    def invoke(root, *args, **kwargs):
        with _notes_lock(root):
            return action(root, *args, **kwargs)
    return invoke


def tool_specs(spec_type):
    return [spec_type(name="neyvia.notes." + name, description=description, category="neyvia-notes",
                      input_schema={"type": "object", "properties": props, "required": required},
                      mutability_class="read" if name in READ else "none",
                      capabilities=("neyvia.notes." + name,), parallel_safe=False)
            for name, description, props, required in DEFINITIONS]


# ---- parsing (pure) -----------------------------------------------------------------------------

def tags_of(body: str) -> list[str]:
    """#tags in prose; headings, code, links (`page#part`) and hex colours like #a1b2c3 are not tags."""
    found = []
    for match in TAG.finditer(FENCE.sub(" ", body)):
        tag = match.group(1).rstrip("-").casefold()
        if re.fullmatch(r"[0-9a-f]{3}|[0-9a-f]{6}", tag) and re.search(r"\d", tag):
            continue
        if tag and tag not in found:
            found.append(tag)
    from .proofs_notes_files import check_tags
    return check_tags(body, found)


def title_of(body: str, path: Path) -> str:
    for line in body.splitlines()[:6]:
        match = HEADING.match(line.strip())
        if match:
            from .proofs_notes_files import check_title
            return check_title(body, path, match.group(1).strip()[:120])
    from .proofs_notes_files import check_title
    return check_title(body, path, path.stem)


def excerpt_of(body: str, length: int = 140) -> str:
    lines = [line for line in body.splitlines() if line.strip() and not HEADING.match(line.strip())]
    lines = [re.sub(r"^\s*(?:[-*+]|\d+[.)]|>)\s+(?:\[[ xX]\]\s+)?", "", line) for line in lines]
    text = re.sub(r"(?<![\w&/])#[^\W\d_][\w-]*", "", " ".join(lines))
    text = re.sub(r"[*_`>#\[\]]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:length] + ("…" if len(text) > length else "")


def snippet(body: str, term: str, width: int = 70) -> str:
    at = body.casefold().find(term.casefold())
    if at < 0:
        return excerpt_of(body)
    start, end = max(0, at - width), min(len(body), at + len(term) + width)
    text = re.sub(r"\s+", " ", body[start:end]).strip()
    return ("…" if start else "") + text + ("…" if end < len(body) else "")


def file_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*#\x00-\x1f]+', " ", title).strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:80].strip()
    if not name or name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "Note " + datetime.now().strftime("%Y-%m-%d %H%M")
    return name


# ---- the folder ---------------------------------------------------------------------------------

def notes_folder(root) -> Path:
    saved = bus_for(root).get("notes:folder")
    default = os.environ.get("NEYVIA_NOTES_DIR") or str(Path.home() / "Neyvia Notes")
    return Path(saved or default).expanduser().resolve()


def _note_path(root, value) -> tuple[Path, Path]:
    folder = notes_folder(root)
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("Give the note's path")
    candidate = Path(text)
    path = (candidate if candidate.is_absolute() else folder / candidate).resolve()
    if folder not in path.parents:
        raise ValueError("Notes live in the notes folder: " + str(folder))
    if path.suffix.lower() not in NOTE_EXT:
        raise ValueError("A note is a .md, .markdown or .txt file")
    return folder, path


def _rel(folder: Path, path: Path) -> str:
    return path.relative_to(folder).as_posix()


def _modified(path: Path) -> str:
    return str(path.stat().st_mtime_ns)


def _meta(folder: Path) -> dict:
    try:
        data = json.loads((folder / META).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("This note is over 2 MB; open it as a file instead")
    return path.read_text(encoding="utf-8", errors="replace", newline="")


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat().st_mtime_ns if path.exists() else 0
    handle, temp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # An accepted replacement must invalidate every previous read stamp,
        # even on filesystems whose clock resolution aliases adjacent writes.
        stamp = max(time.time_ns(), previous + 1_000_000)
        os.utime(temp, ns=(stamp, stamp))
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _summary(folder: Path, path: Path, body: str, pinned: set) -> dict:
    info = path.stat()
    rel = _rel(folder, path)
    return {"path": rel, "title": title_of(body, path), "tags": tags_of(body), "pinned": rel in pinned,
            "modified": str(info.st_mtime_ns), "changed": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            "size": info.st_size, "excerpt": excerpt_of(body)}


def _all(folder: Path) -> list[tuple[Path, str]]:
    rows = []
    if not folder.is_dir():
        return rows
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(name for name in dirs if not name.startswith((".", "_")) and name != "node_modules")
        for name in files:
            path = Path(base, name)
            if name.startswith((".", "~")) or path.suffix.lower() not in NOTE_EXT:
                continue
            try:
                if path.stat().st_size <= MAX_BYTES:
                    rows.append((path, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
            if len(rows) >= MAX_NOTES:
                return rows
    return rows


# ---- actions ------------------------------------------------------------------------------------

def list_notes(root, args) -> dict:
    folder = notes_folder(root)
    pinned = set(_meta(folder).get("pinned") or [])
    query = str(args.get("query") or "").strip()
    terms = [term for term in query.split() if not term.startswith("#")]
    wanted = [term[1:].casefold() for term in query.split() if term.startswith("#") and len(term) > 1]
    if args.get("tag"):
        wanted.append(str(args["tag"]).lstrip("#").casefold())
    counts, rows = {}, []
    for path, body in _all(folder):
        row = _summary(folder, path, body, pinned)
        for tag in row["tags"]:
            counts[tag] = counts.get(tag, 0) + 1
        hay = (row["title"] + "\n" + body).casefold()
        if all(term.casefold() in hay for term in terms) and all(tag in row["tags"] for tag in wanted):
            if terms:
                row["snippet"] = snippet(body, terms[0])
            rows.append(row)
    rows.sort(key=lambda row: (not row["pinned"], -int(row["modified"])))
    limit = int(args.get("limit") or 500)
    return {"ok": True, "folder": str(folder), "exists": folder.is_dir(), "total": len(rows),
            "notes": rows[:limit], "tags": sorted(({"tag": tag, "count": count} for tag, count in counts.items()),
                                                  key=lambda row: (-row["count"], row["tag"]))}


def search_notes(root, args) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("Give words to search for")
    result = list_notes(root, {"query": query, "limit": args.get("limit") or 20})
    terms = [term.casefold() for term in query.split() if not term.startswith("#")]
    # Title matches rank above body-only matches; recency breaks ties.
    result["notes"].sort(key=lambda row: (-sum(term in row["title"].casefold() for term in terms), -int(row["modified"])))
    return {"ok": True, "folder": result["folder"], "query": query, "total": result["total"], "hits": result["notes"]}


def read_note(root, args) -> dict:
    folder, path = _note_path(root, args["path"])
    if not path.is_file():
        raise ValueError("No note at " + _rel(folder, path))
    body = _read_text(path)
    pinned = set(_meta(folder).get("pinned") or [])
    return {"ok": True, **_summary(folder, path, body, pinned), "body": body, "file": str(path)}


def _unique(folder: Path, name: str) -> Path:
    path, count = folder / f"{name}.md", 2
    while path.exists():
        path, count = folder / f"{name} {count}.md", count + 1
    return path


@_serialized
def write_note(root, args) -> dict:
    folder = notes_folder(root)
    body = args.get("body")
    if not isinstance(body, str):
        raise ValueError("body must be text")
    title = str(args.get("title") or "").strip()
    created = False
    if args.get("path"):
        folder, path = _note_path(root, args["path"])
        created = not path.exists()
    else:
        folder.mkdir(parents=True, exist_ok=True)
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        path = _unique(folder, file_name(title or (HEADING.match(first).group(1) if HEADING.match(first) else first[:60])))
        created = True
        if title and not HEADING.match(first):
            body = f"# {title}\n\n{body}" if body.strip() else f"# {title}\n\n"
    if not created:
        expected = args.get("expectedModified")
        current = _modified(path)
        if expected and str(expected) != current:
            return {"ok": False, "status": "conflict", "error": "This note changed since it was opened",
                    "path": _rel(folder, path), "modified": current}
        if args.get("mode") == "append":
            old = _read_text(path)
            body = old + ("" if not old or old.endswith("\n\n") else "\n" if old.endswith("\n") else "\n\n") + body
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise ValueError("A note can be up to 2 MB")
    _atomic_write(path, body)
    pinned = set(_meta(folder).get("pinned") or [])
    return {"ok": True, "created": created, **_summary(folder, path, body, pinned), "file": str(path)}


@_serialized
def pin_note(root, args) -> dict:
    folder, path = _note_path(root, args["path"])
    if not path.is_file():
        raise ValueError("No note at " + _rel(folder, path))
    meta = _meta(folder)
    pinned = [entry for entry in meta.get("pinned") or [] if (folder / entry).is_file()]
    rel = _rel(folder, path)
    pinned = [entry for entry in pinned if entry != rel] + ([rel] if args.get("pinned", True) is not False else [])
    _atomic_write(folder / META, json.dumps({**meta, "pinned": pinned}, indent=2))
    return {"ok": True, "path": rel, "pinned": rel in pinned}


def set_folder(root, args) -> dict:
    if not args.get("folder"):
        folder = notes_folder(root)
        return {"ok": True, "folder": str(folder), "exists": folder.is_dir()}
    from .neyvia_workspace_tools import WorkspaceTools
    folder = WorkspaceTools.safe_path(str(args["folder"]))
    if not folder.is_absolute():
        raise ValueError("Use a full folder path")
    if folder.exists() and not folder.is_dir():
        raise ValueError("That is a file, not a folder")
    folder.mkdir(parents=True, exist_ok=True)
    bus_for(root).put("notes:folder", str(folder))
    return {"ok": True, "folder": str(folder), "exists": True}


def _call_notes_unchecked(root, name: str, args: dict, source: str = "model", *, local: bool = False) -> dict:
    from .neyvia_workspace_tools import workspace_for
    if not local and source != "ui" and workspace_for(root).backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        from .neyvia_ui_client import call_tool
        return call_tool("notes." + name, args)
    if name == "list":
        return list_notes(root, args)
    if name == "search":
        return search_notes(root, args)
    if name == "read":
        return read_note(root, args)
    bus = bus_for(root)
    if name == "open":
        note = read_note(root, args)
        return {"ok": True, "path": note["path"], "title": note["title"], "uiVerified": False,
                "event": bus.emit("notes.open", {"path": note["path"]})}
    if name == "write":
        result = write_note(root, args)
    elif name == "pin":
        result = pin_note(root, args)
    elif name == "folder":
        result = set_folder(root, args)
    else:
        raise ValueError("Unknown Notes action")
    if result.get("ok") and source != "ui":
        result["event"] = bus.emit("notes.changed", {"op": name, "path": result.get("path"), "by": source})
    return result


def call_notes(root, name: str, args: dict, source: str = "model", *, local: bool = False) -> dict:
    from .neyvia_workspace_tools import workspace_for
    # Remote actions are checked at their owning host, where durable state lives.
    if not local and source != "ui" and workspace_for(root).backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        return _call_notes_unchecked(root, name, args, source)
    from .proofs_notes_files import before, after
    tool = "neyvia.notes." + name
    if name in {"write", "pin"}:
        with _notes_lock(root):
            capture = before(tool, args, root)
            result = _call_notes_unchecked(root, name, args, source)
            after(tool, args, result, root, capture)
            return result
    capture = before(tool, args, root)
    result = _call_notes_unchecked(root, name, args, source, local=local)
    after(tool, args, result, root, capture)
    return result
