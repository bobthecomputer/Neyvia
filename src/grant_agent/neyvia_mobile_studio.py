"""Mobile Studio (Studio suite): a phone preview beside the chat, iPhone builds
through the Windows-native IPA engine, Android builds with Gradle and installs
with adb. One state on the bus (app:mobile-studio) for both sides.

User side: web/src/neyvia/next/NxMobileStudio.jsx. Bot side: neyvia.mobile.*.
Manual: docs/manuals/mobile-studio.md.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .subprocess_utils import hidden_windows_subprocess_kwargs

TEXT = {"type": "string"}
BOOL = {"type": "boolean"}
STATE_KEY = "app:mobile-studio"
TOKENS_KEY = "mobile:preview-tokens"
BUILDS = Path(".agent_control") / "mobile_builds"
STORAGE = Path(".agent_control") / "mobile_preview_storage.json"
PREVIEW_PREFIX = "/api/ui/mobile-preview/"
SKIP_DIRS = {"node_modules", ".git", ".agent_control", ".expo", ".gradle", "build", "Pods", "DerivedData"}

# Screen sizes in CSS points (iPhone) / dp (Pixel), portrait. Safe areas are what
# the system reserves: status bar or Dynamic Island on top, the home indicator
# or gesture bar at the bottom. iPhone values are Apple's; Pixel values are the
# typical edge-to-edge insets of Android 15 on those phones.
IOS_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 15; {model}) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/129.0.0.0 Mobile Safari/537.36")
DEVICES = [
    {"id": "iphone-16-pro", "name": "iPhone 16 Pro", "platform": "ios", "width": 402, "height": 874, "radius": 62,
     "cutout": "island", "statusBar": 54, "home": "indicator",
     "safe": {"portrait": [62, 0, 34, 0], "landscape": [0, 62, 21, 62]}, "ua": IOS_UA},
    {"id": "iphone-16-pro-max", "name": "iPhone 16 Pro Max", "platform": "ios", "width": 440, "height": 956, "radius": 62,
     "cutout": "island", "statusBar": 54, "home": "indicator",
     "safe": {"portrait": [62, 0, 34, 0], "landscape": [0, 62, 21, 62]}, "ua": IOS_UA},
    {"id": "iphone-16", "name": "iPhone 16", "platform": "ios", "width": 393, "height": 852, "radius": 55,
     "cutout": "island", "statusBar": 54, "home": "indicator",
     "safe": {"portrait": [59, 0, 34, 0], "landscape": [0, 59, 21, 59]}, "ua": IOS_UA},
    {"id": "iphone-se", "name": "iPhone SE", "platform": "ios", "width": 375, "height": 667, "radius": 0,
     "cutout": "none", "statusBar": 20, "home": "button",
     "safe": {"portrait": [20, 0, 0, 0], "landscape": [0, 0, 0, 0]}, "ua": IOS_UA},
    {"id": "pixel-9", "name": "Pixel 9", "platform": "android", "width": 412, "height": 923, "radius": 46,
     "cutout": "punch", "statusBar": 40, "home": "gesture",
     "safe": {"portrait": [40, 0, 24, 0], "landscape": [24, 0, 24, 40]}, "ua": ANDROID_UA.format(model="Pixel 9")},
    {"id": "pixel-9-pro-xl", "name": "Pixel 9 Pro XL", "platform": "android", "width": 448, "height": 997, "radius": 50,
     "cutout": "punch", "statusBar": 40, "home": "gesture",
     "safe": {"portrait": [40, 0, 24, 0], "landscape": [24, 0, 24, 40]}, "ua": ANDROID_UA.format(model="Pixel 9 Pro XL")},
]
DEVICE_IDS = [device["id"] for device in DEVICES]

_APPLE_FRAMES = [
    ("ipad-pro-13", "iPad Pro 13", "ipados", 1024, 1366, 24, 24, [24, 0, 20, 0], "indicator"),
    ("mac-window", "Mac window", "macos", 1120, 760, 12, 30, [30, 0, 0, 0], "none"),
    ("watch-46", "Watch 46 · web concept", "watchos", 208, 248, 44, 24, [24, 6, 12, 6], "none"),
    ("apple-tv", "Apple TV · web concept", "tvos", 1280, 720, 6, 0, [36, 64, 36, 64], "none"),
    ("vision-window", "Vision window · flat concept", "visionos", 1024, 768, 28, 0, [0, 0, 0, 0], "none"),
]
for frame_id, name, platform, width, height, radius, status_bar, safe, home in _APPLE_FRAMES:
    DEVICES.append({"id": frame_id, "name": name, "platform": platform, "width": width, "height": height,
                    "radius": radius, "statusBar": status_bar, "cutout": "none", "home": home,
                    "safe": {"portrait": safe, "landscape": safe},
                    "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15" if platform == "macos" else IOS_UA.replace("iPhone", "iPad") if platform == "ipados" else IOS_UA,
                    "emulated": True})
DEVICE_IDS = [device["id"] for device in DEVICES]

# Exact download sizes (bytes) of the pieces Neyvia never downloads by itself,
# read from the official release servers on 2 Oct 2026.
DOWNLOADS = {
    "llvm": ("LLVM 22.1.6 for Windows (iPhone compiler)", 861_999_212, "In Mobile Studio: Install iPhone compiler, or `python -m grant_agent.cli ios-studio-windows-setup --root <app> --engine win32`"),
    "zsign": ("zsign 1.0.8 (iPhone signer)", 1_812_881, "Installed together with LLVM"),
    "jdk": ("Java 21 (Eclipse Temurin JDK, zip)", 205_073_461, "https://adoptium.net/temurin/releases/?version=21&os=windows"),
    "cmdline-tools": ("Android command-line tools", 143_040_480, "https://developer.android.com/studio#command-line-tools-only"),
    "platform-tools": ("Android platform-tools (adb)", 8_044_989, "sdkmanager \"platform-tools\""),
    "build-tools": ("Android build-tools 35", 59_878_107, "sdkmanager \"build-tools;35.0.0\""),
    "platform": ("Android 15 platform (API 35)", 64_273_788, "sdkmanager \"platforms;android-35\""),
    "emulator": ("Android Emulator", 459_420_448, "sdkmanager \"emulator\""),
    "system-image": ("Android 15 phone image (Google APIs, x86_64)", 1_738_815_903, "sdkmanager \"system-images;android-35;google_apis;x86_64\""),
}
GRADLE_FIRST_BUILD = "Gradle fetches about 400 MB of build tools into ~/.gradle on the first Android build."

DEFINITIONS = [
    ("mobile.status", "Read Mobile Studio: the app folder and its kind, the phone preview, iPhone and Android toolchains with exactly what is missing (and download sizes), connected phones/emulators, running and last builds.",
     {"project": TEXT}, []),
    ("mobile.preview", "Show the app in a phone frame beside the chat (opens Mobile Studio). device: " + ", ".join(DEVICE_IDS) + ". Hot reload is on: edits to the app's files show at once.",
     {"device": {"type": "string", "enum": DEVICE_IDS}, "project": TEXT, "orientation": {"type": "string", "enum": ["portrait", "landscape"]}, "dark": BOOL, "startExpo": BOOL,
      "textScale": {"type": "number", "minimum": 0.8, "maximum": 2}, "keyboard": BOOL}, []),
    ("mobile.build", "Build the app. platform ios: a .ipa compiled on Windows (sideload with a free Apple ID). platform android: a debug .apk with Gradle. Runs in the background; waitSeconds (0-900) waits for it, else poll mobile.status.",
     {"platform": {"type": "string", "enum": ["ios", "android", "ipados", "macos", "watchos", "tvos", "visionos"]}, "project": TEXT, "waitSeconds": {"type": "integer", "minimum": 0, "maximum": 900}, "addShell": BOOL}, ["platform"]),
    ("mobile.verify", "Re-read the last completed Apple bundle and archive: architecture, load commands, metadata and all signature/resource hashes. Does not prove Apple trust or launch.",
     {"project": TEXT, "platform": {"type": "string", "enum": ["ios", "ipados", "macos", "watchos", "tvos", "visionos"]}}, ["platform"]),
    ("mobile.simulate", "instant: emulated browser frame; cloud: prepare dormant own-account GitHub macOS Simulator capsule or import downloaded results (never dispatch); device: installation guide.",
     {"project": TEXT, "tier": {"type": "string", "enum": ["instant", "cloud", "device"]},
      "platform": {"type": "string", "enum": ["ios", "ipados", "macos", "watchos", "tvos", "visionos"]}, "results": TEXT}, ["tier"]),
    ("mobile.install", "Install the last build. target: emulator (starts one if needed; avd picks which), usb (the one plugged-in Android phone), an adb serial, or iphone (returns the sideload steps for the .ipa).",
     {"target": TEXT, "project": TEXT, "avd": TEXT, "waitSeconds": {"type": "integer", "minimum": 0, "maximum": 600}}, ["target"]),
    ("mobile.setup", "Install the iPhone compiler (LLVM 22.1.6 + zsign, 864 MB download, checksum-verified, no admin rights) into the Neyvia toolchains folder under LOCALAPPDATA. Needs Paul's approval every time; never call it unasked.",
     {"part": {"type": "string", "enum": ["ios-compiler"]}, "project": TEXT}, ["part"]),
    ("mobile.create", "Create a starter phone app (plain HTML/CSS/JS, previewable at once, builds for iPhone and Android) in an empty folder and open it in Mobile Studio.",
     {"path": TEXT, "name": TEXT, "bundleId": TEXT}, ["path", "name"]),
]

_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_java_cache: dict[str, tuple[float, str]] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(command, cwd=None, timeout=600, env=None):
    return subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                          **hidden_windows_subprocess_kwargs())


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _preview_storage_snapshot(path: Path) -> dict:
    if not path.parent.is_dir():
        return {}
    from .harness_jobs import _exclusive_job_lock
    with _exclusive_job_lock(path):
        return _read_json(path, {}) or {}


def _size(value: int) -> str:
    return f"{value / 1_000_000_000:.2f} GB" if value >= 1_000_000_000 else f"{round(value / 1_000_000)} MB"


def _missing(key: str, why: str = "") -> dict:
    label, size, how = DOWNLOADS[key]
    return {"id": key, "label": label, "bytes": size, "size": _size(size), "how": how, **({"why": why} if why else {})}


# ---------------------------------------------------------------- project --

def project_info(root: Path) -> dict:
    """What kind of app this folder is, where its screens live and its IDs."""
    package = _read_json(root / "package.json", {}) or {}
    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    app = _read_json(root / "app.json", {}) or {}
    expo = app.get("expo") if isinstance(app.get("expo"), dict) else {}
    cap = _read_json(root / "capacitor.config.json", None)
    if cap is None:
        for name in ("capacitor.config.ts", "capacitor.config.js"):
            text = (root / name).read_text(encoding="utf-8", errors="replace") if (root / name).is_file() else ""
            if text:
                found = {key: re.search(key + r"\s*:\s*['\"]([^'\"]+)['\"]", text) for key in ("appId", "appName", "webDir")}
                cap = {key: match.group(1) for key, match in found.items() if match}
                break
    kind = "expo" if "expo" in deps else "capacitor" if cap is not None or "@capacitor/core" in deps else "react-native" if "react-native" in deps else "web"
    candidates = ([cap.get("webDir")] if cap and cap.get("webDir") else []) + ["www", "dist", "web-build", "build/web", "build", "public", "."]
    web_root = next((root / name for name in candidates if name and (root / name / "index.html").is_file()), None)
    ios_id = str(((expo.get("ios") or {}) if isinstance(expo.get("ios"), dict) else {}).get("bundleIdentifier") or "")
    android_id = str(((expo.get("android") or {}) if isinstance(expo.get("android"), dict) else {}).get("package") or "")
    gradle = root / "android" / "app" / "build.gradle"
    if gradle.is_file():
        match = re.search(r"applicationId\s*[= ]\s*['\"]([^'\"]+)", gradle.read_text(encoding="utf-8", errors="replace"))
        android_id = match.group(1) if match else android_id
    native = _read_json(root / "neyvia.app.json", {}) or {}
    app_id = (cap or {}).get("appId") or native.get("bundleIdentifier") or ("com.neyvia." + re.sub(r"[^A-Za-z0-9]", "", str(native["instance"])) if native.get("instance") else "")
    result = {
        "root": str(root), "exists": root.is_dir(), "kind": kind,
        "name": str(expo.get("name") or (cap or {}).get("appName") or package.get("displayName") or package.get("name") or root.name),
        "webRoot": str(web_root) if web_root else "",
        "iosBundleId": ios_id or app_id, "androidPackage": android_id or app_id or ios_id,
        "hasAndroidProject": (root / "android" / "gradlew.bat").is_file() or (root / "android" / "gradlew").is_file(),
        "hasPackageJson": (root / "package.json").is_file(),
        "dependenciesInstalled": (root / "node_modules").is_dir(),
    }
    from .proofs_d_neyvia import mobile_project
    mobile_project(root, candidates, kind, str(expo.get("name") or (cap or {}).get("appName") or package.get("displayName") or package.get("name") or root.name),
                   ios_id or app_id, android_id or app_id or ios_id, result)
    return result


# --------------------------------------------------------------- toolchains --

def _first_dir(*paths):
    return next((Path(path) for path in paths if path and Path(path).is_dir()), None)


def _drive_missing(path: str) -> str:
    drive = os.path.splitdrive(path)[0]
    return drive if drive and not Path(drive + "\\").exists() else ""


def android_toolchain(probe_devices: bool = True) -> dict:
    probe_devices = probe_devices and os.environ.get("NEYVIA_MOBILE_PROBE_DEVICES", "1") != "0"
    notes, missing = [], []
    env_sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    env_java = os.environ.get("JAVA_HOME") or ""
    for name, value in (("ANDROID_HOME", env_sdk), ("JAVA_HOME", env_java)):
        drive = _drive_missing(value) if value else ""
        if drive:
            notes.append(f"{name} points to {value}, but drive {drive} is not connected. Reconnect it to use that setup.")
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
    sdk = _first_dir(env_sdk, local, r"C:\Android\Sdk", r"D:\Android\Sdk")
    studio_jbr = Path(r"C:\Program Files\Android\Android Studio\jbr")
    java_home = _first_dir(env_java, studio_jbr, *sorted((Path.home() / ".jdks").glob("*"), reverse=True))
    java = java_home / "bin" / ("java.exe" if os.name == "nt" else "java") if java_home else None
    java = java if java and java.is_file() else (Path(shutil.which("java")) if shutil.which("java") else None)
    java_version = ""
    if java:
        cached = _java_cache.get(str(java))
        if cached and time.monotonic() - cached[0] < 300:
            java_version = cached[1]
        else:
            try:
                out = _run([str(java), "-version"], timeout=20)
                match = re.search(r'version "(\d+)', out.stderr + out.stdout)
                java_version = match.group(1) if match else ""
                _java_cache[str(java)] = (time.monotonic(), java_version)
            except (OSError, subprocess.SubprocessError):
                java = None
    if not java:
        missing.append(_missing("jdk"))
    elif not java_version or int(java_version) < 21:
        missing.append(_missing("jdk", f"Java {java_version or 'version unknown'} cannot build the Capacitor 7 shell; use JDK 21 or newer"))
    exe = ".exe" if os.name == "nt" else ""
    adb = sdk / "platform-tools" / f"adb{exe}" if sdk else None
    emulator = sdk / "emulator" / f"emulator{exe}" if sdk else None
    build_tools = sorted((sdk / "build-tools").glob("*")) if sdk and (sdk / "build-tools").is_dir() else []
    platforms = sorted((sdk / "platforms").glob("android-*")) if sdk and (sdk / "platforms").is_dir() else []
    images = sorted(str(path.relative_to(sdk / "system-images")) for path in (sdk / "system-images").glob("*/*/*")) if sdk and (sdk / "system-images").is_dir() else []
    if not sdk:
        missing.append(_missing("cmdline-tools", "No Android SDK folder was found"))
    if not (adb and adb.is_file()):
        missing.append(_missing("platform-tools"))
    if not any(path.is_dir() and path.name == "35.0.0" for path in build_tools):
        missing.append(_missing("build-tools"))
    if not any(path.is_dir() and path.name == "android-35" for path in platforms):
        missing.append(_missing("platform"))
    avd_home = Path(os.environ.get("ANDROID_AVD_HOME") or Path.home() / ".android" / "avd")
    avds = sorted(path.stem for path in avd_home.glob("*.ini")) if avd_home.is_dir() else []
    emulator_ready = bool(emulator and emulator.is_file() and images and avds)
    emulator_missing = [] if emulator and emulator.is_file() else [_missing("emulator")]
    if not images:
        emulator_missing.append(_missing("system-image"))
    devices = []
    if probe_devices and adb and adb.is_file():
        try:
            for line in _run([str(adb), "devices", "-l"], timeout=15).stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    info = dict(part.split(":", 1) for part in parts[2:] if ":" in part)
                    devices.append({"serial": parts[0], "state": parts[1], "emulator": parts[0].startswith("emulator-"),
                                    "model": info.get("model", "").replace("_", " ")})
        except (OSError, subprocess.SubprocessError):
            notes.append("adb did not answer.")
    build_ready = bool(java and sdk and not any(item["id"] in {"jdk", "build-tools", "platform"} for item in missing))
    return {
        "ready": build_ready, "sdk": str(sdk) if sdk else "", "java": str(java) if java else "", "javaVersion": java_version,
        "javaHome": str(java.parent.parent) if java else "",
        "adb": str(adb) if adb and adb.is_file() else "", "emulator": str(emulator) if emulator and emulator.is_file() else "",
        "buildTools": [path.name for path in build_tools], "platforms": [path.name for path in platforms],
        "systemImages": images, "avds": avds, "devices": devices,
        "deviceProbeEnabled": probe_devices,
        "emulatorReady": emulator_ready, "missing": missing, "emulatorMissing": emulator_missing, "notes": notes,
        "gradleNote": GRADLE_FIRST_BUILD,
        "totalMissing": _size(sum(item["bytes"] for item in missing)) if missing else "",
    }


def ios_toolchain(root: Path) -> dict:
    from .windows_ios_compiler import inspect_windows_ios_toolchain
    try:
        found = inspect_windows_ios_toolchain(root)
    except Exception as exc:  # A broken config must not hide the rest of Mobile Studio.
        found = {"ready": False, "summary": str(exc), "signingConfigured": False}
    missing = [] if found.get("ready") else [_missing("llvm"), _missing("zsign")]
    return {"ready": bool(found.get("ready")), "summary": found.get("summary", ""),
            "signingConfigured": bool(found.get("signingConfigured")), "missing": missing,
            "totalMissing": _size(sum(item["bytes"] for item in missing)) if missing else "",
            "sideload": SIDELOAD_STEPS}


SIDELOAD_STEPS = [
    "No paid Apple account is needed. A free Apple ID signs the app for 7 days; then refresh it (SideStore refreshes on the phone).",
    "Free Apple ID limits: 3 sideloaded apps at once (SideStore/AltStore counts as one), 10 new app IDs per 7 days.",
    "AltStore route (PC needed to refresh): install iTunes and iCloud from apple.com (not the Microsoft Store), then AltServer from altstore.io.",
    "Plug the iPhone in by USB, trust the PC, start AltServer, choose Install AltStore, and sign in with your Apple ID.",
    "On the iPhone: Settings > General > VPN & Device Management > trust your Apple ID. On iOS 16+ also turn on Settings > Privacy & Security > Developer Mode.",
    "Send the .ipa to the phone (AirDrop is not on Windows: use iCloud Drive, OneDrive or a cable), open AltStore > My Apps > + and pick the .ipa. AltStore re-signs it with your Apple ID.",
    "SideStore route (refreshes on the phone without the PC): set it up once with AltServer or iloader from sidestore.io, then add .ipa files the same way.",
]


# ------------------------------------------------------------------- state --

def state(service) -> dict:
    return service.bus.get(STATE_KEY, {}) or {}


def _save(service, patch: dict) -> dict:
    with _lock:
        current = state(service)
        current.update(patch)
        current["updatedAt"] = now()
        service.bus.put(STATE_KEY, current)
        return current


def _project(service, args) -> Path:
    raw = args.get("project") or state(service).get("project") or service.bus.get("activeProject")
    if not raw:
        raise ValueError("Choose the app folder first: pass project, or open one in Mobile Studio")
    path = service.safe_path(raw)
    if not path.is_dir():
        raise ValueError(f"The app folder does not exist: {path}")
    return path


def preview_token(service, root: Path) -> str:
    tokens = service.bus.get(TOKENS_KEY, {}) or {}
    for token, path in tokens.items():
        if os.path.normcase(path) == os.path.normcase(str(root)):
            return token
    token = secrets.token_urlsafe(18)
    service.bus.update(TOKENS_KEY, {token: str(root)})
    return token


def _preview(service, root: Path, info: dict) -> dict:
    """Where the phone frame points: our own hot-reloading server, or a running Expo dev server."""
    from .ios_studio import _preview_status
    expo = _preview_status(root) if info["kind"] == "expo" else {"running": False}
    if expo.get("running"):
        return {"mode": "expo", "url": expo.get("url", ""), "ready": bool(expo.get("ready")), "hotReload": "Expo Fast Refresh",
                "touch": False, "note": "Expo dev server: frame, rotation and dark mode apply; touch and safe-area emulation need a web export."}
    if info["webRoot"]:
        token = preview_token(service, root)
        return {"mode": "static", "url": PREVIEW_PREFIX + token + "/", "ready": True, "hotReload": "on",
                "touch": True, "webRoot": info["webRoot"]}
    if info["kind"] == "expo":
        return {"mode": "none", "url": "", "ready": False, "canStartExpo": True,
                "note": "Start the Expo preview (runs `expo start --web`), or export the web build once."}
    return {"mode": "none", "url": "", "ready": False, "note": "No index.html found (looked in www, dist, web-build, build, public and the folder itself)."}


def status(service, args) -> dict:
    from .apple_targets import capabilities
    current = state(service)
    raw = args.get("project") or current.get("project")
    result = {"ok": True, "devices": DEVICES, "device": current.get("device") or DEVICE_IDS[0],
              "orientation": current.get("orientation") or "portrait", "dark": bool(current.get("dark")),
              "jobs": _job_list(service), "android": android_toolchain(), "apple": capabilities(),
              "textScale": current.get("textScale", 1), "keyboard": bool(current.get("keyboard")),
              "cloudResult": current.get("cloudResult"), "cloudPreparation": current.get("cloudPreparation")}
    if not raw:
        return {**result, "project": None, "next": "Pick an app folder or create a starter app (neyvia.mobile.create)."}
    root = service.safe_path(raw)
    info = project_info(root)
    result.update({"project": info, "preview": _preview(service, root, info) if info["exists"] else None,
                   "ios": ios_toolchain(root), "builds": _last_builds(root)})
    return result


def preview(service, args) -> dict:
    patch = {}
    if args.get("device"):
        if args["device"] not in DEVICE_IDS:
            raise ValueError("Unknown device; choose one of " + ", ".join(DEVICE_IDS))
        patch["device"] = args["device"]
    if args.get("orientation"):
        if args["orientation"] not in {"portrait", "landscape"}:
            raise ValueError("orientation is portrait or landscape")
        patch["orientation"] = args["orientation"]
    if "dark" in args:
        patch["dark"] = bool(args["dark"])
    if "textScale" in args:
        scale = args["textScale"]
        if type(scale) not in {int, float} or not 0.8 <= scale <= 2:
            raise ValueError("textScale must be between 0.8 and 2")
        patch["textScale"] = scale
    if "keyboard" in args:
        patch["keyboard"] = bool(args["keyboard"])
    if args.get("project"):
        patch["project"] = str(_project(service, args))
    saved = _save(service, patch)
    root = _project(service, {"project": saved.get("project")}) if saved.get("project") else None
    info = project_info(root) if root else None
    if args.get("startExpo"):
        if not info or info["kind"] != "expo":
            raise ValueError("startExpo needs an Expo app folder")
        from .ios_studio import start_ios_preview
        start_ios_preview(root, install_dependencies=False)
    shown = _preview(service, root, info) if root else None
    payload = {"device": saved.get("device") or DEVICE_IDS[0], "orientation": saved.get("orientation") or "portrait",
               "dark": bool(saved.get("dark")), "textScale": saved.get("textScale", 1), "keyboard": bool(saved.get("keyboard")),
               "project": saved.get("project") or "", "url": (shown or {}).get("url", ""), "tier": "instant", "nativeSimulator": False}
    return {**service.result("mobile.preview", payload), "preview": shown,
            **({"note": "No app folder yet: the frame opens empty."} if not root else {})}


def report_state(service, value, client) -> dict:
    """The user side reports device, orientation, dark mode and folder as Paul changes them."""
    if not isinstance(value, dict):
        raise ValueError("state must be an object")
    patch = {key: value[key] for key in ("device", "orientation", "dark", "textScale", "keyboard") if key in value}
    if "textScale" in patch and (type(patch["textScale"]) not in {int, float} or not 0.8 <= patch["textScale"] <= 2):
        raise ValueError("textScale must be between 0.8 and 2")
    if patch.get("device") not in (None, *DEVICE_IDS) or patch.get("orientation") not in (None, "portrait", "landscape"):
        raise ValueError("Unknown device or orientation")
    if value.get("project"):
        patch["project"] = str(service.safe_path(value["project"]))
    patch["seenBy"] = client
    return {"ok": True, "state": _save(service, patch)}


# ------------------------------------------------------------------ create --

STARTER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#f4efe4" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#14201a" media="(prefers-color-scheme: dark)">
  <title>__NAME__</title>
  <link rel="stylesheet" href="app.css">
</head>
<body>
  <header class="top">
    <p class="kicker">Today</p>
    <h1>__NAME__</h1>
  </header>
  <main>
    <form id="add" class="add">
      <input id="text" placeholder="Add something small" autocomplete="off" enterkeyhint="done">
      <button type="submit" aria-label="Add">+</button>
    </form>
    <ul id="list" class="list"></ul>
    <p id="empty" class="empty">Nothing yet. Add one thing you want done today.</p>
  </main>
  <footer class="tabbar">
    <span id="count">0 left</span>
    <span class="hint">Swipe left to remove</span>
  </footer>
  <script src="app.js"></script>
</body>
</html>
"""

