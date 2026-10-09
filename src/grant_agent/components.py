"""One list of everything Neyvia installs or keeps current, with real state and one-click actions.

Onboarding renders its download sections from ``components_status_command`` (live state) and
``config/components.json`` (titles, groups, what each unlocks). Commands, all taking
``{"component": "<id>"}`` where relevant:

* ``components_status_command``   all components, or one: state, installed and bundled versions, actions
* ``components_install_command``  install (claude-mod, codex-skills); opts the person in to automatic updates
* ``components_update_command``   bring one component to this build (python-env, claude-mod, codex-skills);
                                  ``check`` for app-updater
* ``components_remove_command``   remove what Neyvia installed and opt out
* ``components_sync_command``     update every installed, opted-in component; run on startup after an app update

State values: ``not-installed`` ``current`` ``update-available`` ``broken`` ``unavailable``
``check-only`` (version reported, no installer) ``unknown``.
Nothing is installed without the person's click; updates apply only to what they installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import claude_mod, codex_skills, compat, venv_sync
from .component_install import REPO, app_version, components_root, human_size, now
from .durability import atomic_write_json
from .runtimes.base import neyvia_managed_runtime_root

COMMANDS = frozenset({
    "components_status_command", "components_install_command", "components_update_command",
    "components_remove_command", "components_sync_command",
})
MANIFEST = REPO / "config" / "components.json"
UPDATER_ENDPOINT_DEFAULT = "https://github.com/bobthecomputer/Neyvia/releases/latest/download/latest.json"
LAYA_WEIGHTS_BYTES = 842_609_210


def manifest() -> list[dict[str, Any]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["components"]


def _state_path(runtime_root: str | Path | None) -> Path:
    return components_root(runtime_root) / "state.json"


def optins(runtime_root: str | Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(_state_path(runtime_root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _set_optin(runtime_root: str | Path | None, component: str, enabled: bool) -> None:
    data = optins(runtime_root)
    data[component] = {"enabled": enabled, "at": now(), "appVersion": app_version()}
    atomic_write_json(_state_path(runtime_root), data)


def venv_root(runtime_root: str | Path | None = None) -> Path:
    if runtime_root:
        return Path(runtime_root) / "venv"
    override = os.environ.get("NEYVIA_RUNTIME_ROOT", "").strip()
    return (Path(override) / "runtime" / "venv") if override else neyvia_managed_runtime_root() / "venv"


def requirements_file() -> Path | None:
    for candidate in (os.environ.get("NEYVIA_BACKEND_REQUIREMENTS"), REPO / "backend-requirements.txt",
                      REPO / "src-tauri" / "resources" / "backend-requirements.txt"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _row(spec: dict[str, Any], **live: Any) -> dict[str, Any]:
    return {"id": spec["id"], "group": spec["group"], "title": spec["title"], "summary": spec["summary"],
            "unlocks": spec.get("unlocks", []), "needs": spec.get("needs", []), "required": bool(spec.get("required")),
            "autoUpdate": bool(spec.get("autoUpdate")), "actions": list(spec.get("actions", [])),
            "updatePath": spec.get("updatePath", ""), "appVersion": app_version(), **live}


def _python_env(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    requirements = requirements_file()
    if requirements is None:
        return _row(spec, state="unknown", detail="No bundled requirements file in this build (a source checkout uses its own .venv).")
    info = venv_sync.status(venv_root(runtime_root), requirements)
    state = {"current": "current", "stale": "update-available", "unrecorded": "update-available", "missing": "not-installed"}[info["state"]]
    return _row(spec, state=state, installedVersion=(info["installedHash"] or "")[:12] or None, bundledVersion=info["bundledHash"][:12],
                installedAt=info["installedAt"], detail=f"Pinned packages: {len(venv_sync.pinned(requirements))}. Environment: {info['venv']}")


def _claude(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    info = claude_mod.status(runtime_root)
    live = {k: info.get(k) for k in ("state", "installedVersion", "bundledVersion", "installedAt", "problems") if k in info}
    live["detail"] = info.get("detail") or ("Claude Code finds the plugin in " + info["marketplaceDir"] if info["state"] != "not-installed" else "")
    return _row(spec, **live)


def _codex(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    info = codex_skills.status()
    states = [s["state"] for s in info["skills"]]
    if all(s == "not-installed" for s in states):
        state = "not-installed"
    elif all(s == "current" for s in states) and not info["stale"]:
        state = "current"
    elif any(s == "modified" for s in states):
        state = "broken"
    else:
        state = "update-available"
    unmanaged = [s["name"] for s in info["skills"] if s["state"] == "unmanaged"]
    detail = f"{len(states)} skills into {info['target']}."
    if unmanaged:
        detail += " Already there but not installed by Neyvia: " + ", ".join(unmanaged) + " (installing asks before replacing them)."
    versions = {s["installedVersion"] for s in info["skills"] if s["installedVersion"]}
    return _row(spec, state=state, installedVersion=", ".join(sorted(versions)) or None,
                bundledVersion=f"{len(states)} skills", skills=info["skills"], unmanaged=unmanaged, detail=detail)


def _laya(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    config = {}
    try:
        config = json.loads((REPO / "config" / "laya.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    model = Path(str(config.get("model") or "")).expanduser()
    weights = model / "model.safetensors"
    if not config.get("model") or not weights.is_file():
        return _row(spec, state="not-installed", bundledVersion="g3-c2", installedVersion=None,
                    detail="Weights not found at the configured model folder" + (f" ({model})" if config.get("model") else "") + ". Neyvia works without LAYA and uses the big model for those decisions.")
    size = weights.stat().st_size
    ok = size == LAYA_WEIGHTS_BYTES
    return _row(spec, state="current" if ok else "broken", installedVersion="g3-c2" if ok else None, bundledVersion="g3-c2",
                detail=(f"{human_size(size)} found." if ok else f"Found {size} bytes, expected {LAYA_WEIGHTS_BYTES}. Re-copy the weights."))


def _dictation(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    try:
        from .neyvia_dictation import _engine_dir, read_settings
        engine = _engine_dir(read_settings(REPO))
    except Exception:  # noqa: BLE001 - settings API differs between roots; fall back to the env/default places
        engine = None
        for candidate in (os.environ.get("NEYVIA_DICTATION_ENGINE_DIR"), str(Path.home() / "Projects" / "dictation-phonon2")):
            if candidate and (Path(candidate) / "phonon2_engine.py").is_file():
                engine = Path(candidate)
                break
    if engine is None:
        return _row(spec, state="not-installed", installedVersion=None, detail="phonon2_engine.py was not found. Dictation is off until the engine folder is set in Settings.")
    version = None
    try:
        done = subprocess.run(["git", "-C", str(engine), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        version = done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return _row(spec, state="check-only", installedVersion=version or time.strftime("%Y-%m-%d", time.localtime((engine / "phonon2_engine.py").stat().st_mtime)),
                detail=f"Engine folder: {engine}")


def _bridge_versions() -> dict[str, str]:
    base = REPO / "scripts" / "gamedev"
    found: dict[str, str] = {}
    try:
        found["unity"] = str(json.loads((base / "unity" / "package.json").read_text(encoding="utf-8")).get("version"))
    except (OSError, ValueError):
        pass
    import re
    for name, path, pattern in (("godot", base / "godot" / "addons" / "neyvia_bridge" / "plugin.cfg", r'^version="([^"]+)"'),
                                ("blender", base / "blender" / "neyvia_bridge" / "__init__.py", r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)')):
        try:
            match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
            if match:
                found[name] = ".".join(match.groups())
        except OSError:
            pass
    return found


def _bridges(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    versions = _bridge_versions()
    return _row(spec, state="check-only" if versions else "unknown", bundledVersion=", ".join(f"{k} {v}" for k, v in sorted(versions.items())) or None,
                installedVersion=None, bridges=versions,
                detail="Neyvia cannot see the copy inside your game project, so compare these numbers with the add-on's own version there.")


def _updater(spec: dict[str, Any], runtime_root: str | Path | None) -> dict[str, Any]:
    endpoint, slim = UPDATER_ENDPOINT_DEFAULT, False
    try:
        config = json.loads((REPO / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        endpoint = (config.get("plugins", {}).get("updater", {}).get("endpoints") or [endpoint])[0]
        slim = not json.loads((REPO / "src-tauri" / "tauri.slim.conf.json").read_text(encoding="utf-8")).get("plugins", {}).get("updater", {}).get("endpoints")
    except (OSError, ValueError):
        pass
    return _row(spec, state="check-only", installedVersion=app_version(), endpoint=endpoint, slimHasNoSelfUpdate=slim,
                detail=f"Looks for releases at {endpoint}")


BUILDERS = {"python-env": _python_env, "claude-mod": _claude, "codex-skills": _codex, "laya-weights": _laya,
            "dictation": _dictation, "gamedev-bridges": _bridges, "app-updater": _updater}


def status(runtime_root: str | Path | None = None, component: str | None = None) -> dict[str, Any]:
    opted = optins(runtime_root)
    rows = []
    for spec in manifest():
        if component and spec["id"] != component:
            continue
        try:
            row = BUILDERS[spec["id"]](spec, runtime_root)
        except Exception as exc:  # noqa: BLE001 - one broken probe must not hide the others
            row = _row(spec, state="unknown", detail=f"Could not read state: {exc}"[:300])
        row["optedIn"] = bool(opted.get(spec["id"], {}).get("enabled"))
        rows.append(row)
    if component and not rows:
        raise ValueError(f"Unknown component: {component}")
    return {"ok": True, "schema": "neyvia.components_status/v1", "appVersion": app_version(),
            "compat": {"neyviaApi": compat.NEYVIA_API, "sdkAbi": compat.SDK_ABI}, "components": rows}


def _in_running_venv(venv: Path) -> bool:
    try:
        return Path(sys.prefix).resolve() == venv.resolve()
    except OSError:
        return False


_ACT_LOCK = threading.Lock()


def act(action: str, component: str, runtime_root: str | Path | None = None, *, adopt: bool = False) -> dict[str, Any]:
    with _ACT_LOCK:  # one install at a time: they all write to the person's tool folders
        return _act(action, component, runtime_root, adopt=adopt)


def _act(action: str, component: str, runtime_root: str | Path | None = None, *, adopt: bool = False) -> dict[str, Any]:
    spec = next((s for s in manifest() if s["id"] == component), None)
    if spec is None:
        raise ValueError(f"Unknown component: {component}")
    if action not in spec.get("actions", []):
        raise ValueError(f"{spec['title']} does not support {action}. {spec.get('updatePath', '')}".strip())
    if component == "claude-mod":
        receipt = claude_mod.install(runtime_root) if action in {"install", "update"} else claude_mod.remove(runtime_root)
    elif component == "codex-skills":
        receipt = codex_skills.install(runtime_root=runtime_root, adopt=adopt) if action in {"install", "update"} else codex_skills.remove(runtime_root=runtime_root)
    elif component == "python-env":
        requirements = requirements_file()
        venv = venv_root(runtime_root)
        if requirements is None:
            raise ValueError("This build has no bundled requirements file")
        if _in_running_venv(venv):
            return {"ok": False, "status": "restart_required", "component": component,
                    "detail": "The backend is running from this environment. The desktop app syncs it before the backend starts; restart Neyvia."}
        receipt = venv_sync.sync(venv, requirements, create_with=sys.executable, runtime_root=runtime_root)
    elif component == "app-updater":
        receipt = check_updater(runtime_root)
    else:
        raise ValueError(f"No installer for {component}")
    if receipt.get("ok") and component in {"claude-mod", "codex-skills"}:
        _set_optin(runtime_root, component, action != "remove")
    return {**receipt, "component": component, "state": status(runtime_root, component)["components"][0]}


def check_updater(runtime_root: str | Path | None = None) -> dict[str, Any]:
    from .component_install import write_receipt
    row = _updater(next(s for s in manifest() if s["id"] == "app-updater"), runtime_root)
    request = urllib.request.Request(row["endpoint"], method="HEAD", headers={"User-Agent": "neyvia-updater-check"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https endpoint from tauri.conf.json
            code, reachable = response.status, True
    except urllib.error.HTTPError as exc:
        code, reachable = exc.code, False
    except (urllib.error.URLError, OSError) as exc:
        return write_receipt(runtime_root, {"component": "app-updater", "action": "check", "ok": False, "status": "offline",
                                            "endpoint": row["endpoint"], "detail": str(exc)[:200]})
    detail = ("The release feed is reachable." if reachable else
              f"The release feed answers HTTP {code}. Anyone without access to that repository gets no updates; publish releases to a public repository or host latest.json elsewhere.")
    return write_receipt(runtime_root, {"component": "app-updater", "action": "check", "ok": reachable, "status": "reachable" if reachable else "unreachable",
                                        "endpoint": row["endpoint"], "httpStatus": code, "detail": detail})


def sync(runtime_root: str | Path | None = None) -> dict[str, Any]:
    """After an app update: bring each installed, opted-in component to this build. Installs nothing new."""
    done, current = [], []
    chosen = optins(runtime_root)
    for row in status(runtime_root)["components"]:
        wants = row["required"] or chosen.get(row["id"], {}).get("enabled")
        if not wants or not row["autoUpdate"]:
            continue
        if row["id"] == "python-env" and _in_running_venv(venv_root(runtime_root)):
            continue  # the desktop app syncs it before the backend starts
        if row["state"] in {"update-available", "broken"}:
            try:
                result = act("update", row["id"], runtime_root, adopt=False)
                done.append({"component": row["id"], "ok": bool(result.get("ok")), "status": result.get("status")})
            except Exception as exc:  # noqa: BLE001
                done.append({"component": row["id"], "ok": False, "status": "error", "detail": str(exc)[:200]})
        else:
            current.append(row["id"])
    return {"ok": all(item["ok"] for item in done), "updated": done, "alreadyCurrent": current}


def handle_command(backend: Any, command: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    component = str(payload.get("component") or "").strip() or None
    if command == "components_status_command":
        return status(None, component)
    if command == "components_sync_command":
        return sync(None)
    if not component:
        raise ValueError("component is required")
    action = {"components_install_command": "install", "components_update_command": "update",
              "components_remove_command": "remove"}[command]
    if component == "app-updater" and action == "update":
        action = "check"
    return act(action, component, None, adopt=bool(payload.get("adopt")))
