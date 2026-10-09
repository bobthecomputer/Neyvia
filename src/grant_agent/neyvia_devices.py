"""Owner-approved, scoped PC file access over the tailnet.

Inbound capabilities are salted hashes. Outbound capabilities are Windows
DPAPI blobs, bound to the current OS user; no plaintext token reaches disk.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from .native_pairing import _digest
from .neyvia_files_tools import TEXT_EXT, entry, guard, list_folder, stat_path
from .ui_command_bus import bus_for, now

CHUNK = 8 * 1024 * 1024
MAX_TOTAL = 50 * 1024 ** 3
TEXT = {"type": "string"}
DEVICE = {"device": TEXT}
DEFINITIONS = [
    ("list", "List paired PCs, requests and recent transfers.", {}, []),
    ("files.list", "Browse only the folders another paired PC shares.", {**DEVICE, "path": TEXT, "showHidden": {"type": "boolean"}}, ["device"]),
    ("files.stat", "Inspect a shared remote file; optional preview and SHA-256.", {**DEVICE, "path": TEXT, "preview": {"type": "boolean"}, "hash": {"type": "boolean"}}, ["device", "path"]),
    ("files.read", "Read up to 1 MiB of a shared file at a byte offset.", {**DEVICE, "path": TEXT, "offset": {"type": "integer"}, "length": {"type": "integer"}}, ["device", "path"]),
    ("files.fetch", "Take a remote file or folder into a local folder without overwriting.", {**DEVICE, "from": TEXT, "to": TEXT, "wait": {"type": "number"}}, ["device", "from"]),
    ("files.send", "Send a local file or folder to the paired PC inbox or an allowed writable folder; first use needs approval.", {**DEVICE, "from": TEXT, "to": TEXT, "wait": {"type": "number"}}, ["device", "from"]),
    ("transfers", "Inspect transfers, including progress, errors and verified SHA-256.", {"id": TEXT}, []),
]


def tool_specs(spec_type):
    return [spec_type(name="neyvia.devices." + name, description=description, category="neyvia-devices",
                     input_schema={"type": "object", "properties": props, "required": required},
                     mutability_class="external_action" if name == "files.send" else "artifact_write" if name == "files.fetch" else "read",
                     capabilities=("neyvia.devices." + name,), parallel_safe=False)
            for name, description, props, required in DEFINITIONS]


class PeerError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _protect(value, decrypt=False):
    if os.name != "nt":
        raise PeerError("Pairing needs OS protected secret storage on this platform")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    data = base64.b64decode(value) if decrypt else value.encode()
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise PeerError("OS protected secret storage failed")
    try:
        result = ctypes.string_at(output.data, output.size)
        return result.decode() if decrypt else base64.b64encode(result).decode()
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(CHUNK):
            digest.update(data)
    return digest.hexdigest()


def _inside(path, base):
    return path == base or base in path.parents


def _filename(value):
    name = str(value)
    if not name or name in {".", ".."} or any(char in name for char in "/\\:"):
        raise PeerError("Use a file or folder name")
    return name


def _local(root, value):
    text = str(value or "")
    normalized = text.replace("\\", "/").lower().rstrip("/")
    forbidden = ("c:/users/user/projects/neyvia", "c:/users/user/projects/neyvia-next")
    if any(normalized == base or normalized.startswith(base + "/") for base in forbidden):
        raise PeerError("That tree is protected", 403)
    if ".." in normalized.split("/"):
        raise PeerError("That path is protected", 403)
    path = guard(root, text)
    resolved = str(path).replace("\\", "/").lower()
    if any(resolved == base or resolved.startswith(base + "/") for base in forbidden):
        raise PeerError("That tree is protected", 403)
    # A selected workspace can itself live under an agent scratch directory.
    # Protect secret/state descendants of that workspace; its already-selected
    # ancestry is not a share. Outside it, keep the full absolute-path guard.
    workspace = Path(root).resolve()
    parts = path.relative_to(workspace).parts if path.is_relative_to(workspace) else path.parts
    if any(part.lower() in {".agent_control", ".neyvia", ".ssh", ".codex", ".claude", "credentials"} for part in parts):
        raise PeerError("That path is protected", 403)
    return path


def _unique(path):
    original, number = path, 2
    while path.exists() or path.with_name(path.name + ".neyvia-part").exists():
        path = original.with_name(f"{original.stem} ({number}){original.suffix}")
        number += 1
    return path


def _tailnet(ip):
    address = ipaddress.ip_address(ip.split("%")[0])
    return address in ipaddress.ip_network("100.64.0.0/10") or address in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def network_allowed(ip, headers):
    try:
        address = ipaddress.ip_address(ip.split("%")[0])
        return _tailnet(ip) or (address.is_loopback and (os.environ.get("NEYVIA_PEER_ALLOW_LOOPBACK") == "1" or bool(headers.get("Tailscale-User-Login"))))
    except ValueError:
        return False


def _url(value):
    parsed = urlsplit(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise PeerError("Use a tailnet Neyvia URL")
    addresses = {row[4][0] for row in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    if not addresses or not all(_tailnet(ip) or (ipaddress.ip_address(ip).is_loopback and os.environ.get("NEYVIA_PEER_ALLOW_LOOPBACK") == "1") for ip in addresses):
        raise PeerError("Only tailnet addresses are allowed", 403)
    return str(value).rstrip("/")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PeerError("Peer redirects are not allowed", 403)


def _request(url, route, token="", body=None, method=None, headers=None, timeout=15, raw=False):
    url = _url(url)
    request_headers = {"Authorization": "Neyvia-Peer " + token} if token else {}
    request_headers.update(headers or {})
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    request = Request(url + "/api/peer/v1/" + route, data=body, method=method, headers=request_headers)
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            if raw:
                data = response.read(CHUNK + 1)
                if len(data) > CHUNK:
                    raise PeerError("Peer chunk exceeds the limit")
                return data, dict(response.headers)
            result = json.load(response)
            if result.get("ok") is False:
                raise PeerError(result.get("error") or "Peer request failed")
            return result
    except HTTPError as exc:
        try:
            message = json.load(exc).get("error")
        except (ValueError, OSError):
            message = "Peer request failed"
        raise PeerError(message, exc.code) from None


class Devices:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = self.root / ".neyvia" / "devices"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.workers = set()
        self.rates = {}
        self.hashes = {}
        self.progress_events = {}
        with self.state() as state:
            if not state.get("here"):
                state["here"] = {"id": uuid.uuid4().hex, "name": socket.gethostname()}
            for transfer in state["transfers"].values():
                if transfer["status"] in {"running", "queued", "verifying"}:
                    transfer.update(status="paused", error="Backend restarted; resume continues from verified chunks")
            waiting = [peer["id"] for peer in state["peers"].values() if peer.get("status") == "waiting"]
        for identity in waiting:
            threading.Thread(target=self.poll, args=(identity,), daemon=True).start()

    @contextmanager
    def state(self):
        import msvcrt
        with self.lock, (self.folder / "state.lock").open("a+b") as lock:
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            path = self.folder / "peers.json"
            try:
                state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                for key in ("peers", "requests", "transfers", "uploads"):
                    state.setdefault(key, {})
                try:
                    yield state
                finally:
                    _atomic(path, state)
                    _atomic(self.folder / "transfers.json", state["transfers"])
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def public(self, peer):
        return {key: peer.get(key) for key in ("id", "name", "os", "online", "status", "url", "lastSeen", "pairedAt", "theyShare", "iShare", "error")}

    def snapshot(self):
        with self.state() as state:
            requests = [{key: row[key] for key in ("id", "fromId", "fromName", "fromUrl", "code", "at", "expiresAt")}
                        for row in state["requests"].values() if row["status"] == "pending" and row["expires"] > time.time()]
            return {"here": state["here"], "devices": [self.public(row) for row in state["peers"].values()], "requests": requests,
                    "transfers": sorted(state["transfers"].values(), key=lambda row: row["startedAt"], reverse=True)[:30],
                    "tailnet": state.get("tailnet", "missing"), "detail": state.get("detail", "Choose Find PCs to refresh the tailnet roster")}

    def shares(self, args):
        folders = args.get("folders", [{"path": os.environ.get("NEYVIA_PEER_DEFAULT_SHARE") or str(Path.home()), "write": False}])
        if not isinstance(folders, list) or len(folders) > 30:
            raise PeerError("Choose at most 30 shared folders")
        normalized = []
        for row in folders:
            path = _local(self.root, row["path"])
            if not path.is_dir():
                raise PeerError("Shared paths must be folders")
            normalized.append({"name": path.name, "path": str(path), "write": bool(row.get("write"))})
        inbox = _local(self.root, args.get("inbox") or os.environ.get("NEYVIA_PEER_DEFAULT_INBOX") or Path.home() / "Downloads" / "Neyvia inbox")
        inbox.mkdir(parents=True, exist_ok=True)
        return {"folders": normalized, "inbox": str(inbox), "writeAnywhere": bool(args.get("writeAnywhere"))}

    def peer(self, identity):
        with self.state() as state:
            peer = state["peers"].get(str(identity))
            if not peer or peer["status"] != "paired":
                raise PeerError("Pair with that PC first", 401)
            return dict(peer)

    def auth(self, authorization):
        if not authorization.startswith("Neyvia-Peer "):
            raise PeerError("Bad or revoked pair token", 401)
        token = authorization.removeprefix("Neyvia-Peer ")
        identity, _, secret = token.partition(".")
        with self.state() as state:
            for peer in state["peers"].values():
                if peer.get("pairId") == identity and peer["status"] == "paired" and hmac.compare_digest(_digest(secret, peer["salt"]), peer["hash"]):
                    peer["lastSeen"] = now()
                    return dict(peer)
        raise PeerError("Bad or revoked pair token", 401)

    def remote(self, peer, route, **kwargs):
        return _request(peer["url"], route, _protect(peer["outbound"], True), **kwargs)

    def scoped(self, peer, value, write=False):
        path = _local(self.root, value)
        shares = peer["iShare"]
        inbox = Path(shares["inbox"])
        if write:
            allowed = _inside(path, inbox) or shares["writeAnywhere"] or any(row["write"] and _inside(path, Path(row["path"])) for row in shares["folders"])
            if not allowed:
                raise PeerError(f"That PC only takes files in its inbox ({inbox})", 403)
        elif not (_inside(path, inbox) or any(_inside(path, Path(row["path"])) for row in shares["folders"])):
            raise PeerError("That folder is not shared with this pair", 403)
        return path

    def incoming(self, body, ip):
        current = time.time()
        events = [stamp for stamp in self.rates.get(ip, []) if current - stamp < 60]
        if len(events) >= 5:
            raise PeerError("Too many pairing requests; try again in a minute", 429)
        self.rates[ip] = events + [current]
        url = _url(body.get("fromUrl"))
        token = str(body.get("token") or "")
        if len(token) < 40 or "." not in token or not str(body.get("code", "")).isdigit() or len(str(body["code"])) != 4:
            raise PeerError("Invalid pairing request")
        with self.state() as state:
            if sum(row["status"] == "pending" and row["expires"] > current for row in state["requests"].values()) >= 5:
                raise PeerError("Five requests are already waiting", 429)
            identity, salt = uuid.uuid4().hex, secrets.token_hex(16)
            row = {"id": identity, "fromId": str(body["fromId"]), "fromName": str(body["fromName"])[:100], "fromUrl": url,
                   "code": str(body["code"]), "at": now(), "expiresAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current + 600)),
                   "expires": current + 600, "status": "pending", "outbound": _protect(token), "proofSalt": salt, "proofHash": _digest(token, salt), "fromShare": body.get("share")}
            state["requests"][identity] = row
            # An unauthenticated request may ask for a new pairing, but cannot
            # replace an established capability before the owner approves it.
            if state["peers"].get(row["fromId"], {}).get("status") != "paired":
                state["peers"][row["fromId"]] = {"id": row["fromId"], "name": row["fromName"], "url": url, "status": "asked-you", "online": True, "lastSeen": now()}
        bus_for(self.root).emit("devices.pair_request", {"id": identity, "fromName": row["fromName"], "code": row["code"]})
        return {"request": {key: row[key] for key in ("id", "fromId", "fromName", "fromUrl", "code", "at", "expiresAt")}}

    def status(self, identity, authorization):
        if not authorization.startswith("Neyvia-Pair "):
            raise PeerError("The requesting PC's proof is required", 401)
        proof = authorization.removeprefix("Neyvia-Pair ")
        with self.state() as state:
            row = state["requests"].get(identity)
            if not row or not hmac.compare_digest(_digest(proof, row["proofSalt"]), row["proofHash"]):
                raise PeerError("The requesting PC's proof is required", 401)
            if row["expires"] < time.time() and row["status"] == "pending":
                row["status"] = "expired"
            result = {"status": row["status"]}
            if row["status"] == "approved" and row.get("issued"):
                result.update(token=_protect(row.pop("issued"), True), share=state["peers"][row["fromId"]]["iShare"])
            return result

    def poll(self, identity):
        while True:
            with self.state() as state:
                peer = dict(state["peers"].get(identity, {}))
            if peer.get("status") != "waiting":
                return
            if peer.get("expires", 0) < time.time():
                with self.state() as state:
                    state["peers"][identity].update(status="available", error="Pair request expired")
                    state["peers"][identity].pop("proof", None)
                bus_for(self.root).emit("devices.changed", {"device": identity, "status": "expired"})
                return
            try:
                result = _request(peer["url"], "pair/status?" + urlencode({"request": peer["request"]}),
                                  headers={"Authorization": "Neyvia-Pair " + _protect(peer["proof"], True)})
                if result["status"] != "pending":
                    with self.state() as state:
                        row = state["peers"].get(identity)
                        if row and row["status"] == "waiting":
                            if result["status"] == "approved" and result.get("token"):
                                row.update(status="paired", pairedAt=now(), outbound=_protect(result["token"]), theyShare=result["share"])
                            else:
                                row.update(status="available", error=result["status"])
                            row.pop("proof", None)
                    bus_for(self.root).emit("devices.changed", {"device": identity, "status": result["status"]})
                    return
            except (OSError, PeerError):
                pass
            time.sleep(2)

    def pair(self, args):
        with self.state() as state:
            old = state["peers"].get(str(args.get("device")), {})
            here = state["here"]
            url = _url(args.get("url") or old.get("url"))
            self_url = state.get("url")
        if not self_url:
            raise PeerError("This backend has no peer URL yet")
        hello = _request(url, "hello")
        if not hello.get("neyvia") or hello["id"] == here["id"]:
            raise PeerError("Choose another Neyvia PC")
        with self.state() as state:
            if state["peers"].get(hello["id"], {}).get("status") == "paired":
                raise PeerError("That PC is already paired", 409)
        pair_id, secret, salt = uuid.uuid4().hex, secrets.token_urlsafe(40), secrets.token_hex(16)
        token = pair_id + "." + secret
        code = f"{secrets.randbelow(10000):04d}"
        share = self.shares({})
        if old.get("status") == "paired":
            raise PeerError("That PC is already paired", 409)
        response = _request(url, "pair/request", body={"fromId": here["id"], "fromName": here["name"], "fromUrl": self_url, "code": code, "token": token, "share": share})
        with self.state() as state:
            peer = {"id": hello["id"], "name": args.get("name") or hello["name"], "os": old.get("os"), "online": True,
                    "status": "waiting", "url": url, "lastSeen": now(), "iShare": share, "theyShare": None,
                    "pairId": pair_id, "salt": salt, "hash": _digest(secret, salt), "proof": _protect(token),
                    "request": response["request"]["id"], "expires": time.time() + 600}
            if state["peers"].get(hello["id"], {}).get("status") == "paired":
                raise PeerError("That PC is already paired", 409)
            state["peers"][hello["id"]] = peer
        threading.Thread(target=self.poll, args=(hello["id"],), daemon=True).start()
        return {"device": self.public(peer), "code": code}

    def approve(self, args):
        share = self.shares(args)
        with self.state() as state:
            row = state["requests"].get(str(args.get("request")))
            if not row or row["status"] != "pending" or row["expires"] < time.time():
                raise PeerError("That request is no longer waiting", 409)
            pair_id, secret, salt = uuid.uuid4().hex, secrets.token_urlsafe(40), secrets.token_hex(16)
            token = pair_id + "." + secret
            peer = {"id": row["fromId"], "name": row["fromName"], "url": row["fromUrl"], "online": True, "status": "paired",
                    "lastSeen": now(), "pairedAt": now(), "pairId": pair_id, "salt": salt, "hash": _digest(secret, salt),
                    "outbound": row["outbound"], "iShare": share, "theyShare": row.get("fromShare")}
            state["peers"][peer["id"]] = peer
            row.update(status="approved", issued=_protect(token))
        bus_for(self.root).emit("devices.changed", {"device": peer["id"], "status": "approved"})
        return {"device": self.public(peer)}

    def revoke(self, identity, notify=True):
        with self.state() as state:
            old = state["peers"].pop(identity, None)
            for row in state["requests"].values():
                if row["fromId"] == identity:
                    row.update(status="denied")
                    row.pop("issued", None)
                    row.pop("outbound", None)
        if notify and old and old.get("outbound"):
            try:
                self.remote(old, "revoke", body={})
            except (OSError, PeerError):
                pass
        bus_for(self.root).emit("devices.changed", {"device": identity, "status": "revoked"})
        bus_for(self.root).put("grant:devices:send:" + identity, False)
        return {"ok": True}

    def file_list(self, peer, args):
        share = peer["iShare"]
        places = [{**row, "kind": "shared"} for row in share["folders"]] + [{"name": "Inbox", "path": share["inbox"], "kind": "inbox", "write": True}]
        if not args.get("path"):
            return {"ok": True, "device": peer["id"], "path": None, "places": places, "entries": [], "share": share}
        path = self.scoped(peer, args["path"])
        result = list_folder(self.root, {**args, "path": str(path)})
        result["entries"] = [row for row in result["entries"] if self._readable(peer, row["path"])]
        place = max((row for row in places if _inside(path, Path(row["path"]))), key=lambda row: len(row["path"]))
        result.update(device=peer["id"], place=place, parent=None if path == Path(place["path"]) else str(path.parent))
        result["crumbs"] = [row for row in result["crumbs"] if _inside(Path(row["path"]), Path(place["path"]))]
        return result

    def _readable(self, peer, path):
        try:
            self.scoped(peer, path)
            return True
        except (ValueError, OSError):
            return False

    def destination(self, peer, args):
        # Writes may be permitted where reads are not. Reserve a destination
        # without exposing an unshared folder's directory listing.
        folder = self.scoped(peer, args["path"], write=True)
        name = _filename(args["name"])
        if not folder.is_dir():
            raise PeerError("Send needs an existing destination folder")
        with self.state():
            target = _unique(folder / name)
            if args.get("kind") == "folder":
                while True:
                    try:
                        target.mkdir()
                        break
                    except FileExistsError:
                        target = _unique(target)
        return {"path": str(target)}

    def file_stat(self, peer, args):
        path = self.scoped(peer, args["path"])
        result = stat_path(self.root, {**args, "path": str(path)})
        result["device"] = peer["id"]
        if args.get("hash") and path.is_file():
            if path.stat().st_size > 2 * 1024 ** 3:
                raise PeerError("Hash inspection is limited to 2 GB")
            result["sha256"] = self.file_hash(path)
        return result

    def file_hash(self, path):
        info = path.stat()
        key = (str(path), info.st_size, info.st_mtime_ns)
        if key not in self.hashes:
            self.hashes[key] = _hash(path)
            if len(self.hashes) > 1000:
                self.hashes = {key: self.hashes[key]}
        return self.hashes[key]

    def tree(self, peer, path):
        base = self.scoped(peer, path)
        files, total = [], 0
        if not base.is_dir():
            raise PeerError("Choose a folder")
        for directory, folders, names in os.walk(base, followlinks=False):
            folders[:] = [name for name in folders if self._readable(peer, Path(directory) / name) and not (Path(directory) / name).is_symlink()]
            for name in names:
                file = Path(directory) / name
                if not self._readable(peer, file):
                    continue
                info = file.stat()
                total += info.st_size
                if len(files) >= 5000 or total > MAX_TOTAL:
                    raise PeerError("Folder copies are limited to 5000 files and 50 GB")
                files.append({"rel": file.relative_to(base).as_posix(), "size": info.st_size, "mtime": info.st_mtime_ns})
        return {"files": files}

    def upload(self, peer, query, data, chunk_hash):
        identity = query["id"]
        if not identity.isalnum() or len(identity) > 100:
            raise PeerError("Invalid transfer id")
        path = self.scoped(peer, query["path"], write=True)
        offset, total = int(query["offset"]), int(query["total"])
        digest = hashlib.sha256(data).hexdigest()
        if len(data) > CHUNK or not 0 <= offset <= total <= MAX_TOTAL or offset + len(data) > total:
            raise PeerError("Invalid upload range")
        if not chunk_hash or not hmac.compare_digest(digest, chunk_hash):
            raise PeerError("Chunk SHA-256 mismatch", 409)
        with self.state() as state:
            row = state["uploads"].get(identity)
            if not row:
                path.parent.mkdir(parents=True, exist_ok=True)
                path = _unique(path)
                row = {"device": peer["id"], "path": str(path), "requested": query["path"], "total": total, "chunks": []}
                state["uploads"][identity] = row
            if row["device"] != peer["id"] or row["requested"] != query["path"] or row["total"] != total:
                raise PeerError("Transfer id belongs to another file", 409)
            if row.get("finished"):
                raise PeerError("That upload is finished", 409)
            target = self.scoped(peer, row["path"], write=True)
            received = _verified_part(target, row)
            if offset != received:
                raise PeerError(f"Resume at verified offset {received}", 409)
            part = target.with_name(target.name + ".neyvia-part")
            with part.open("ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            row["chunks"].append({"length": len(data), "sha256": digest})
            _atomic(part.with_name(part.name + ".json"), row)
            return {"received": offset + len(data), "sha256": digest}

    def upload_status(self, peer, identity):
        with self.state() as state:
            row = state["uploads"].get(identity)
            if not row:
                return {"received": 0}
            if row["device"] != peer["id"]:
                raise PeerError("That transfer belongs to another PC", 403)
            path = self.scoped(peer, row["path"], True)
            if row.get("finished"):
                return {"received": row["total"], "finished": True, "path": row["path"], "sha256": row["sha256"]}
            return {"received": _verified_part(path, row)}

    def finish(self, peer, args):
        with self.state() as state:
            row = state["uploads"].get(args["id"])
            if not row or row["device"] != peer["id"]:
                raise PeerError("Unknown upload", 404)
            path = self.scoped(peer, row["path"], True)
            if row.get("finished"):
                return {"ok": True, "path": str(path)}
            part = path.with_name(path.name + ".neyvia-part")
            if _verified_part(path, row) != row["total"] or not part.exists() or not hmac.compare_digest(_hash(part), str(args.get("sha256"))):
                _drop_part(path)
                state["uploads"].pop(args["id"])
                raise PeerError("File SHA-256 mismatch; partial copy dropped", 409)
            destination = _unique_finished(path)
            destination = _publish(part, destination)
            part.with_name(part.name + ".json").unlink(missing_ok=True)
            row.update(finished=True, path=str(destination), sha256=args["sha256"])
            return {"ok": True, "path": str(destination)}


def _verified_part(target, row):
    part = target.with_name(target.name + ".neyvia-part")
    offset, good = 0, []
    if part.exists():
        with part.open("r+b") as stream:
            for chunk in row.get("chunks", []):
                data = stream.read(chunk["length"])
                if len(data) != chunk["length"] or hashlib.sha256(data).hexdigest() != chunk["sha256"]:
                    break
                offset += len(data)
                good.append(chunk)
            stream.truncate(offset)
    row["chunks"] = good
    return offset


def _drop_part(path):
    part = path.with_name(path.name + ".neyvia-part")
    part.unlink(missing_ok=True)
    part.with_name(part.name + ".json").unlink(missing_ok=True)


def _unique_finished(path):
    original, index = path, 2
    while path.exists():
        path = original.with_name(f"{original.stem} ({index}){original.suffix}")
        index += 1
    return path


def _publish(part, target):
    # Hard link atomically refuses a destination that appeared after naming.
    while True:
        try:
            os.link(part, target)
            part.unlink()
            return target
        except FileExistsError:
            target = _unique_finished(target)


_instances = {}
_instances_lock = threading.Lock()


def devices_for(root):
    key = str(Path(root).resolve())
    with _instances_lock:
        if key not in _instances:
            _instances[key] = Devices(root)
        return _instances[key]


def bind_peer_backend(backend, handler):
    devices = devices_for(backend.root)
    host = str(handler.headers.get("Host") or "")
    parsed = urlsplit("http://" + host)
    if parsed.hostname:
        try:
            url = _url(("https" if isinstance(handler.connection, __import__("ssl").SSLSocket) else "http") + "://" + host)
            with devices.state() as state:
                state["url"] = url
        except (OSError, ValueError):
            pass
    return devices


def _transfer_update(service, identity, **changes):
    with service.state() as state:
        row = state["transfers"][identity]
        previous = row["status"]
        if row["status"] in {"paused", "cancelled"}:
            changes.pop("status", None)
        row.update(changes, updatedAt=now())
        result = dict(row)
    current = time.monotonic()
    if previous != result["status"] or not changes or current - service.progress_events.get(identity, 0) >= 1:
        service.progress_events[identity] = current
        bus_for(service.root).emit("devices.transfer", result)
    return result


def _active(service, identity):
    with service.state() as state:
        return state["transfers"][identity]["status"] not in {"paused", "cancelled"}


def _copy_worker(service, identity):
    try:
        with service.state() as state:
            transfer = dict(state["transfers"][identity])
        peer = service.peer(transfer["device"])
        progress, completed, started = 0, 0, time.monotonic()
        _transfer_update(service, identity, status="running", error="")
        for number, item in enumerate(transfer["plan"]):
            if not _active(service, identity):
                return
            upload_id = identity + str(number)
            if transfer["direction"] == "send":
                origin = _local(service.root, item["from"])
                digest = _hash(origin)
                info = origin.stat()
                if info.st_size != item["size"] or info.st_mtime_ns != item["mtime"]:
                    raise PeerError("The source changed; start a new transfer")
                status = service.remote(peer, "files/upload?" + urlencode({"id": upload_id}))
                offset = int(status["received"])
                if status.get("finished"):
                    if status.get("sha256") != digest:
                        raise PeerError("The completed remote file has a different SHA-256")
                    offset = item["size"]
                else:
                    with origin.open("rb") as stream:
                        stream.seek(offset)
                        while offset < item["size"] or (item["size"] == 0 and offset == 0):
                            if not _active(service, identity):
                                return
                            data = stream.read(min(CHUNK, item["size"] - offset))
                            if not data and item["size"]:
                                raise PeerError("The source changed while copying")
                            chunk_hash = hashlib.sha256(data).hexdigest()
                            result = service.remote(peer, "files/upload?" + urlencode({"id": upload_id, "path": item["to"], "offset": offset, "total": item["size"]}),
                                                    method="PUT", body=data, headers={"X-Neyvia-Chunk-Sha256": chunk_hash})
                            if result.get("sha256") != chunk_hash or int(result["received"]) != offset + len(data):
                                raise PeerError("The remote PC did not verify this chunk")
                            offset += len(data)
                            _transfer_update(service, identity, done=progress + offset, bytesPerSecond=int((progress + offset) / max(.001, time.monotonic() - started)))
                            if not item["size"]:
                                break
                    if origin.stat().st_mtime_ns != info.st_mtime_ns:
                        raise PeerError("The source changed while copying")
                    if not _active(service, identity):
                        return
                    _transfer_update(service, identity, status="verifying")
                    finished = service.remote(peer, "files/upload/finish", body={"id": upload_id, "sha256": digest})
                    item["actualTo"] = finished["path"]
            else:
                target = _local(service.root, item["to"])
                if item.get("finished"):
                    if target.is_file() and _hash(target) == item["sha256"]:
                        progress += item["size"]
                        completed += 1
                        continue
                    raise PeerError("A completed local copy changed; start a new transfer")
                target.parent.mkdir(parents=True, exist_ok=True)
                metadata_path = target.with_name(target.name + ".neyvia-part.json")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {"chunks": [], "from": item["from"], "size": item["size"]}
                if metadata.get("from") != item["from"] or metadata.get("size") != item["size"]:
                    raise PeerError("Partial file belongs to a different source")
                offset = _verified_part(target, metadata)
                part = target.with_name(target.name + ".neyvia-part")
                digest = metadata.get("sha256")
                while offset < item["size"] or (item["size"] == 0 and not digest):
                    if not _active(service, identity):
                        return
                    data, headers = service.remote(peer, "files/raw?" + urlencode({"path": item["from"], "offset": offset, "length": min(CHUNK, item["size"] - offset)}), raw=True)
                    if int(headers["X-Neyvia-Size"]) != item["size"] or str(headers["X-Neyvia-Mtime"]) != str(item["mtime"]):
                        raise PeerError("The remote source changed; start a new transfer")
                    whole_hash = headers["X-Neyvia-Sha256"]
                    if digest and whole_hash != digest:
                        raise PeerError("The remote source changed between chunks")
                    digest = whole_hash
                    chunk_hash = hashlib.sha256(data).hexdigest()
                    if chunk_hash != headers["X-Neyvia-Chunk-Sha256"]:
                        raise PeerError("Remote chunk SHA-256 mismatch")
                    if len(data) != min(CHUNK, item["size"] - offset):
                        raise PeerError("Remote chunk range is incomplete")
                    with part.open("ab") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    metadata["chunks"].append({"length": len(data), "sha256": chunk_hash})
                    metadata["sha256"] = digest
                    _atomic(metadata_path, metadata)
                    offset += len(data)
                    _transfer_update(service, identity, done=progress + offset, bytesPerSecond=int((progress + offset) / max(.001, time.monotonic() - started)))
                    if not item["size"]:
                        break
                if not _active(service, identity):
                    return
                _transfer_update(service, identity, status="verifying")
                if _hash(part) != digest:
                    _drop_part(target)
                    raise PeerError("File SHA-256 mismatch; partial copy dropped", 409)
                target = _publish(part, _unique_finished(target))
                metadata_path.unlink(missing_ok=True)
                item.update(to=str(target), actualTo=str(target))
            item.update(finished=True, sha256=digest)
            progress += item["size"]
            completed += 1
            with service.state() as state:
                state["transfers"][identity]["plan"][number] = item
            _transfer_update(service, identity, status="running", done=progress, files={"done": completed, "total": len(transfer["plan"])}, sha256=digest,
                             **({"to": item["actualTo"]} if transfer["kind"] == "file" else {}))
        _transfer_update(service, identity, status="done", finishedAt=now(), done=transfer["size"])
    except (OSError, ValueError, KeyError) as exc:
        if _active(service, identity):
            _transfer_update(service, identity, status="failed", error=str(exc)[:500], finishedAt=now())
    finally:
        with service.lock:
            service.workers.discard(identity)


def _start_worker(service, identity):
    with service.lock:
        if identity in service.workers:
            return
        service.workers.add(identity)
        threading.Thread(target=_copy_worker, args=(service, identity), daemon=True).start()


def _start_transfer(service, direction, args, source):
    peer = service.peer(args["device"])
    if direction == "send" and source != "ui":
        from .neyvia_workspace_tools import workspace_for
        approval = workspace_for(service.root).require_approval("devices:send:" + peer["id"], "Allow models to send files to " + peer["name"], {"device": peer["id"]})
        if approval:
            return approval
    origin = str(args["from"])
    if direction == "take":
        info = service.remote(peer, "files/stat", body={"path": origin})
        info["name"] = _filename(info["name"])
        folder = _local(service.root, args.get("to") or Path.home() / "Downloads" / ("From " + "".join(c for c in peer["name"] if c.isalnum() or c in " -_")[:80]))
        folder.mkdir(parents=True, exist_ok=True)
        if not folder.is_dir():
            raise PeerError("Take needs a local destination folder")
        if info["kind"] == "folder":
            files = service.remote(peer, "files/tree?" + urlencode({"path": origin}))["files"]
            for row in files:
                relative = str(row["rel"]).replace("\\", "/")
                if not relative or relative.startswith("/") or ":" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
                    raise PeerError("Remote folder contains an unsafe relative path", 403)
        else:
            # The raw response supplies nanosecond mtime without leaking local path APIs.
            _, headers = service.remote(peer, "files/raw?" + urlencode({"path": origin, "offset": 0, "length": 0}), raw=True)
            files = [{"rel": "", "size": info["size"], "mtime": int(headers["X-Neyvia-Mtime"])}]
        with service.state():
            target = _unique(folder / info["name"])
            while True:
                try:
                    if info["kind"] == "folder":
                        target.mkdir()
                    else:
                        target.with_name(target.name + ".neyvia-part").open("xb").close()
                    break
                except FileExistsError:
                    target = _unique(target)
        plan = [{"from": origin.rstrip("/\\") + ("/" + row["rel"] if row["rel"] else ""),
                 "to": str(target / row["rel"] if row["rel"] else target), "size": row["size"], "mtime": row["mtime"]} for row in files]
    else:
        path = _local(service.root, origin)
        if not path.exists():
            raise PeerError("Nothing is at the source path")
        info = {"name": path.name, "kind": "folder" if path.is_dir() else "file"}
        listing = service.remote(peer, "files/list", body={})
        destination = args.get("to") or listing["places"][-1]["path"]
        target = service.remote(peer, "files/destination", body={"path": destination, "name": path.name, "kind": info["kind"]})["path"]
        if path.is_dir():
            files = []
            for directory, folders, names in os.walk(path, followlinks=False):
                folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink() and _local(service.root, Path(directory) / name)]
                for name in names:
                    child = _local(service.root, Path(directory) / name)
                    stat = child.stat()
                    files.append({"rel": child.relative_to(path).as_posix(), "size": stat.st_size, "mtime": stat.st_mtime_ns})
                    if len(files) > 5000 or sum(row["size"] for row in files) > MAX_TOTAL:
                        raise PeerError("Folder copies are limited to 5000 files and 50 GB")
        else:
            stat = path.stat()
            files = [{"rel": "", "size": stat.st_size, "mtime": stat.st_mtime_ns}]
        plan = [{"from": str(path / row["rel"] if row["rel"] else path), "to": target + ("/" + row["rel"] if row["rel"] else ""), "size": row["size"], "mtime": row["mtime"]} for row in files]
    if any(row["size"] < 0 for row in plan) or sum(row["size"] for row in plan) > MAX_TOTAL or len(plan) > 5000:
        raise PeerError("Transfers are limited to 5000 files and 50 GB")
    identity = uuid.uuid4().hex
    transfer = {"id": identity, "direction": direction, "device": peer["id"], "deviceName": peer["name"], "from": origin, "to": str(target),
                "name": info["name"], "kind": info["kind"], "size": sum(row["size"] for row in plan), "done": 0, "files": {"done": 0, "total": len(plan)},
                "status": "queued", "sha256": "", "bytesPerSecond": 0, "error": "", "startedAt": now(), "updatedAt": now(), "finishedAt": None, "by": source, "plan": plan}
    with service.state() as state:
        state["transfers"][identity] = transfer
    _start_worker(service, identity)
    deadline = time.monotonic() + max(0, min(120, float(args.get("wait", 0 if source == "ui" else 30))))
    while time.monotonic() < deadline:
        with service.state() as state:
            transfer = dict(state["transfers"][identity])
        if transfer["status"] in {"done", "failed", "paused", "cancelled"}:
            break
        time.sleep(.1)
    return {"transfer": transfer}


def call_devices(root, name, args, source="model"):
    service = devices_for(root)
    name = name.removeprefix("neyvia.devices.")
    args = args or {}
    if source != "ui" and name not in {row[0] for row in DEFINITIONS}:
        raise PeerError("Pairing and share changes need the owner's UI", 403)
    if name in {"list", "requests"}:
        return service.snapshot() if name == "list" else {"requests": service.snapshot()["requests"]}
    if name == "discover":
        from .connected_device_inventory import connected_device_snapshot
        roster = connected_device_snapshot()
        from .connected_device_inventory import _tailscale_executable, _tailscale_json
        executable = _tailscale_executable()
        status = _tailscale_json(executable, "status") if executable else {}
        raw_peers = list((status.get("Peer") or {}).values())
        def probe(raw):
            if raw.get("OS", "").lower() not in {"windows", "macos", "linux"}:
                return None
            dns = str(raw.get("DNSName") or "").rstrip(".")
            url = "https://" + dns + ":8443" if dns else ""
            row = {"id": str(raw.get("ID") or raw.get("HostName")), "name": raw.get("HostName"), "os": raw.get("OS"), "online": bool(raw.get("Online")),
                   "url": url, "lastSeen": raw.get("LastSeen"), "status": "offline"}
            candidates = ([url] if url else []) + ["http://" + str(ip) + ":47881" for ip in raw.get("TailscaleIPs", []) if ":" not in str(ip)]
            if row["online"]:
                row["status"] = "not-neyvia"
                for candidate in candidates:
                    try:
                        hello = _request(candidate, "hello", timeout=1.5)
                        row.update(id=hello["id"], name=hello["name"], status="available", url=candidate)
                        break
                    except (OSError, ValueError):
                        pass
            return row
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(probe, raw_peers))
        with service.state() as state:
            state.update(tailnet="ok" if roster["source"] == "tailscale" else "missing", detail=roster["detail"])
            for row in rows:
                if row and state["peers"].get(row["id"], {}).get("status") not in {"paired", "waiting", "asked-you"}:
                    state["peers"][row["id"]] = row
            self_dns = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
            if self_dns:
                state["url"] = "https://" + self_dns + ":8443"
        return service.snapshot()
    if name == "pair":
        return service.pair(args)
    if name == "approve":
        return service.approve(args)
    if name in {"revoke", "pair.cancel"}:
        return service.revoke(str(args["device"]))
    if name == "deny":
        with service.state() as state:
            row = state["requests"].get(str(args["request"]))
            if not row or row["status"] != "pending":
                raise PeerError("That request is no longer waiting", 409)
            row["status"] = "denied"
            if state["peers"].get(row["fromId"], {}).get("status") != "paired":
                state["peers"].pop(row["fromId"], None)
        bus_for(service.root).emit("devices.changed", {"device": row["fromId"], "status": "denied"})
        return {"ok": True}
    if name == "shares.set":
        share = service.shares(args)
        with service.state() as state:
            peer = state["peers"][args["device"]]
            peer["iShare"] = share
            result = service.public(peer)
        bus_for(service.root).emit("devices.changed", {"device": peer["id"], "status": "shares"})
        return {"device": result}
    if name in {"files.list", "files.stat"}:
        peer = service.peer(args["device"])
        result = service.remote(peer, name.replace(".", "/", 1), body=args)
        if name == "files.list" and result.get("share"):
            with service.state() as state:
                state["peers"][peer["id"]]["theyShare"] = result["share"]
        return result
    if name == "files.read":
        peer = service.peer(args["device"])
        offset, length = int(args.get("offset", 0)), int(args.get("length", 65536))
        if offset < 0 or not 0 <= length <= 1024 * 1024:
            raise PeerError("Read range must be nonnegative and at most 1 MiB")
        data, headers = service.remote(peer, "files/raw?" + urlencode({"path": args["path"], "offset": offset, "length": length}), raw=True)
        text = Path(args["path"]).suffix.lower() in TEXT_EXT
        return {"ok": True, "device": peer["id"], "path": args["path"], "offset": offset, "length": len(data), "size": int(headers["X-Neyvia-Size"]),
                "eof": offset + len(data) >= int(headers["X-Neyvia-Size"]), "encoding": "utf-8" if text else "base64",
                "content": data.decode("utf-8", "replace") if text else base64.b64encode(data).decode()}
    if name in {"files.fetch", "files.send"}:
        return _start_transfer(service, "take" if name == "files.fetch" else "send", args, source)
    if name == "transfers":
        with service.state() as state:
            return {"transfers": [row for row in state["transfers"].values() if not args.get("id") or row["id"] == args["id"]][-30:]}
    if name in {"transfer.pause", "transfer.resume", "transfer.cancel"}:
        identity = args["id"]
        with service.state() as state:
            row = state["transfers"].get(identity)
            if not row or row["status"] in {"done", "cancelled"}:
                raise PeerError("That transfer cannot be changed", 409)
            if name != "transfer.resume":
                row["status"] = "paused" if name == "transfer.pause" else "cancelled"
        if name == "transfer.resume":
            # The previous worker can still be returning from an in-flight chunk.
            deadline = time.monotonic() + 20
            while identity in service.workers and time.monotonic() < deadline:
                time.sleep(.05)
            if identity in service.workers:
                raise PeerError("The previous chunk is still finishing; try resume again", 409)
            with service.state() as state:
                state["transfers"][identity]["status"] = "queued"
            _start_worker(service, identity)
        elif name == "transfer.cancel":
            deadline = time.monotonic() + 20
            while identity in service.workers and time.monotonic() < deadline:
                time.sleep(.05)
            if identity in service.workers:
                raise PeerError("The current chunk is still finishing; try cancel again", 409)
            peer = service.peer(row["device"])
            for index, item in enumerate(row["plan"]):
                if row["direction"] == "take":
                    _drop_part(_local(service.root, item["to"]))
                else:
                    service.remote(peer, "files/upload/cancel", body={"id": identity + str(index)})
        return {"transfer": _transfer_update(service, identity)}
    raise PeerError("Unknown devices operation")


def serve_peer(backend, handler, parsed, method):
    from .web_backend import _json_response, _read_json_body
    if not parsed.path.startswith("/api/peer/v1/"):
        return False
    if not network_allowed(handler.client_address[0], handler.headers):
        _json_response(handler, 403, {"ok": False, "error": "tailnet only"})
        return True
    service = bind_peer_backend(backend, handler)
    route = parsed.path[len("/api/peer/v1/"):]
    query = {key: values[0] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    try:
        if method == "POST" and (not 0 <= int(handler.headers.get("Content-Length", 0)) <= 65536 or handler.headers.get("Content-Encoding")):
            handler.close_connection = True
            raise PeerError("Peer JSON bodies must be plain JSON up to 64 KiB", 413)
        if route == "hello" and method == "GET":
            result = {"neyvia": True, **service.snapshot()["here"], "version": "1", "peerApi": 1}
        elif route == "pair/request" and method == "POST":
            result = service.incoming(_read_json_body(handler), handler.client_address[0])
        elif route == "pair/status" and method == "GET":
            result = service.status(query.get("request", ""), handler.headers.get("Authorization", ""))
        else:
            peer = service.auth(handler.headers.get("Authorization", ""))
            if route == "revoke" and method == "POST":
                result = service.revoke(peer["id"], notify=False)
            elif route in {"files/list", "files/stat"} and method == "POST":
                args = _read_json_body(handler)
                result = service.file_list(peer, args) if route == "files/list" else service.file_stat(peer, args)
            elif route == "files/destination" and method == "POST":
                result = service.destination(peer, _read_json_body(handler))
            elif route == "files/tree" and method == "GET":
                result = service.tree(peer, query["path"])
            elif route == "files/raw" and method == "GET":
                path = service.scoped(peer, query["path"])
                if not path.is_file():
                    raise PeerError("Choose a file")
                info = path.stat()
                offset, length = int(query.get("offset", 0)), int(query.get("length", CHUNK))
                if offset < 0 or offset > info.st_size or not 0 <= length <= CHUNK:
                    raise PeerError("Invalid file range", 416)
                digest = service.file_hash(path)
                with path.open("rb") as stream:
                    stream.seek(offset)
                    data = stream.read(length)
                if path.stat().st_mtime_ns != info.st_mtime_ns:
                    raise PeerError("The file changed while reading", 409)
                handler.send_response(200)
                for key, value in {"Content-Type": "application/octet-stream", "Content-Length": len(data), "X-Neyvia-Size": info.st_size,
                                   "X-Neyvia-Mtime": info.st_mtime_ns, "X-Neyvia-Sha256": digest, "X-Neyvia-Chunk-Sha256": hashlib.sha256(data).hexdigest(),
                                   "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{info.st_size}" if data else f"bytes */{info.st_size}",
                                   "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}.items():
                    handler.send_header(key, str(value))
                handler.end_headers()
                handler.wfile.write(data)
                return True
            elif route == "files/upload" and method == "PUT":
                length = int(handler.headers.get("Content-Length", -1))
                if not 0 <= length <= CHUNK or handler.headers.get("Transfer-Encoding"):
                    raise PeerError("Upload chunks must be at most 8 MiB", 413)
                data = handler.rfile.read(length)
                if len(data) != length:
                    raise PeerError("Incomplete upload chunk")
                result = service.upload(peer, query, data, handler.headers.get("X-Neyvia-Chunk-Sha256"))
            elif route == "files/upload" and method == "GET":
                result = service.upload_status(peer, query["id"])
            elif route == "files/upload/finish" and method == "POST":
                result = service.finish(peer, _read_json_body(handler))
            elif route == "files/upload/cancel" and method == "POST":
                args = _read_json_body(handler)
                with service.state() as state:
                    row = state["uploads"].get(args["id"])
                    if row and row["device"] == peer["id"]:
                        if not row.get("finished"):
                            _drop_part(service.scoped(peer, row["path"], True))
                        state["uploads"].pop(args["id"])
                result = {"ok": True}
            else:
                raise PeerError("Unknown peer route", 404)
        _json_response(handler, 200, result)
    except (ValueError, KeyError, OSError) as exc:
        _json_response(handler, getattr(exc, "status", 400), {"ok": False, "error": str(exc)[:500]})
    return True


def serve_raw(root, handler, parsed):
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    service = devices_for(root)
    peer = service.peer(query["device"])
    info = service.remote(peer, "files/stat", body={"path": query["path"]})
    if info.get("openWith") not in {"image", "pdf"} or info.get("size", 0) > 64 * 1024 * 1024:
        raise PeerError("Quick look serves images/PDFs up to 64 MB")
    handler.send_response(200)
    handler.send_header("Content-Type", mimetypes.guess_type(info["name"])[0] or "application/octet-stream")
    handler.send_header("Content-Length", str(info["size"]))
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
    from .web_backend import _apply_security_headers, _send_cors_headers
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    offset, digest = 0, None
    while offset < info["size"]:
        data, headers = service.remote(peer, "files/raw?" + urlencode({"path": query["path"], "offset": offset, "length": min(CHUNK, info["size"] - offset)}), raw=True)
        if not data or (digest and digest != headers["X-Neyvia-Sha256"]) or hashlib.sha256(data).hexdigest() != headers["X-Neyvia-Chunk-Sha256"]:
            raise PeerError("The remote preview changed while reading")
        digest = headers["X-Neyvia-Sha256"]
        handler.wfile.write(data)
        offset += len(data)
