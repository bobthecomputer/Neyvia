"""Files app: a file explorer over Home, the workspace and project folders.

The user side (Files in the Documents suite) and the bot side (neyvia.files.*) call the same
functions here, so both act on the same folders. Delete always goes to the Recycle Bin; the last
move, new folder or delete can be undone by either side.
"""
from __future__ import annotations

import mimetypes
import os
import shutil
import stat as statmod
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ui_command_bus import bus_for, now

TEXT = {"type": "string"}
DEFINITIONS = [
    ("list", "List a folder (folders first). With no path, list the places Paul can browse: Home, the workspace, "
             "Neyvia Notes and project folders.", {"path": TEXT, "showHidden": {"type": "boolean"}}, []),
    ("stat", "Read one file or folder's details; preview=true adds the first 64 KB of a text file.",
     {"path": TEXT, "preview": {"type": "boolean"}}, ["path"]),
    ("move", "Move or rename a file or folder. `to` is the new full path, or an existing folder to move into. "
             "Never overwrites. Undo with neyvia.files.undo.", {"from": TEXT, "to": TEXT}, ["from", "to"]),
    ("mkdir", "Create a new folder (parents must exist).", {"path": TEXT}, ["path"]),
    ("trash", "Send a file or folder to the Recycle Bin (never a permanent delete). Undo with neyvia.files.undo.",
     {"path": TEXT}, ["path"]),
    ("undo", "Undo the last move, rename, new folder or delete made in Files by Paul or a model.", {}, []),
]