STARTER_CSS = """:root {
  color-scheme: light dark;
  --bg: #f4efe4; --card: #fffdf7; --text: #1f2620; --muted: #6c7366; --accent: #3e7c4f; --line: rgba(40, 50, 30, .12);
  font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14201a; --card: #1c2a22; --text: #eef0e6; --muted: #9aa496; --accent: #6fcf97; --line: rgba(255, 255, 255, .1); }
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body { display: flex; flex-direction: column; min-height: 100vh; min-height: 100dvh; }
.top { padding: calc(env(safe-area-inset-top, 0px) + 18px) calc(env(safe-area-inset-right, 0px) + 22px) 8px calc(env(safe-area-inset-left, 0px) + 22px); }
.kicker { margin: 0; color: var(--accent); font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 4px 0 0; font-size: 34px; letter-spacing: -.02em; }
main { flex: 1; padding: 8px calc(env(safe-area-inset-right, 0px) + 16px) 16px calc(env(safe-area-inset-left, 0px) + 16px); }
.add { display: flex; gap: 8px; margin-bottom: 14px; }
.add input { flex: 1; height: 48px; padding: 0 14px; border: 1px solid var(--line); border-radius: 14px; background: var(--card); color: var(--text); font-size: 17px; }
.add button { width: 48px; height: 48px; border: 0; border-radius: 14px; background: var(--accent); color: var(--bg); font-size: 26px; }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.item { display: flex; align-items: center; gap: 12px; min-height: 54px; padding: 0 14px; border-radius: 14px; background: var(--card); border: 1px solid var(--line); touch-action: pan-y; transition: transform .2s, opacity .2s; }
.item.done span { color: var(--muted); text-decoration: line-through; }
.check { width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--accent); flex: none; display: grid; place-items: center; color: var(--bg); }
.item.done .check { background: var(--accent); }
.empty { color: var(--muted); text-align: center; margin-top: 40px; }
.tabbar { display: flex; justify-content: space-between; padding: 12px calc(env(safe-area-inset-right, 0px) + 22px) calc(env(safe-area-inset-bottom, 0px) + 12px) calc(env(safe-area-inset-left, 0px) + 22px); border-top: 1px solid var(--line); color: var(--muted); font-size: 14px; background: var(--card); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { .item { transition: none; } }
"""

