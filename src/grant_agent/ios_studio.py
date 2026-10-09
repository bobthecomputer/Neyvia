from __future__ import annotations

from .subprocess_utils import process_is_alive

import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .windows_ios_compiler import (
    WINDOWS_IOS_BUILDS,
    build_windows_ios_app,
    inspect_windows_ios_toolchain,
)


IOS_STUDIO_SCHEMA = "neyvia.ios_studio.v1"
IOS_STUDIO_CONFIG = Path(".agent_control") / "ios_studio.json"
IOS_STUDIO_BUILDS = Path(".agent_control") / "ios_builds"
IOS_STUDIO_PREVIEW = Path(".agent_control") / "ios_preview" / "state.json"
SUPPORTED_BUILD_MODES = {"windows-native", "simulator", "development", "app-store"}
DEFAULT_REMOTE_ROOT = "~/NeyviaBuilds"
DEFAULT_PREVIEW_PORT = 19006

_REMOTE_ROOT_PATTERN = re.compile(r"^(?:~)?(?:/[A-Za-z0-9._-]+)+/?$")
_HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_USER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_TEAM_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
_BUNDLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+){2,}$")
_SECRET_SUFFIXES = {
    ".cer",
    ".key",
    ".mobileprovision",
    ".p12",
    ".pem",
    ".pfx",
}
_CAPSULE_EXCLUDED_PARTS = {
    ".agent_control",
    ".expo",
    ".git",
    ".idea",
    ".vscode",
    "DerivedData",
    "build",
    "dist",
    "node_modules",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _resolved_root(root: str | Path) -> Path:
    resolved = Path(root).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise RuntimeError(f"iOS project folder does not exist: {resolved}")
    return resolved


def _safe_child(root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("New iOS apps must be created inside the selected Neyvia workspace.") from exc
    return resolved


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "ios-app"


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    check: bool = True,
    **process_kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    hidden_kwargs = hidden_windows_subprocess_kwargs()
    hidden_kwargs.update(process_kwargs)
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        **hidden_kwargs,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Command failed without output.").strip()
        raise RuntimeError(f"{command[0]} failed: {detail[-1200:]}")
    return completed


def _decode_last_json(text: str) -> dict[str, Any]:
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("The Mac builder did not return a readable JSON receipt.")


def _package_metadata(root: Path) -> dict[str, Any]:
    package_path = root / "package.json"
    package = _read_json(package_path, {})
    dependencies = {
        **(package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}),
        **(package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}),
    }
    framework = "unknown"
    if "expo" in dependencies:
        framework = "expo"
    elif "react-native" in dependencies:
        framework = "react-native"

    app_config = _read_json(root / "app.json", {})
    expo_config = app_config.get("expo") if isinstance(app_config.get("expo"), dict) else app_config
    if not isinstance(expo_config, dict):
        expo_config = {}
    ios_config = expo_config.get("ios") if isinstance(expo_config.get("ios"), dict) else {}
    bundle_identifier = str(ios_config.get("bundleIdentifier") or "").strip()
    app_name = str(expo_config.get("name") or package.get("displayName") or package.get("name") or root.name).strip()

    return {
        "package": package,
        "dependencies": dependencies,
        "framework": framework,
        "appName": app_name,
        "bundleIdentifier": bundle_identifier,
        "expoVersion": str(dependencies.get("expo") or ""),
        "reactNativeVersion": str(dependencies.get("react-native") or ""),
        "hasPackageJson": package_path.exists(),
        "hasAppConfig": (root / "app.json").exists()
        or (root / "app.config.js").exists()
        or (root / "app.config.ts").exists(),
        "hasNativeIos": (root / "ios").is_dir(),
        "dependenciesInstalled": (root / "node_modules").is_dir(),
    }


def _pid_running(pid: int) -> bool:
    return process_is_alive(pid)


def _port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _preview_status(root: Path) -> dict[str, Any]:
    path = root / IOS_STUDIO_PREVIEW
    state = _read_json(path, {})
    if not isinstance(state, dict) or not state:
        return {
            "status": "stopped",
            "running": False,
            "url": "",
            "port": DEFAULT_PREVIEW_PORT,
            "logPath": str(path.parent / "preview.log"),
        }
    pid = int(state.get("pid") or 0)
    port = int(state.get("port") or DEFAULT_PREVIEW_PORT)
    running = _pid_running(pid)
    ready = running and _port_ready(port)
    return {
        **state,
        "running": running,
        "status": "ready" if ready else "starting" if running else "stopped",
        "ready": ready,
    }


