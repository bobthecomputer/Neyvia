"""Consented, hidden harness installation; progress and receipts share the Connections card."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from .component_install import atomic_write_json, neyvia_managed_runtime_root, now
from .runtimes.base import runtime_subprocess_env, runtime_which
from .subprocess_utils import hidden_windows_subprocess_kwargs

PACKAGES = {"claude-code": ("npm", "@anthropic-ai/claude-code", "claude"),
            "codex": ("npm", "@openai/codex", "codex"), "opencode": ("npm", "opencode-ai", "opencode"),
            "kimi-code": ("uv", "kimi-cli", "kimi"), "gptme": ("uv", "gptme", "gptme")}
_lock = threading.RLock()
_jobs: dict[tuple[str, str], dict[str, Any]] = {}


def environment(root: Path) -> dict[str, str]:
    env = runtime_subprocess_env(root)
    managed = neyvia_managed_runtime_root()
    extra = [managed / "bin", managed / "bootstrap" / "node", managed / "bootstrap" / "Scripts",
             managed / "bootstrap" / "bin", managed / "bootstrap" / "uv", Path.home() / ".local/bin"]
    if os.name == "nt":
        extra += [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "nodejs",
                  Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links"]
        # A prerequisite installer can change PATH while this backend stays running.
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    extra += [Path(os.path.expandvars(p)) for p in winreg.QueryValueEx(handle, "Path")[0].split(";") if p]
            except OSError:
                pass
    env["PATH"] = os.pathsep.join([str(p) for p in extra] + [env.get("PATH", "")])
    env.update(UV_TOOL_DIR=str(managed / "python-tools"), UV_TOOL_BIN_DIR=str(managed / "bin"),
               UV_PYTHON_INSTALL_DIR=str(managed / "python"), UV_NO_PROGRESS="1", UV_PYTHON="3.12")
    return env


def command(name: str, root: Path) -> str:
    return shutil.which(name, path=environment(root)["PATH"]) or runtime_which(name, root) or ""


def progress(service: Any, ident: str) -> dict[str, Any] | None:
    key = (str(service.bus.root), ident)
    with _lock:
        live = _jobs.get(key)
        if live:
            return dict(live)
    saved = service.bus.get("connections.install:" + ident)
    if saved and saved.get("state") == "installing":
        return {**saved, "state": "failed", "line": "Neyvia restarted before installation finished. Please retry."}
    return saved


def _line(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text).strip()
    text = re.sub(r"https?://\S+", "[download]", text)
    # Package-manager output only: keep account-like material out of the card.
    if re.search(r"secret|password|api.?key|access.?token|refresh.?token|authorization|sk-[\w-]+", text, re.I):
        return "Working…"
    return text[-240:]


def run_hidden(argv: list[str] | str, root: Path, emit: Callable[[str], None], *, timeout: float = 1800,
               env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Stream both pipes without blocking timeouts; kill only this child tree on timeout."""
    from .harness_auth_inventory import _kill_tree
    actual = argv
    if os.name == "nt" and isinstance(argv, list) and Path(argv[0]).suffix.lower() in {".cmd", ".bat"}:
        actual = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"]) + ' "' + subprocess.list2cmdline(argv) + '"'
    output: list[str] = []
    errors: list[str] = []
    process = subprocess.Popen(actual, cwd=str(root), env=env or environment(root), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace", **hidden_windows_subprocess_kwargs())

    def drain(stream: Any, lines: list[str]) -> None:
        for line in stream:
            lines.append(line)
            shown = _line(line)
            if shown:
                emit(shown)

    readers = [threading.Thread(target=drain, args=(process.stdout, output), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, errors), daemon=True)]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)  # cold Python tools can spend >15 min downloading and extracting 100+ packages
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        raise RuntimeError("Installation took too long on this PC. Retry to continue with the downloaded packages.") from None
    finally:
        for reader in readers:
            reader.join(3)
    return subprocess.CompletedProcess(argv, process.returncode, "".join(output), "".join(errors))


def _require(argv: list[str], root: Path, emit: Callable[[str], None]) -> None:
    result = run_hidden(argv, root, emit)
    if result.returncode:
        raise RuntimeError("The installer could not finish. " + (_line(result.stderr or result.stdout) or "Check your connection and retry."))


