"""App SDK transport bindings; generator and running-app checks live in app_sdk."""
from __future__ import annotations

from pathlib import Path

TEXT = {"type": "string"}
PORT = {"type": "integer", "minimum": 1, "maximum": 65535}
GOAL = {"type": "object", "properties": {
    "project": TEXT, "url": TEXT, "clSource": TEXT,
    "native": {"type": "object"}, "steps": {"type": "array", "items": {"type": "object"}},
}, "required": ["project", "url"], "additionalProperties": False}
DEFINITIONS = [
    ("app_sdk.toolchain", "Read the installed native App Factory toolchain without starting adb, emulators or downloads.",
     {"platform": {"enum": ["android", "ios"]}, "project": TEXT}, ["platform"]),
    ("app_sdk.new", "Generate an app with a CL 1.1 manual, shared user/agent state and executable running-app goals. Does not install dependencies.",
     {"path": TEXT, "name": TEXT, "kind": {"enum": ["web", "pwa", "expo", "desktop"]}}, ["path", "name", "kind"]),
    ("app_sdk.describe", "Read an SDK app's manual, platforms and current build/verification receipts.", {"project": TEXT}, ["project"]),
    ("app_sdk.state", "Read the app's persisted shared state; the user UI and agents use this exact store.", {"project": TEXT}, ["project"]),
    ("app_sdk.action", "Apply a typed app action through its exact running reducer using T18; the same shared state updates the user UI.",
     {"project": TEXT, "url": TEXT, "name": TEXT, "arguments": {"type": "object"}, "clSource": TEXT, "native": {"type": "object"}}, ["project", "url", "name"]),
    ("app_sdk.verify", "Run the app's goals through T18 web perception and optional T16 native inspection; failed goals refuse completion. Uses an explicit running-app URL.", GOAL["properties"], GOAL["required"]),
    ("app_sdk.preview", "Open an SDK app in Mobile Studio's existing phone frame. port is the explicit running Neyvia backend port.",
     {"project": TEXT, "device": TEXT, "port": PORT}, ["project", "port"]),
    ("app_sdk.build", "Build an SDK app using installed local tools. Offline web builds carry source hashes; unavailable native toolchains are reported, never installed.",
     {"project": TEXT, "platform": {"enum": ["web", "pwa", "expo", "desktop", "ios", "android"]}}, ["project", "platform"]),
]
COMMANDS = frozenset("app_sdk_" + name + "_command" for name in ("new", "describe", "state", "action", "verify", "preview", "build", "toolchain"))


def call(service, name: str, args: dict) -> dict:
    from . import app_sdk
    from .neyvia_awareness import claim, release
    operation = name.removeprefix("app_sdk.")
    if operation not in {"new", "describe", "state", "action", "verify", "preview", "build", "toolchain"}:
        raise ValueError("Unknown App SDK operation")
    payload = dict(args)
    if operation == "toolchain":
        from .neyvia_mobile_studio import android_toolchain, ios_toolchain
        platform = payload.get('platform')
        if platform == 'android':
            tools = android_toolchain(probe_devices=False)
        elif platform == 'ios':
            project = service.safe_path(service.bus.root / Path(payload.get('project') or '.'))
            tools = ios_toolchain(project)
        else:
            raise ValueError('Native toolchain platform is android or ios')
        return {'platform': platform, 'ready': bool(tools.get('ready')), 'toolchain': tools}
    key = "path" if operation == "new" else "project"
    project = service.safe_path(service.bus.root / Path(payload[key]).expanduser())
    payload[key] = str(project)
    if operation == "preview":
        port = payload.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("preview requires an explicit valid backend port")
        from .neyvia_mobile_studio import preview
        result = preview(service, {"project": str(project), **({"device": payload["device"]} if payload.get("device") else {})})
        frame = result.get("preview") or {}
        url = frame.get("url", "")
        result.update(project=str(project), port=port, url=f"http://127.0.0.1:{port}{url}" if url.startswith("/") else url)
        result["ok"] = bool(frame.get("ready"))
        result["status"] = "ready" if result["ok"] else "blocked"
        return result
    function = getattr(app_sdk, operation + "_app")
    if operation in {"describe", "state"}:
        return function(service.bus.root, payload)
    work = claim(service.bus.root, {"files": [str(project)], "intent": "App SDK " + operation,
                                   "agent": "Neyvia App SDK", "app": "app-sdk"})
    try:
        if operation == "build" and payload.get("platform") in {"ios", "android"}:
            result = build_mobile(service, project, payload)
        else:
            result = function(service.bus.root, payload)
        result["workClaim"] = work["claim"]["id"]
        result["overlappingClaims"] = work["overlaps"]
        service.bus.put("app:sdk", {"project": str(project), "operation": operation, "result": result})
        service.bus.emit("app-sdk." + operation, {"project": str(project), "ok": result.get("ok"), "status": result.get("status")})
        return result
    finally:
        release(service.bus.root, {"id": work["claim"]["id"]})


def build_mobile(service, project: Path, payload: dict) -> dict:
    """Admission to the existing native build owner requires current app proof."""
    from .app_sdk import read, source_hashes
    from .neyvia_mobile_studio import ios_toolchain, android_toolchain, build
    hashes = source_hashes(project)
    for name in ("latest-build.json", "latest-verification.json"):
        path = project / ".neyvia" / name
        if not path.is_file():
            return {"ok": False, "status": "blocked", "error": "Build and verify the current running app before its native build", "missingReceipt": name}
        receipt = read(path)
        if receipt.get("ok") is not True or receipt.get("sourceHashes") != hashes:
            return {"ok": False, "status": "blocked", "error": "The native build requires current source-bound build and runtime verification receipts", "staleReceipt": name}
    platform = payload["platform"]
    tools = ios_toolchain(project) if platform == "ios" else android_toolchain(probe_devices=False)
    if not tools.get("ready"):
        return {"ok": False, "status": "blocked", "platform": platform, "needsPaul": True,
                "error": "Mobile Studio native toolchain is unavailable; App SDK does not install it", "toolchain": tools, "missing": tools.get("missing", [])}
    result = build(service, {"project": str(project), "platform": platform, "addShell": False, "offline": True})
    result["verifiedSourceHashes"] = hashes
    return result


def handle_command(backend, command: str, payload: dict) -> dict:
    if command not in COMMANDS:
        raise ValueError("Unknown App SDK command")
    from .neyvia_workspace_tools import workspace_for
    root = backend.root if hasattr(backend, "root") else Path(backend)
    service = workspace_for(root, backend if hasattr(backend, "dispatch") else None)
    args = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    return call(service, "app_sdk." + command.removeprefix("app_sdk_").removesuffix("_command"), args)