def _build_history(root: Path, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative_root in (IOS_STUDIO_BUILDS, WINDOWS_IOS_BUILDS):
        build_root = root / relative_root
        if not build_root.exists():
            continue
        for path in build_root.glob("*/receipt.json"):
            payload = _read_json(path, {})
            if isinstance(payload, dict) and payload:
                payload.setdefault("receiptPath", str(path))
                rows.append(payload)
    rows.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return rows[:limit]


def load_ios_studio_config(root: str | Path) -> dict[str, Any]:
    resolved = _resolved_root(root)
    value = _read_json(resolved / IOS_STUDIO_CONFIG, {})
    config = value if isinstance(value, dict) else {}
    builder = config.get("builder") if isinstance(config.get("builder"), dict) else {}
    return {
        "schema": IOS_STUDIO_SCHEMA,
        "builder": {
            "label": str(builder.get("label") or "Private Mac builder"),
            "host": str(builder.get("host") or ""),
            "user": str(builder.get("user") or ""),
            "port": int(builder.get("port") or 22),
            "remoteRoot": str(builder.get("remoteRoot") or DEFAULT_REMOTE_ROOT),
            "identityFile": str(builder.get("identityFile") or ""),
            "appleTeamId": str(builder.get("appleTeamId") or ""),
            "knownHostsPolicy": str(builder.get("knownHostsPolicy") or "accept-new"),
            "lastProbe": builder.get("lastProbe") if isinstance(builder.get("lastProbe"), dict) else {},
            "lastProbeAt": str(builder.get("lastProbeAt") or ""),
        },
        "updatedAt": str(config.get("updatedAt") or ""),
    }


def inspect_ios_studio(root: str | Path) -> dict[str, Any]:
    resolved = _resolved_root(root)
    metadata = _package_metadata(resolved)
    config = load_ios_studio_config(resolved)
    builder = config["builder"]
    preview = _preview_status(resolved)
    windows_toolchain = inspect_windows_ios_toolchain(resolved)

    node_version = ""
    if shutil.which("node"):
        try:
            node_version = _run_command(["node", "--version"], timeout=10).stdout.strip()
        except RuntimeError:
            node_version = ""

    builder_configured = bool(builder["host"] and builder["user"])
    last_probe = builder.get("lastProbe") or {}
    builder_ready = bool(last_probe.get("ready"))
    bundle_ready = bool(metadata["bundleIdentifier"] and _BUNDLE_PATTERN.fullmatch(metadata["bundleIdentifier"]))
    project_ready = bool(metadata["hasPackageJson"] and metadata["framework"] in {"expo", "react-native"})

    checks = [
        {
            "id": "project",
            "label": "iOS project",
            "state": "ready" if project_ready else "blocked",
            "detail": (
                f"{metadata['framework']} project detected."
                if project_ready
                else "Choose an Expo or React Native project, or create one here."
            ),
        },
        {
            "id": "node",
            "label": "Windows toolchain",
            "state": "ready" if node_version else "blocked",
            "detail": f"Node {node_version} is available." if node_version else "Node.js is required for preview and dependency installation.",
        },
        {
            "id": "bundle",
            "label": "Bundle identifier",
            "state": "ready" if bundle_ready else "blocked",
            "detail": metadata["bundleIdentifier"] or "Add expo.ios.bundleIdentifier to app.json.",
        },
        {
            "id": "windows-native",
            "label": "Windows native compiler",
            "state": "ready" if windows_toolchain["ready"] else "blocked",
            "detail": windows_toolchain["summary"],
        },
        {
            "id": "builder",
            "label": "Mac build node",
            "state": "ready" if builder_ready else "missing" if builder_configured else "optional",
            "detail": (
                str(last_probe.get("summary") or "Mac builder verified.")
                if builder_ready
                else "Builder saved but not verified."
                if builder_configured
                else "Optional: connect a Mac only for Xcode, SwiftUI, native modules, or App Store export."
            ),
        },
        {
            "id": "signing",
            "label": "Apple signing team",
            "state": "ready" if _TEAM_PATTERN.fullmatch(builder["appleTeamId"]) else "optional",
            "detail": (
                f"Team {builder['appleTeamId']} will sign device builds."
                if builder["appleTeamId"]
                else "Not needed for Simulator builds; required for device and App Store IPAs."
            ),
        },
    ]

    return {
        "schema": IOS_STUDIO_SCHEMA,
        "generatedAt": _utc_now(),
        "project": {
            "root": str(resolved),
            **{key: value for key, value in metadata.items() if key not in {"package", "dependencies"}},
            "recognized": project_ready,
        },
        "builder": builder,
        "windowsToolchain": windows_toolchain,
        "preview": preview,
        "checks": checks,
        "readiness": {
            "windowsPreview": project_ready and metadata["framework"] == "expo" and bool(node_version),
            "windowsNativeBuild": project_ready and bundle_ready and windows_toolchain["ready"],
            "simulatorBuild": project_ready and bundle_ready and builder_ready,
            "signedBuild": project_ready
            and bundle_ready
            and builder_ready
            and bool(_TEAM_PATTERN.fullmatch(builder["appleTeamId"])),
        },
        "buildModes": [
            {
                "id": "windows-native",
                "label": "Compile on Windows",
                "detail": "Local arm64 Mach-O and IPA using Neyvia's clean-room runtime and direct Win32 LLVM.",
                "ready": project_ready and bundle_ready and windows_toolchain["ready"],
            },
            {
                "id": "simulator",
                "label": "iOS Simulator",
                "detail": "Unsigned .app.zip for a Mac simulator. No Apple membership required.",
                "ready": project_ready and bundle_ready and builder_ready,
            },
            {
                "id": "development",
                "label": "Registered iPhone",
                "detail": "Development-signed .ipa for devices registered to your Apple team.",
                "ready": project_ready and bundle_ready and builder_ready and bool(_TEAM_PATTERN.fullmatch(builder["appleTeamId"])),
            },
            {
                "id": "app-store",
                "label": "TestFlight / App Store",
                "detail": "Distribution-signed .ipa prepared for App Store Connect upload.",
                "ready": project_ready and bundle_ready and builder_ready and bool(_TEAM_PATTERN.fullmatch(builder["appleTeamId"])),
            },
        ],
        "history": _build_history(resolved),
    }


def create_ios_app(
    root: str | Path,
    *,
    name: str,
    directory: str = "",
    bundle_identifier: str,
    install_dependencies: bool = False,
) -> dict[str, Any]:
    workspace_root = _resolved_root(root)
    app_name = str(name or "").strip()
    if len(app_name) < 2:
        raise RuntimeError("App name must contain at least two characters.")
    if not _BUNDLE_PATTERN.fullmatch(str(bundle_identifier or "").strip()):
        raise RuntimeError("Use a reverse-domain bundle identifier such as com.yourname.pocketatlas.")

    slug = _safe_slug(app_name)
    requested_directory = str(directory or f"apps/{slug}").strip()
    target = _safe_child(workspace_root, requested_directory)
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f"The target folder is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    package = {
        "name": slug,
        "version": "1.0.0",
        "private": True,
        "main": "index.ts",
        "scripts": {
            "start": "expo start",
            "web": "expo start --web",
            "ios": "expo run:ios",
            "doctor": "npx expo-doctor",
        },
        "dependencies": {
            "@expo/metro-runtime": "~57.0.0",
            "expo": "~57.0.4",
            "expo-status-bar": "~57.0.0",
            "react": "19.2.3",
            "react-dom": "19.2.3",
            "react-native": "0.86.0",
            "react-native-web": "~0.21.0",
        },
        "devDependencies": {"@types/react": "~19.2.0", "typescript": "~5.9.2"},
    }
    app_config = {
        "expo": {
            "name": app_name,
            "slug": slug,
            "version": "1.0.0",
            "orientation": "portrait",
            "userInterfaceStyle": "automatic",
            "newArchEnabled": True,
            "ios": {
                "supportsTablet": True,
                "bundleIdentifier": bundle_identifier.strip(),
            },
            "web": {"bundler": "metro"},
        }
    }
    app_source = f'''import {{ StatusBar }} from "expo-status-bar";
import React from "react";
import {{ Pressable, SafeAreaView, StyleSheet, Text, View }} from "react-native";

const ACCENT = "#E08A5B";

export default function App() {{
  return (
    <SafeAreaView style={{styles.screen}}>
      <StatusBar style="dark" />
      <View style={{styles.shell}}>
        <View style={{styles.header}}>
          <Text style={{styles.kicker}}>NEYVIA IOS STARTER</Text>
          <Text style={{styles.title}}>{app_name}</Text>
          <Text style={{styles.subtitle}}>
            This screen is live on Windows and ready for native compilation on your private Mac builder.
          </Text>
        </View>

        <View style={{styles.focusPanel}}>
          <Text style={{styles.panelLabel}}>FIRST BUILD</Text>
          <Text style={{styles.panelTitle}}>Turn one useful action into a finished app.</Text>
          <Text style={{styles.panelCopy}}>
            Open iOS Studio in Neyvia, describe the next screen, preview it, then request a signed build.
          </Text>
          <Pressable
            accessibilityRole="button"
            style={{({{ pressed }}) => [styles.button, pressed && styles.buttonPressed]}}
          >
            <Text style={{styles.buttonText}}>Plan the first flow</Text>
          </Pressable>
        </View>

        <View style={{styles.footer}}>
          <View style={{styles.statusDot}} />
          <Text style={{styles.footerText}}>Windows authoring · macOS native build</Text>
        </View>
      </View>
    </SafeAreaView>
  );
}}

const styles = StyleSheet.create({{
  screen: {{ flex: 1, backgroundColor: "#F2EFE8" }},
  shell: {{ flex: 1, justifyContent: "space-between", paddingHorizontal: 26, paddingVertical: 24 }},
  header: {{ paddingTop: 34 }},
  kicker: {{ color: "#8A5C44", fontSize: 11, fontWeight: "700", letterSpacing: 1.8 }},
  title: {{ color: "#202421", fontSize: 42, fontWeight: "800", letterSpacing: -1.4, marginTop: 12 }},
  subtitle: {{ color: "#656A65", fontSize: 17, lineHeight: 25, marginTop: 12, maxWidth: 430 }},
  focusPanel: {{ backgroundColor: "#202421", borderRadius: 30, padding: 26 }},
  panelLabel: {{ color: ACCENT, fontSize: 11, fontWeight: "800", letterSpacing: 1.6 }},
  panelTitle: {{ color: "#F7F4ED", fontSize: 29, fontWeight: "750", letterSpacing: -0.7, lineHeight: 35, marginTop: 18 }},
  panelCopy: {{ color: "#B9BDB8", fontSize: 15, lineHeight: 22, marginTop: 12 }},
  button: {{ alignItems: "center", backgroundColor: ACCENT, borderRadius: 16, marginTop: 24, paddingVertical: 16 }},
  buttonPressed: {{ transform: [{{ scale: 0.98 }}] }},
  buttonText: {{ color: "#241D19", fontSize: 15, fontWeight: "800" }},
  footer: {{ alignItems: "center", flexDirection: "row", gap: 9, paddingBottom: 4 }},
  statusDot: {{ backgroundColor: "#3E9B67", borderRadius: 5, height: 9, width: 9 }},
  footerText: {{ color: "#6B706B", fontSize: 12, fontWeight: "600" }},
}});
'''

    files = {
        "package.json": json.dumps(package, indent=2) + "\n",
        "app.json": json.dumps(app_config, indent=2) + "\n",
        "index.ts": 'import { registerRootComponent } from "expo";\n\nimport App from "./App";\n\nregisterRootComponent(App);\n',
        "App.tsx": app_source,
        "tsconfig.json": json.dumps({"extends": "expo/tsconfig.base", "compilerOptions": {"strict": True}}, indent=2) + "\n",
        ".gitignore": "node_modules/\n.expo/\ndist/\nweb-build/\nios/build/\n.env*\n*.p12\n*.mobileprovision\n",
        "neyvia.ios.json": json.dumps(
            {
                "schema": IOS_STUDIO_SCHEMA,
                "createdAt": _utc_now(),
                "bundleIdentifier": bundle_identifier.strip(),
                "framework": "expo",
            },
            indent=2,
        )
        + "\n",
    }
    for relative_path, content in files.items():
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    from .proofs_c_mobile import check_project
    check_project(target, package, app_config, files)

    install_receipt: dict[str, Any] = {"requested": bool(install_dependencies), "status": "not-requested"}
    if install_dependencies:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        completed = _run_command([npm, "install"], cwd=target, timeout=900, check=False)
        install_receipt = {
            "requested": True,
            "status": "completed" if completed.returncode == 0 else "failed",
            "returnCode": completed.returncode,
            "detail": (completed.stderr or completed.stdout or "").strip()[-1000:],
        }
        if completed.returncode != 0:
            raise RuntimeError(f"App files were created, but npm install failed: {install_receipt['detail']}")

    return {
        "schema": IOS_STUDIO_SCHEMA,
        "created": True,
        "projectRoot": str(target),
        "appName": app_name,
        "bundleIdentifier": bundle_identifier.strip(),
        "install": install_receipt,
        "status": inspect_ios_studio(target),
    }


