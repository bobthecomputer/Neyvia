"""Developer-source apps and mods on the existing marketplace catalog and host.

Source snapshots are local owner installs, never signed-package attestations.
They are immutable, content addressed and activated by the existing atomic/file-lock helpers.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import urllib.request
import urllib.error
import base64
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from . import compat
from .durability import atomic_write_json

LIMIT = 200_000_000
IGNORE = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", ".neyvia", ".agent_control"}
COMMANDS = frozenset("source_marketplace_" + op + "_command" for op in ("list", "get", "install", "set", "update", "read", "remove", "updates"))
EXAMPLES = Path(__file__).resolve().parents[2] / "apps"
# Folders a mod or app may not be installed from: this install's own source, plus any the owner lists.
LIVE_ROOTS = [EXAMPLES.parent] + [Path(p) for p in os.environ.get("NEYVIA_LIVE_SOURCE_ROOTS", "").split(os.pathsep) if p]
ICON_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
ICON_LIMIT = 96_000
DEFINITIONS = [
    ("marketplace.list", "Read installed developer-source apps and mods with manuals, contracts and saved lifecycle state.", {}, []),
    ("marketplace.get", "Read one installed source app or mod's current immutable version and lifecycle state.", {"id": {"type": "string"}}, ["id"]),
    ("marketplace.install", "Install a trusted local folder or GitHub git URL into an immutable private snapshot; no dependency installs. A GitHub install is pinned to the commit its ref points at (recorded with a sha256 of the files); pass sha256 to refuse anything else. The item must declare the Neyvia API it supports.",
     {"source": {"type": "string"}, "ref": {"type": "string"}, "sha256": {"type": "string"}}, ["source"]),
    ("marketplace.set", "Enable or disable an installed source app or mod, protecting active dependencies.",
     {"id": {"type": "string"}, "enabled": {"type": "boolean"}}, ["id", "enabled"]),
    ("marketplace.update", "Update one item. preview=true shows the new commit and every file added, removed or changed without installing; a git item then updates only with that commit. Prior versions and the enabled state are kept.",
     {"id": {"type": "string"}, "preview": {"type": "boolean"}, "commit": {"type": "string"}, "sha256": {"type": "string"}}, ["id"]),
    ("marketplace.read", "Read an installed item's executable manual and declared contracts without running its code.",
     {"id": {"type": "string"}}, ["id"]),
    ("marketplace.remove", "Remove a disabled source app or mod that nothing depends on; its snapshots move aside, recoverable.",
     {"id": {"type": "string"}}, ["id"]),
]


def _inside(root, relative):
    target = (root / relative).resolve()
    target.relative_to(root.resolve())
    return target


API_BASE = "https://api.github.com"
CODELOAD_BASE = "https://codeload.github.com"
_HEX40 = re.compile(r"[0-9a-f]{40}")


def _github_hosts():
    # Overridable only through these module constants (the evidence script points them at a local stand-in).
    return {urlsplit(base).hostname for base in (API_BASE, CODELOAD_BASE)} | {"github.com"}


def _github_headers():
    """Anonymous by default for public repos; the owner's existing GitHub CLI login is reused unless
    NEYVIA_GITHUB_ANONYMOUS=1. No new token store, no secret output, nothing in snapshots."""
    headers = {"User-Agent": "neyvia-source-marketplace"}
    if os.environ.get("NEYVIA_GITHUB_ANONYMOUS") != "1" and shutil.which("gh"):
        credentials = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"], capture_output=True,
            text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if credentials.returncode == 0 and credentials.stdout.strip():
            headers["Authorization"] = "Bearer " + credentials.stdout.strip()
    return headers


class _GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        target = urlsplit(url)
        local = urlsplit(API_BASE).scheme != "https"
        if (target.scheme != "https" and not local) or target.hostname not in _github_hosts():
            raise ValueError("GitHub archive redirect escaped the allowed host")
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if redirected:
            redirected.remove_header("Authorization")
        return redirected


def _tree(root):
    files = []
    total = 0
    candidates = []
    for directory, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(folder for folder in folders if folder not in IGNORE and not folder.startswith(".env"))
        for folder in folders:
            path = Path(directory) / folder
            if path.is_symlink() or path.is_junction():
                raise ValueError("Source packages must not contain symbolic links or junctions")
        candidates.extend(Path(directory) / name for name in names if not name.startswith(".env"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if IGNORE.intersection(relative.parts) or any(part.startswith(".env") for part in relative.parts):
            continue
        if path.is_symlink() or path.is_junction():
            raise ValueError("Source packages must not contain symbolic links or junctions")
        if path.is_file():
            total += path.stat().st_size
            if total > LIMIT:
                raise ValueError("Source package exceeds 200 MB")
            files.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return files


class SourceMarketplace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = self.root / ".agent_control/source-marketplace"
        self.index = self.store / "catalog.json"

    def _load(self):
        return json.loads(self.index.read_text(encoding="utf-8")) if self.index.is_file() else {"schema": "neyvia.source-marketplace.v1", "items": {}}

    def _lock(self):
        from .module_marketplace import _module_file_lock
        self.store.mkdir(parents=True, exist_ok=True)
        return _module_file_lock(self.store / ".catalog")

    def _resolve_commit(self, owner, repo, ref, headers):
        """The full commit id a branch, tag or HEAD points at now. A 40-character id is used as is."""
        if _HEX40.fullmatch(ref):
            return ref
        url = API_BASE + "/repos/" + owner + "/" + repo + "/commits/" + urllib.request.quote(ref, safe="/")
        request = urllib.request.Request(url, headers={**headers, "Accept": "application/vnd.github.sha"})
        try:
            with urllib.request.build_opener(_GitHubRedirect()).open(request, timeout=30) as response:
                commit = response.read(100).decode("ascii", "replace").strip()
        except urllib.error.HTTPError as exc:
            raise ValueError("GitHub could not find " + ref + " in " + owner + "/" + repo + " (HTTP " + str(exc.code) + ")")
        if not _HEX40.fullmatch(commit):
            raise ValueError("GitHub did not return a commit id for " + ref)
        return commit

    def _source(self, source, ref, staging):
        """Returns (folder, pin). A GitHub source is resolved to one commit first and downloaded by that
        commit, so what is installed never depends on where a branch points later. Folders have no pin."""
        if source.startswith("https://"):
            match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?", source)
            if not match or not re.fullmatch(r"[\w./-]+", ref) or ".." in ref:
                raise ValueError("Use a GitHub HTTPS git URL and an explicit branch, tag or commit")
            headers = _github_headers()
            commit = self._resolve_commit(match[1], match[2], ref, headers)
            if "Authorization" in headers:
                url = API_BASE + "/repos/" + match[1] + "/" + match[2] + "/zipball/" + commit
            else:
                url = CODELOAD_BASE + "/" + match[1] + "/" + match[2] + "/zip/" + commit
            archive = staging / "source.zip"
            opener = urllib.request.build_opener(_GitHubRedirect())
            archive_hash = hashlib.sha256()
            with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response, archive.open("wb") as out:
                if int(response.headers.get("Content-Length") or 0) > LIMIT:
                    raise ValueError("Git source download exceeds 200 MB")
                size = 0
                while size < LIMIT:
                    chunk = response.read(min(65536, LIMIT - size))
                    if not chunk:
                        break
                    out.write(chunk)
                    archive_hash.update(chunk)
                    size += len(chunk)
                if size == LIMIT:
                    raise ValueError("Git source reached the 200 MB download limit")
            extracted = staging / "extracted"
            with zipfile.ZipFile(archive) as package:
                if sum(item.file_size for item in package.infolist()) > LIMIT:
                    raise ValueError("Expanded git source exceeds 200 MB")
                for item in package.infolist():
                    _inside(extracted, item.filename)
                    if stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError("Git source contains a symbolic link")
                package.extractall(extracted)
            roots = list(extracted.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError("Git source needs one repository root")
            return roots[0], {"commit": commit, "track": ref, "archiveSha256": archive_hash.hexdigest()}
        root = Path(source).expanduser().resolve()
        bundled = root.is_relative_to(EXAMPLES)  # this build's own example apps and mods
        for forbidden in LIVE_ROOTS:
            if root.is_relative_to(forbidden.resolve()) and not bundled:
                raise ValueError("Live Neyvia source is outside this install scope")
        if not root.is_dir():
            raise ValueError("Source folder is missing")
        return root, None

    def _describe(self, source):
        app = source / "neyvia.app.json"
        mod = source / "neyvia.module.json"
        if app.is_file() == mod.is_file():
            raise ValueError("Source needs exactly one neyvia.app.json or neyvia.module.json")
        descriptor = json.loads((app if app.is_file() else mod).read_text(encoding="utf-8"))
        identity = descriptor.get("instance") if app.is_file() else descriptor.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", identity):
            raise ValueError("Source item needs a unique lowercase instance/id")
        manual = descriptor.get("sourceManual", descriptor.get("manual", "manual.cl"))
        if not manual.endswith(".cl"):
            manual = "manual.cl"
        contract = descriptor.get("contract", "host-contract.json")
        if not _inside(source, manual).is_file() or not _inside(source, contract).is_file():
            raise ValueError("Source item needs its executable .cl manual and contracts JSON")
        text = _inside(source, manual).read_text(encoding="utf-8")
        if app.is_file() and descriptor.get("standard") == "CL-1.1" and text.startswith("L app v1"):
            if not all(re.search(r"^" + tag + r"(?:\s|:)", text, re.MULTILINE) for tag in ("G", "A")):
                raise ValueError("App manual needs observer goals and public actions")
        else:
            from .cl.manuals import cl_to_manual
            cl_to_manual(text)
        checks = json.loads(_inside(source, contract).read_text(encoding="utf-8"))
        dependencies = descriptor.get("dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", dep) or dep == identity for dep in dependencies):
            raise ValueError("Dependencies must be other source item IDs")
        entry = (descriptor.get("webRoot", "www") + "/index.html") if app.is_file() else ""
        if entry and not _inside(source, entry).is_file():
            raise ValueError("App needs its declared static web entry point")
        return {"id": identity, "name": descriptor.get("name", identity), "kind": "app" if app.is_file() else "mod",
            "summary": descriptor.get("purpose", descriptor.get("summary", "")), "manual": manual, "contract": contract,
            "contracts": checks.get("checks", []), "entrypoint": entry, "dependencies": dependencies,
            "services": descriptor.get("services", []), "descriptor": descriptor, "compat": compat.check(descriptor)}

    def _stage(self, source, ref, staging, expected_id=None, sha256=None):
        """Download or read a source and validate it. Nothing is installed or recorded yet."""
        local, pin = self._source(source, ref, staging)
        item = self._describe(local)
        if item["compat"]["status"] != "compatible":
            raise ValueError(item["id"] + ": " + item["compat"]["message"])
        from .module_marketplace import ModuleMarketplace
        if (ModuleMarketplace(self.root).module_root / item["id"]).is_dir():
            raise ValueError("Source identity conflicts with an installed signed package")
        if expected_id and item["id"] != expected_id:
            raise ValueError("Update changed item identity")
        files = _tree(local)
        full = hashlib.sha256(json.dumps(files).encode()).hexdigest()
        if sha256 and sha256.lower() != full:
            raise ValueError("The source does not match the expected sha256 (got " + full + ")")
        if pin:
            pin = {**pin, "treeSha256": full}
        return local, item, files, full, pin

    def diff(self, installed_hashes, files):
        """What changes between the installed snapshot and a candidate: plain path lists."""
        old, new = dict(installed_hashes), dict(files)
        return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)),
                "changed": sorted(path for path in set(old) & set(new) if old[path] != new[path])}

    def install(self, source, ref="HEAD", expected_id=None, sha256=None):
        staging = self.store / "staging" / uuid.uuid4().hex
        staging.mkdir(parents=True)
        try:
            return self._install(staging, source, ref, expected_id, sha256)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _install(self, staging, source, ref, expected_id, sha256):
        local, item, files, full, pin = self._stage(source, ref, staging, expected_id, sha256)
        version = full[:20]
        target = self.store / "items" / item["id"] / "versions" / version
        with self._lock():
            data = self._load()
            previous = data["items"].get(item["id"], {})
            if previous and previous["kind"] != item["kind"]:
                raise ValueError("Reinstall cannot change an app into a mod or a mod into an app")
            if previous.get("enabled") and any(self._project(data["items"][dep])["state"] != "active" if dep in data["items"] else True for dep in item["dependencies"]):
                raise ValueError("Update requires active dependencies")
            if not target.exists():
                payload = staging / "payload"
                for relative, digest in files:
                    destination = payload / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(local / relative, destination)
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        raise ValueError("Source changed during snapshot; retry install")
                target.parent.mkdir(parents=True, exist_ok=True)
                payload.rename(target)
            # A git source is stored by its commit, never by the branch name it was asked for.
            item.update(source=source, ref=pin["commit"] if pin else ref, version=version,
                        previousVersion=previous.get("version") if previous.get("version") != version else previous.get("previousVersion"),
                        enabled=previous.get("enabled", False), targetPath=str(target), sourceHashes=dict(files))
            if pin:
                item["pin"] = pin
            data["items"][item["id"]] = item
            atomic_write_json(self.index, data)
        return {"ok": True, "item": self._project(item)}

    def update(self, identity, commit=None, preview=False, sha256=None):
        """Explicit update. A git source is never moved on its own: preview shows the commit it would
        move to and every file that changes; applying it needs that commit (and may pin its sha256)."""
        item = self._load()["items"].get(identity)
        if not item:
            raise ValueError("Source item is not installed")
        git = str(item["source"]).startswith("https://")
        if not git:
            if preview:
                return self._preview(item, item["source"], item["ref"])
            return self.install(item["source"], item["ref"], expected_id=item["id"], sha256=sha256)
        track = (item.get("pin") or {}).get("track") or "HEAD"
        if preview:
            return self._preview(item, item["source"], track)
        if not commit:
            raise ValueError("Preview the update first, then apply it with the commit you reviewed")
        if not _HEX40.fullmatch(str(commit)):
            raise ValueError("Commit must be the full 40-character id from the preview")
        result = self.install(item["source"], commit, expected_id=item["id"], sha256=sha256)
        with self._lock():
            data = self._load()
            if data["items"].get(identity, {}).get("pin"):
                data["items"][identity]["pin"]["track"] = track  # keep following the same branch, but only when asked
                atomic_write_json(self.index, data)
        return result

    def _preview(self, item, source, ref):
        staging = self.store / "staging" / uuid.uuid4().hex
        staging.mkdir(parents=True)
        try:
            local, new, files, full, pin = self._stage(source, ref, staging, expected_id=item["id"])
            changes = self.diff(item["sourceHashes"], files)
            same = full[:20] == item["version"]
            return {"ok": True, "id": item["id"], "available": not same,
                    "from": {"version": item["version"], "commit": (item.get("pin") or {}).get("commit")},
                    "to": {"version": full[:20], "commit": (pin or {}).get("commit"), "sha256": full,
                           "archiveSha256": (pin or {}).get("archiveSha256")},
                    "diff": changes, "compat": new["compat"],
                    "apply": None if same else {"id": item["id"], **({"commit": pin["commit"]} if pin else {}), "sha256": full}}
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _project(self, item):
        try:
            valid = dict(_tree(Path(item["targetPath"]))) == item["sourceHashes"]
        except (ValueError, OSError):
            valid = False
        # Judged again on every read, so an app update that narrows the API range stops an old item cleanly.
        fit = compat.check(item.get("descriptor") or {})
        refused = fit["status"] == "incompatible"
        return {**{key: value for key, value in item.items() if key not in {"sourceHashes", "descriptor"}},
                "compat": fit,
                "state": "integrity-blocked" if not valid else "incompatible" if refused else "active" if item["enabled"] else "disabled", "origin": "developer-source",
                "moduleId": item["id"], "permissions": [str(p) for p in (item.get("descriptor") or {}).get("permissions", [])][:12], "publisher": {"id": "local-owner", "name": "Local source"},
                "manifest": {"services": item.get("services", [])},
                "runtime": {"entrypoint": item["entrypoint"]}, "applicationProjection": {
                    "capabilities": [{"operationId": item["id"] + ".open", "name": item["name"]}],
                    "surfaces": [{"kind": "web"}] if item["kind"] == "app" else [], "compatibility": "neyvia-sdk.v1"}}

    def catalog(self):
        return {"ok": True, "items": [self._project(item) for item in self._load()["items"].values()]}

    def _present(self, row, item, root=None):
        """Store presentation: icon, plain actions and source link. Read-only; never runs item code."""
        descriptor = item.get("descriptor") or {}
        root = Path(root or item["targetPath"])
        web_root = descriptor.get("webRoot", "www")
        manifest = {}
        try:
            if item["kind"] == "app" and _inside(root, web_root + "/manifest.webmanifest").is_file():
                manifest = json.loads(_inside(root, web_root + "/manifest.webmanifest").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        candidates = [descriptor["icon"]] if isinstance(descriptor.get("icon"), str) else []
        candidates += [web_root + "/" + icon["src"] for icon in manifest.get("icons", [])
                       if isinstance(icon, dict) and isinstance(icon.get("src"), str)]
        icon = None
        for relative in candidates:
            try:
                path = _inside(root, relative)
                kind = ICON_TYPES.get(path.suffix.lower())
                if kind and path.is_file() and path.stat().st_size <= ICON_LIMIT:
                    icon = "data:" + kind + ";base64," + base64.b64encode(path.read_bytes()).decode()
                    break
            except (ValueError, OSError):
                continue
        source = str(item.get("source") or "")
        repository = source if source.startswith("https://") else descriptor.get("sourceRepository")
        actions = [{"name": action.get("name", ""), "description": action.get("description", ""), "mutability": action.get("mutability", "")}
                   for action in descriptor.get("actions", []) if isinstance(action, dict)]
        upstream = descriptor.get("upstream") if isinstance(descriptor.get("upstream"), dict) else None
        return {**row, "icon": icon, "summary": row.get("summary") or manifest.get("description", ""),
                "permissions": [str(p) for p in descriptor.get("permissions", [])][:12],
                "upstream": {k: str(upstream[k]) for k in ("repository", "license", "version") if k in upstream} if upstream else None,
                "sourceKind": "github" if source.startswith("https://") else "folder",
                "sourceRepository": repository if isinstance(repository, str) and repository.startswith("https://") else None,
                "actions": actions}

    def examples(self, installed):
        """This build's own example apps and mods under apps/ that are not installed yet."""
        rows = []
        if not EXAMPLES.is_dir():
            return rows
        for folder in sorted(EXAMPLES.iterdir()):
            try:
                item = self._describe(folder)
            except (ValueError, OSError):
                continue
            if item["id"] in installed:
                continue
            row = {key: item[key] for key in ("id", "name", "kind", "summary", "dependencies", "services")}
            rows.append({**self._present(row, {**item, "source": str(folder)}, folder), "state": "available",
                         "source": str(folder), "origin": "example", "contracts": item["contracts"], "compat": item["compat"]})
        return rows

    def versions(self, item):
        folder = self.store / "items" / item["id"] / "versions"
        rows = []
        for path in folder.iterdir() if folder.is_dir() else []:
            if path.is_dir():
                rows.append({"version": path.name, "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
                             "current": path.name == item.get("version"), "previous": path.name == item.get("previousVersion")})
        return sorted(rows, key=lambda row: row["installedAt"], reverse=True)

    def updates(self):
        """Whether each local-folder source differs from its installed snapshot. Git sources are not fetched."""
        result = {}
        for identity, item in self._load()["items"].items():
            source = str(item.get("source") or "")
            if source.startswith("https://"):
                result[identity] = {"available": None, "reason": "git"}
                continue
            try:
                files = _tree(Path(source).expanduser().resolve())
                version = hashlib.sha256(json.dumps(files).encode()).hexdigest()[:20]
                result[identity] = {"available": version != item["version"], "reason": "folder"}
            except (ValueError, OSError):
                result[identity] = {"available": None, "reason": "source-missing"}
        return {"ok": True, "updates": result}

    def remove(self, identity):
        with self._lock():
            data = self._load()
            item = data["items"].get(identity)
            if not item:
                raise ValueError("Source item is not installed")
            if item["enabled"]:
                raise ValueError("Turn it off before removing it")
            dependants = [row["id"] for row in data["items"].values() if identity in row.get("dependencies", [])]
            if dependants:
                raise ValueError("Needed by: " + ", ".join(dependants))
            del data["items"][identity]
            atomic_write_json(self.index, data)
            folder = self.store / "items" / identity
            if folder.is_dir():
                # Recoverable: snapshots move aside instead of being deleted.
                aside = self.store / "removed" / (identity + "-" + uuid.uuid4().hex[:8])
                aside.parent.mkdir(parents=True, exist_ok=True)
                folder.rename(aside)
        return {"ok": True, "removed": identity,
                "item": {"id": identity, "name": item["name"], "kind": item["kind"], "state": "removed"}}

    def set_enabled(self, identity, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be boolean")
        with self._lock():
            data = self._load()
            if identity not in data["items"]:
                raise ValueError("Source item is not installed")
            item = data["items"][identity]
            state = self._project(item)
            if state["state"] == "integrity-blocked":
                raise ValueError("Installed source changed; update or reinstall it")
            if enabled and state["state"] == "incompatible":
                raise ValueError(state["compat"]["message"])
            dependencies = item["dependencies"]
            blocked = [dep for dep in dependencies if not data["items"].get(dep, {}).get("enabled")] if enabled else [
                row["id"] for row in data["items"].values() if identity in row["dependencies"] and row["enabled"]]
            if blocked:
                raise ValueError("Active dependency: " + ", ".join(blocked))
            item["enabled"] = enabled
            atomic_write_json(self.index, data)
        return {"ok": True, "item": self._project(item)}

    def call(self, operation, args):
        if operation == "list":
            data = self._load()["items"]
            items = [self._present(self._project(item), item) for item in data.values()]
            return {"ok": True, "items": items, "available": self.examples(set(data))}
        if operation == "install":
            return self.install(args["source"], args.get("ref") or "HEAD", sha256=args.get("sha256"))
        if operation == "updates":
            return self.updates()
        data = self._load()
        item = data["items"].get(args["id"])
        if not item and operation == "read" and re.fullmatch(r"[a-z][a-z0-9-]*", str(args["id"])):
            # An example not installed yet: its manual and contracts, read from this build, never run.
            folder = EXAMPLES / str(args["id"])
            example = self._describe(folder) if folder.is_dir() and folder.parent == EXAMPLES else None
            if example and example["id"] == args["id"]:
                return {"ok": True, "id": example["id"], "manual": _inside(folder, example["manual"]).read_text(encoding="utf-8"),
                        "contracts": json.loads(_inside(folder, example["contract"]).read_text(encoding="utf-8")), "versions": []}
        if not item:
            raise ValueError("Source item is not installed")
        if operation == "set":
            return self.set_enabled(args["id"], args["enabled"])
        if operation == "get":
            return {"ok": True, "item": self._present(self._project(item), item)}
        if operation == "remove":
            return self.remove(args["id"])
        if operation == "update":
            return self.update(args["id"], commit=args.get("commit"), preview=bool(args.get("preview")), sha256=args.get("sha256"))
        if operation == "read":
            target = Path(item["targetPath"])
            return {"ok": True, "id": item["id"], "manual": _inside(target, item["manual"]).read_text(encoding="utf-8"),
                    "contracts": json.loads(_inside(target, item["contract"]).read_text(encoding="utf-8")),
                    "versions": self.versions(item)}
        raise ValueError("Unknown source marketplace operation")


def handle_command(backend, command, args):
    if command not in COMMANDS:
        raise ValueError("Unknown source marketplace command")
    return SourceMarketplace(backend.root).call(command[len("source_marketplace_"):-len("_command")], args)


def authorize_app(backend, handler):
    identity = handler.headers.get("X-Neyvia-App")
    if identity:
        row = next((item for item in SourceMarketplace(backend.root).catalog()["items"] if item["id"] == identity), None)
        if not row or row["kind"] != "app" or row["state"] != "active":
            raise ValueError("This marketplace app is disabled or unavailable")


def serve_sdk(backend, handler):
    # Use the same owner session boundary as hosted application assets.
    if not backend.authenticated_session(handler):
        handler.send_response(401)
        handler.end_headers()
        return
    path = Path(__file__).resolve().parents[2] / "packages/neyvia-sdk/index.js"
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/javascript; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "private, no-cache")
    handler.end_headers()
    handler.wfile.write(body)