STARTER_JS = """const KEY = "starter.items";
const list = document.getElementById("list");
const empty = document.getElementById("empty");
const count = document.getElementById("count");
let items = [];
try { items = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { items = []; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(items)); } catch {} };

function render() {
  list.replaceChildren(...items.map((item, index) => {
    const row = document.createElement("li");
    row.className = "item" + (item.done ? " done" : "");
    row.innerHTML = '<span class="check">\\u2713</span><span></span>';
    row.lastChild.textContent = item.text;
    row.addEventListener("click", () => { item.done = !item.done; save(); render(); });
    let startX = 0, dx = 0;
    row.addEventListener("touchstart", event => { startX = event.touches[0].clientX; dx = 0; }, { passive: true });
    row.addEventListener("touchmove", event => { dx = Math.min(0, event.touches[0].clientX - startX); row.style.transform = `translateX(${dx}px)`; }, { passive: true });
    row.addEventListener("touchend", () => {
      if (dx < -90) { row.style.opacity = "0"; setTimeout(() => { items.splice(index, 1); save(); render(); }, 180); }
      else row.style.transform = "";
    });
    return row;
  }));
  empty.hidden = items.length > 0;
  count.textContent = `${items.filter(item => !item.done).length} left`;
}

document.getElementById("add").addEventListener("submit", event => {
  event.preventDefault();
  const input = document.getElementById("text");
  if (!input.value.trim()) return;
  items.push({ text: input.value.trim(), done: false });
  input.value = "";
  save();
  render();
});
render();
"""