def _save_ios_builder_locked(
    root: str | Path,
    *,
    label: str = "Private Mac builder",
    host: str,
    user: str,
    port: int = 22,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    identity_file: str = "",
    apple_team_id: str = "",
    known_hosts_policy: str = "accept-new",
) -> dict[str, Any]:
    resolved = _resolved_root(root)
    normalized_host = str(host or "").strip()
    normalized_user = str(user or "").strip()
    normalized_remote_root = str(remote_root or DEFAULT_REMOTE_ROOT).strip()
    normalized_team = str(apple_team_id or "").strip().upper()
    if not _HOST_PATTERN.fullmatch(normalized_host):
        raise RuntimeError("Mac builder host contains unsupported characters.")
    if not _USER_PATTERN.fullmatch(normalized_user):
        raise RuntimeError("Mac builder user contains unsupported characters.")
    if not 1 <= int(port) <= 65535:
        raise RuntimeError("SSH port must be between 1 and 65535.")
    if not _REMOTE_ROOT_PATTERN.fullmatch(normalized_remote_root):
        raise RuntimeError("Remote build root must be an absolute path or a simple ~/ path without spaces.")
    if normalized_team and not _TEAM_PATTERN.fullmatch(normalized_team):
        raise RuntimeError("Apple Team ID must contain exactly 10 uppercase letters or digits.")
    if known_hosts_policy not in {"accept-new", "yes"}:
        raise RuntimeError("Known-host policy must be accept-new or yes.")

    previous = load_ios_studio_config(resolved)
    builder = {
        "label": str(label or "Private Mac builder").strip(),
        "host": normalized_host,
        "user": normalized_user,
        "port": int(port),
        "remoteRoot": normalized_remote_root,
        "identityFile": str(identity_file or "").strip(),
        "appleTeamId": normalized_team,
        "knownHostsPolicy": known_hosts_policy,
        "lastProbe": previous["builder"].get("lastProbe") or {},
        "lastProbeAt": previous["builder"].get("lastProbeAt") or "",
    }
    payload = {"schema": IOS_STUDIO_SCHEMA, "updatedAt": _utc_now(), "builder": builder}
    _write_json(resolved / IOS_STUDIO_CONFIG, payload)
    from .proofs_c_mobile import check_config
    check_config(resolved / IOS_STUDIO_CONFIG, payload, "proofs-c.mobile.builder-config")
    return payload


