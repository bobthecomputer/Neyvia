"""Canonical owner preferences on the existing durable UI bus."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from .ui_command_bus import now
from .subprocess_utils import hidden_windows_subprocess_kwargs

COMMANDS = frozenset({"settings_get_command", "settings_update_command", "settings_setup_command", "settings_network_check_command",
                      "settings_background_save_command", "settings_background_get_command"})
LEVELS = ("suggest", "act-and-tell", "silent")
THEMES = {"forest": "dark", "morning": "light", "sunset": "sunset", "night-green": "night",
          "terminal": "terminal", "paper": "paper", "ember": "ember"}
# Settings > Look: typeface pair, text size and what sits behind the chats (the
# shell applies them; web/src/neyvia/next/nxLookModel.js keeps the same names and limits).
FONTS = ("neyvia", "windows", "inter", "geist", "editorial")
TEXT_SIZES = ("s", "m", "l")
BACKGROUND_KINDS = ("theme", "preset", "solid", "image")
# Follow the sun (Settings > Look; plan 29 THEMES2): off by default, offered only for themes with a day/night pair
# (nxThemeRegistry.js daypair). Sunrise and sunset are the person's own local times, "HH:MM".
SUN_DEFAULTS = {"follow": False, "intoNight": False, "sunrise": "07:00", "sunset": "19:30"}
SUN_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
SUN_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LOOK_DEFAULTS = {"font": "neyvia", "textSize": "m",
                 "background": {"kind": "theme", "preset": "", "color": "", "image": "", "dim": 0, "blur": 0},
                 "sun": SUN_DEFAULTS}
BACKGROUND_FILE = re.compile(r"^bg-[0-9a-f]{16}\.(png|jpg|webp)$")
DEFAULTS = {"density": "calm", "theme": "forest", "initiative": "suggest", "projectInitiative": {}, "localOnly": False,
            "toolAutoUpdate": "allow", "look": LOOK_DEFAULTS}  # harness CLIs stay current by default (Paul, 9 Oct); Settings can switch to ask or off
PATCH_SCHEMA = {"type": "object", "properties": {
    "density": {"type": "string", "enum": ["calm", "workshop", "grove"]},
    "theme": {"type": "string", "enum": list(THEMES)},
    "initiative": {"type": "string", "enum": list(LEVELS)},
    "projectInitiative": {"type": "object", "additionalProperties": {"type": "string", "enum": list(LEVELS)}},
    "localOnly": {"type": "boolean"}, "cleanup": {"type": "object"}, "nightShift": {"type": "object"}},
    "additionalProperties": False}
PATCH_SCHEMA["properties"]["toolAutoUpdate"] = {"type": "string", "enum": ["ask", "off", "allow"]}
PATCH_SCHEMA["properties"]["look"] = {"type": "object", "additionalProperties": False, "properties": {
    "font": {"type": "string", "enum": list(FONTS)}, "textSize": {"type": "string", "enum": list(TEXT_SIZES)},
    "background": {"type": "object", "additionalProperties": False, "properties": {
        "kind": {"type": "string", "enum": list(BACKGROUND_KINDS)}, "preset": {"type": "string", "maxLength": 40},
        "color": {"type": "string", "pattern": "^(#[0-9a-f]{6})?$"}, "image": {"type": "string", "maxLength": 40},
        "dim": {"type": "integer", "minimum": 0, "maximum": 90}, "blur": {"type": "integer", "minimum": 0, "maximum": 40}}},
    "sun": {"type": "object", "additionalProperties": False, "properties": {
        "follow": {"type": "boolean"}, "intoNight": {"type": "boolean"},
        "sunrise": {"type": "string", "pattern": SUN_PATTERN}, "sunset": {"type": "string", "pattern": SUN_PATTERN}}}}}
DEFINITIONS = [
    ("settings.get", "Read canonical persistent settings and enforced local-only status.", {}, []),
    ("settings.propose", "Propose settings to the PC owner; never applies without owner approval. Reuse the observed revision.",
     {"patch": PATCH_SCHEMA, "expectedRevision": {"type": "integer", "minimum": 0}}, ["patch", "expectedRevision"]),
    ("settings.setup", "Re-enter existing setup without erasing installation or credentials.", {}, []),
    ("settings.network_check", "Check local-only TCP, UDP, DNS, HTTP and child-process refusals. Runs only when local-only is on.", {}, []),
]


class SettingsConflict(ValueError):
    status = 409


def _state(db):
    from .connected_sessions.sidebar_cleanup import DEFAULT_POLICY
    from .nightshift_resources import DEFAULTS as RESOURCE_DEFAULTS
    values = {row["key"]: json.loads(row["value"]) for row in db.execute(
        "SELECT key,value FROM state WHERE key IN ('settings','cleanupPolicy','nightshift.resources','density','theme')")}
    saved = {**DEFAULTS, **values.get("settings", {})}
    density = values.get("density", {})
    saved["density"] = density.get("level", saved["density"]) if isinstance(density, dict) else saved["density"]
    saved["theme"] = {v: k for k, v in THEMES.items()}.get(values.get("theme"), saved["theme"])
    saved["cleanup"] = {**DEFAULT_POLICY, **values.get("cleanupPolicy", {})}
    saved["nightShift"] = {**RESOURCE_DEFAULTS, **values.get("nightshift.resources", {})}
    look = saved.get("look") if isinstance(saved.get("look"), dict) else {}
    saved["look"] = {**LOOK_DEFAULTS, **look, "background": {**LOOK_DEFAULTS["background"], **(look.get("background") or {})},
                     "sun": {**SUN_DEFAULTS, **(look.get("sun") if isinstance(look.get("sun"), dict) else {})}}
    return saved.pop("revision", 0), saved


def get(service):
    from .local_network_policy import install, status
    install(service.bus.root, owner=service)
    with service.bus.connect() as db:
        revision, settings = _state(db)
    return {"revision": revision, "settings": settings, "network": status(),
            "setup": service.bus.get("settings.setup", {})}


def validate(current, patch):
    from .connected_sessions.sidebar_cleanup import DEFAULT_POLICY, normalize_policy
    from .nightshift_resources import validate_policy
    if not isinstance(patch, dict) or not patch or set(patch) - (set(DEFAULTS) | {"cleanup", "nightShift"}):
        raise ValueError("Give a nonempty settings patch with known fields")
    value = {**current, **patch}
    for field, choices in (("density", ("calm", "workshop", "grove")), ("theme", THEMES), ("initiative", LEVELS),
                           ("toolAutoUpdate", ("ask", "off", "allow"))):
        if not isinstance(value[field], str) or value[field] not in choices:
            raise ValueError("Unknown " + field)
    if not isinstance(value["localOnly"], bool):
        raise ValueError("localOnly must be boolean")
    overrides = value["projectInitiative"]
    if not isinstance(overrides, dict) or len(overrides) > 200:
        raise ValueError("projectInitiative must be a map of at most 200 absolute project paths")
    for path, level in overrides.items():
        if not isinstance(path, str) or not Path(path).is_absolute() or level not in LEVELS:
            raise ValueError("Project initiative needs absolute paths and supported levels")
    value["projectInitiative"] = {str(Path(path).resolve()): level for path, level in overrides.items()}
    if "cleanup" in patch:
        cleanup = patch["cleanup"]
        if not isinstance(cleanup, dict) or set(cleanup) - set(DEFAULT_POLICY):
            raise ValueError("Unknown cleanup rule")
        if "autoArchive" in cleanup and not isinstance(cleanup["autoArchive"], bool):
            raise ValueError("autoArchive must be boolean")
        for field in ("noFolderDays", "projectDays", "tidyThreshold"):
            if field in cleanup and (not isinstance(cleanup[field], int) or isinstance(cleanup[field], bool)):
                raise ValueError(field + " must be an integer")
        value["cleanup"] = normalize_policy({**current["cleanup"], **cleanup})
    if "nightShift" in patch:
        value["nightShift"] = validate_policy(current["nightShift"], patch["nightShift"])
    if "look" in patch:
        value["look"] = validate_look(current["look"], patch["look"])
    return value


def validate_look(current, patch):
    """Merge a Look patch (font, textSize, background fields) into the saved look."""
    if not isinstance(patch, dict) or set(patch) - set(LOOK_DEFAULTS):
        raise ValueError("Unknown look field")
    background = patch.get("background", {})
    if not isinstance(background, dict) or set(background) - set(LOOK_DEFAULTS["background"]):
        raise ValueError("Unknown background field")
    sun = patch.get("sun", {})
    if not isinstance(sun, dict) or set(sun) - set(SUN_DEFAULTS):
        raise ValueError("Unknown follow-the-sun field")
    value = {**current, **{k: v for k, v in patch.items() if k not in ("background", "sun")},
             "background": {**current["background"], **background}, "sun": {**SUN_DEFAULTS, **current.get("sun", {}), **sun}}
    if value["font"] not in FONTS:
        raise ValueError("Unknown font; choose " + ", ".join(FONTS))
    if value["textSize"] not in TEXT_SIZES:
        raise ValueError("Text size is s, m or l")
    bg = value["background"]
    if bg["kind"] not in BACKGROUND_KINDS:
        raise ValueError("Background is theme, preset, solid or image")
    if not isinstance(bg["preset"], str) or not re.fullmatch(r"[a-z0-9-]{0,40}", bg["preset"]):
        raise ValueError("Unknown background preset")
    if not isinstance(bg["color"], str) or not re.fullmatch(r"(#[0-9a-f]{6})?", bg["color"]):
        raise ValueError("Background colour must look like #1a2b3c")
    if not isinstance(bg["image"], str) or (bg["image"] and not BACKGROUND_FILE.fullmatch(bg["image"])):
        raise ValueError("Unknown background image")
    for field, top in (("dim", 90), ("blur", 40)):
        if type(bg[field]) is not int or not 0 <= bg[field] <= top:
            raise ValueError(f"{field} must be a whole number from 0 to {top}")
    sun = value["sun"]
    for field in ("follow", "intoNight"):
        if type(sun[field]) is not bool:
            raise ValueError(f"{field} must be true or false")
    for field in ("sunrise", "sunset"):
        if not isinstance(sun[field], str) or not SUN_TIME.fullmatch(sun[field]):
            raise ValueError(f"{field} must look like 07:00")
    minutes = {f: int(sun[f][:2]) * 60 + int(sun[f][3:]) for f in ("sunrise", "sunset")}
    if minutes["sunset"] - minutes["sunrise"] < 240:
        raise ValueError("Sunset must be at least four hours after sunrise")
    needed = {"preset": "preset", "solid": "color", "image": "image"}.get(bg["kind"])
    if needed and not bg[needed]:
        raise ValueError(f"A {bg['kind']} background needs its {needed}")
    return value


# ---- your own background image (Settings > Look) ---------------------------

MAX_BACKGROUND_BYTES = 12 * 1024 * 1024
KEEP_BACKGROUNDS = 4
_IMAGE_KINDS = {"image/png": (".png", b"\x89PNG\r\n\x1a\n"), "image/jpeg": (".jpg", b"\xff\xd8\xff"), "image/webp": (".webp", b"RIFF")}


def background_dir(root):
    return Path(root) / ".neyvia" / "look"


def save_background(root, data_url):
    """Keep an uploaded background in the app's state folder; returns its file name."""
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)", str(data_url or ""))
    if not match:
        raise ValueError("Choose a PNG, JPEG or WebP image")
    data = base64.b64decode(match.group(2), validate=False)
    extension, magic = _IMAGE_KINDS[match.group(1)]
    if not data.startswith(magic) or (extension == ".webp" and data[8:12] != b"WEBP"):
        raise ValueError("That file is not the image type it claims to be")
    if len(data) > MAX_BACKGROUND_BYTES:
        raise ValueError("Background images can be up to 12 MB")
    folder = background_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    name = "bg-" + hashlib.sha256(data).hexdigest()[:16] + extension
    target = folder / name
    if not target.exists():
        partial = folder / (name + ".part")
        partial.write_bytes(data)
        partial.replace(target)
    target.touch()
    # Only the few newest uploads are kept; the one just saved is always among them.
    others = sorted((p for p in folder.glob("bg-*") if BACKGROUND_FILE.fullmatch(p.name) and p.name != name),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in others[KEEP_BACKGROUNDS - 1:]:
        stale.unlink(missing_ok=True)
    return {"image": name, "bytes": len(data)}


def read_background(root, name):
    if not isinstance(name, str) or not BACKGROUND_FILE.fullmatch(name):
        raise ValueError("Unknown background image")
    path = background_dir(root) / name
    if not path.is_file():
        raise ValueError("That background image is no longer on this PC")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
    return {"image": name, "dataUrl": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")}


def update(service, patch, expected_revision=None, *, request_id=None):
    if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
        raise ValueError('Settings request ID must contain 1 to 128 characters')
    from .local_network_policy import install, transition, status
    from .proofs_settings import snapshot, check_revision, check_rejection, check_committed
    install(service.bus.root, owner=service)
    # Network lock precedes SQLite everywhere: no child start can race activation.
    with transition(False):
        with service.bus.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision, current = _state(db)
            check_revision(expected_revision, revision)
            before, previous_revision = snapshot(db), revision
            try:
                value = validate(current, patch)
            except ValueError:
                check_rejection(db, before)
                raise
            with transition(value["localOnly"] and not current["localOnly"]):
                revision += 1
                def put(key, item):
                    db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(item)))
                put("settings", {**value, "revision": revision})
                put("cleanupPolicy", value["cleanup"])
                put("nightshift.resources", value["nightShift"])
                put("density", {"level": value["density"]})
                put("theme", THEMES[value["theme"]])
                events = []
                actions = [("settings.changed", {"revision": revision, "settings": value, "changedKeys": list(patch)})]
                if "nightShift" in patch:
                    actions.append(("nightshift.resources.updated", value["nightShift"]))
                if value["density"] != current["density"]:
                    actions.append(("view.layout", {"level": value["density"]}))
                if value["theme"] != current["theme"]:
                    actions.append(("view.theme", {"theme": THEMES[value["theme"]]}))
                for action, payload in actions:
                    if request_id and action in {"settings.changed", "view.layout", "view.theme"}:
                        payload = {**payload, "settingsRequestId": request_id}
                    at = now()
                    cursor = db.execute("INSERT INTO events(ts,action,payload) VALUES(?,?,?)", (at, action, json.dumps(payload)))
                    events.append({"id": str(cursor.lastrowid), "ts": at, "action": action, "payload": payload})
                check_committed(db, patch, value, previous_revision, revision, events)
    with service.bus.changed:
        service.bus.changed.notify_all()
    service.wake.set()
    if "nightShift" in patch and service.backend is not None:
        from .nightshift import refresh_settings
        refresh_settings(service.bus.root)
    return {"revision": revision, "settings": value, "network": status(),
            "setup": service.bus.get("settings.setup", {}), "events": events}