def create(service, args) -> dict:
    name = str(args.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("Give the app a name of at least two characters")
    parent = service.safe_path(args["path"])
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "app"
    target = parent if parent.is_dir() and not any(parent.iterdir()) else parent / slug
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"The folder is not empty: {target}")
    bundle = str(args.get("bundleId") or f"com.neyvia.{re.sub(r'[^a-z0-9]', '', slug) or 'app'}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+){2,}", bundle):
        raise ValueError("bundleId looks like com.yourname.appname")
    android_package = bundle.replace("-", "_")
    www = target / "www"
    www.mkdir(parents=True, exist_ok=True)
    (www / "index.html").write_text(STARTER_HTML.replace("__NAME__", html_lib.escape(name)), encoding="utf-8")
    (www / "app.css").write_text(STARTER_CSS, encoding="utf-8")
    (www / "app.js").write_text(STARTER_JS, encoding="utf-8")
    # app.json is what the Windows iPhone compiler reads; capacitor.config.json is the Android shell's.
    (target / "app.json").write_text(json.dumps({"expo": {"name": name, "slug": slug, "version": "1.0.0",
        "ios": {"bundleIdentifier": bundle}, "android": {"package": android_package}}}, indent=2) + "\n", encoding="utf-8")
    (target / "capacitor.config.json").write_text(json.dumps({"appId": android_package, "appName": name, "webDir": "www"}, indent=2) + "\n", encoding="utf-8")
    (target / ".gitignore").write_text("node_modules/\n.agent_control/\nandroid/app/build/\n*.p12\n*.mobileprovision\n", encoding="utf-8")
    result = preview(service, {"project": str(target)})
    return {**result, "created": str(target), "bundleId": bundle}