def save_ios_builder(
    root: str | Path,
    *,
    label: str = "Private Mac builder",
    host: str,
    user: str,
    port: int = 22,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    identity_file: str = "",
    apple_team_id: str = "",
    known_hosts_policy: str = "accept-new",
) -> dict[str, Any]:
    """Serialize selected-root preference publication and its durable check."""
    from .harness_jobs import _exclusive_job_lock
    resolved = _resolved_root(root)
    target = resolved / IOS_STUDIO_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _save_ios_builder_locked(
            resolved, label=label, host=host, user=user, port=port,
            remote_root=remote_root, identity_file=identity_file,
            apple_team_id=apple_team_id, known_hosts_policy=known_hosts_policy,
        )


def _ssh_args(builder: dict[str, Any]) -> list[str]:
    ssh = shutil.which("ssh")
    if not ssh:
        raise RuntimeError("OpenSSH client is not installed on this Windows machine.")
    args = [
        ssh,
        "-p",
        str(int(builder.get("port") or 22)),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        f"StrictHostKeyChecking={builder.get('knownHostsPolicy') or 'accept-new'}",
    ]
    identity = str(builder.get("identityFile") or "").strip()
    if identity:
        identity_path = Path(identity).expanduser()
        if not identity_path.exists():
            raise RuntimeError(f"SSH identity file does not exist: {identity_path}")
        args.extend(["-i", str(identity_path)])
    args.append(f"{builder['user']}@{builder['host']}")
    return args


