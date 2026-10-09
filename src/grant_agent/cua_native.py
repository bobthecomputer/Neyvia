"""Hidden, bounded JSONL bridge to the installed Windows UI Automation runtime."""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path


class NativeWorker:
    def __init__(self, *, compiled_host=True, fast=True, desktop=None, guard=None):
        # UIA stays in a persistent in-process MTA lane. The compiled sidecar
        # owns input hooks/status; image capture has its own bounded lane.
        self.compiled_host = compiled_host
        self.fast = fast
        self.fast_client = None
        self.parked_client = None
        self.desktop = desktop
        self.guard = guard
        self._owns_desktop = desktop is None
        self._owns_guard = guard is None
        self.lock = threading.RLock()
        self.proc = None
        self.responses = queue.Queue()
        self.generation = 0
        self.browser_specs = {}
        self.browser_documents = {}
        self.pending_fixtures = {}
        atexit.register(self.close)

    def isolation(self):
        """No native target is admitted from the owner's input desktop."""
        if os.name != "nt":
            raise RuntimeError("The native CUA driver requires Windows")
        if self.guard is None:
            from .cua_guard import ZeroDisturbanceGuard
            self.guard = ZeroDisturbanceGuard().start()
        if self.desktop is None:
            from .cua_desktop import AgentDesktop
            self.desktop = AgentDesktop()
        return self.desktop

    def launch_policy(self, argv):
        """Check both containment layers before reporting permission needed."""
        desktop = self.isolation()
        policy = desktop.launch_policy(argv)
        from .cua_bureau import VirtualDesktopLibrary
        from .cua_parked import parked_hook_path
        hook_error=None
        try:hook=parked_hook_path(desktop.profile_root)
        except RuntimeError as exc:
            hook=desktop.profile_root/'c11-parked/missing-hook.dll'
            hook_error=str(exc)
        library = desktop.profile_root / "c11-bureau/VirtualDesktopAccessor.dll"
        bureau = {"tier": 1, "route": "agent-bureau", "allowed": False,
                  "status": "unavailable", "reason": hook_error or "Task-local Bureau library or containment hook is absent"}
        if hook.is_file() and library.is_file():
            try:
                desktop._validate_launch([str(a) for a in argv], bureau=True)
                bureau.update(status="eligible", allowed=True,
                              library=VirtualDesktopLibrary(library, desktop.profile_root).status())
                bureau["reason"] = "New-process/job containment; existing hidden Shell view and verified inactive Bureau membership required before actions"
                if not policy['allowed']:
                    policy.update(allowed=True,status='eligible',route='agent-bureau',permissionRequired=False)
            except (OSError, RuntimeError, ValueError) as exc:
                bureau["reason"] = str(exc)
        if not policy['allowed']:
            policy['layerFailures']={'agent-desktop':policy['reason'],'agent-bureau':bureau['reason']}
            policy.update(status='isolation-unavailable',permissionRequired=False)
        policy["fallbackLadder"] = [policy["fallbackLadder"][0], bureau,
            {"tier": 2, "route": "needs-permission", "allowed": False,
             "requires": "Both layers failed; no visible launch in this session"}]
        return policy

    def launch(self, argv, *, cwd=None, environment="agent-desktop", hook_path=None, env=None, disposable_target=None):
        desktop = self.isolation()
        if disposable_target is not None:
            import re
            if not isinstance(disposable_target,dict):raise ValueError("disposable_target requires path and token")
            target=Path(disposable_target.get('path','')).resolve()
            token=disposable_target.get('token','')
            if (not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{32}',token)
                    or token not in str(target) or not target.is_relative_to(desktop.profile_root) or not target.exists()):
                raise ValueError("disposable_target requires a new token-named task-local target")
        check = self.guard.check()
        if not check["ok"]:
            raise RuntimeError("zero_disturbance_guard_failed")
        transport_at = time.perf_counter()
        if (Path(argv[0]).name.casefold() in {"chrome.exe", "msedge.exe", "code.exe", "cursor.exe", "antigravity.exe"}
                and any(str(arg).startswith("--remote-debugging-port=") for arg in argv[1:])):
            from .cua_chromium import ChromiumDocument
            ChromiumDocument.prepare_transport()
        transport_ms = (time.perf_counter() - transport_at) * 1000
        if environment in {"parked-hidden", "agent-bureau"}:
            if hook_path is None:
                root = Path(__file__).resolve().parents[2]
                from .cua_parked import parked_hook_path
                hook_path = parked_hook_path(root/'.agent_control')
                if not hook_path.is_file():
                    raise RuntimeError("parked_hook_unavailable: build scripts/build_c11_parked.ps1 with existing local compiler")
            launcher = desktop.launch_bureau if environment == "agent-bureau" else desktop.launch_parked
            process = launcher(argv, cwd=cwd, env=env, guard=self.guard, dll_path=hook_path)
        elif environment == "agent-desktop":
            process = desktop.launch(argv, cwd=cwd, env=env)
        else:
            raise ValueError("Unsupported background launch environment")
        self.guard.register_pid(process.pid)
        process.transport_initialization_ms = transport_ms
        if disposable_target is not None:self.pending_fixtures[process.pid]=(target,token)
        if Path(argv[0]).name.casefold() in {"chrome.exe", "msedge.exe", "code.exe", "cursor.exe", "antigravity.exe"}:
            ports=[int(str(a).split("=",1)[1]) for a in argv if str(a).startswith("--remote-debugging-port=")]
            from urllib.parse import urlparse, unquote
            documents=[]
            for argument in argv[1:]:
                value=str(argument)
                if value.startswith("file:///"):
                    value=unquote(urlparse(value).path).lstrip("/")
                candidate=Path(value)
                if candidate.suffix.lower() in {".html",".txt"}: documents.append(candidate.resolve())
            if len(ports)==1 and ports[0] in range(48701,48710) and len(documents)==1 and documents[0].is_relative_to(desktop.profile_root):
                self.browser_specs[process.pid]=(ports[0],documents[0])
        return process

    def browser_document(self, hwnd):
        import ctypes
        from ctypes import wintypes
        pid=wintypes.DWORD()
        self.desktop.u.GetWindowThreadProcessId(int(hwnd),ctypes.byref(pid))
        spec=self.browser_specs.get(int(pid.value))
        if not spec or not self.desktop.disposable_target(hwnd): return None
        if hwnd not in self.browser_documents:
            from .cua_chromium import ChromiumDocument
            self.browser_documents[hwnd]=ChromiumDocument(self.desktop,hwnd,*spec)
        return self.browser_documents[hwnd]

    @staticmethod
    def _compile(source_name, target):
        directory = Path(__file__).resolve().parents[2] / "tools/cua-driver-win"
        source = directory / source_name
        digest = hashlib.sha256(source.read_bytes() + target.encode("ascii")).hexdigest()
        build = directory / ".build"
        extension = ".dll" if target == "library" else ".exe"
        output = build / (digest + extension)
        if output.is_file():
            return output
        build.mkdir(parents=True, exist_ok=True)
        temporary = build / (digest + "-" + uuid.uuid4().hex + extension)
        framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
        args = [str(framework / "csc.exe"), "/nologo", "/target:" + target, "/out:" + str(temporary), str(source)]
        if target == "library" or source_name == "json-host.cs":
            args += ["/reference:" + str(framework / "WPF" / (name + ".dll")) for name in ("UIAutomationClient", "UIAutomationTypes", "WindowsBase")]
            args += ["/reference:" + str(framework / "System.Drawing.dll")]
            if source_name == "json-host.cs":
                args += ["/reference:" + str(framework / "System.Web.Extensions.dll")]
        elif source_name == "remote-indicator.cs":
            args += ["/reference:" + str(framework / (name + ".dll")) for name in ("System.Windows.Forms", "System.Drawing")]
        elif source_name == "json-host.cs":
            args += ["/reference:" + str(framework / "System.Web.Extensions.dll")]
        try:
            completed = subprocess.run(args, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode:
                raise RuntimeError("Windows native worker compilation failed: " + completed.stdout.decode(errors="replace")[:2000])
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    @staticmethod
    def assembly():
        return NativeWorker._compile("NativeWorker.cs", "library")

    @staticmethod
    def stdio_host():
        return NativeWorker._compile("stdio-host.cs", "winexe")

    @staticmethod
    def json_host():
        return NativeWorker._compile("json-host.cs", "exe")

    def _start(self):
        if os.name != "nt":
            raise RuntimeError("The native CUA driver requires Windows")
        assembly = self.assembly()
        if self.compiled_host:
            command = [str(self.json_host()), str(assembly)]
        else:
            script = Path(__file__).resolve().parents[2] / "tools/cua-driver-win/driver.ps1"
            if not script.is_file():
                raise RuntimeError("The Windows CUA worker is missing")
            command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-STA",
                       "-ExecutionPolicy", "Bypass", "-File", str(script), "-AssemblyPath", str(assembly)]
        self.responses = queue.Queue()
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.generation += 1
        responses, proc = self.responses, self.proc
        def read():
            try:
                while True:
                    line = proc.stdout.readline(16 * 1024 * 1024 + 1)
                    if not line:
                        break
                    if len(line) > 16 * 1024 * 1024 or not line.endswith("\n"):
                        responses.put(RuntimeError("Native response exceeds 16 MiB"))
                        break
                    responses.put(json.loads(line))
            except Exception as exc:
                responses.put(exc)
            finally:
                responses.put(RuntimeError("Native worker exited"))
        threading.Thread(target=read, name="cua-native-output", daemon=True).start()

    def request(self, op, args=None, timeout=20, *, preflight=None):
        if op == "agentDesktop":
            desktop = self.isolation()
            return {"name": desktop.name, "isolation": "windows-desktop", "guard": self.guard.check()}
        if self.fast and os.name == "nt" and op in {
            "windows", "window", "inspect", "inspectElements", "action",
            "remoteAction", "remoteObserve", "remoteGuard", "cycle", "capture",
        }:
            with self.lock:
                self.isolation()
                if not self.guard.check()["ok"]:
                    raise RuntimeError("zero_disturbance_guard_failed")
                if self.fast_client is None:
                    from .cua_fast import FastClient
                    # PrintWindow/providers have their own lanes, so they
                    # cannot block the hook transport's takeover checks.
                    self.fast_client = FastClient(self)
                client = self.fast_client
                parked = self.desktop.parked
                if parked:
                    # Enumerate/register before admitting any hidden HWND. A
                    # separate fresh lane binds before COM to the input desktop.
                    parked.windows()
                    target = int((args or {}).get("windowId", 0))
                    if op == "windows" or parked.owns(target):
                        if self.parked_client is None:
                            from .cua_fast import FastClient
                            self.parked_client = FastClient(self, desktop=parked)
                        if op != "windows":
                            client = self.parked_client
                if preflight is not None:
                    preflight()
                value = client.request(op, args or {})
                if op == "windows" and parked:
                    value += self.parked_client.request(op, args or {})
                if op == "windows":
                    for window in value:
                        fixture=self.pending_fixtures.get(int(window['pid']))
                        if fixture and self.desktop.owns(int(window['windowId'])):
                            self.desktop.register_fixture(int(window['windowId']),*fixture)
                if not self.guard.check()["ok"]:
                    raise RuntimeError("zero_disturbance_guard_failed; inspect before retry")
                return value
        if op not in {"status", "desktopStatus"}:
            raise ValueError("isolated_desktop_required: legacy native target routes are disabled")
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            identity = uuid.uuid4().hex
            try:
                if preflight is not None:
                    preflight()
                self.proc.stdin.write(json.dumps({"id": identity, "op": op, "args": args or {}},
                                                 ensure_ascii=True) + "\n")
                self.proc.stdin.flush()
                result = self.responses.get(timeout=timeout)
                if isinstance(result, Exception):
                    raise result
                if result.get("id") != identity:
                    raise RuntimeError("Native response identity mismatch")
                if not result.get("ok"):
                    raise ValueError(result.get("error") or "Native operation failed")
                return result["data"]
            except (queue.Empty, OSError, RuntimeError) as exc:
                self.close()
                raise RuntimeError("Native operation outcome is uncertain; inspect before retrying") from exc

    def close(self):
        with self.lock:
            self.browser_close_errors = []
            for document in self.browser_documents.values():
                try:
                    document.close()
                except Exception as exc:
                    self.browser_close_errors.append(type(exc).__name__ + ": " + str(exc))
            self.browser_documents.clear()
            self.browser_specs.clear()
            self.pending_fixtures.clear()
            if self.fast_client:
                self.fast_client.close()
                self.fast_client = None
            if self.parked_client:
                self.parked_client.close()
                self.parked_client = None
            proc, self.proc = self.proc, None
            if proc:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait(timeout=3)
            if self.desktop and self._owns_desktop:
                self.desktop.close()
                self.desktop = None
            if self.guard and self._owns_guard:
                self.guard.close()
                self.guard = None