# ------------------------------------------------------------------- jobs ---

def _job_list(service):
    with _lock:
        saved = state(service).get("jobs") or []
    live = {job["id"]: job for job in _jobs.values()}
    rows = [live.pop(row["id"], row) for row in saved]
    return sorted([*rows, *live.values()], key=lambda job: job.get("startedAt", ""), reverse=True)[:8]


def _store_job(service, job):
    with _lock:
        _jobs[job["id"]] = job
        current = state(service)
        rows = [row for row in current.get("jobs") or [] if row["id"] != job["id"]]
        current["jobs"] = ([dict(job)] + rows)[:8]
        current["updatedAt"] = now()
        service.bus.put(STATE_KEY, current)
    service.bus.emit("mobile.job", {key: job.get(key) for key in ("id", "kind", "platform", "status", "step", "error", "artifact")})


def _start_job(service, kind, platform, root, work, wait):
    with _lock:
        for job in _jobs.values():
            if job["status"] == "running" and job["project"] == str(root) and job["kind"] == kind:
                return {"ok": True, "status": "running", "job": job, "note": "Already running; poll mobile.status"}
    job = {"id": f"{kind}-{platform}-{uuid.uuid4().hex[:6]}", "kind": kind, "platform": platform, "project": str(root),
           "status": "running", "step": "Starting", "startedAt": now(), "log": []}
    _store_job(service, job)

    def step(text):
        job["step"] = text
        job["log"] = (job["log"] + [f"{now()} {text}"])[-30:]
        _store_job(service, job)

    def body():
        try:
            job.update(work(step) or {})
            job["status"] = "done"
            job["step"] = "Done"
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)[-1500:]
        job["finishedAt"] = now()
        _store_job(service, job)

    thread = threading.Thread(target=body, name=job["id"], daemon=True)
    thread.start()
    if wait:
        thread.join(wait)
    final = job["status"] != "running"
    return {"ok": job["status"] != "failed", "status": job["status"], "job": dict(job),
            **({} if final else {"note": "Still running; poll neyvia.mobile.status"}),
            **({"error": job["error"]} if job.get("error") else {})}