def _scp_args(builder: dict[str, Any]) -> list[str]:
    scp = shutil.which("scp")
    if not scp:
        raise RuntimeError("OpenSSH scp client is not installed on this Windows machine.")
    args = [
        scp,
        "-P",
        str(int(builder.get("port") or 22)),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        f"StrictHostKeyChecking={builder.get('knownHostsPolicy') or 'accept-new'}",
    ]
    identity = str(builder.get("identityFile") or "").strip()
    if identity:
        args.extend(["-i", str(Path(identity).expanduser())])
    return args


def _runner_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "scripts" / "neyvia_ios_builder.py"
    if not path.exists():
        raise RuntimeError(f"Neyvia Mac builder runner is missing: {path}")
    return path


def _deploy_builder_runner(builder: dict[str, Any]) -> str:
    remote_root = str(builder["remoteRoot"])
    remote_script = f"{remote_root.rstrip('/')}/neyvia_ios_builder.py"
    # The root has already passed the strict path allow-list above. Keep a leading
    # ~/ unquoted so the remote shell expands it to the builder user's home.
    mkdir_command = f"mkdir -p -- {remote_root}"
    _run_command(_ssh_args(builder) + [mkdir_command], timeout=30)
    target = f"{builder['user']}@{builder['host']}:{remote_script}"
    _run_command(_scp_args(builder) + [str(_runner_path()), target], timeout=60)
    return remote_script


