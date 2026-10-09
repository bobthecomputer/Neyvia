"""Reuse existing host executables in managed work folders, without installation.

These sessions retain host-user access. They are not security sandboxes and do
not claim that arbitrary GUI programs can be embedded in a web frame.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import urllib.parse
import urllib.request

from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock, _terminate_process_tree


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _save(path, value):
    # Windows readers/antivirus can briefly deny replacement. Keep the previous
    # complete record and retry the atomic operation, never truncate in place.
    for attempt in range(12):
        try:
            return atomic_write_json(path, value)
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(.025 * (attempt + 1))


def _load(path):
    # Atomic replacement can briefly deny a Windows reader too. Retry only
    # this observation, never the launch/stop operation around it.
    for attempt in range(12):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(.025 * (attempt + 1))


class InstalledPrograms:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.base = self.root / ".agent_control" / "installed_programs"

    def _session(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", str(identity)):
            raise ValueError("Invalid session identity")
        path = (self.base / "sessions" / identity).resolve()
        path.relative_to(self.base.resolve())
        return path

    def discover(self):
        candidates = {sys.executable}
        for name in ("python", "python3", "node", "git", "pwsh", "powershell", "ffmpeg", "chrome", "msedge", "firefox", "code"):
            found = shutil.which(name)
            if found:
                candidates.add(found)
        if os.name == "nt":
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                        for index in range(min(winreg.QueryInfoKey(key)[0], 200)):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, index)) as item:
                                    value = winreg.QueryValueEx(item, "")[0]
                                    if isinstance(value, str):
                                        candidates.add(os.path.expandvars(value.strip('"')))
                            except OSError:
                                continue
                except OSError:
                    continue
        rows = []
        for candidate in sorted(candidates):
            path = Path(candidate).resolve()
            if path.is_file() and (os.name != "nt" or path.suffix.lower() == ".exe"):
                rows.append({"name": path.stem, "path": str(path), "bytes": path.stat().st_size})
        return {"programs": rows, "discovery": "PATH and Windows App Paths; not exhaustive",
                "installationRequired": False, "isolation": "working-directory", "hostAccess": True}

    def prepare_file(self, path):
        source = Path(str(path)).expanduser()
        source = (source if source.is_absolute() else self.root / source).resolve()
        source.relative_to(self.root)
        if not source.is_file():
            raise ValueError("Choose an existing workspace script")
        if source.suffix.lower() == ".py":
            interpreter = None
            for directory in (source.parent, *source.parent.parents):
                if directory != self.root and self.root not in directory.parents:
                    break
                candidate = directory / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                if candidate.is_file():
                    interpreter = candidate; break
            executable = str(interpreter or Path(sys.executable))
            reason = "Existing project virtual environment" if interpreter else "Existing Neyvia Python interpreter; project dependencies have not been verified"
        elif source.suffix.lower() in {".js", ".mjs", ".cjs"}:
            executable = shutil.which("node")
            if not executable:
                raise ValueError("No installed Node runtime was found; no installation was attempted")
            reason = "Existing Node runtime; modules resolve from the script location"
        else:
            raise ValueError("Automatic runtime selection supports Python and JavaScript scripts")
        return {"executable": executable, "arguments": [str(source)], "reason": reason,
                "sourceSha256": _digest(source), "installationRequired": False, "dependenciesVerified": False}

    def launch_file(self, path, arguments=None, timeoutSeconds=3600, _actor="agent"):
        recipe = self.prepare_file(path)
        if arguments is not None and not isinstance(arguments, list):
            raise ValueError("Script arguments must be a list")
        result = self.launch(recipe["executable"], recipe["arguments"] + (arguments or []), timeoutSeconds, _actor)
        _save(self._session(result["sessionId"]) / "source-recipe.json", recipe)
        return {**result, "sourceRecipe": recipe}

    def launch(self, executable, arguments=None, timeoutSeconds=3600, _actor="agent"):
        if _actor not in {"operator", "agent"}:
            raise ValueError("Invalid session actor")
        path = Path(str(executable)).expanduser().resolve()
        if not path.is_file() or (os.name == "nt" and path.suffix.lower() != ".exe"):
            raise ValueError("Choose an existing executable; Windows scripts require their installed interpreter")
        arguments = [] if arguments is None else arguments
        if not isinstance(arguments, list) or len(arguments) > 100 or any(not isinstance(arg, str) or '\0' in arg or len(arg) > 16000 for arg in arguments):
            raise ValueError("Arguments must be a bounded list of strings")
        timeout = int(timeoutSeconds)
        if not 1 <= timeout <= 86400:
            raise ValueError("Session time limit must be 1 to 86400 seconds")
        identity = uuid.uuid4().hex
        folder = self._session(identity)
        (folder / "work").mkdir(parents=True)
        (folder / "temp").mkdir()
        value = {"schema": "neyvia.installed-program-session.v1", "sessionId": identity,
                 "executable": str(path), "executableSha256": _digest(path), "arguments": arguments,
                 "timeoutSeconds": timeout, "status": "queued", "createdAt": time.time(),
                 "workingDirectory": str(folder / "work"), "isolation": "working-directory",
                 "hostAccess": True, "installationRequired": False}
        _save(folder / "session.json", value)
        _save(folder / "control.json", {"owner": _actor, "revision": 0})
        env = dict(os.environ)
        env["NEYVIA_HOST_ORIGINAL_PYTHONPATH"] = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        try:
            with (folder / "worker.log").open("ab") as log:
                subprocess.Popen([sys.executable, "-m", "grant_agent.installed_programs", str(self.root), identity],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt")
        except Exception as error:
            value.update(status="failed", error=str(error))
            _save(folder / "session.json", value)
            raise
        return value

    def status(self, sessionId):
        folder = self._session(sessionId)
        value = _load(folder / "session.json")
        control_path = folder / "control.json"
        value["control"] = _load(control_path) if control_path.exists() else {"owner": "operator", "revision": 0}
        recipe_path = folder / "source-recipe.json"
        if recipe_path.exists():
            value["sourceRecipe"] = _load(recipe_path)
        if value["status"] in {"queued", "starting", "running"} and time.time() - value.get("heartbeatAt", value["createdAt"]) > 15:
            value = {**value, "status": "unknown", "message": "Worker heartbeat is stale; no completion or safe replay is inferred"}
        for name in ("stdout", "stderr"):
            file = folder / f"{name}.log"
            value[name] = ""
            if file.exists():
                with file.open("rb") as stream:
                    stream.seek(max(0, os.fstat(stream.fileno()).st_size - 16000))
                    value[name] = stream.read(16000).decode("utf-8", errors="replace")
        preview = folder / "preview.json"
        if preview.exists():
            observation = _load(preview)
            value["preview"] = {key: observation[key] for key in ("url", "observedAt", "httpStatus", "title", "contentSha256", "processOwnership") if key in observation}
        return value

    def inspect_preview(self, sessionId, url):
        """Observe an explicitly supplied loopback endpoint without ambient cookies.

        A live process and responding endpoint are separate observations. This
        does not assert the process owns the port or expose the service remotely.
        """
        current = self.status(sessionId)
        if current["status"] != "running":
            raise ValueError("Preview inspection requires a currently running session")
        parsed = urllib.parse.urlsplit(str(url))
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username is not None or parsed.password is not None or parsed.fragment):
            raise ValueError("Use a loopback HTTP URL without credentials or fragment")
        # Resolve localhost to a literal address instead of trusting DNS/proxies.
        hostname = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
        target = urllib.parse.urlunsplit((parsed.scheme, hostname + (f":{parsed.port}" if parsed.port else ""), parsed.path or "/", parsed.query, ""))
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("Preview redirects require an explicit new target")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(target, headers={"User-Agent": "Neyvia-Preview/1", "Accept": "text/html,text/plain,application/json"})
        with opener.open(request, timeout=4) as response:
            content = response.read(1048577)
            content_type = response.headers.get("Content-Type", "")
            text = content[:1048576].decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            title = ""
            if "html" in content_type.lower():
                from .native_tools import _ReadableHtmlParser
                parser = _ReadableHtmlParser(); parser.feed(text)
                text, title = parser.readable_text(), parser.title
            observation = {"url": target, "observedAt": time.time(), "httpStatus": response.status,
                "title": title, "text": text[:16000], "truncated": len(content) > 1048576 or len(text) > 16000,
                "contentSha256": hashlib.sha256(content[:1048576]).hexdigest(), "hashScope": "first-1048576-response-bytes",
                "contentType": content_type, "processOwnership": "unverified", "sessionId": sessionId,
                "observationKind": "fetched_response", "browserStateIncluded": False}
        if self.status(sessionId)["status"] != "running":
            raise ValueError("Session ended during inspection; endpoint association was not saved")
        _save(self._session(sessionId) / "preview.json", observation)
        return {"preview": observation}

    def set_control(self, sessionId, owner, expectedRevision, operatorIdentity):
        if not operatorIdentity or owner not in {"operator", "agent"}:
            raise ValueError("An authenticated operator must choose the session controller")
        folder = self._session(sessionId)
        with _exclusive_job_lock(folder / "control"):
            current = self.status(sessionId)
            if current["status"] not in {"queued", "starting", "running"} or (folder / "stop.json").exists():
                raise ValueError("Session has ended or a stop is already accepted")
            if type(expectedRevision) is not int or expectedRevision != current["control"]["revision"]:
                raise ValueError("Session control changed; refresh before handing off")
            control = {"owner": owner, "revision": expectedRevision + 1, "changedAt": time.time(), "operatorIdentity": str(operatorIdentity)}
            _save(folder / "control.json", control)
            return control

    def stop(self, sessionId, expectedRevision=None, _actor="agent"):
        folder = self._session(sessionId)
        with _exclusive_job_lock(folder / "control"):
            current = self.status(sessionId)
            if _actor != "operator" and (_actor != "agent" or current["control"]["owner"] != "agent"
                    or type(expectedRevision) is not int or expectedRevision != current["control"]["revision"]):
                raise ValueError("Agent session control is absent or stale; ask the operator to hand it over")
            if current["status"] in {"queued", "starting", "running", "unknown"}:
                _save(folder / "stop.json", {"requestedAt": time.time(), "actor": _actor, "controlRevision": current["control"]["revision"]})
                return {**current, "stopRequested": True}
            return current

    def list_sessions(self):
        files = sorted((self.base / "sessions").glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {"sessions": [self.status(p.parent.name) for p in files[:30]], "omittedCount": max(0, len(files) - 30)}

    def _work(self, identity):
        folder = self._session(identity)
        with _exclusive_job_lock(folder / "worker"):
            value = _load(folder / "session.json")
            if value["status"] != "queued":
                return  # Never replay a running or completed launch.
            process = None
            from .resource_admission import ProcessAdmission
            admission = ProcessAdmission(self.root)
            try:
                if _digest(value["executable"]) != value["executableSha256"]:
                    raise ValueError("Executable changed after launch request")
                if (folder / "stop.json").exists():
                    value["status"] = "stopped"
                    return
                waiting_since = time.monotonic()
                actor = _load(folder / "control.json")["owner"]
                while not admission.acquire(actor):
                    if (folder / "stop.json").exists():
                        value["status"] = "stopped"
                        return
                    if time.monotonic() - waiting_since >= value["timeoutSeconds"]:
                        value.update(status="timed_out", error="Managed process admission timed out before execution")
                        return
                    value.update(heartbeatAt=time.time(), admissionStatus="waiting_for_slot")
                    _save(folder / "session.json", value)
                    time.sleep(.25)
                value.update(admissionStatus="admitted", admissionSlot=admission.slot)
                env = dict(os.environ)
                env.update(TEMP=str(folder / "temp"), TMP=str(folder / "temp"), TMPDIR=str(folder / "temp"))
                # Preserve installed dependency resolution; don't pass the worker's project override.
                original_pythonpath = env.pop("NEYVIA_HOST_ORIGINAL_PYTHONPATH", "")
                if original_pythonpath:
                    env["PYTHONPATH"] = original_pythonpath
                else:
                    env.pop("PYTHONPATH", None)
                value.update(status="starting", heartbeatAt=time.time())
                _save(folder / "session.json", value)
                process = subprocess.Popen([value["executable"], *value["arguments"]],
                    cwd=folder / "work", env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt")
                output_counts = {}
                def drain(stream, name):
                    count = 0
                    with (folder / f"{name}.log").open("wb") as output:
                        remaining = 1024 * 1024
                        while data := stream.read1(4096):
                            count += len(data)
                            if remaining:
                                output.write(data[:remaining]); output.flush()
                                remaining = max(0, remaining - len(data))
                    output_counts[name] = count
                    stream.close()
                threads = [threading.Thread(target=drain, args=(stream, name), daemon=True)
                           for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr"))]
                for thread in threads:
                    thread.start()
                start = time.monotonic()
                last_saved = 0.0
                value.update(status="running", pid=process.pid, startedAt=time.time(), logLimitBytes=1048576)
                while process.poll() is None:
                    if time.monotonic() - last_saved >= 1:
                        value["heartbeatAt"] = time.time()
                        _save(folder / "session.json", value)
                        last_saved = time.monotonic()
                    stop = (folder / "stop.json").exists()
                    expired = time.monotonic() - start >= value["timeoutSeconds"]
                    if stop or expired:
                        _terminate_process_tree(process.pid)
                        process.wait(timeout=15)
                        value["status"] = "stopped" if stop else "timed_out"
                        break
                    time.sleep(.2)
                else:
                    value["status"] = "completed" if process.returncode == 0 else "failed"
                value["exitCode"] = process.returncode
                for thread in threads:
                    thread.join(timeout=2)
                value["logsComplete"] = all(not thread.is_alive() for thread in threads)
                value["outputTruncated"] = any(count > 1048576 for count in output_counts.values()) or not value["logsComplete"]
            except Exception as error:
                value.update(status="failed", error=str(error))
                if process is not None and process.poll() is None:
                    value["status"] = "unknown"
            finally:
                # An uncertain child must retain its slot while it remains alive.
                # Ordinary stop/timeout paths have already joined the process.
                if process is not None and process.poll() is None:
                    try:
                        _terminate_process_tree(process.pid)
                        process.wait(timeout=15)
                    except Exception:
                        value["status"] = "unknown"
                        while process.poll() is None:
                            value["heartbeatAt"] = time.time()
                            _save(folder / "session.json", value)
                            time.sleep(1)
                admission.release()
                value["finishedAt"] = time.time()
                _save(folder / "session.json", value)


def installed_program_tool_definitions():
    return [
        ("host.prepare_file", "Select an already-installed Python or Node runtime for an existing workspace script, preferring a nearby Python virtual environment. No installation or execution.", "read", {"path":{"type":"string"}}, ["path"]),
        ("host.launch_file", "Run an existing workspace Python or JavaScript file with an already-installed runtime in its own working folder. No dependency installation.", "process_execute", {"path":{"type":"string"},"arguments":{"type":"array","items":{"type":"string"}},"timeoutSeconds":{"type":"integer","minimum":1,"maximum":86400}}, ["path"]),
        ("host.programs", "Discover existing host executables without installing anything.", "read", {}, []),
        ("host.sessions", "List recent managed installed-program sessions and bounded output.", "read", {}, []),
        ("host.inspect_preview", "Inspect an explicit loopback HTTP endpoint for a running session, without browser cookies or redirects. Process ownership of the endpoint remains unverified.", "artifact_write", {"sessionId": {"type": "string"}, "url": {"type": "string"}}, ["sessionId", "url"]),
        ("host.launch", "Run an existing executable with arguments in its own working folder; retains host-user access, not a sandbox. No installation.", "process_execute",
         {"executable": {"type": "string"}, "arguments": {"type": "array", "items": {"type": "string"}}, "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 86400}}, ["executable"]),
        ("host.status", "Inspect a managed session and its logs.", "read", {"sessionId": {"type": "string"}}, ["sessionId"]),
        ("host.stop", "Request the owning worker to stop its managed process tree. Agent calls require agent ownership and the current control revision from host.status.", "process_execute", {"sessionId": {"type": "string"}, "expectedRevision": {"type": "integer", "minimum": 0}}, ["sessionId"]),
    ]


if __name__ == "__main__":
    InstalledPrograms(sys.argv[1])._work(sys.argv[2])
