"""Normal WebView2 runtime on C1's private desktop, never the input desktop."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time


def _c1_module(name):
    source = Path(r"C:\Users\user\Projects\nx-c1-cua\src\grant_agent") / (name + ".py")
    spec = importlib.util.spec_from_file_location("neyvia_browser_" + name, source)
    module = importlib.util.module_from_spec(spec)
    data = source.read_bytes()
    exec(compile(data, str(source), "exec"), module.__dict__)
    return module, source, hashlib.sha256(data).hexdigest()


class NativeBrowserProcess:
    """Reuse C1 CreateProcess(lpDesktop)/job containment and disturbance guard.

    Launcher support is task-local and explicit: no default-desktop fallback,
    user profile import, browser masking, Bureau activation or focus call.
    """
    def __init__(self, executable, directory, env):
        from urllib.parse import urlparse
        base = urlparse(env.get("NEYVIA_BROWSER_BASE", ""))
        if base.scheme != "http" or base.hostname not in {"127.0.0.1", "localhost"} or base.port not in range(48721, 48740):
            raise ValueError("Private C2g browser needs its explicit assigned backend port")
        self.directory = Path(directory).resolve()
        repo = Path(__file__).resolve().parents[2]
        if not self.directory.is_relative_to(repo / ".agent_control"):
            raise ValueError("Private browser profiles must remain under this task's .agent_control")
        self.directory.mkdir(parents=True, exist_ok=True)
        executable = Path(executable).resolve()
        if not executable.is_file() or not executable.is_relative_to(repo / ".agent_control"):
            raise ValueError("Native browser needs an explicitly built task-local executable")
        # C1 admits task-owned probe binaries, rather than arbitrary singleton apps.
        owned = self.directory / "browser-c2g-probe.exe"
        if executable != owned:
            shutil.copy2(executable, owned)
        desktop_module, self.desktop_source, self.desktop_hash = _c1_module("cua_desktop")
        guard_module, self.guard_source, self.guard_hash = _c1_module("cua_guard")
        self.guard = guard_module.ZeroDisturbanceGuard().start()
        self.desktop = desktop_module.AgentDesktop(profile_root=self.directory)
        self._stop = threading.Event()
        self.process = None
        try:
            if not self.guard.check()["ok"]:
                raise RuntimeError("Private browser input-desktop guard is unavailable")
            launch_env = {**env, "NEYVIA_BROWSER_PROOF_SCOPE": "C2b", "NEYVIA_BROWSER_PROOF_ROOT": str(self.directory)}
            self.process = self.desktop.launch([str(owned)], cwd=str(repo), env=launch_env)
            self.guard.register_pid(self.process.pid)
            self._watcher = threading.Thread(target=self._lease, name="C2g-private-browser-lease", daemon=True)
            self._watcher.start()
        except BaseException:
            self.close()
            raise

    def _lease(self):
        allow = Path(r"C:\Users\user\Projects\plans\logs\window-guard-allow.jsonl")
        while not self._stop.wait(0.5):
            try:
                if self.process.poll() is not None:
                    return
                self.desktop._assert_private()
                windows = self.desktop.windows()
                if windows:
                    with allow.open("a", encoding="utf-8") as stream:
                        for window in windows:
                            stream.write(json.dumps({"hwnd": window["hwnd"], "pid": window["pid"], "until": time.time() + 2, "owner": "C2g-private-WebView2"}) + "\n")
                if not self.guard.check()["ok"]:
                    raise RuntimeError("Input-desktop guard rejected private browser")
            except BaseException as error:
                (self.directory / "native-launcher-failure.json").write_text(json.dumps({"status": "isolation_refused", "reason": str(error)}) + "\n", encoding="utf-8")
                self.desktop.close()
                return

    def receipt(self):
        return {"engine": "WebView2", "route": "agent-private-desktop", "desktop": self.desktop.name,
                "pid": self.process.pid if self.process else None, "controllerPid": os.getpid(), "stealth": False,
                "launcherSources": [str(self.desktop_source), str(self.guard_source)],
                "launcherSourceHashes": {str(self.desktop_source): self.desktop_hash, str(self.guard_source): self.guard_hash}, "guard": self.guard.check()}

    def close(self):
        self._stop.set()
        if getattr(self, "_watcher", None):
            self._watcher.join(3)
        if getattr(self, "desktop", None):
            self.desktop.close()
        result = self.guard.close() if getattr(self, "guard", None) else None
        if getattr(self, "directory", None):
            (self.directory / "native-launcher-receipt.json").write_text(json.dumps({"guard": result, "route": "agent-private-desktop", "closed": True}, indent=2) + "\n", encoding="utf-8")
        return result


if __name__ == "__main__":
    import sys
    process = NativeBrowserProcess(sys.argv[1], sys.argv[2], dict(os.environ))
    try:
        print(json.dumps(process.receipt()), flush=True)
        while process.process.poll() is None:
            time.sleep(0.5)
    finally:
        process.close()