def _remote_command_text(command: list[str], *, expandable_paths: set[str]) -> str:
    return " ".join(
        part if part in expandable_paths and part.startswith("~/") else shlex.quote(part)
        for part in command
    )


def probe_ios_builder(root: str | Path) -> dict[str, Any]:
    resolved = _resolved_root(root)
    config = load_ios_studio_config(resolved)
    builder = config["builder"]
    if not builder["host"] or not builder["user"]:
        raise RuntimeError("Save a Mac builder host and user before running verification.")
    started = time.monotonic()
    try:
        remote_script = _deploy_builder_runner(builder)
        completed = _run_command(
            _ssh_args(builder) + [f"python3 {remote_script} probe"],
            timeout=45,
        )
        probe = _decode_last_json(completed.stdout)
        probe["ready"] = bool(probe.get("ready"))
        probe["durationMs"] = round((time.monotonic() - started) * 1000)
    except Exception as exc:
        probe = {
            "schema": "neyvia.ios_builder_probe.v1",
            "ready": False,
            "summary": str(exc),
            "error": str(exc),
            "durationMs": round((time.monotonic() - started) * 1000),
        }

    config["builder"]["lastProbe"] = probe
    config["builder"]["lastProbeAt"] = _utc_now()
    config["updatedAt"] = _utc_now()
    _write_json(resolved / IOS_STUDIO_CONFIG, config)
    return {"schema": IOS_STUDIO_SCHEMA, "builder": config["builder"], "probe": probe}