def _portable_node(root: Path, emit: Callable[[str], None]) -> None:
    """Official checksum-verified Windows distribution when App Installer is absent."""
    import json
    import platform
    import urllib.request
    import zipfile
    from .component_install import unique_staging, sha256_file, swap_dir, write_receipt
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if os.name != "nt" or not arch:
        raise RuntimeError("Automatic Node installation is unavailable on this platform.")
    emit("Downloading Node.js and npm from their official distributor…")
    base = "https://nodejs.org/dist/"
    with urllib.request.urlopen(base + "index.json", timeout=30) as response:
        releases = json.load(response)
    version = next(row["version"] for row in releases if row.get("lts") and f"win-{arch}-zip" in row.get("files", []))
    filename = f"node-{version}-win-{arch}.zip"
    with urllib.request.urlopen(base + version + "/SHASUMS256.txt", timeout=30) as response:
        hashes = dict((line.split()[1], line.split()[0]) for line in response.read().decode().splitlines() if line.strip())
    stage = unique_staging(neyvia_managed_runtime_root() / "bootstrap", "node")
    archive = stage / filename
    with urllib.request.urlopen(base + version + "/" + filename, timeout=90) as response, archive.open("wb") as target:
        shutil.copyfileobj(response, target)
    if sha256_file(archive) != hashes.get(filename):
        raise RuntimeError("Node's download did not pass its security check. Please retry.")
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if not (stage / member).resolve().is_relative_to(stage.resolve()):
                raise RuntimeError("The Node download contains an unsafe file path.")
        bundle.extractall(stage)
    staged = stage / filename.removesuffix(".zip")
    _require([str(staged / "node.exe"), "--version"], root, emit)
    _require([str(staged / "npm.cmd"), "--version"], root, emit)
    live = stage.parent / "node"
    swap_dir(staged, live, stage.parent / "node-previous")
    write_receipt(None, {"component": "node-prerequisite", "version": version, "archiveSha256": hashes[filename],
                         "installedPath": str(live), "status": "passed"})


def prerequisite(kind: str, root: Path, emit: Callable[[str], None]) -> str:
    name = "npm" if kind == "npm" else "uv"
    found = command(name, root)
    if found:
        return found
    winget = command("winget", root)
    if winget:
        emit("Installing Node.js and npm…" if kind == "npm" else "Installing the Python tool installer…")
        package = "OpenJS.NodeJS.LTS" if kind == "npm" else "astral-sh.uv"
        _require([winget, "install", "--id", package, "--exact", "--silent", "--accept-package-agreements",
                  "--accept-source-agreements", "--disable-interactivity"], root, emit)
    elif kind == "uv":
        import sys
        emit("Installing the Python tool installer…")
        _require([sys.executable, "-m", "pip", "install", "--target", str(neyvia_managed_runtime_root() / "bootstrap"), "uv"], root, emit)
    else:
        _portable_node(root, emit)
    found = command(name, root)
    if not found:
        raise RuntimeError("The prerequisite was installed but cannot start yet. Restart Neyvia and retry.")
    os.environ["PATH"] = environment(root)["PATH"]
    return found


def install_package(ident: str, root: Path, emit: Callable[[str], None], approval_id: str, *, update: bool = False) -> str:
    kind, package, executable = PACKAGES[ident]
    installer = prerequisite(kind, root, emit)
    if kind == "npm":
        from .cli_installer import perform_cli_action
        emit("Downloading and checking the official package…")

        def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            def log(line: str) -> None:
                if not line.startswith(("{", "}", "[", "]", '"')):
                    emit(line)
            return run_hidden(argv, Path(kwargs.get("cwd") or root), log, timeout=kwargs.get("timeout", 900))

        result = perform_cli_action(root, ident, "update" if update else "install", approved=True,
                                    approval_id=approval_id, npm_path=installer, runner=runner)
        if not result.get("ok"):
            raise RuntimeError(_line(result.get("detail") or "Installation failed. Please retry."))
    else:
        emit("Downloading the harness and its Python environment…")
        # PyPI's final 1.52 release is a migration stub: login/chat no longer run.
        # Keep the user's requested uv route on its last functional release.
        requirement = "kimi-cli==1.51.0" if ident == "kimi-code" else package
        _require([installer, "tool", "install", "--upgrade", requirement, "--python", "3.12"], root, emit)
    emit("Checking that the installed harness starts…")
    exe = command(executable, root)
    if not exe:
        raise RuntimeError("The download finished but the harness was not found. Please retry.")
    version = run_hidden([exe, "--version"], root, lambda _: None, timeout=90)
    if version.returncode or not version.stdout.strip():
        raise RuntimeError("The installed harness could not start. Please retry; the previous installation was kept where possible.")
    if "no longer maintained" in (version.stdout + version.stderr).lower():
        raise RuntimeError("This Kimi package only shows a migration notice. Retry to install the working legacy CLI.")
    return _line(version.stdout.splitlines()[0])


