"""Safe staging and explicit installation of local skill files and archives.

Archives are treated as data. Nothing in them is executed during import.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs

MAX_UPLOAD = 20 * 1024 * 1024
MAX_UNPACKED = 50 * 1024 * 1024
MAX_FILE = 5 * 1024 * 1024
MAX_SKILL_TEXT = 512 * 1024
MAX_ENTRIES = 1000
MAX_SELECTED_FILES = 100


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip(".-_")
    value = (value or "imported-skill")[:72].rstrip(".")
    _safe_member(value)
    return value


def _safe_member(name: str) -> str | None:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ValueError("Archive contains an absolute or invalid path")
    parts = name.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Archive contains a traversal path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in parts:
        if any(ord(char) < 32 or char in ':*?<>|"' for char in part) or part.endswith((".", " ")) or part.split(".", 1)[0].upper() in reserved:
            raise ValueError("Archive contains a Windows-reserved path")
    if any(part == "__pycache__" for part in parts) or name.endswith(".pyc"):
        return None
    return "/".join(parts)


def _description(markdown: str, fallback: str) -> tuple[str, str]:
    markdown = markdown.replace("\r\n", "\n")
    if not markdown.startswith("---\n"):
        return fallback, ""
    end = markdown.find("\n---", 4)
    if end < 0:
        return fallback, ""
    fm = markdown[4:end]
    name = re.search(r"(?m)^name:\s*(?:['\"]([^'\"]+)['\"]|([^\r\n#]+))", fm)
    desc = re.search(r"(?m)^description:\s*(?:['\"]([^'\"]+)['\"]|([^\r\n#]+))", fm)
    return (name.group(1) or name.group(2)).strip() if name else fallback, (desc.group(1) or desc.group(2)).strip() if desc else ""


def _read_zip(data: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    total = 0
    normalized: set[str] = set()
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError("Archive exceeds the 1,000 entry limit")
        for info in infos:
            safe = _safe_member(info.filename)
            if safe is None or info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError("Archive links are not supported")
            if info.file_size > MAX_FILE:
                raise ValueError(f"{safe} exceeds the 5 MB file limit")
            total += info.file_size
            if total > MAX_UNPACKED:
                raise ValueError("Archive exceeds the 50 MB unpacked limit")
            if safe in result:
                raise ValueError(f"Archive contains a duplicate path: {safe}")
            key = safe.casefold()
            if key in normalized:
                raise ValueError(f"Archive contains paths that collide on Windows: {safe}")
            normalized.add(key)
            with zf.open(info) as stream:
                content = stream.read(MAX_FILE + 1)
            if len(content) != info.file_size:
                raise ValueError(f"Could not read archive member: {safe}")
            result[safe] = content
    return result


def _bsdtar() -> str:
    candidates = [shutil.which("bsdtar"), shutil.which("tar")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                version = subprocess.run([candidate, "--version"], capture_output=True, timeout=3, **hidden_windows_subprocess_kwargs()).stdout.decode("utf-8", "replace").lower()
            except (OSError, subprocess.TimeoutExpired):
                continue
            if "bsdtar" in version or "libarchive" in version:
                return candidate
    raise ValueError("RAR import needs a libarchive-compatible tar command; ZIP and MD files work without it")


def _bounded_process(args: list[str], limit: int, timeout: int = 30) -> bytes:
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
    expired = threading.Event()
    timer = threading.Timer(timeout, lambda: (expired.set(), proc.kill() if proc.poll() is None else None))
    timer.daemon = True
    timer.start()
    try:
        assert proc.stdout is not None
        data = proc.stdout.read(limit + 1)
        if len(data) > limit:
            proc.kill()
            proc.wait()
            raise ValueError("RAR listing or member exceeds the import size limit")
        proc.stdout.close()
        code = proc.wait()
        if expired.is_set():
            raise ValueError("RAR operation timed out")
        if code:
            raise ValueError("RAR operation failed")
        return data
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _read_rar(data: bytes) -> dict[str, bytes]:
    # Keep RAR bytes in a random private temp file; extract each regular member
    # to stdout only, never to a filesystem path supplied by an archive.
    with tempfile.TemporaryDirectory(prefix="neyvia-rar-") as tmp:
        archive = Path(tmp) / "input.rar"
        archive.write_bytes(data)
        exe = _bsdtar()
        lines = _bounded_process([exe, "-tvf", str(archive)], 2 * 1024 * 1024).decode("utf-8", "replace").splitlines()
        if len(lines) > MAX_ENTRIES:
            raise ValueError("Archive exceeds the 1,000 entry limit")
        result: dict[str, bytes] = {}
        total = 0
        names = _bounded_process([exe, "-tf", str(archive)], 2 * 1024 * 1024).decode("utf-8", "replace").splitlines()
        if len(names) > MAX_ENTRIES or len(names) != len(lines):
            raise ValueError("Archive exceeds the 1,000 entry limit")
        normalized = set()
        # libarchive's verbose listing emits one line per member, with first
        # column d/-/l/h; reject symbolic and hard links independent of path.
        for idx, name in enumerate(names):
            safe = _safe_member(name)
            line = lines[idx] if idx < len(lines) else ""
            if line[:1] not in ("-", "d") or " link to " in line:
                raise ValueError("Archive links are not supported")
            if safe is None or line.startswith("d"):
                continue
            if safe.casefold() in normalized:
                raise ValueError("Archive contains paths that collide on Windows")
            normalized.add(safe.casefold())
            # `-xOf archive member` writes bytes to stdout and cannot create paths.
            content = _bounded_process([exe, "-xOf", str(archive), name], MAX_FILE)
            if len(content) > MAX_FILE:
                raise ValueError(f"{safe} exceeds the 5 MB file limit")
            total += len(content)
            if total > MAX_UNPACKED:
                raise ValueError("Archive exceeds the 50 MB unpacked limit")
            if safe in result:
                raise ValueError(f"Archive contains a duplicate path: {safe}")
            result[safe] = content
        return result


def _groups(name: str, files: dict[str, bytes]) -> list[dict[str, Any]]:
    skills = [path for path in files if PurePosixPath(path).name.lower() == "skill.md"]
    if skills:
        groups = []
        prefixes = []
        for skill_file in skills:
            p = str(PurePosixPath(skill_file).parent)
            prefixes.append("" if p == "." else p + "/")
        for skill_file, prefix in zip(skills, prefixes):
            grouped = {}
            for path, content in files.items():
                if not path.startswith(prefix):
                    continue
                rel = path[len(prefix):]
                if any(other != prefix and other.startswith(prefix) and rel.startswith(other[len(prefix):]) for other in prefixes):
                    continue
                grouped[rel] = content
            skill_key = next((key for key in grouped if key.lower() == "skill.md"), None)
            if skill_key is None:
                continue
            if skill_key != "SKILL.md":
                grouped["SKILL.md"] = grouped.pop(skill_key)
            fallback = PurePosixPath(skill_file).parent.name or Path(name).stem
            groups.append(_make_group(fallback, grouped, source=name))
        return groups
    # A directly selected Markdown/text file is itself one skill.
    if len(files) == 1:
        path, content = next(iter(files.items()))
        if Path(path).suffix.lower() in (".md", ".txt"):
            return [_make_group(Path(path).stem, {"SKILL.md": content}, source=name)]
    raise ValueError("No SKILL.md found. Select a .md/.txt file or an archive containing skill folders.")


def _make_group(fallback: str, files: dict[str, bytes], source: str | None = None) -> dict[str, Any]:
    if len(files) > MAX_ENTRIES:
        raise ValueError("Skill exceeds the 1,000 file limit")
    total = sum(len(data) for data in files.values())
    if total > MAX_UNPACKED or any(len(data) > MAX_FILE for data in files.values()):
        raise ValueError("Skill files exceed the import size limits")
    text = files["SKILL.md"].decode("utf-8-sig", "replace")
    display, description = _description(text, fallback)
    _slug(display)
    digest = hashlib.sha256(b"".join(p.encode() + b"\0" + files[p] for p in sorted(files))).hexdigest()
    return {"id": digest[:20], "name": display, "description": description, "source": source or fallback, "fileCount": len(files), "files": {p: base64.b64encode(v).decode("ascii") for p, v in files.items()}, "digest": digest}


def inspect_skills(root: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list) or not files:
        return {"ok": False, "error": "Select one or more files to import."}
    if len(files) > MAX_SELECTED_FILES:
        return {"ok": False, "error": "Select at most 100 files at a time."}
    staged: list[dict[str, Any]] = []
    uploaded = 0
    unpacked = 0
    try:
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("dataBase64"), str):
                raise ValueError("Each selected file needs a name and base64 content")
            filename = Path(item["name"]).name
            encoded = item["dataBase64"]
            if len(encoded) > (MAX_UPLOAD * 4 // 3 + 16):
                raise ValueError("Selected files exceed the 20 MB upload limit")
            try:
                data = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise ValueError(f"Could not decode {filename}") from exc
            uploaded += len(data)
            if uploaded > MAX_UPLOAD:
                raise ValueError("Selected files exceed the 20 MB upload limit")
            ext = Path(filename).suffix.lower()
            if ext in (".md", ".txt"):
                if len(data) > MAX_FILE:
                    raise ValueError(f"{filename} exceeds the 5 MB file limit")
                groups = [_make_group(Path(filename).stem, {"SKILL.md": data}, source=filename)]
                unpacked += len(data)
            elif ext == ".zip":
                content_map = _read_zip(data)
                unpacked += sum(map(len, content_map.values()))
                groups = _groups(filename, content_map)
            elif ext == ".rar":
                content_map = _read_rar(data)
                unpacked += sum(map(len, content_map.values()))
                groups = _groups(filename, content_map)
            else:
                raise ValueError(f"Unsupported file type: {filename}")
            staged.extend(groups)
            if unpacked > MAX_UNPACKED:
                raise ValueError("Selected files exceed the 50 MB total unpacked limit")
            for skill in groups:
                if len(base64.b64decode(skill["files"]["SKILL.md"])) > MAX_SKILL_TEXT:
                    raise ValueError(f"{skill['name']} SKILL.md exceeds the 512 KB instruction limit")
        if len(staged) > MAX_SELECTED_FILES:
            raise ValueError("Select a smaller batch (maximum 100 skills).")
        used_ids: set[str] = set()
        for index, skill in enumerate(staged, 1):
            base_id = skill["id"]
            candidate = base_id
            suffix = 2
            while candidate in used_ids:
                candidate = f"{base_id}-{suffix}"
                suffix += 1
            skill["id"] = candidate
            used_ids.add(candidate)
        if not staged:
            raise ValueError("No installable skills were found.")
        import_id = uuid.uuid4().hex
        root_path = Path(root).resolve()
        codex_dir = root_path / ".codex"
        try:
            codex_dir.resolve().relative_to(root_path)
        except ValueError:
            raise ValueError("The workspace .codex folder points outside the workspace")
        stage_dir = codex_dir / "skill-import-staging"
        stage_dir.mkdir(parents=True, exist_ok=True)
        try:
            stage_dir.resolve().relative_to(root_path)
        except ValueError:
            raise ValueError("The skill staging folder points outside the workspace")
        stage_file = stage_dir / f"{import_id}.json"
        temp = stage_file.with_suffix(".tmp")
        temp.write_text(json.dumps({"importId": import_id, "skills": staged}, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, stage_file)
        return {"ok": True, "importId": import_id, "items": [{k: skill[k] for k in ("id", "name", "description", "fileCount", "source")} for skill in staged]}
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}


def install_skills(root: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    import_id = payload.get("importId") if isinstance(payload, dict) else None
    selected = payload.get("selectedIds") if isinstance(payload, dict) else None
    if not isinstance(import_id, str) or not re.fullmatch(r"[0-9a-f]{32}", import_id):
        return {"ok": False, "error": "Invalid import selection."}
    if not isinstance(selected, list) or not selected:
        return {"ok": False, "error": "Select at least one skill to install."}
    root_path = Path(root).resolve()
    stage_dir = root_path / ".codex" / "skill-import-staging"
    stage_file = stage_dir / f"{import_id}.json"
    try:
        stage_dir.resolve().relative_to(root_path)
        stage_file.resolve().relative_to(stage_dir.resolve())
        if stage_file.is_symlink():
            raise ValueError("Staged import is invalid")
        stage = json.loads(stage_file.read_text(encoding="utf-8"))
        if stage.get("importId") != import_id:
            raise ValueError("Staged import did not match")
        by_id = {skill["id"]: skill for skill in stage["skills"]}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"ok": False, "error": "This import has expired. Select the files again."}
    codex_root = root_path / ".codex"
    skills_candidate = codex_root / "skills"
    try:
        codex_root.resolve().relative_to(root_path)
        skills_root = skills_candidate.resolve()
        skills_root.relative_to(root_path)
    except ValueError:
        return {"ok": False, "error": "The local skills folder points outside the workspace."}
    skills_root.mkdir(parents=True, exist_ok=True)
    results = []
    for skill_id in selected:
        skill = by_id.get(skill_id) if isinstance(skill_id, str) else None
        if not skill:
            results.append({"id": skill_id, "status": "error", "error": "Unknown skill selection."})
            continue
        temp = None
        try:
            target = skills_root / _slug(skill["name"])
            target.resolve().relative_to(skills_root)
            if target.exists():
                results.append({"id": skill_id, "name": skill["name"], "status": "skipped", "reason": "A skill with this folder name already exists."})
                continue
            temp = skills_root / f".import-{uuid.uuid4().hex}.tmp"
            temp.mkdir()
            for rel, encoded in skill["files"].items():
                safe = _safe_member(rel)
                if safe is None:
                    continue
                path = (temp / Path(*PurePosixPath(safe).parts)).resolve()
                path.relative_to(temp.resolve())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(encoded, validate=True))
            os.replace(temp, target)
            results.append({"id": skill_id, "name": skill["name"], "status": "installed", "path": str(target)})
        except Exception as exc:
            try:
                if temp is not None and temp.exists():
                    shutil.rmtree(temp)
            except OSError:
                pass
            results.append({"id": skill_id, "name": skill.get("name"), "status": "error", "error": str(exc)})
    try:
        stage_file.unlink()
    except OSError:
        pass
    return {"ok": all(r["status"] != "error" for r in results), "results": results, "items": results}