def _capsule_filter(project_root: Path) -> Callable[[tarfile.TarInfo], tarfile.TarInfo | None]:
    def apply(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        relative_parts = Path(info.name).parts[1:]
        if any(part in _CAPSULE_EXCLUDED_PARTS for part in relative_parts):
            return None
        name = Path(info.name).name
        suffix = Path(name).suffix.lower()
        if name == ".env" or name.startswith(".env.") or suffix in _SECRET_SUFFIXES:
            return None
        if info.issym() or info.islnk():
            return None
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        return info

    return apply


def create_ios_build_capsule(root: str | Path, *, job_id: str, mode: str) -> dict[str, Any]:
    resolved = _resolved_root(root)
    status = inspect_ios_studio(resolved)
    if not status["project"]["recognized"]:
        raise RuntimeError("The selected folder is not an Expo or React Native project.")
    build_dir = resolved / IOS_STUDIO_BUILDS / job_id
    build_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = build_dir / "source.tar.gz"
    manifest = {
        "schema": "neyvia.ios_build_capsule.v1",
        "jobId": job_id,
        "mode": mode,
        "createdAt": _utc_now(),
        "appName": status["project"]["appName"],
        "bundleIdentifier": status["project"]["bundleIdentifier"],
        "framework": status["project"]["framework"],
        "sourceRootName": resolved.name,
    }
    with tarfile.open(capsule_path, "w:gz") as archive:
        archive.add(resolved, arcname="project", recursive=True, filter=_capsule_filter(resolved))
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo("neyvia-build-manifest.json")
        info.size = len(manifest_bytes)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(manifest_bytes))
    from .proofs_c_mobile import check_capsule
    check_capsule(capsule_path, manifest)
    capsule_sha = hashlib.sha256(capsule_path.read_bytes()).hexdigest()
    return {
        **manifest,
        "capsulePath": str(capsule_path),
        "capsuleSha256": capsule_sha,
        "capsuleBytes": capsule_path.stat().st_size,
        "buildDirectory": str(build_dir),
    }


def run_ios_build(root: str | Path, *, mode: str = "windows-native", timeout_seconds: int = 3600) -> dict[str, Any]:
    resolved = _resolved_root(root)
    normalized_mode = str(mode or "windows-native").strip().lower()
    if normalized_mode not in SUPPORTED_BUILD_MODES:
        raise RuntimeError(f"Unsupported iOS build mode: {normalized_mode}")
    status = inspect_ios_studio(resolved)
    matching_mode = next((item for item in status["buildModes"] if item["id"] == normalized_mode), None)
    if not matching_mode or not matching_mode["ready"]:
        raise RuntimeError(f"{matching_mode['label'] if matching_mode else normalized_mode} is not ready. Resolve the blocked checks first.")

    if normalized_mode == "windows-native":
        return build_windows_ios_app(resolved, timeout_seconds=timeout_seconds)

    builder = status["builder"]
    job_id = f"ios_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    build_dir = resolved / IOS_STUDIO_BUILDS / job_id
    receipt_path = build_dir / "receipt.json"
    receipt: dict[str, Any] = {
        "schema": "neyvia.ios_build_receipt.v1",
        "jobId": job_id,
        "mode": normalized_mode,
        "status": "running",
        "createdAt": _utc_now(),
        "updatedAt": _utc_now(),
        "projectRoot": str(resolved),
        "appName": status["project"]["appName"],
        "bundleIdentifier": status["project"]["bundleIdentifier"],
        "builderLabel": builder["label"],
        "builderHost": builder["host"],
        "receiptPath": str(receipt_path),
    }
    _write_json(receipt_path, receipt)

    try:
        remote_script = _deploy_builder_runner(builder)
        capsule = create_ios_build_capsule(resolved, job_id=job_id, mode=normalized_mode)
        receipt["capsule"] = capsule
        _write_json(receipt_path, receipt)

        remote_root = str(builder["remoteRoot"]).rstrip("/")
        remote_capsule = f"{remote_root}/{job_id}-source.tar.gz"
        remote_target = f"{builder['user']}@{builder['host']}:{remote_capsule}"
        _run_command(_scp_args(builder) + [capsule["capsulePath"], remote_target], timeout=300)

        remote_command = [
            "python3",
            remote_script,
            "build",
            "--capsule",
            remote_capsule,
            "--job-id",
            job_id,
            "--mode",
            normalized_mode,
            "--remote-root",
            remote_root,
        ]
        if builder["appleTeamId"]:
            remote_command.extend(["--team-id", builder["appleTeamId"]])
        # shlex.quote intentionally quotes '~', which prevents home expansion.
        # Only the three strictly validated, generated remote paths are left
        # unquoted; all user-independent values remain shell quoted.
        expandable_paths = {remote_script, remote_capsule, remote_root}
        command_text = _remote_command_text(remote_command, expandable_paths=expandable_paths)
        completed = _run_command(
            _ssh_args(builder) + [command_text],
            timeout=max(300, int(timeout_seconds)),
            check=False,
        )
        remote_receipt = _decode_last_json(completed.stdout or completed.stderr)
        receipt["remote"] = remote_receipt
        if completed.returncode != 0 or remote_receipt.get("status") != "completed":
            raise RuntimeError(str(remote_receipt.get("error") or completed.stderr or "Remote Xcode build failed."))

        remote_artifact = str(remote_receipt.get("artifactPath") or "")
        if not remote_artifact:
            raise RuntimeError("Mac builder completed without reporting an artifact path.")
        artifact_name = Path(remote_artifact).name
        if not artifact_name or artifact_name in {".", ".."}:
            raise RuntimeError("Mac builder returned an invalid artifact name.")
        local_artifact = build_dir / artifact_name
        remote_artifact_source = f"{builder['user']}@{builder['host']}:{remote_artifact}"
        _run_command(_scp_args(builder) + [remote_artifact_source, str(local_artifact)], timeout=600)

        remote_log = str(remote_receipt.get("logPath") or "")
        local_log = build_dir / "build.log"
        if remote_log:
            _run_command(
                _scp_args(builder) + [f"{builder['user']}@{builder['host']}:{remote_log}", str(local_log)],
                timeout=120,
                check=False,
            )

        receipt.update(
            {
                "status": "completed",
                "updatedAt": _utc_now(),
                "artifactPath": str(local_artifact),
                "artifactBytes": local_artifact.stat().st_size,
                "artifactSha256": hashlib.sha256(local_artifact.read_bytes()).hexdigest(),
                "logPath": str(local_log),
            }
        )
    except Exception as exc:
        receipt.update({"status": "failed", "updatedAt": _utc_now(), "error": str(exc)})

    _write_json(receipt_path, receipt)
    return receipt