def _last_builds(root: Path) -> dict:
    from .apple_targets import latest
    found = {target: receipt for target in ("ios", "ipados", "macos") if (receipt := latest(root, target))}
    for platform, folder in (("android", BUILDS),):
        receipts = sorted((root / folder).glob("*/receipt.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in receipts:
            receipt = _read_json(path, {}) or {}
            if platform == "android" and receipt.get("platform") != "android":
                continue
            found[platform] = {key: receipt.get(key) for key in ("status", "artifactPath", "ipaPath", "artifactSha256", "ipaSha256", "updatedAt", "createdAt", "error", "jobId")}
            found[platform]["receipt"] = str(path)
            break
    return found


# ------------------------------------------------------------------ build ---

def _gradle_env(tools: dict) -> dict:
    env = dict(os.environ)
    if tools["javaHome"]:
        env["JAVA_HOME"] = tools["javaHome"]
    env["ANDROID_HOME"] = env["ANDROID_SDK_ROOT"] = tools["sdk"]
    return env


def _check(completed, what):
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{what} failed: {detail[-1200:]}")
    return completed


def build(service, args) -> dict:
    platform = args.get("platform")
    from .apple_targets import TARGETS
    if platform not in {*TARGETS, "android"}:
        raise ValueError("Unknown build platform")
    if platform in TARGETS and not TARGETS[platform]["build"]:
        return {"ok": False, "status": "unsupported", "platform": platform, "error": TARGETS[platform]["kind"]}
    root = _project(service, args)
    info = project_info(root)
    wait = int(args.get("waitSeconds") or 0)
    if platform in {"ios", "ipados", "macos"}:
        tools = ios_toolchain(root)
        if not tools["ready"]:
            return {"ok": False, "status": "blocked", "error": "The iPhone compiler is not installed on this PC.",
                    "missing": tools["missing"], "total": tools["totalMissing"], "needsPaul": True}
        if not info["iosBundleId"]:
            return {"ok": False, "status": "blocked", "error": "Add expo.ios.bundleIdentifier to app.json (like com.yourname.app)."}

        def work(step):
            from .windows_ios_compiler import build_windows_ios_app
            step("Compiling for " + platform + " on Windows")
            if platform == "macos":
                from .windows_macos_compiler import build_windows_macos_app
                receipt = build_windows_macos_app(root)
            else:
                receipt = build_windows_ios_app(root, target=platform)
            if receipt.get("status") != "completed":
                raise RuntimeError(receipt.get("error") or "The iPhone build failed; see " + str(receipt.get("receiptPath")))
            return {"artifact": receipt.get("ipaPath") or receipt.get("artifactPath"), "receipt": receipt.get("receiptPath"),
                    "next": "Use mobile.verify, then mobile.simulate tier device for installation steps."}
        return _start_job(service, "build", platform, root, work, wait)

    tools = android_toolchain(probe_devices=False)
    if not tools["ready"]:
        return {"ok": False, "status": "blocked", "error": "Android build tools are missing on this PC.", "missing": tools["missing"],
                "total": tools["totalMissing"], "notes": tools["notes"], "gradle": GRADLE_FIRST_BUILD, "needsPaul": True}
    offline_gradle = None
    offline_cap = None
    if args.get("offline"):
        if not info["hasAndroidProject"]:
            return {"ok": False, "status": "blocked", "needsPaul": True,
                    "error": "An existing Android project is required for the SDK offline build; no shell or dependencies are downloaded"}
        wrapper = root / "android/gradle/wrapper/gradle-wrapper.properties"
        match = re.search(r"gradle-([0-9][^/\\:]*?)-(?:bin|all)\.zip", wrapper.read_text(encoding="utf-8") if wrapper.is_file() else "")
        cache = Path(os.environ.get("GRADLE_USER_HOME") or Path.home() / ".gradle") / "wrapper/dists"
        cached = list(cache.glob("gradle-" + match.group(1) + "-*/*/gradle-*/bin/gradle.bat")) if match else []
        offline_gradle = cached[0] if cached else None
        if not offline_gradle:
            return {"ok": False, "status": "blocked", "needsPaul": True,
                    "error": "The project's Gradle distribution is not installed in the local cache; SDK builds never download it"}
        if (root / "capacitor.config.json").is_file() or info["kind"] == "capacitor":
            offline_cap = root / "node_modules/.bin" / ("cap.cmd" if os.name == "nt" else "cap")
            if not offline_cap.is_file():
                return {"ok": False, "status": "blocked", "needsPaul": True,
                        "error": "Capacitor CLI is missing from this app; SDK builds never install it"}
    if not info["hasAndroidProject"] and info["kind"] in {"web", "capacitor"} and not args.get("addShell"):
        return {"ok": False, "status": "blocked", "needsShell": True,
                "error": "This app has no Android shell yet. Build again with addShell true: Neyvia adds one with Capacitor "
                         "(npm packages, about 25 MB) in an android/ folder. " + GRADLE_FIRST_BUILD}
    npx = "npx.cmd" if os.name == "nt" else "npx"
    npm = "npm.cmd" if os.name == "nt" else "npm"

    def work(step):
        env = _gradle_env(tools)
        if not info["hasAndroidProject"]:
            if info["kind"] == "expo":
                step("Generating the Android project (expo prebuild)")
                _check(_run([npx, "expo", "prebuild", "--platform", "android", "--no-install"], cwd=root, timeout=900, env=env), "expo prebuild")
            else:
                if not (root / "package.json").is_file():
                    (root / "package.json").write_text(json.dumps({"name": root.name.casefold(), "private": True, "version": "1.0.0"}, indent=2) + "\n", encoding="utf-8")
                step("Adding Capacitor (npm install)")
                _check(_run([npm, "install", "--save", "@capacitor/core@7", "@capacitor/cli@7", "@capacitor/android@7"], cwd=root, timeout=900, env=env), "npm install")
                if not (root / "capacitor.config.json").is_file():
                    web_dir = os.path.relpath(info["webRoot"] or root / "www", root)
                    _check(_run([npx, "cap", "init", info["name"], info["androidPackage"] or "com.neyvia.app", "--web-dir", web_dir], cwd=root, timeout=300, env=env), "cap init")
                step("Adding the Android shell (cap add android)")
                _check(_run([npx, "cap", "add", "android"], cwd=root, timeout=900, env=env), "cap add android")
        elif (root / "capacitor.config.json").is_file() or info["kind"] == "capacitor":
            step("Copying the web app into Android (cap sync)")
            cap_command = [str(offline_cap), "sync", "android"] if offline_cap else [npx, "cap", "sync", "android"]
            _check(_run(cap_command, cwd=root, timeout=600, env=env), "cap sync")
        android = root / "android"
        local = android / "local.properties"
        if not local.is_file():
            local.write_text("sdk.dir=" + tools["sdk"].replace("\\", "\\\\") + "\n", encoding="utf-8")
        gradlew = android / ("gradlew.bat" if os.name == "nt" else "gradlew")
        step("Building the APK offline" if offline_gradle else "Building the APK with Gradle (first build downloads ~400 MB)")
        gradle_command = [str(offline_gradle or gradlew), "assembleDebug", "--console=plain"] + (["--offline"] if offline_gradle else [])
        _check(_run(gradle_command, cwd=android, timeout=3600, env=env), "Gradle assembleDebug")
        apk = next(iter(sorted((android / "app" / "build" / "outputs" / "apk" / "debug").glob("*.apk"))), None)
        if not apk:
            raise RuntimeError("Gradle finished but no debug APK was found under android/app/build/outputs/apk/debug")
        job_dir = root / BUILDS / f"android_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        job_dir.mkdir(parents=True, exist_ok=True)
        copy = job_dir / apk.name
        shutil.copy2(apk, copy)
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        receipt = {"schema": "neyvia.mobile_build.v1", "platform": "android", "status": "completed", "artifactPath": str(copy),
                   "artifactSha256": digest, "bytes": copy.stat().st_size, "package": project_info(root)["androidPackage"],
                   "createdAt": now(), "updatedAt": now()}
        (job_dir / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return {"artifact": str(copy), "receipt": str(job_dir / "receipt.json")}
    return _start_job(service, "build", "android", root, work, wait)


# ---------------------------------------------------------------- install ---

def install(service, args) -> dict:
    target = str(args.get("target") or "").strip()
    root = _project(service, args)
    builds = _last_builds(root)
    if target in {"iphone", "ipad"}:
        ios = builds.get("ipados" if target == "ipad" else "ios") or {}
        ipa = ios.get("ipaPath") or ios.get("artifactPath")
        return {"ok": True, "status": "manual", "ipa": ipa or "", "steps": SIDELOAD_STEPS,
                "note": "Windows cannot push an app onto an iPhone by itself; AltStore or SideStore does it with your free Apple ID."
                        + ("" if ipa else " Build first: mobile.build platform ios.")}
    if target == "mac":
        receipt = builds.get("macos") or {}
        return {"ok": True, "status": "manual", "artifact": receipt.get("artifactPath", ""), "installed": False,
                "steps": ["Copy the universal ZIP to a Mac and extract it (preserves executable permissions).",
                          "Run codesign --verify --deep --strict on the extracted app; inspect Gatekeeper before opening.",
                          "Use Finder's explicit Open action for this unnotarized local app if you trust its source.",
                          "Optional notarization requires your Apple Developer identity and Apple's service; this build is ad-hoc."],
                "note": "Opening, WebKit rendering and Apple codesign validation require a real Mac."}
    android = builds.get("android") or {}
    apk = android.get("artifactPath")
    if not apk or not Path(apk).is_file():
        return {"ok": False, "status": "blocked", "error": "No Android build yet; run mobile.build platform android first."}
    tools = android_toolchain()
    if not tools["adb"]:
        return {"ok": False, "status": "blocked", "error": "adb is missing.", "missing": [_missing("platform-tools")], "needsPaul": True}
    online = [device for device in tools["devices"] if device["state"] == "device"]
    if target == "emulator":
        chosen = next((device for device in online if device["emulator"]), None)
        if not chosen and not tools["emulatorReady"]:
            return {"ok": False, "status": "blocked", "error": "No Android emulator is set up.", "missing": tools["emulatorMissing"],
                    "note": "Create a phone with Android Studio's Device Manager or avdmanager once the image is installed.", "needsPaul": True}
    elif target == "usb":
        usb = [device for device in online if not device["emulator"]]
        if len(usb) != 1:
            unauthorized = [device for device in tools["devices"] if device["state"] == "unauthorized"]
            return {"ok": False, "status": "blocked", "error": (
                "Unlock the phone and accept the USB debugging prompt." if unauthorized else
                "Plug in one Android phone with USB debugging on (Settings > About phone > tap Build number 7 times, then Developer options > USB debugging)."
                if not usb else "More than one phone is plugged in; pass its serial as target.")}
        chosen = usb[0]
    else:
        chosen = next((device for device in online if device["serial"] == target), None)
        if not chosen:
            raise ValueError("Unknown target; use emulator, usb, iphone or a serial from mobile.status")
    package = project_info(root)["androidPackage"]
    adb = tools["adb"]

    def work(step):
        serial = chosen["serial"] if chosen else ""
        if not serial:
            avd = args.get("avd") or tools["avds"][0]
            if avd not in tools["avds"]:
                raise RuntimeError("Unknown emulator; choose one of " + ", ".join(tools["avds"]))
            step(f"Starting the {avd} emulator")
            subprocess.Popen([tools["emulator"], "-avd", avd, "-no-boot-anim"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs(new_process_group=True))
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                for line in _run([adb, "devices"], timeout=15).stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) == 2 and parts[0].startswith("emulator-") and parts[1] == "device":
                        serial = parts[0]
                if serial and _run([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], timeout=15).stdout.strip() == "1":
                    break
                time.sleep(3)
            else:
                raise RuntimeError("The emulator did not finish starting within 4 minutes")
        step(f"Installing on {serial}")
        _check(_run([adb, "-s", serial, "install", "-r", apk], timeout=300), "adb install")
        if package:
            step("Opening the app")
            _check(_run([adb, "-s", serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30), "Opening the app")
        return {"artifact": apk, "device": serial}
    return _start_job(service, "install", "android", root, work, int(args.get("waitSeconds") or 0))


# ------------------------------------------------------------ dispatch ------

def simulate(service, args):
    from .apple_targets import TARGETS, prepare_cloud, import_cloud
    root = _project(service, args)
    platform = args.get("platform", "ios")
    if platform not in TARGETS:
        raise ValueError("Unknown Apple target")
    if args["tier"] == "instant":
        return preview(service, {"project": str(root), "device": TARGETS[platform]["device"]})
    if args["tier"] == "device":
        if platform not in {"ios", "ipados", "macos"}:
            return {"ok": False, "status": "unsupported", "error": TARGETS[platform]["kind"]}
        return install(service, {"project": str(root), "target": {"ios": "iphone", "ipados": "ipad", "macos": "mac"}[platform]})
    if args["tier"] != "cloud":
        raise ValueError("tier must be instant, cloud or device")
    if args.get("results"):
        result = import_cloud(root, service.safe_path(args["results"]), platform)
        result["screenshotUrl"] = PREVIEW_PREFIX + preview_token(service, root) + "/__nx/cloud.png"
        result["project"] = str(root)
        _save(service, {"cloudResult": result})
        return {key: value for key, value in result.items() if key != "screenshotPath"}
    result = prepare_cloud(root, platform)
    if result.get("ok"):
        _save(service, {"cloudPreparation": {**result, "project": str(root)}})
    return result


def call(service, name, args):
    if name == "mobile.verify":
        from .apple_targets import verify
        return verify(_project(service, args), args["platform"])
    if name == "mobile.simulate":
        return simulate(service, args)
    if name == "mobile.status":
        return status(service, args)
    if name == "mobile.preview":
        return preview(service, args)
    if name == "mobile.build":
        return build(service, args)
    if name == "mobile.install":
        return install(service, args)
    if name == "mobile.setup":
        if args.get("part") != "ios-compiler":
            raise ValueError("part is ios-compiler")
        refusal = service.require_approval("mobile-setup:ios-compiler", "Approve downloading the iPhone compiler (LLVM + zsign, 864 MB)", args)
        if refusal:
            return refusal
        service.bus.put("grant:mobile-setup:ios-compiler", False)  # one approval, one download
        root = _project(service, args) if args.get("project") or state(service).get("project") else Path(service.bus.root)

        def work(step):
            from .windows_ios_compiler import install_windows_ios_toolchain
            step("Downloading and checking LLVM 22.1.6 and zsign (864 MB)")
            result = install_windows_ios_toolchain(root, engine="win32")
            if not result.get("ready", True) and result.get("error"):
                raise RuntimeError(result["error"])
            return {"artifact": "", "next": "Build for iPhone again."}
        return _start_job(service, "setup", "ios", root, work, 0)
    if name == "mobile.create":
        refusal = service.require_approval("mobile-create:" + os.path.normcase(str(service.safe_path(args["path"]))),
                                           "Approve creating a phone app under " + str(args["path"]), args)
        return refusal or create(service, args)
    raise ValueError("Unknown Mobile Studio action")


# ------------------------------------------------------- preview server -----

HELPER_JS = (Path(__file__).with_name("neyvia_mobile_preview_helper.js"))


def _web_version(web_root: Path) -> dict:
    css = other = count = 0
    for folder, dirs, files in os.walk(web_root):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        for name in files:
            count += 1
            if count > 4000:
                return {"css": str(css), "other": f"{other}-4000"}
            try:
                stamp = os.stat(os.path.join(folder, name)).st_mtime_ns
            except OSError:
                continue
            if name.endswith(".css"):
                css = max(css, stamp)
            else:
                other = max(other, stamp)
    return {"css": str(css), "other": f"{other}-{count}"}


def _insets(device: dict, orientation: str) -> dict:
    top, right, bottom, left = device["safe"]["landscape" if orientation == "landscape" else "portrait"]
    return {"top": top, "right": right, "bottom": bottom, "left": left}


_TRUE_MEDIA, _FALSE_MEDIA = "(min-width: 0px)", "(max-width: -1px)"
_view_by_token: dict[str, dict] = {}  # what the phone frame asked for last; stylesheets follow it


def _scheme(text: str, dark: bool) -> str:
    """Chromium does not pass the frame's color scheme into a sandboxed page, so the
    page's own prefers-color-scheme queries are answered here, in its HTML and CSS."""
    original = text
    text = text.replace("env(safe-area-inset-", "var(--nx-safe-area-inset-")
    text = re.sub(r"\(\s*prefers-color-scheme\s*:\s*dark\s*\)", _TRUE_MEDIA if dark else _FALSE_MEDIA, text)
    result = re.sub(r"\(\s*prefers-color-scheme\s*:\s*light\s*\)", _FALSE_MEDIA if dark else _TRUE_MEDIA, text)
    from .proofs_d_neyvia import mobile_scheme
    mobile_scheme(original, dark, result)
    return result


def _inject(html: str, config: dict) -> str:
    vars_css = ":root{" + "".join(f"--nx-safe-area-inset-{side}:{value}px;" for side, value in config["safe"].items()) + "}"
    config_json = json.dumps(config).replace("<", "\\u003c")
    base = html_lib.escape(config["base"], quote=True)
    html = re.sub(r'''(?P<attr>\b(?:src|href)\s*=\s*['"])/(?!/)''',
                  lambda match: match["attr"] + base, html, flags=re.I)
    head = (f'<base href="{base}"><script>window.__NX_MOBILE__={config_json};</script>'
            f'<style id="nx-mobile-safe">{vars_css}</style>'
            f'<script src="{config["base"]}__nx/helper.js"></script>')
    html = _scheme(html, config["dark"])
    match = re.search(r"<head[^>]*>", html, re.I)
    if match:
        result = html[:match.end()] + head + html[match.end():]
    else:
        match = re.search(r"<html[^>]*>", html, re.I)
        result = html[:match.end()] + "<head>" + head + "</head>" + html[match.end():] if match else head + html
    from .proofs_d_neyvia import mobile_inject
    mobile_inject(config, result)
    return result


def serve_preview(root, handler, parsed, method="GET") -> None:
    """GET/POST /api/ui/mobile-preview/<token>/<path>: the app's files, sandboxed, with the
    phone helper injected. The token is the capability; the page gets an opaque origin, so it
    can never reach Neyvia's API with Paul's session."""
    from .ui_command_bus import bus_for
    bus = bus_for(root)
    rest = parsed.path[len(PREVIEW_PREFIX):]
    token, _, relative = rest.partition("/")
    project = (bus.get(TOKENS_KEY, {}) or {}).get(token)
    if not project or not Path(project).is_dir():
        return _send(handler, 404, b"This preview link is not valid any more. Open the app again in Mobile Studio.", "text/plain; charset=utf-8")
    project_root = Path(project)
    info = project_info(project_root)
    web_root = Path(info["webRoot"]) if info["webRoot"] else None
    relative = unquote(relative)
    if relative in {"__neyvia/state", "__neyvia/commit"} and (project_root / "neyvia.app.json").is_file():
        # SDK previews share the generated server's store, including CAS and
        # retry semantics. No second reducer or browser-only storage is used.
        from .app_sdk import state_api, commit_api
        if method == "OPTIONS":
            return _send(handler, 204, b"", "application/json")
        if (relative == "__neyvia/state" and method != "GET") or (relative == "__neyvia/commit" and method != "POST"):
            return _send(handler, 405, b"Method not allowed", "text/plain")
        try:
            if method == "GET":
                result = state_api(project_root)
            else:
                length = int(handler.headers.get("Content-Length") or 0)
                if not 0 < length <= 1_000_000:
                    return _send(handler, 413, b"Invalid SDK commit size", "text/plain")
                payload = json.loads(handler.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("SDK commit must be an object")
                result = commit_api(project_root, payload)
            return _send(handler, 200, json.dumps(result).encode(), "application/json")
        except (ValueError, TypeError, KeyError) as exc:
            return _send(handler, 400, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")
    if relative == "__nx/cloud.png":
        cloud = (bus.get(STATE_KEY, {}) or {}).get("cloudResult") or {}
        if cloud.get("project") != str(project_root) or not cloud.get("screenshotPath"):
            return _send(handler, 404, b"No imported cloud result for this project", "text/plain")
        image_path = Path(cloud["screenshotPath"]).resolve()
        image_path.relative_to((project_root / ".agent_control/apple_cloud/imports").resolve())
        return _send(handler, 200, image_path.read_bytes(), "image/png")
    if relative == "__nx/helper.js":
        return _send(handler, 200, HELPER_JS.read_bytes(), "text/javascript; charset=utf-8")
    if relative == "__nx/version":
        return _send(handler, 200, json.dumps(_web_version(web_root) if web_root else {}).encode(), "application/json")
    if relative == "__nx/storage":
        store_path = project_root / STORAGE
        if method == "POST":
            try:
                length = int(handler.headers.get("Content-Length") or 0)
            except ValueError:
                return _send(handler, 400, b"Invalid content length", "text/plain")
            if length < 0:
                return _send(handler, 400, b"Invalid content length", "text/plain")
            if length > 2_000_000:
                return _send(handler, 413, b"Storage is limited to 2 MB in the preview", "text/plain")
            try:
                body = json.loads(handler.rfile.read(length) or b"{}")
            except (ValueError, UnicodeDecodeError):
                return _send(handler, 400, b"Storage must be valid JSON", "text/plain")
            from .proofs_d_neyvia import mobile_storage_body, mobile_storage_saved
            if not mobile_storage_body(body):
                return _send(handler, 400, b"Storage is a map of strings", "text/plain")
            store_path.parent.mkdir(parents=True, exist_ok=True)
            from .durability import atomic_write_text
            from .harness_jobs import _exclusive_job_lock
            with _exclusive_job_lock(store_path):
                atomic_write_text(store_path, json.dumps(body))
                mobile_storage_saved(store_path, body)
            return _send(handler, 200, b"{}", "application/json")
        return _send(handler, 200, json.dumps(_preview_storage_snapshot(store_path)).encode(), "application/json")
    if not web_root:
        return _send(handler, 404, b"No index.html in this app yet.", "text/plain; charset=utf-8")
    target = (web_root / relative).resolve() if relative else web_root / "index.html"
    try:
        from .proofs_d_neyvia import mobile_target
        mobile_target(web_root, target)
    except ValueError:
        return _send(handler, 403, b"Outside the app", "text/plain")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file() and "." not in Path(relative).name:
        target = web_root / "index.html"  # single-page app routes
    if not target.is_file():
        return _send(handler, 404, b"Not found", "text/plain")
    body = target.read_bytes()
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    kind = {".js": "text/javascript", ".mjs": "text/javascript", ".webmanifest": "application/manifest+json", ".wasm": "application/wasm"}.get(target.suffix, kind)
    if target.suffix in {".html", ".htm"}:
        current = bus.get(STATE_KEY, {}) or {}
        query = parse_qs(parsed.query)
        device_id = (query.get("device") or [current.get("device") or DEVICE_IDS[0]])[0]
        device = next((row for row in DEVICES if row["id"] == device_id), DEVICES[0])
        orientation = (query.get("orientation") or [current.get("orientation") or "portrait"])[0]
        dark = (query.get("dark") or ["1" if current.get("dark") else "0"])[0] == "1"
        _view_by_token[token] = {"dark": dark}
        config = {"device": device["id"], "platform": device["platform"], "ua": device["ua"], "orientation": orientation, "dark": dark,
                  "safe": _insets(device, orientation), "base": PREVIEW_PREFIX + token + "/",
                  "storage": _preview_storage_snapshot(project_root / STORAGE),
                  "textScale": (query.get("textScale") or [current.get("textScale", 1)])[0],
                  "keyboard": (query.get("keyboard") or ["1" if current.get("keyboard") else "0"])[0] == "1"}
        body = _inject(body.decode("utf-8", errors="replace"), config).encode()
        kind = "text/html; charset=utf-8"
    elif target.suffix == ".css":
        dark = _view_by_token.get(token, {}).get("dark", bool((bus.get(STATE_KEY, {}) or {}).get("dark")))
        body = _scheme(body.decode("utf-8", errors="replace"), dark).encode()
        kind = "text/css; charset=utf-8"
    return _send(handler, 200, body, kind)


def _send(handler, status_code, body: bytes, kind: str) -> None:
    handler.send_response(status_code)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    # The page runs in an opaque origin: it keeps scripts and forms, never Neyvia's cookies or storage.
    policy = "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"
    from .proofs_d_neyvia import mobile_sandbox
    mobile_sandbox(policy)
    handler.send_header("Content-Security-Policy", policy)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "content-type, x-neyvia-app")
    handler.close_connection = True
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(body)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass
