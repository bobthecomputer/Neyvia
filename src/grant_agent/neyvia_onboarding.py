"""First run: base pack download, runtime detection, interests and the tour.

One module serves three callers on the same state under
``<root>/.agent_control/onboarding``: the web backend (``onboarding_*``
commands), the desktop bridge (same commands, short-lived process) and the
model (``neyvia.onboarding.*`` tools). Downloads run in a detached worker
(``python -m grant_agent.neyvia_onboarding download --root ...``) so they
survive the desktop bridge's one-call processes and page reloads; the worker
reports through ``base-pack/status.json``.

Manifest format ``neyvia.base-pack/v1`` (see docs/manuals/onboarding.md):
``{schema, packId, version, channel?, baseUrl?, files:[{path, size, sha256,
url?}], totalSize}``. File URLs are relative to ``baseUrl`` or the manifest.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .durability import file_transaction

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "config" / "neyvia_onboarding.json"
TEST_MANIFEST = REPO / "config" / "base_pack" / "test-manifest.json"
PACK_MANIFESTS = REPO / "config" / "onboarding_packs.json"
UPDATER_POLICY = REPO / "config" / "neyvia_updater.json"
MANIFEST_SCHEMA = "neyvia.base-pack/v1"
STATE_SCHEMA = "neyvia.onboarding-state/v1"
STATUS_SCHEMA = "neyvia.base-pack-status/v1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILES = 20000
MAX_FILE_BYTES = 4 * 1024 ** 3
MAX_ADDON_BYTES = 200 * 1024 * 1024
CHUNK = 64 * 1024
STALE_SECONDS = 12
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

COMMANDS = frozenset({
    "onboarding_state_command",
    "onboarding_save_command",
    "onboarding_runtimes_command",
    "onboarding_base_pack_status_command",
    "onboarding_base_pack_start_command",
    "onboarding_base_pack_pause_command",
    "onboarding_pack_install_command",
    "onboarding_pack_status_command",
})

DEFINITIONS = [
    ("onboarding.state", "Read first-run setup: saved interests, tier, picked apps and packs, tour progress, base pack download and the catalog.", {}, []),
    ("onboarding.recommend", "Turn interests or a tier (beginner, intermediate, advanced) into recommended apps, add-on packs and tour chapters. Saves nothing.",
     {"interests": {"type": "array", "items": {"type": "string"}}, "tier": {"type": "string"}}, []),
    ("onboarding.save", "Save the person's setup choices. Only send what they chose; apps and packs must come from the catalog.",
     {"interests": {"type": "array", "items": {"type": "string"}}, "tier": {"type": "string"},
      "apps": {"type": "array", "items": {"type": "string"}}, "packs": {"type": "array", "items": {"type": "string"}},
      "runtime": {"type": "string"}, "completed": {"type": "boolean"}}, []),
    ("onboarding.runtimes", "Detect which agent runtimes (Claude Code, Codex, OpenCode...) are installed on this PC, with setup steps for the rest.", {}, []),
    ("onboarding.base_pack", "Base pack download: status, start (resumes a partial download) or pause.",
     {"action": {"type": "string", "enum": ["status", "start", "pause"]}}, []),
    ("onboarding.pack", "Read or install a separately packaged add-on into local staging. Unavailable packs explain what is missing; no system installation or activation.",
     {"action": {"type": "string", "enum": ["status", "install"]}, "packId": {"type": "string"}}, []),
    ("onboarding.open", "Open the setup screen or the tour on the person's screen.",
     {"step": {"type": "string", "enum": ["welcome", "runtimes", "interests", "tour"]}}, []),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dir(root: Path) -> Path:
    return Path(root).resolve() / ".agent_control" / "onboarding"


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(temp, path)
            return
        except PermissionError:  # a reader holds the file open on Windows
            time.sleep(0.02 * (attempt + 1))
    os.replace(temp, path)


# ---------------------------------------------------------------- catalog ---

def load_catalog() -> dict[str, Any]:
    from .proofs_d_onboarding import check_catalog
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    check_catalog(catalog, _known_apps(), _known_packs())
    return catalog


def _known_apps() -> dict[str, dict[str, Any]]:
    registry = _read_json(REPO / "config" / "neyvia_apps.json", {"suites": []})
    return {app["id"]: {**app, "suite": suite["id"], "suiteName": suite["name"]}
            for suite in registry.get("suites", []) for app in suite.get("apps", [])}


def _known_packs() -> dict[str, dict[str, Any]]:
    from .install_profiles import InstallProfileRegistry
    snapshot = InstallProfileRegistry(REPO).catalog_snapshot()
    return {row["packageId"]: row for row in snapshot["optional"]}


def recommend(catalog: dict[str, Any], interests: list[str] | None = None, tier: str | None = None) -> dict[str, Any]:
    """Union of what each chosen interest (or the tier's interests) recommends, in catalog order."""
    by_id = {row["id"]: row for row in catalog["interests"]}
    chosen = [value for value in (interests or []) if value in by_id]
    if not chosen and tier:
        found = next((row for row in catalog["tiers"] if row["id"] == tier), None)
        if not found:
            raise ValueError(f"Unknown tier {tier!r}; choose beginner, intermediate or advanced")
        chosen = list(found["interests"])
    unknown = sorted(set(interests or []) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown interests: {', '.join(unknown)}")

    def union(key: str) -> list[str]:
        seen: list[str] = []
        for row in catalog["interests"]:
            if row["id"] in chosen:
                seen.extend(value for value in row.get(key, []) if value not in seen)
        return seen

    wanted = set(union("chapters"))
    chapters = [row for row in catalog["tutorial"]["chapters"] if not row["interests"] or row["id"] in wanted]
    result = {"interests": [row["id"] for row in catalog["interests"] if row["id"] in chosen],
            "apps": union("apps"), "packs": union("packs"), "runtimes": union("runtimes"),
            "chapters": [row["id"] for row in chapters],
            "tourSeconds": tour_seconds(chapters)}
    from .proofs_d_onboarding import check_recommendation
    check_recommendation(catalog, chosen, result)
    return result


def tour_seconds(chapters: list[dict[str, Any]]) -> int:
    """The player stretches or speeds every chapter evenly so the tour lasts 60–90 s."""
    total = sum(row["durationMs"] for row in chapters) / 1000
    return round(min(90, max(60, total))) if total else 0


# ------------------------------------------------------------------ state ---

def read_state(root: Path) -> dict[str, Any]:
    with file_transaction(_dir(root) / "state.json"):
        return _read_state(root)


def _read_state(root: Path) -> dict[str, Any]:
    path = _dir(root) / "state.json"
    saved = _read_json(path, None)
    base = {"schema": STATE_SCHEMA, "firstRun": saved is None, "completed": False, "dismissed": False,
            "interests": [], "tier": "", "apps": [], "packs": [], "runtime": "",
            "tour": {"seen": False, "lastChapter": ""}, "updatedAt": ""}
    if isinstance(saved, dict):
        base.update({key: saved[key] for key in base if key in saved and key not in {"schema", "firstRun"}})
    return base


def save_state(root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    with file_transaction(_dir(root) / "state.json"):
        return _save_state(root, patch)


def _save_state(root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    catalog = load_catalog()
    state = read_state(root)
    interests = {row["id"] for row in catalog["interests"]}
    if "interests" in patch:
        values = _strings(patch["interests"], "interests")
        if set(values) - interests:
            raise ValueError(f"Unknown interests: {', '.join(sorted(set(values) - interests))}")
        state["interests"] = values
    if "tier" in patch:
        tier = str(patch["tier"] or "")
        if tier and tier not in {row["id"] for row in catalog["tiers"]}:
            raise ValueError("tier is beginner, intermediate or advanced")
        state["tier"] = tier
    if "apps" in patch:
        values = _strings(patch["apps"], "apps")
        unknown = set(values) - set(_known_apps())
        if unknown:
            raise ValueError(f"Unknown apps: {', '.join(sorted(unknown))}")
        state["apps"] = values
    if "packs" in patch:
        values = _strings(patch["packs"], "packs")
        unknown = set(values) - set(_known_packs())
        if unknown:
            raise ValueError(f"Unknown add-on packs: {', '.join(sorted(unknown))}")
        state["packs"] = values
    if "runtime" in patch:
        runtime = str(patch["runtime"] or "")
        if runtime and runtime not in catalog["runtimes"]["order"]:
            raise ValueError("Unknown runtime")
        state["runtime"] = runtime
    for flag in ("completed", "dismissed"):
        if flag in patch:
            state[flag] = bool(patch[flag])
    if isinstance(patch.get("tour"), dict):
        tour = patch["tour"]
        chapter = str(tour.get("lastChapter") or "")
        if chapter and chapter not in {row["id"] for row in catalog["tutorial"]["chapters"]}:
            raise ValueError("Unknown tour chapter")
        state["tour"] = {"seen": bool(tour.get("seen", state["tour"]["seen"])), "lastChapter": chapter}
    state["updatedAt"] = _now()
    stored = {key: value for key, value in state.items() if key != "firstRun"}
    _write_json(_dir(root) / "state.json", stored)
    from .proofs_d_onboarding import check_saved
    check_saved(root, stored)
    return {**state, "firstRun": False}


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value) or len(value) > 200:
        raise ValueError(f"{name} must be a list of ids")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def snapshot(root: Path) -> dict[str, Any]:
    """Everything the first-run screen needs in one call (runtimes come separately: they probe CLIs)."""
    catalog = load_catalog()
    apps = _known_apps()
    packs = _known_packs()
    delivery = {row["packId"]: row for row in pack_status(root)["packs"]}
    return {"state": read_state(root), "catalog": catalog, "basePack": base_pack_status(root),
            "apps": [{key: app.get(key) for key in ("id", "name", "description", "status", "suite", "suiteName")} for app in apps.values()],
            "packs": [{"id": pack_id, "name": row["name"], "deliveryState": row["deliveryState"],
                       "resourceClass": row["resourceClass"], "ready": delivery[pack_id]["state"] != "unavailable",
                       "deliveryScope": delivery[pack_id]["deliveryScope"], "missing": delivery[pack_id]["missing"]}
                      for pack_id, row in packs.items()]}


# --------------------------------------------------------------- runtimes ---

def detect_runtimes(root: Path, provider_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Reuse the harness catalog probes; Neyvia Native is built in, not "found"."""
    from .harness_registry import build_harness_catalog
    catalog = load_catalog()["runtimes"]
    harnesses = {row["harnessId"]: row for row in build_harness_catalog(Path(root), provider_env=provider_env)["harnesses"]}
    rows = []
    for runtime_id in catalog["order"]:
        row = harnesses.get(runtime_id)
        if not row:
            continue
        setup = catalog["setup"].get(runtime_id, {})
        rows.append({"id": runtime_id, "label": row["label"], "found": bool(row["detected"]),
                     "installed": bool(row["installed"]), "version": row.get("version") or "",
                     "readiness": row["readiness"], "detail": row.get("readinessDetail") or "",
                     "docsUrl": row.get("docsUrl") or "", "steps": setup.get("steps") or ["Install it from its website", "Press Check again"],
                     "command": setup.get("command") or "", "preview": row.get("integrationTier") == "developer-preview"})
    found = [row["id"] for row in rows if row["found"]]
    return {"schema": "neyvia.onboarding-runtimes/v1", "checkedAt": _now(), "runtimes": rows, "found": found,
            "mode": "ready" if found else "begin", "beginWith": catalog["beginWith"],
            "native": {"label": "Neyvia Native", "builtIn": True,
                       "detail": "Built in. It needs a model provider before it can answer."}}


# -------------------------------------------------------------- manifests ---

def parse_manifest(text: str | bytes, source: str, *, trusted_policy: Path | None = None) -> dict[str, Any]:
    """Validate a base-pack manifest and resolve every file's absolute source."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest is larger than 1 MiB")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"Manifest schema must be {MANIFEST_SCHEMA}")
    for key in ("packId", "version"):
        if not isinstance(data.get(key), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", data[key]):
            raise ValueError(f"Manifest {key} is missing or not a plain id")
    files = data.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ValueError(f"Manifest files must list 1–{MAX_FILES} entries")
    base = str(data.get("baseUrl") or source)
    seen: set[str] = set()
    resolved = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest file is an object")
        path = _safe_relative(entry.get("path"))
        if path.casefold() in seen:
            raise ValueError(f"Duplicate path {path}")
        seen.add(path.casefold())
        size = entry.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
            raise ValueError(f"{path}: size must be a whole number of bytes")
        digest = str(entry.get("sha256") or "").lower()
        if not SHA256.match(digest):
            raise ValueError(f"{path}: sha256 must be 64 hex characters")
        url = _join(base, str(entry.get("url") or path))
        _check_source(url)
        resolved.append({"path": path, "size": size, "sha256": digest, "url": url})
        total += size
    if data.get("totalSize") is not None and data["totalSize"] != total:
        raise ValueError(f"totalSize {data['totalSize']} does not match the files ({total})")
    _verify_manifest_signature(data, source, resolved, trusted_policy=trusted_policy)
    dev = data.get("dev") if isinstance(data.get("dev"), dict) else {}
    throttle = dev.get("throttleKbps")
    local_only = all(urlparse(row["url"]).scheme == "file" or urlparse(row["url"]).hostname in LOOPBACK for row in resolved)
    result = {"schema": MANIFEST_SCHEMA, "packId": data["packId"], "version": data["version"],
            "channel": str(data.get("channel") or ""), "source": source, "files": resolved, "totalSize": total,
            "throttleKbps": throttle if local_only and isinstance(throttle, (int, float)) and throttle > 0 else None}
    from .proofs_d_onboarding import check_manifest
    check_manifest(result)
    return result


def _local_source(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme == "file" or parsed.hostname in LOOPBACK or not re.match(r"^[a-z][a-z0-9+.-]*://", source, re.I)


def _canonical_manifest(data: dict[str, Any]) -> bytes:
    return json.dumps({key: value for key, value in data.items() if key != "signature"},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _verify_manifest_signature(data: dict[str, Any], source: str, files: list[dict[str, Any]], *, trusted_policy: Path | None = None) -> None:
    signature = data.get("signature")
    if signature is None:
        if data.get("channel") == "test" or (_local_source(source) and all(_local_source(row["url"]) for row in files)):
            return
        raise ValueError("Remote manifests require an Ed25519 signature")
    if not isinstance(signature, dict) or not isinstance(signature.get("keyId"), str):
        raise ValueError("Manifest signature must contain keyId and ed25519")
    keys = _read_json(trusted_policy or UPDATER_POLICY, {}).get("signing", {}).get("trustedKeys", {})
    key = keys.get(signature.get("keyId"))
    if not isinstance(key, dict) or key.get("provisioned") is not True:
        raise ValueError("Manifest signature key is unknown or not provisioned")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        public = base64.b64decode(key["publicKeyBase64"], validate=True)
        signed = base64.b64decode(signature["ed25519"], validate=True)
        if len(public) != 32 or len(signed) != 64:
            raise ValueError("Manifest signature has an invalid key or signature length")
        if key.get("fingerprintSha256") and hashlib.sha256(public).hexdigest() != key["fingerprintSha256"]:
            raise ValueError("Manifest signature key fingerprint does not match")
        Ed25519PublicKey.from_public_bytes(public).verify(signed, _canonical_manifest(data))
    except (InvalidSignature, binascii.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Manifest Ed25519 signature verification failed") from exc


def _safe_relative(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or ":" in text or any(part in {"", ".", ".."} for part in text.split("/")) or text.endswith(".part"):
        raise ValueError(f"Unsafe manifest path {text!r}")
    return pure.as_posix()


def _join(base: str, relative: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*://", relative, re.I):
        return relative
    if not re.match(r"^[a-z][a-z0-9+.-]*://", base, re.I):
        base = Path(base).resolve().as_uri()
    return urljoin(base, relative)


def _check_source(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in LOOPBACK:
        return
    if parsed.scheme == "file":
        return
    raise ValueError(f"Download source must be https, local http or a local file: {url}")


def manifest_source() -> str:
    return os.environ.get("NEYVIA_BASE_PACK_MANIFEST") or str(TEST_MANIFEST)


def load_manifest(source: str | None = None) -> dict[str, Any]:
    source = source or manifest_source()
    if re.match(r"^https?://", source, re.I):
        _check_source(source)
        with urllib.request.urlopen(source, timeout=15) as response:  # noqa: S310 - scheme checked above
            return parse_manifest(response.read(MAX_MANIFEST_BYTES + 1), source)
    path = Path(url2pathname(urlparse(source).path)) if source.startswith("file:") else Path(source)
    return parse_manifest(path.read_bytes(), str(path.resolve()))


# --------------------------------------------------------------- add-ons ---

class PackUnavailableError(ValueError):
    """The catalog has no deliverable payload, rather than an invalid one."""


def _pack_source(pack_id: str) -> str:
    _pack_dir(Path.cwd(), pack_id)  # reject path separators before consulting a mapping
    sources = _read_json(PACK_MANIFESTS, {}).get("manifests", {})
    if os.environ.get("NEYVIA_ONBOARDING_PACK_MANIFESTS"):
        sources = {**sources, **json.loads(os.environ["NEYVIA_ONBOARDING_PACK_MANIFESTS"])}
    source = sources.get(pack_id)
    if not isinstance(source, str) or not source:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", source, re.I) and not Path(source).is_absolute():
        source = str(REPO / source)
    return source


def load_pack_manifest(pack_id: str) -> dict[str, Any]:
    row = _known_packs().get(pack_id)
    definition = _pack_definition(pack_id)
    if not row:
        raise ValueError(f"Unknown add-on pack {pack_id!r}")
    source = _pack_source(pack_id)
    if not source:
        missing = definition.get("missing") or [f"Packaged payload manifest for {pack_id}"]
        raise PackUnavailableError("Missing: " + "; ".join(missing))
    if row["deliveryState"] not in {"bundled", "verified"} and not definition.get("localComponents"):
        raise PackUnavailableError(row.get("gap") or f"{pack_id} is not a verified delivery")
    manifest = load_manifest(source)
    if manifest["packId"] != pack_id:
        raise ValueError("Manifest packId does not match the selected pack")
    if manifest["totalSize"] > MAX_ADDON_BYTES:
        raise ValueError("Add-on exceeds the 200 MiB delivery limit")
    if definition.get("localComponents") and not (_local_source(source) and all(_local_source(row["url"]) for row in manifest["files"])):
        raise ValueError("Local component packs must contain only local payloads")
    return manifest


def _pack_definition(pack_id: str) -> dict[str, Any]:
    return _read_json(PACK_MANIFESTS, {}).get("packages", {}).get(pack_id, {})


def _installed_pack_error(status: dict[str, Any], manifest: dict[str, Any]) -> str:
    """A stale receipt cannot make a missing or corrupt staged payload look installed."""
    target = Path(status.get("target") or "")
    if status.get("version") != manifest["version"] or not (target / "installed.json").is_file():
        return "The packaged version changed or its install receipt is missing; install again."
    for entry in manifest["files"]:
        path = target / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            return f"Staged payload {entry['path']} is missing or failed its checksum; install again."
    return ""


def pack_status(root: Path, pack_id: str | None = None) -> dict[str, Any]:
    rows = _known_packs()
    if pack_id is not None and pack_id not in rows:
        raise ValueError(f"Unknown add-on pack {pack_id!r}")
    packs = []
    states = {"idle": "not-installed", "starting": "queued", "running": "installing",
              "verifying": "installing", "paused": "not-installed", "done": "installed", "failed": "failed"}
    for identity, row in rows.items():
        if pack_id is not None and identity != pack_id:
            continue
        definition = _pack_definition(identity)
        manifest, manifest_error, unavailable = None, "", False
        try:
            manifest = load_pack_manifest(identity)
        except PackUnavailableError as exc:
            manifest_error, unavailable = str(exc), True
        except (ValueError, OSError) as exc:
            manifest_error = str(exc)
        status = base_pack_status(root, pack_id=identity)
        error = manifest_error or status.get("error", "")
        if not manifest_error and status["state"] == "done":
            error = _installed_pack_error(status, manifest)
        packs.append({"packId": identity, "state": "unavailable" if unavailable else "failed" if error else states.get(status["state"], "failed"),
                      "doneBytes": status.get("doneBytes", 0), "totalBytes": status.get("totalBytes", 0),
                      "error": error, "deliveryScope": "local-components" if definition.get("localComponents") else "runtime",
                      "contents": definition.get("contents", []), "entrypoints": definition.get("entrypoints", []),
                      "missing": definition.get("missing", []), "runtimeReady": not definition.get("missing") and bool(manifest),
                      **{key: status[key] for key in ("receipt", "target", "channel", "version", "files", "finishedAt", "bytesPerSecond") if key in status},
                      "stagedOnly": True})
    from .proofs_d_onboarding import check_pack_status
    check_pack_status(root, packs)
    return {"packs": packs}


def install_pack(root: Path, pack_id: str, *, spawn: bool = True) -> dict[str, Any]:
    from .proofs_d_onboarding import check_staging_scope
    check_staging_scope(root, pack_id)
    current = pack_status(root, pack_id)
    if current["packs"][0]["state"] in {"unavailable", "installed", "queued", "installing"}:
        return current
    pack = _pack_dir(root, pack_id)
    pack.mkdir(parents=True, exist_ok=True)
    try:
        manifest = load_pack_manifest(pack_id)
        (pack / "pause").unlink(missing_ok=True)
        _write_json(pack / "status.json", {**_status_base(manifest, base_pack_status(root, pack_id=pack_id)),
                                           "state": "starting", "heartbeat": time.time(), "error": ""})
        if spawn:
            _spawn_worker(Path(root), pack_id)
    except Exception as exc:
        _write_json(pack / "status.json", {"state": "failed", "error": str(exc)[:500]})
    return pack_status(root, pack_id)


# ------------------------------------------------------------- downloader ---

def _pack_dir(root: Path, pack_id: str | None = None) -> Path:
    if pack_id is None:
        return _dir(root) / "base-pack"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", pack_id):
        raise ValueError("Pack id must be a plain id")
    return _dir(root) / "packs" / pack_id


def base_pack_status(root: Path, *, pack_id: str | None = None) -> dict[str, Any]:
    status = _read_json(_pack_dir(root, pack_id) / "status.json", None)
    if not isinstance(status, dict):
        return {"schema": STATUS_SCHEMA, "state": "idle", "doneBytes": 0, "totalBytes": 0, "files": {"done": 0, "total": 0}}
    if status.get("state") in {"starting", "running", "verifying"}:
        updated = status.get("heartbeat") or 0
        if time.time() - float(updated) > STALE_SECONDS:
            status = {**status, "state": "paused", "detail": "The download stopped (Neyvia closed or the PC slept). Resume picks up where it left off."}
    return status


def start_base_pack(root: Path, *, spawn: bool = True) -> dict[str, Any]:
    status = base_pack_status(root)
    if status.get("state") in {"starting", "running", "verifying"}:
        return {**status, "alreadyRunning": True}
    manifest = load_manifest()  # validate before promising anything
    pack = _pack_dir(root)
    (pack / "pause").unlink(missing_ok=True)
    _write_json(pack / "status.json", {**_status_base(manifest, status), "state": "starting", "heartbeat": time.time(), "error": ""})
    if spawn:
        _spawn_worker(Path(root))
    return base_pack_status(root)


def pause_base_pack(root: Path) -> dict[str, Any]:
    pack = _pack_dir(root)
    status = base_pack_status(root)
    if status.get("state") not in {"starting", "running", "verifying"}:
        return status
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "pause").write_text(_now(), encoding="utf-8")
    deadline = time.time() + 3
    while time.time() < deadline:
        status = base_pack_status(root)
        if status.get("state") not in {"starting", "running", "verifying"}:
            return status
        time.sleep(0.1)
    return {**status, "pausing": True}


def _status_base(manifest: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    return {"schema": STATUS_SCHEMA, "packId": manifest["packId"], "version": manifest["version"],
            "channel": manifest["channel"], "manifest": manifest["source"], "totalBytes": manifest["totalSize"],
            "doneBytes": int(previous.get("doneBytes") or 0) if previous.get("packId") == manifest["packId"] else 0,
            "files": {"done": 0, "total": len(manifest["files"])}, "startedAt": _now(), "attempts": int(previous.get("attempts") or 0) + 1}


def _spawn_worker(root: Path, pack_id: str | None = None) -> None:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")]))}
    args = [sys.executable, "-m", "grant_agent.neyvia_onboarding", "download", "--root", str(root)]
    if pack_id:
        args += ["--pack-id", pack_id]
    log = (_pack_dir(root, pack_id) / "worker.log").open("ab")
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "cwd": str(REPO), "env": env, "close_fds": True}
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        try:  # outlive the desktop bridge's job object when it allows breakaway
            subprocess.Popen(args, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **kwargs)  # noqa: S603
            return
        except OSError:
            pass
        subprocess.Popen(args, creationflags=flags, **kwargs)  # noqa: S603
    else:
        subprocess.Popen(args, start_new_session=True, **kwargs, **hidden_windows_subprocess_kwargs())  # noqa: S603


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _Paused(Exception):
    pass


def run_download(root: Path, manifest: dict[str, Any] | None = None, *, pack_id: str | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Download every manifest file into the staging folder, resuming partial files and verifying SHA-256."""
    from .harness_jobs import _exclusive_job_lock
    from .proofs_d_onboarding import check_staging_scope
    root = Path(root).resolve()
    check_staging_scope(root, pack_id)
    pack = _pack_dir(root, pack_id)
    pack.mkdir(parents=True, exist_ok=True)
    identity = os.path.normcase(str(pack.resolve())).encode("utf-8")
    shard = int.from_bytes(hashlib.sha256(identity).digest()[:2], "big") % len(_DOWNLOAD_LOCKS)
    # Base/add-on callers, including independent detached workers, share one
    # partial and verified journal per pack. An OS-released lease preserves
    # resumable bytes after a stopped worker without permitting two writers.
    with _DOWNLOAD_LOCKS[shard], _exclusive_job_lock(pack / "download", timeout_seconds=120):
        return _run_download_locked(root, manifest, pack_id=pack_id, sleep=sleep)


_DOWNLOAD_LOCKS = tuple(threading.RLock() for _ in range(64))


def _run_download_locked(root: Path, manifest: dict[str, Any] | None = None, *, pack_id: str | None = None,
                         sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    from .proofs_d_onboarding import check_manifest, check_staged_file, check_download_result, safe_destination, check_staging_scope
    root = Path(root).resolve()
    check_staging_scope(root, pack_id)
    pack = _pack_dir(root, pack_id)
    status_path = pack / "status.json"
    try:
        manifest = manifest or (load_pack_manifest(pack_id) if pack_id else load_manifest())
        check_manifest(manifest)
        if pack_id and manifest["packId"] != pack_id:
            raise ValueError("Manifest packId does not match the selected pack")
    except Exception as exc:
        status = {**base_pack_status(root, pack_id=pack_id), "state": "failed", "error": f"Manifest: {exc}", "heartbeat": time.time()}
        _write_json(status_path, status)
        return status
    target = pack / manifest["packId"] / manifest["version"]
    verified = _read_json(pack / "verified.json", {})
    previous = base_pack_status(root, pack_id=pack_id)
    status = {**_status_base(manifest, previous), "state": "running", "target": str(target), "error": "",
              "attempts": int(previous.get("attempts") or 1)}  # start_base_pack already counted this attempt
    started = time.monotonic()
    fetched = 0
    last_write = 0.0

    def report(force: bool = False, **changes: Any) -> None:
        nonlocal last_write
        status.update(changes)
        elapsed = max(0.001, time.monotonic() - started)
        status["bytesPerSecond"] = round(fetched / elapsed)
        status["heartbeat"] = time.time()
        if force or time.monotonic() - last_write >= 0.25:
            _write_json(status_path, status)
            last_write = time.monotonic()

    done_bytes = 0
    try:
        for index, entry in enumerate(manifest["files"]):
            destination = safe_destination(target, entry["path"])
            key = f"{manifest['packId']}/{manifest['version']}/{entry['path']}"
            if destination.is_file() and destination.stat().st_size == entry["size"] and verified.get(key) == [entry["sha256"], destination.stat().st_mtime_ns] and _sha256(destination) == entry["sha256"]:
                check_staged_file(destination, entry)
                done_bytes += entry["size"]
                report(doneBytes=done_bytes, files={"done": index + 1, "total": len(manifest["files"])})
                continue
            for attempt in (1, 2):
                partial = destination.with_name(destination.name + ".part")
                destination.parent.mkdir(parents=True, exist_ok=True)
                have = partial.stat().st_size if partial.is_file() else 0
                if have > entry["size"]:
                    partial.unlink()
                    have = 0
                if have:
                    status["resumedBytes"] = int(status.get("resumedBytes") or 0) + have

                def progress(count: int, base: int = done_bytes) -> None:
                    nonlocal fetched
                    fetched += count
                    report(doneBytes=base + partial.stat().st_size if partial.exists() else base,
                           current={"path": entry["path"], "size": entry["size"]})
                    if (pack / "pause").exists():
                        raise _Paused()

                _fetch(entry["url"], partial, have, entry["size"], progress, manifest.get("throttleKbps"), sleep)
                report(True, state="verifying", current={"path": entry["path"], "size": entry["size"]})
                if partial.stat().st_size == entry["size"] and _sha256(partial) == entry["sha256"]:
                    os.replace(partial, destination)
                    check_staged_file(destination, entry)
                    verified[key] = [entry["sha256"], destination.stat().st_mtime_ns]
                    _write_json(pack / "verified.json", verified)
                    break
                partial.unlink(missing_ok=True)  # a corrupt copy is never kept or resumed
                if attempt == 2:
                    raise ValueError(f"{entry['path']} failed its checksum twice; the source may be wrong")
                status["retries"] = int(status.get("retries") or 0) + 1
            done_bytes += entry["size"]
            report(True, state="running", doneBytes=done_bytes, files={"done": index + 1, "total": len(manifest["files"])})
        receipt = {"schema": "neyvia.base-pack-receipt/v1", "packId": manifest["packId"], "version": manifest["version"],
                   "manifest": manifest["source"], "installedAt": _now(), "target": str(target),
                   "files": [{"path": row["path"], "size": row["size"], "sha256": row["sha256"]} for row in manifest["files"]]}
        _write_json(target / "installed.json", receipt)
        report(True, state="done", doneBytes=done_bytes, finishedAt=_now(), current=None, receipt=str(target / "installed.json"))
    except _Paused:
        (pack / "pause").unlink(missing_ok=True)
        report(True, state="paused", detail="Paused. Resume picks up where it left off.")
    except Exception as exc:  # the UI shows this and offers Try again
        report(True, state="failed", error=str(exc)[:500])
    check_download_result(pack, target, manifest, status)
    return status


def _fetch(url: str, partial: Path, have: int, size: int, progress: Callable[[int], None],
           throttle_kbps: float | None, sleep: Callable[[float], None]) -> None:
    if have >= size:
        if size == 0:
            partial.touch()
        return
    parsed = urlparse(url)
    if parsed.scheme == "file":
        source = Path(url2pathname(parsed.path))
        stream = source.open("rb")
        stream.seek(have)
    else:
        request = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        try:
            stream = urllib.request.urlopen(request, timeout=30)  # noqa: S310 - checked by _check_source
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have:  # the server says we already have it all; checksum decides
                return
            raise
        if have and getattr(stream, "status", 200) != 206:
            partial.unlink(missing_ok=True)  # no range support: start this file again
            have = 0
    with stream, partial.open("ab" if have else "wb") as out:
        while True:
            block = stream.read(CHUNK)
            if not block:
                break
            if out.tell() + len(block) > size:
                raise ValueError("Download exceeds the manifest's declared size")
            out.write(block)
            out.flush()
            progress(len(block))
            if throttle_kbps:
                sleep(len(block) / (throttle_kbps * 1024))


# ------------------------------------------------------------ dispatchers ---

def handle(root: Path, command: str, payload: dict[str, Any] | None = None, *, provider_env: dict[str, str] | None = None) -> Any:
    payload = payload or {}
    if command == "onboarding_state_command":
        return snapshot(root)
    if command == "onboarding_save_command":
        return {"state": save_state(root, payload)}
    if command == "onboarding_runtimes_command":
        return detect_runtimes(root, provider_env)
    if command == "onboarding_base_pack_status_command":
        return base_pack_status(root)
    if command == "onboarding_base_pack_start_command":
        return start_base_pack(root)
    if command == "onboarding_base_pack_pause_command":
        return pause_base_pack(root)
    if command == "onboarding_pack_status_command":
        return pack_status(root, payload.get("packId"))
    if command == "onboarding_pack_install_command":
        return install_pack(root, str(payload.get("packId") or ""))
    raise ValueError(f"Unknown onboarding command {command}")


def tool_specs(spec_type):
    return [spec_type(name="neyvia." + name, description=description, category="neyvia-onboarding",
                      input_schema={"type": "object", "properties": props, "required": required},
                      mutability_class="artifact_write" if name == "onboarding.pack" else "read" if name in {"onboarding.state", "onboarding.recommend", "onboarding.runtimes"} else "none",
                      capabilities=("neyvia." + name,), parallel_safe=False)
            for name, description, props, required in DEFINITIONS]


def call_tool(root: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The bot side: same state and commands as the setup screen."""
    from .ui_command_bus import bus_for
    if name == "state":
        return {"ok": True, **snapshot(root)}
    if name == "recommend":
        return {"ok": True, **recommend(load_catalog(), args.get("interests"), args.get("tier"))}
    if name == "save":
        allowed = {key: args[key] for key in ("interests", "tier", "apps", "packs", "runtime", "completed") if key in args}
        return {"ok": True, "state": save_state(root, allowed)}
    if name == "runtimes":
        return {"ok": True, **detect_runtimes(root)}
    if name == "base_pack":
        action = args.get("action") or "status"
        result = {"status": base_pack_status, "start": start_base_pack, "pause": pause_base_pack}[action](root)
        return {"ok": result.get("state") != "failed", **result}
    if name == "pack":
        action = args.get("action") or "status"
        if action not in {"status", "install"}:
            raise ValueError("Pack action is status or install")
        result = install_pack(root, str(args.get("packId") or "")) if action == "install" else pack_status(root, args.get("packId"))
        return {"ok": action == "status" or all(row["state"] not in {"failed", "unavailable"} for row in result["packs"]), **result}
    if name == "open":
        step = args.get("step") or "welcome"
        if step not in {"welcome", "runtimes", "interests", "tour"}:
            raise ValueError("step is welcome, runtimes, interests or tour")
        event = bus_for(root).emit("onboarding.open", {"step": step})
        return {"ok": True, "event": event, "uiVerified": False}
    raise ValueError(f"Unknown onboarding tool {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neyvia base pack downloader")
    sub = parser.add_subparsers(dest="action", required=True)
    download = sub.add_parser("download")
    download.add_argument("--root", required=True)
    download.add_argument("--pack-id", help="Install a separately packaged add-on instead of the base pack")
    build = sub.add_parser("manifest", help="Write a base-pack manifest for a folder or file list")
    build.add_argument("--from", dest="source", required=True, help="Folder whose files make up the pack")
    build.add_argument("--pack-id", default="base")
    build.add_argument("--version", required=True)
    build.add_argument("--base-url", default="", help="Where the files will be served; empty means next to the manifest")
    build.add_argument("--out", required=True)
    build.add_argument("--channel", default="")
    build.add_argument("--test-throttle-kbps", type=int, default=0, help="Slow local test downloads so progress is visible")
    args = parser.parse_args(argv)
    if args.action == "download":
        status = run_download(Path(args.root), pack_id=args.pack_id)
        return 0 if status.get("state") in {"done", "paused"} else 1
    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    files = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source).as_posix()
        url = relative if args.base_url else Path(os.path.relpath(path, out.parent)).as_posix()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256(path), "url": url})
    manifest = {"schema": MANIFEST_SCHEMA, "packId": args.pack_id, "version": args.version, "createdAt": _now(),
                **({"channel": args.channel} if args.channel else {}),
                **({"baseUrl": args.base_url} if args.base_url else {}),
                **({"dev": {"throttleKbps": args.test_throttle_kbps}} if args.test_throttle_kbps else {}),
                "totalSize": sum(row["size"] for row in files), "files": files}
    parse_manifest(json.dumps(manifest), str(out))
    _write_json(out, manifest)
    print(f"{len(files)} files, {manifest['totalSize']} bytes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