def start_ios_preview(
    root: str | Path,
    *,
    port: int = DEFAULT_PREVIEW_PORT,
    install_dependencies: bool = True,
) -> dict[str, Any]:
    resolved = _resolved_root(root)
    status = inspect_ios_studio(resolved)
    if not status["project"]["recognized"] or status["project"]["framework"] != "expo":
        raise RuntimeError("Windows preview currently requires an Expo project.")
    existing = _preview_status(resolved)
    if existing.get("running"):
        return existing
    normalized_port = int(port)
    if not 1024 <= normalized_port <= 65535:
        raise RuntimeError("Preview port must be between 1024 and 65535.")

    npm = "npm.cmd" if os.name == "nt" else "npm"
    npx = "npx.cmd" if os.name == "nt" else "npx"
    if not (resolved / "node_modules").is_dir():
        if not install_dependencies:
            raise RuntimeError("Install project dependencies before starting the Windows preview.")
        _run_command([npm, "install"], cwd=resolved, timeout=900)

    state_path = resolved / IOS_STUDIO_PREVIEW
    log_path = state_path.parent / "preview.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"BROWSER": "none", "CI": "1"})
    command = [npx, "expo", "start", "--web", "--port", str(normalized_port), "--host", "lan"]
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(resolved),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            **hidden_windows_subprocess_kwargs(new_process_group=True),
        )
    state = {
        "schema": "neyvia.ios_preview.v1",
        "pid": process.pid,
        "port": normalized_port,
        "url": f"http://127.0.0.1:{normalized_port}",
        "status": "starting",
        "running": True,
        "ready": False,
        "startedAt": _utc_now(),
        "logPath": str(log_path),
        "command": command,
    }
    _write_json(state_path, state)
    time.sleep(0.5)
    return _preview_status(resolved)


def stop_ios_preview(root: str | Path) -> dict[str, Any]:
    resolved = _resolved_root(root)
    state_path = resolved / IOS_STUDIO_PREVIEW
    state = _read_json(state_path, {})
    pid = int(state.get("pid") or 0) if isinstance(state, dict) else 0
    if pid and _pid_running(pid):
        if os.name == "nt":
            _run_command(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                timeout=20,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
    stopped = {
        **(state if isinstance(state, dict) else {}),
        "status": "stopped",
        "running": False,
        "ready": False,
        "stoppedAt": _utc_now(),
    }
    _write_json(state_path, stopped)
    return stopped
