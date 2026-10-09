"""Supported Apple lanes, dormant cloud preparation and artifact observations."""
from __future__ import annotations
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from . import windows_ios_compiler as ios
from .apple_bundle import verify_bundle

TARGETS = {
    "ios": {"build": True, "kind": "UIKit/WKWebView ARM64 device IPA", "device": "iphone-16-pro"},
    "ipados": {"build": True, "kind": "UIKit/WKWebView ARM64, iPad family and multitasking metadata", "device": "ipad-pro-13"},
    "macos": {"build": True, "kind": "AppKit/WKWebView arm64+x86_64 app ZIP, ad-hoc, not notarized", "device": "mac-window"},
    "watchos": {"build": False, "kind": "No WKWebView. Native WatchKit runtime is not implemented; web frame only", "device": "watch-46"},
    "tvos": {"build": False, "kind": "No supported WKWebView. Native focus-engine runtime is not implemented; web frame only", "device": "apple-tv"},
    "visionos": {"build": False, "kind": "WKWebView exists; spatial runtime, visionOS linker target and signing are not implemented; flat web frame only", "device": "vision-window"},
}


def capabilities() -> dict:
    return {"targets": TARGETS, "tiers": [
        {"id": "instant", "available": True, "label": "Browser frame · emulated behaviours", "nativeSimulator": False},
        {"id": "cloud", "available": False, "enabled": False, "label": "Apple Simulator · optional GitHub macOS runner",
         "note": "Prepared only. Paul must check billing, install the workflow in his account and explicitly enable/dispatch it."},
        {"id": "device", "available": True, "label": "Sideload IPA / open app on Apple hardware", "installed": False}],
        "notarization": "Optional external Apple Developer/Xcode service; not implemented or invoked here",
        "macOSVM": False, "cloudEnabled": False}


def latest(root: Path, target: str) -> dict:
    folder = ".agent_control/windows_macos_builds" if target == "macos" else str(ios.WINDOWS_IOS_BUILDS)
    for path in sorted((root / folder).glob("*/receipt.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        receipt = ios._read_json(path, {})
        if receipt.get("platform", "ios") == target:
            return receipt
    return {}


def verify(root: Path, target: str) -> dict:
    if target not in TARGETS or not TARGETS[target]["build"]:
        return {"ok": False, "status": "unsupported", "error": TARGETS.get(target, {}).get("kind", "Unknown target")}
    receipt = latest(root, target)
    if receipt.get("status") != "completed":
        return {"ok": False, "status": "blocked", "error": "No completed " + target + " build", "receipt": receipt}
    app = Path(receipt["appPath"]) if target == "macos" else Path(receipt["executablePath"]).parent
    outcome = verify_bundle(app, target)
    artifact = Path(receipt["artifactPath"])
    if ios._file_sha256(artifact) != receipt["artifactSha256"]:
        raise ValueError("Packaged artifact digest differs from build receipt")
    # Re-read archive contents, rather than trusting an earlier packaging log.
    import zipfile
    with zipfile.ZipFile(artifact) as archive:
        prefix = app.name + "/" if target == "macos" else "Payload/" + app.name + "/"
        files = {prefix + p.relative_to(app).as_posix(): p for p in app.rglob("*") if p.is_file()}
        if set(archive.namelist()) != set(files):
            raise ValueError("Archive members differ from verified bundle")
        for name, path in files.items():
            if archive.read(name) != path.read_bytes():
                raise ValueError("Archive bytes differ from verified bundle: " + name)
            if target == "macos" and path.parent.name == "MacOS" and not (archive.getinfo(name).external_attr >> 16) & 0o111:
                raise ValueError("Mac ZIP loses executable permissions")
    return {**outcome, "artifact": str(artifact), "artifactSha256": receipt["artifactSha256"], "receipt": receipt["receiptPath"]}


def prepare_cloud(root: Path, target: str) -> dict:
    if target not in {"ios", "ipados"}:
        return {"ok": False, "status": "unsupported", "error": "The prepared cloud lane supports iPhone/iPad Simulator only"}
    name, identifier = ios._resolve_project_metadata(root)
    destination = root / ".agent_control/apple_cloud" / ("prepare_" + uuid.uuid4().hex[:10])
    destination.mkdir(parents=True)
    staging = destination / "App.app"
    assets = ios._safe_copy_web_assets(root, destination, staging)
    assets.rename(destination / "www")
    template = ios._repo_root() / "scripts/apple"
    workflow_dir = destination / ".github/workflows"
    workflow_dir.mkdir(parents=True)
    shutil.copyfile(template / "simulator-workflow.yml", workflow_dir / "apple-simulator.yml")
    shutil.copyfile(template / "simulator.sh", destination / "simulator.sh")
    shutil.copyfile(ios._runtime_source(), destination / "neyvia_runtime.c")
    config = {"name": name, "bundleIdentifier": identifier, "target": target}
    ios._write_json(destination / "apple-cloud.json", config)
    manifest = {p.relative_to(destination).as_posix(): ios._file_sha256(p) for p in destination.rglob("*") if p.is_file()}
    ios._write_json(destination / "capsule.json", {"files": manifest, "enabled": False})
    return {"ok": True, "tier": "cloud", "status": "prepared", "enabled": False, "dispatched": False,
            "path": str(destination), "files": manifest, "needsPaul": "Copy capsule to a repository in bobthecomputer's account, review billing, enable repository variable NEYVIA_APPLE_SIMULATOR_ENABLED=true, then manually dispatch with explicit confirmation. No run was started."}


def import_cloud(root: Path, source: Path, target: str = "ios") -> dict:
    """Import a downloaded outcome; never dispatch, poll GitHub or imply live streaming."""
    receipt = json.loads((source / "cloud-outcome.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "neyvia.apple_simulator.v1" or receipt.get("status") != "completed" or not str(receipt.get("runUrl", "")).startswith("https://github.com/bobthecomputer/"):
        raise ValueError("Expected completed outcome from Paul's own GitHub repository")
    screenshot = source / "screenshot.png"
    data = screenshot.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != receipt.get("screenshotSha256"):
        raise ValueError("Cloud screenshot does not match outcome")
    if receipt.get("target") != target or target not in {"ios", "ipados"}:
        raise ValueError("Cloud result target differs from requested platform")
    if receipt.get("bundleIdentifier") != ios._resolve_project_metadata(root)[1]:
        raise ValueError("Cloud result belongs to a different app")
    destination = root / ".agent_control/apple_cloud/imports" / uuid.uuid4().hex[:10]
    destination.mkdir(parents=True)
    shutil.copyfile(screenshot, destination / "screenshot.png")
    ios._write_json(destination / "cloud-outcome.json", receipt)
    return {"ok": True, "tier": "cloud", "status": "imported", "enabled": False, "dispatched": False,
            "screenshotPath": str(destination / "screenshot.png"), "runUrl": receipt["runUrl"],
            "target": receipt["target"], "provenance": "Imported self-reported runner receipt; GitHub authenticity not independently verified", "liveStream": False}