def effective_initiative(service, project=None):
    saved = service.bus.get("settings", DEFAULTS)
    if isinstance(project, dict):
        project = project.get("path")
    return saved.get("projectInitiative", {}).get(str(Path(project).resolve()) if project else "", saved.get("initiative", "suggest"))


def setup(service):
    value = {"requestedAt": now()}
    service.bus.put("settings.setup", value)
    return {"ok": True, "setup": value, "events": [service.bus.emit("setup.open", {"resume": True})]}


def call(service, name, args):
    if name == "settings.get":
        return {"ok": True, **get(service)}
    if name == "settings.setup":
        return setup(service)
    if name == "settings.network_check":
        return network_check(service)
    if name != "settings.propose":
        raise ValueError("Unknown settings operation")
    observed = get(service)
    revision = args.get("expectedRevision")
    if type(revision) is not int or revision != observed["revision"]:
        raise SettingsConflict("Settings changed. Read settings.get before proposing.")
    validate(observed["settings"], args.get("patch"))
    details = {"patch": args["patch"], "expectedRevision": revision}
    digest = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
    key = "settings:" + digest
    receipt = service.bus.get("settings.applied:" + digest)
    if receipt:
        return {"ok": True, "status": "approved", **receipt}
    return service.require_approval(key, "Review the proposed Settings change", details)