def install(service: Any, args: dict[str, Any], finished: Callable[[str], None]) -> dict[str, Any]:
    ident = str(args.get("id") or "")
    if args.get("fromClick") is not True or ident not in PACKAGES:
        raise ValueError("Use Install on a supported harness card.")
    root = Path(service.bus.root)
    key = (str(root), ident)
    approval_key = "connections-install:" + ident
    with _lock:
        if _jobs.get(key, {}).get("state") == "installing":
            return {"ok": True, "started": False, "install": dict(_jobs[key])}
        previous = progress(service, ident) or {}
        # Retry is the same download the person already approved, including after a restart.
        retired = ident == "kimi-code" and "1.52.0" in str(previous.get("version", ""))
        retry_approval = previous.get("approvalId") if previous.get("state") == "failed" or retired else None
        if previous.get("state") == "failed" and not retry_approval:
            # Earlier install receipts did not keep the approval ID. An existing job was
            # only written after consent; recover its exact fixed-package approval.
            with service.bus.connect() as db:
                requests = db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'").fetchall()
            import json
            for row in requests:
                record = json.loads(row["value"])
                if record.get("key") == approval_key and (record.get("details") or {}).get("package") == PACKAGES[ident][1]:
                    retry_approval = row["key"][9:]
                    break
        approval_id = str(args.get("approvalId") or "")
        if retry_approval and not args.get("consent"):
            approval_id = str(retry_approval)
        approved = service.bus.get("approval:" + approval_id, {}) if approval_id else {}
        if not (args.get("consent") or retry_approval) or approved.get("key") != approval_key:
            service.bus.put("grant:" + approval_key, False)
            refusal = service.require_approval(approval_key, "Install this harness and any missing prerequisites?",
                                               {"id": ident, "package": PACKAGES[ident][1], "hidden": True})
            return {**(refusal or {}), "ok": True, "needsConsent": True}
        service.approve(approval_id)
        service.bus.put("grant:" + approval_key, False)  # one consent, one install attempt
        service.bus.emit("approval.closed", {"approvalId": approval_id})
        _jobs[key] = {"state": "installing", "line": "Preparing installation…", "startedAt": now(), "approvalId": approval_id}

    def emit(line: str) -> None:
        with _lock:
            _jobs[key]["line"] = line
            snapshot = dict(_jobs[key])
        service.bus.put("connections.install:" + ident, snapshot)

    def worker() -> None:
        try:
            version = install_package(ident, root, emit, approval_id)
            atomic_write_json(neyvia_managed_runtime_root() / "connections" / (ident + ".json"),
                              {"id": ident, "version": version, "installedAt": now(), "autoUpdate": True})
            with _lock:
                _jobs[key].update(state="completed", line="Installed and checked.", version=version, completedAt=now())
            finished(ident)
        except Exception as exc:
            with _lock:
                _jobs[key].update(state="failed", line=_line(str(exc)) or "Installation failed. Please retry.", completedAt=now())
        finally:
            service.bus.put("connections.install:" + ident, dict(_jobs[key]))

    emit("Preparing installation…")
    threading.Thread(target=worker, name="connections-install-" + ident, daemon=True).start()
    return {"ok": True, "started": True, "install": progress(service, ident)}


def update_label(root: Path, ident: str) -> str:
    if ident == "kimi-code":
        return "Legacy Kimi CLI — the provider has stopped updates"
    from .runtime_auto_update import tool_update_admission
    admission = tool_update_admission(root)
    return "Neyvia keeps it updated" if admission["allowed"] else "Automatic updates paused — enable tool updates in Settings" if admission["policy"] != "allow" else "Automatic updates paused in this workspace"