READ = {"list", "stat"}
TEXT_EXT = {".md", ".markdown", ".txt", ".log", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini", ".cfg",
            ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html", ".xml", ".rs", ".go", ".java", ".c", ".h",
            ".cpp", ".cs", ".sh", ".ps1", ".bat", ".sql", ".tex", ".bib", ".gitignore", ".env.example", ".lua", ".gd"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp", ".ico"}
MAX_ENTRIES = 2000
PREVIEW_BYTES = 64 * 1024
MAX_TRASH_BYTES = 2 * 1024 ** 3


def tool_specs(spec_type):
    return [spec_type(name="neyvia.files." + name, description=description, category="neyvia-files",
                      input_schema={"type": "object", "properties": props, "required": required},
                      mutability_class="read" if name in READ else "none",
                      capabilities=("neyvia.files." + name,), parallel_safe=False)
            for name, description, props, required in DEFINITIONS]


# ---- places -------------------------------------------------------------------------------------

def places(root) -> list[dict]:
    from .neyvia_notes_tools import notes_folder
    bus = bus_for(root)
    rows = [("Home", Path.home(), "home"), ("Workspace", bus.root, "workspace"), ("Neyvia Notes", notes_folder(root), "notes")]
    rows += [(project.get("name") or Path(project["path"]).name, Path(project["path"]), "project")
             for project in bus.get("projects", {}).values() if project.get("path")]
    seen, result = set(), []
    for name, path, kind in rows:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        result.append({"name": name, "path": str(resolved), "kind": kind})
    return result


def _protected(path: Path) -> bool:
    from .neyvia_workspace_tools import WorkspaceTools
    try:
        WorkspaceTools.safe_path(path)
        return False
    except ValueError:
        return True


def guard(root, value) -> Path:
    """Resolve a path and require it inside one of the places (the live Neyvia tree stays protected)."""
    from .neyvia_workspace_tools import WorkspaceTools
    text = str(value or "").strip()
    if not text:
        raise ValueError("Give a path")
    path = WorkspaceTools.safe_path(text)
    if not path.is_absolute():
        raise ValueError("Use a full path")
    allowed = [Path(place["path"]) for place in places(root)]
    if not any(path == base or base in path.parents for base in allowed):
        raise ValueError("That path is outside Home, the workspace and your project folders")
    return path


def place_of(root, path: Path) -> dict | None:
    best = None
    for place in places(root):
        base = Path(place["path"])
        if (path == base or base in path.parents) and (best is None or len(place["path"]) > len(best["path"])):
            best = place
    return best


# ---- entries ------------------------------------------------------------------------------------

def _hidden(path: Path, info) -> bool:
    if path.name.startswith("."):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & (getattr(statmod, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(statmod, "FILE_ATTRIBUTE_SYSTEM", 4)))


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def open_with(root, path: Path, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown"}:
        from .neyvia_notes_tools import notes_folder
        folder = notes_folder(root)
        if folder in path.parents:
            return "notes"
    if suffix in IMAGE_EXT:
        return "image"
    if suffix in TEXT_EXT or path.name.lower() in {"readme", "license", "makefile", "dockerfile"}:
        return "text"
    return "none"


def entry(root, path: Path, info=None) -> dict:
    info = info or path.stat()
    is_dir = statmod.S_ISDIR(info.st_mode)
    return {"name": path.name or str(path), "path": str(path), "kind": "folder" if is_dir else "file",
            "size": None if is_dir else info.st_size, "modified": _iso(info.st_mtime),
            "ext": "" if is_dir else path.suffix.lower().lstrip("."), "openWith": open_with(root, path, is_dir),
            "hidden": _hidden(path, info), **({"protected": True} if is_dir and _protected(path) else {})}


def list_folder(root, args) -> dict:
    if not args.get("path"):
        return {"ok": True, "path": None, "places": places(root), "entries": []}
    path = guard(root, args["path"])
    if not path.is_dir():
        raise ValueError("That is not a folder")
    show_hidden = bool(args.get("showHidden"))
    rows, hidden, truncated = [], 0, False
    try:
        children = list(os.scandir(path))
    except PermissionError:
        raise ValueError("Windows does not allow reading this folder") from None
    for item in children:
        try:
            info = item.stat(follow_symlinks=True)
        except OSError:
            continue
        child = Path(item.path)
        row = entry(root, child, info)
        if row["hidden"] and not show_hidden:
            hidden += 1
            continue
        if len(rows) >= MAX_ENTRIES:
            truncated = True
            break
        rows.append(row)
    rows.sort(key=lambda row: (row["kind"] != "folder", row["name"].casefold()))
    place = place_of(root, path)
    parent = None if place and os.path.normcase(str(path)) == os.path.normcase(place["path"]) else str(path.parent)
    crumbs, cursor = [], path
    while place:
        crumbs.append({"name": cursor.name if cursor != Path(place["path"]) else place["name"], "path": str(cursor)})
        if os.path.normcase(str(cursor)) == os.path.normcase(place["path"]) or cursor.parent == cursor:
            break
        cursor = cursor.parent
    return {"ok": True, "path": str(path), "parent": parent, "place": place, "crumbs": crumbs[::-1],
            "entries": rows, "hiddenCount": hidden, "truncated": truncated}


def stat_path(root, args) -> dict:
    path = guard(root, args["path"])
    if not path.exists():
        raise ValueError("Nothing is at that path")
    row = entry(root, path)
    result = {"ok": True, **row, "mime": mimetypes.guess_type(path.name)[0]}
    if row["kind"] == "folder":
        try:
            result["items"] = sum(1 for _ in os.scandir(path))
        except PermissionError:
            result["items"] = None
    if row["openWith"] == "pdf":
        try:
            from .neyvia_pdf_tools import safe_pdf
            safe_pdf(root, str(path))
            result["pdfApp"] = True  # the PDF app (and its bot side) can read it by path
        except ValueError:
            result["pdfApp"] = False  # shown from the file route; outside the PDF app's folders
    if args.get("preview") and row["kind"] == "file" and row["openWith"] in {"text", "notes"}:
        with path.open("rb") as stream:
            data = stream.read(PREVIEW_BYTES + 1)
        result["preview"] = data[:PREVIEW_BYTES].decode("utf-8", errors="replace")
        result["previewTruncated"] = len(data) > PREVIEW_BYTES
    return result


# ---- changes (and the one-step undo) ------------------------------------------------------------

def _remember(root, action: dict):
    bus_for(root).put("files:last", {**action, "at": now()})


def _approval(root, path: Path, verb: str, source: str):
    """A model moving or deleting outside Neyvia Notes and the workspace asks Paul once per place."""
    if source == "ui":
        return None
    place = place_of(root, path) or {}
    if place.get("kind") in {"notes", "workspace"}:
        return None
    from .neyvia_workspace_tools import workspace_for
    return workspace_for(root).require_approval("files:" + os.path.normcase(place.get("path") or str(path)),
                                                f"Allow models to move and delete files in {place.get('path') or path}",
                                                {"verb": verb, "path": str(path)})


def move(root, args, source) -> dict:
    origin = guard(root, args["from"])
    if not origin.exists():
        raise ValueError("Nothing is at the path to move")
    target = guard(root, args["to"])
    if target.is_dir() and os.path.normcase(str(target)) != os.path.normcase(str(origin)):
        target = guard(root, target / origin.name)
    if os.path.normcase(str(target)) == os.path.normcase(str(origin)) and target.name == origin.name:
        raise ValueError("That is already its name and place")
    if origin.is_dir() and (target == origin or origin in target.parents):
        raise ValueError("A folder can't move inside itself")
    if target.exists() and os.path.normcase(str(target)) != os.path.normcase(str(origin)):
        raise ValueError(f"{target.name} already exists there")
    if not target.parent.is_dir():
        raise ValueError("The destination folder does not exist")
    refusal = _approval(root, origin, "move", source) or _approval(root, target, "move", source)
    if refusal:
        return refusal
    shutil.move(str(origin), str(target))
    _remember(root, {"op": "move", "from": str(origin), "to": str(target), "by": source})
    return {"ok": True, "from": str(origin), "to": str(target), "entry": entry(root, target)}


def mkdir(root, args, source) -> dict:
    path = guard(root, args["path"])
    if path.exists():
        raise ValueError(f"{path.name} already exists")
    if not path.parent.is_dir():
        raise ValueError("The parent folder does not exist")
    path.mkdir()
    _remember(root, {"op": "mkdir", "path": str(path), "by": source})
    return {"ok": True, "entry": entry(root, path)}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
        if total > MAX_TRASH_BYTES:
            break
    return total


def trash(root, args, source) -> dict:
    path = guard(root, args["path"])
    if not path.exists():
        raise ValueError("Nothing is at that path")
    if any(os.path.normcase(str(path)) == os.path.normcase(place["path"]) for place in places(root)):
        raise ValueError("A place itself (Home, the workspace, a project) can't be deleted from Files")
    refusal = _approval(root, path, "trash", source)
    if refusal:
        return refusal
    if _size(path) > MAX_TRASH_BYTES:
        raise ValueError("This is over 2 GB and might not fit in the Recycle Bin; delete it in Explorer instead")
    recycle(path)
    if path.exists():
        raise RuntimeError("Windows did not move it to the Recycle Bin")
    _remember(root, {"op": "trash", "path": str(path), "by": source})
    return {"ok": True, "path": str(path), "recycled": True}


def undo(root, source) -> dict:
    bus = bus_for(root)
    last = bus.get("files:last")
    if not last:
        raise ValueError("Nothing to undo")
    op = last["op"]
    if op == "move":
        origin, target = Path(last["to"]), Path(last["from"])
        if not origin.exists():
            raise ValueError(f"{origin.name} is no longer where it was moved")
        if target.exists() and os.path.normcase(str(target)) != os.path.normcase(str(origin)):
            raise ValueError(f"Something new is at {target}; undo would overwrite it")
        shutil.move(str(origin), str(target))
        message = f"Moved {target.name} back"
    elif op == "mkdir":
        path = Path(last["path"])
        if path.exists():
            if any(path.iterdir()):
                raise ValueError(f"{path.name} is no longer empty; it stays")
            path.rmdir()
        message = f"Removed the new folder {path.name}"
    elif op == "trash":
        restore(Path(last["path"]))
        message = f"Restored {Path(last['path']).name} from the Recycle Bin"
    else:
        raise ValueError("Unknown last action")
    bus.put("files:last", None)
    return {"ok": True, "undone": op, "message": message, "action": last}


# ---- Recycle Bin --------------------------------------------------------------------------------

def recycle(path: Path):
    if sys.platform != "win32":
        try:
            from send2trash import send2trash
        except ImportError:
            raise ValueError("No Recycle Bin is available on this system; nothing was deleted") from None
        send2trash(str(path))
        return
    import ctypes
    from ctypes import wintypes
    drive = path.anchor
    if ctypes.windll.kernel32.GetDriveTypeW(drive) != 3 or not Path(drive, "$Recycle.Bin").is_dir():
        raise ValueError("This drive has no Recycle Bin; nothing was deleted")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    source = ctypes.create_unicode_buffer(str(path) + "\0")  # double-null terminated list
    # FO_DELETE with FOF_ALLOWUNDO (Recycle Bin), quiet, and a warning instead of a silent permanent delete.
    operation = SHFILEOPSTRUCTW(None, 3, ctypes.cast(source, wintypes.LPCWSTR), None, 0x40 | 0x10 | 0x4 | 0x400 | 0x4000, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if code or operation.fAnyOperationsAborted:
        raise RuntimeError(f"Windows could not move it to the Recycle Bin (code {code})")


def parse_recycle_info(data: bytes) -> dict:
    """Read a Recycle Bin `$I` record: original path, size and deletion time (Vista+ v1 and Windows 10+ v2)."""
    version, size, filetime = struct.unpack_from("<qqq", data, 0)
    if version == 2:
        (length,) = struct.unpack_from("<i", data, 24)
        original = data[28:28 + length * 2].decode("utf-16-le")
    elif version == 1:
        original = data[24:24 + 520].decode("utf-16-le")
    else:
        raise ValueError("Unknown Recycle Bin record")
    from .proofs_notes_files import check_recycle_record
    return check_recycle_record(data, {"path": original.split("\0", 1)[0], "size": size, "deleted": filetime})


def bin_records(path: Path) -> list[dict]:
    rows = []
    base = Path(path.anchor, "$Recycle.Bin")
    for owner in (base.iterdir() if base.is_dir() else []):
        try:
            infos = list(owner.glob("$I*"))
        except OSError:
            continue
        for info in infos:
            try:
                record = parse_recycle_info(info.read_bytes())
            except (OSError, ValueError, struct.error):
                continue
            if os.path.normcase(record["path"]) == os.path.normcase(str(path)):
                rows.append({**record, "info": info, "data": owner / ("$R" + info.name[2:])})
    return sorted(rows, key=lambda row: row["deleted"], reverse=True)


def restore(path: Path):
    if path.exists():
        raise ValueError(f"Something new is at {path}; restore it from the Recycle Bin by hand")
    if sys.platform != "win32":
        raise ValueError("Restore it from the system trash; undo here works on Windows")
    for record in bin_records(path):
        if record["data"].exists():
            if not path.parent.is_dir():
                raise ValueError("Its old folder is gone; restore it from the Recycle Bin by hand")
            shutil.move(str(record["data"]), str(path))
            record["info"].unlink(missing_ok=True)  # the bin's index entry for the item just restored
            return
    raise ValueError("It is no longer in the Recycle Bin")


# ---- one entry point for both sides ------------------------------------------------------------

def _call_files_unchecked(root, name: str, args: dict, source: str = "model") -> dict:
    from .neyvia_workspace_tools import workspace_for
    if source != "ui" and workspace_for(root).backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        from .neyvia_ui_client import call_tool
        return call_tool("files." + name, args)
    if name == "list":
        return list_folder(root, args)
    if name == "stat":
        return stat_path(root, args)
    if name == "move":
        result = move(root, args, source)
    elif name == "mkdir":
        result = mkdir(root, args, source)
    elif name == "trash":
        result = trash(root, args, source)
    elif name == "undo":
        result = undo(root, source)
    else:
        raise ValueError("Unknown Files action")
    if result.get("ok") and source != "ui":
        result["event"] = bus_for(root).emit("files.changed", {"op": name, "by": source,
                                                                "paths": [str(value) for value in (args.get("from"), args.get("to"), args.get("path")) if value]})
    return result


def call_files(root, name: str, args: dict, source: str = "model") -> dict:
    from .neyvia_workspace_tools import workspace_for
    if source != "ui" and workspace_for(root).backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        return _call_files_unchecked(root, name, args, source)
    from .proofs_notes_files import before, after
    tool = "neyvia.files." + name
    capture = before(tool, args, root)
    result = _call_files_unchecked(root, name, args, source)
    after(tool, args, result, root, capture)
    return result


def serve_raw(root, handler, parsed):
    """Quick look bytes for images and PDFs (authenticated, sandboxed, never HTML)."""
    from urllib.parse import parse_qs
    from .web_backend import _apply_security_headers, _send_cors_headers
    path = guard(root, (parse_qs(parsed.query).get("path") or [""])[0])
    kind = open_with(root, path, path.is_dir())
    if not path.is_file() or kind not in {"image", "pdf"}:
        raise ValueError("Quick look serves images and PDFs only")
    mime = "application/pdf" if kind == "pdf" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    size = path.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    with path.open("rb") as stream:
        shutil.copyfileobj(stream, handler.wfile, 128 * 1024)