def handle_command(backend, command, payload):
    from .neyvia_workspace_tools import workspace_for
    expected_root = payload.get("_expectedStateRoot")
    if expected_root and Path(expected_root).resolve() != backend.root:
        raise SettingsConflict("The service uses a different state folder")
    service = workspace_for(backend.root, backend)
    if command == "settings_get_command":
        return get(service)
    if command == "settings_setup_command":
        return setup(service)
    if command == "settings_network_check_command":
        return network_check(service)
    if command == "settings_background_save_command":
        return save_background(backend.root, payload.get("dataUrl"))
    if command == "settings_background_get_command":
        return read_background(backend.root, payload.get("image"))
    if command != "settings_update_command" or type(payload.get("expectedRevision")) is not int:
        raise ValueError("expectedRevision is required")
    return update(service, payload.get("patch"), payload["expectedRevision"], request_id=payload.get("requestId"))


def network_check(service):
    """Real denied operations, serialized against disabling; never probe online."""
    import asyncio
    import socket
    import subprocess
    import sys
    import os
    import urllib.error
    import urllib.request
    from .local_network_policy import LocalOnlyError, enabled, transition
    results = []
    port = int(os.environ.get("NEYVIA_NETWORK_CHECK_PORT", "48259"))
    if not 1024 <= port <= 65535 or port == 47881:
        raise ValueError("Use an explicit non-public network-check port")
    with transition(False):
        if not enabled():
            raise SettingsConflict("Enable local-only mode before running its network check")
        def probe(name, operation):
            try:
                operation()
            except LocalOnlyError:
                results.append({"name": name, "blocked": True})
            except urllib.error.URLError as exc:
                if not isinstance(exc.reason, LocalOnlyError):
                    raise
                results.append({"name": name, "blocked": True})
            else:
                results.append({"name": name, "blocked": False})
        with socket.socket() as stream:
            stream.settimeout(0.2)
            probe("tcp", lambda: stream.connect(("192.0.2.1", port)))
            probe("connect_ex", lambda: stream.connect_ex(("192.0.2.1", port)))
        with socket.socket(socket.AF_INET6) as stream:
            probe("ipv6", lambda: stream.connect(("2001:db8::1", port)))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            probe("udp", lambda: stream.sendto(b"local-only-check", ("192.0.2.1", port)))
        probe("dns", lambda: socket.getaddrinfo("local-only-check.invalid", port))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        probe("http", lambda: opener.open(f"http://192.0.2.1:{port}/", timeout=0.2))
        probe("https", lambda: opener.open(f"https://192.0.2.1:{port}/", timeout=0.2))
        probe("child", lambda: subprocess.run([sys.executable, "-c", "pass"], check=True, timeout=2, **hidden_windows_subprocess_kwargs()))
        from .connected_sessions.claude_terminal import spawn_terminal
        probe("conpty_child", lambda: spawn_terminal([sys.executable, "-c", "pass"], str(service.bus.root), {}))
        async def async_tcp():
            with socket.socket() as stream:
                stream.setblocking(False)
                await asyncio.get_running_loop().sock_connect(stream, ("192.0.2.1", port))
        probe("async_tcp", lambda: asyncio.run(async_tcp()))
    return {"ok": all(row["blocked"] for row in results), "checks": results, "network": get(service)["network"]}