def _external_python_tools(root: Path) -> dict[str, tuple[list[str], dict[str, str]]]:
    """Find user-owned uv/pipx tools without installing anything that is absent."""
    env = environment(root)
    for name in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_PYTHON_INSTALL_DIR", "UV_PYTHON"):
        if name in os.environ:
            env[name] = os.environ[name]
        else:
            env.pop(name, None)
    tools: dict[str, tuple[list[str], dict[str, str]]] = {}
    uv = command("uv", root)
    if uv:
        done = run_hidden([uv, "tool", "list"], root, lambda _: None, timeout=30, env=env)
        for package in ("kimi-cli", "gptme"):
            if done.returncode == 0 and re.search(r"^" + re.escape(package) + r"\s+v", done.stdout, re.M):
                tools[package] = ([uv, "tool", "upgrade", package], env)
    pipx = command("pipx", root)
    if pipx:
        import json
        done = run_hidden([pipx, "list", "--json"], root, lambda _: None, timeout=30, env=env)
        try:
            installed = json.loads(done.stdout).get("venvs", {}) if done.returncode == 0 else {}
            if "gptme" in installed and "gptme" not in tools:
                tools["gptme"] = ([pipx, "upgrade", "gptme"], env)
        except ValueError:
            pass
    return tools


def update_installed(root: Path) -> dict[str, Any]:
    """Called by the existing hourly updater, under its owner/environment policy."""
    from .cli_installer import load_manifest
    from .runtime_auto_update import tool_update_admission, record_tool_update
    from .runtime_updates import latest_npm_release, compare_version_tokens
    admission = tool_update_admission(root)
    if not admission["allowed"]:
        return {"status": "blocked", **admission}
    rows = []
    managed = neyvia_managed_runtime_root()
    external = _external_python_tools(root)
    for ident, (kind, package, executable) in PACKAGES.items():
        if ident == "kimi-code":
            rows.append({"package": package, "status": "skipped", "reason": "Legacy uv CLI is archived; 1.52 is a migration stub."})
            continue
        npm = load_manifest(ident) if kind == "npm" else None
        marker = managed / "connections" / (ident + ".json")
        user_tool = external.get(package) if kind == "uv" and not marker.is_file() else None
        if not npm and not marker.is_file() and not user_tool:
            continue
        if not tool_update_admission(root)["allowed"]:
            break
        # Never replace a running harness; another hourly round will retry it.
        try:
            import psutil
            target = str(npm.get("installDir") if npm else managed / "python-tools" / package).casefold()
            launcher = command(executable, root).casefold()
            package_path = re.compile(r"[\\/]" + re.escape(package) + r"[\\/]", re.I)
            busy = any(target in (line := " ".join(p.info.get("cmdline") or []).casefold())
                       or bool(launcher and launcher in line) or bool(package_path.search(line))
                       for p in psutil.process_iter(["cmdline"]))
        except Exception:  # psutil access errors also mean the tool cannot safely be updated
            busy = True  # unable to establish that updating is safe
        if busy:
            rows.append({"package": package, "status": "deferred"})
            continue
        try:
            if npm:
                latest = latest_npm_release(package).get("version")
                if not latest or compare_version_tokens(npm["version"], latest) >= 0:
                    rows.append({"package": package, "status": "skipped"})
                    continue
            if user_tool:
                argv, env = user_tool
                done = run_hidden(argv, root, lambda _: None, env=env)
                checked = run_hidden([command(executable, root), "--version"], root, lambda _: None, timeout=90, env=env)
                if done.returncode or checked.returncode:
                    raise RuntimeError("The tool update did not pass its version check.")
                version = _line(checked.stdout.splitlines()[0])
            else:
                version = install_package(ident, root, lambda _: None, "owner-tool-updates", update=True)
                atomic_write_json(marker, {"id": ident, "version": version, "updatedAt": now(), "autoUpdate": True})
            rows.append({"package": package, "status": "updated", "after": version})
        except Exception as exc:
            rows.append({"package": package, "status": "failed", "reason": _line(str(exc))})
    receipt = {"schema": "neyvia.connection-updates/v1", "completedAt": now(), "clis": rows,
               "updatedCount": sum(row["status"] == "updated" for row in rows),
               "status": "failed" if any(row["status"] == "failed" for row in rows) else "passed"}
    atomic_write_json(managed / "connections" / "updates.json", receipt)
    record_tool_update(root, receipt)
    return receipt
