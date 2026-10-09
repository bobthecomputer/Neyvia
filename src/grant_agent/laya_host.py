"""The Neyvia backend owns the LAYA service: start it hidden, watch it, restart it, stop it with the backend.

LAYA is the small local model layer that answers routine decisions so the big model does not. Nothing
here needs an environment variable: the service address is the loopback port from configuration, and
`laya_service.endpoint()` asks this module before it looks at ``NEYVIA_LAYA_URL`` (which stays as an
explicit override for an external service).

Where things live (all inside this checkout except the model weights):
  tools/laya/laya/            the LAYA package (MIT, 236 KB)
  tools/laya/laya_system1/    the System 1 HTTP service (frozen encoder + typed heads + reversible memory)
  tools/laya/question_sets/   Neyvia's question sets (CL-State browser, taste triage, CL routing)
  tools/laya/memory-seed.sqlite  labelled cases admitted as verified outcomes (see docs/evidence/laya-calibration.md)
  calibrated CPU candidate    config "project": the existing g3-c2 checkpoint and calibration evidence,
                              referenced in place, never downloaded or copied.
  default transformer         config "model" retains the frozen System-1 regression floor;
                              only live browser requests use the g3-c2 head.

When the service cannot start (no Python runtime, no weights, port taken by something else, local-only mode
forbids child processes, repeated crashes) the state says why and every caller keeps using its checked
big-model route.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULTS = {
    "enabled": True,
    "port": 48841,
    "device": "cpu",
    "architecture": "transformer",
    "project": "~/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement",
    "python": "~/miniforge3/envs/whisper/python.exe",
    "model": "~/Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english",
    "memoryCapacity": 4096,
    "startTimeoutSeconds": 150,
    "cpuThreads": 4,
    "maxRestarts": 5,
    "restartWindowSeconds": 600,
}
RESERVED = {47881}
_LOCK = threading.RLock()
_HOST = None
# Set by the web backend once it accepts connections. LAYA's instant encoders are loaded only after
# that, and only after a separate low-priority process has primed their files and DLLs, so loading
# them never stands in the way of sign-in or any other request (loading native libraries in this
# process holds the Windows loader lock that every new request thread needs).
_SERVING = threading.Event()


def mark_serving():
    _SERVING.set()


def instant_ready() -> bool:
    """True when instant decisions may run now; False while the encoders are still warming up.
    Without a host (tests, command-line tools) nothing is being warmed, so nothing waits."""
    host = _HOST
    if host is None or not host.config.get("enabled", True):
        return True
    return host.encoders.get("state") in {"ready", "partial", "idle"}


WARMING_UP = "LAYA is warming up"


def _expand(value) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def load_config(root=None) -> dict:
    """Repository defaults, then config/laya.json, then <root>/.neyvia/laya/config.json."""
    config = dict(DEFAULTS)
    for path in (REPO / "config" / "laya.json", Path(root) / ".neyvia" / "laya" / "config.json" if root else None):
        if path and path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    config.update({k: v for k, v in value.items() if k in DEFAULTS})
            except (OSError, ValueError):
                pass
    return config


def _health(port: int, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=timeout) as response:
            value = json.load(response)
        return value if value.get("status") == "ready" else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _port_taken(port: int) -> bool:
    import socket
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


class _KillOnClose:
    """Windows job object: the child dies with the backend even if the backend is killed."""

    def __init__(self):
        self.handle = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.windll.kernel32
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            handle = kernel.CreateJobObjectW(None, None)

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class IoCounters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in ("a", "b", "c", "d", "e", "f")]

            class Extended(ctypes.Structure):
                _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            info = Extended()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                self.handle, self._kernel = handle, kernel
        except Exception:
            self.handle = None

    def add(self, process) -> bool:
        if not self.handle:
            return False
        try:
            return bool(self._kernel.AssignProcessToJobObject(self.handle, int(process._handle)))
        except Exception:
            return False


class LayaHost:
    def __init__(self, root, config=None):
        self.root = Path(root).resolve()
        self.config = config or load_config(self.root)
        self.port = int(self.config["port"])
        self.state = "idle"          # idle | starting | ready | restarting | external | unavailable | disabled | stopped
        self.reason = ""
        # Why it is not running, as a stable code the UI turns into plain words, and the technical
        # detail (paths, exception text, log) the UI keeps behind a disclosure.
        self.problem = ""            # off | port-reserved | port-taken | code-missing | runtime-missing | model-missing | spawn-failed | local-only | crashed | lost
        self.detail = ""
        self.process = None
        self.pid = None
        self.started_at = None
        self.restarts = []
        self.last_health = None
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.thread = None
        self.job = _KillOnClose()
        self.directory = self.root / ".neyvia" / "laya"
        self.encoder_thread = None
        self.encoders = {"state": "idle"}

    # ----- public
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ready(self) -> bool:
        return self.state in {"ready", "external"}

    def start(self):
        with self.lock:
            if self.config.get('enabled', True) and self.encoder_thread is None:
                self.encoders = {'state': 'waiting'}
                self.encoder_thread = threading.Thread(target=self._warm_encoders,
                    name='neyvia-laya-encoders', daemon=True)
                self.encoder_thread.start()
            if self.thread and self.thread.is_alive():
                return self
            self.stopping.clear()
            self.problem = self.detail = ""
            problem = self._preflight()
            if problem:
                self.state = "disabled" if not self.config.get("enabled", True) else "unavailable"
                self.reason = problem
                return self
            if self.state == "external":
                # _preflight adopted a healthy service already on the port. Overwriting that with
                # "starting" made the watcher spawn a second child with this install's own runtime,
                # which failed with FileNotFoundError wherever that runtime does not exist.
                self.reason = "Using the LAYA service already running on this PC"
            else:
                self.state = "starting"
                self.reason = "Loading the local model"
            self.thread = threading.Thread(target=self._watch, name="neyvia-laya-host", daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stopping.set()
        with self.lock:
            process, self.process = self.process, None
            if self.state not in {"unavailable", "disabled"}:
                self.state = "stopped"
        if process and process.poll() is None:
            try:
                from .local_network_policy import stop_child
                stop_child(process)
            except Exception:
                process.kill()

    def status(self) -> dict:
        with self.lock:
            model_path = _expand(self.config['project']) / 'evidence/r5/models/g3-c2' \
                if self.config.get('architecture') == 'fast-cpu' else _expand(self.config['model'])
            model = model_path / ('head.npz' if self.config.get('architecture') == 'fast-cpu' else 'model.safetensors')
            return {"state": self.state, "ready": self.ready(), "reason": self.reason, "problem": self.problem, "detail": self.detail,
                    "port": self.port, "pid": self.pid,
                    "owned": self.process is not None, "startedAt": self.started_at, "restarts": len(self.restarts),
                    "device": self.config.get("device"), "architecture": self.config.get('architecture'), "model": {"path": str(model_path),
                    "bytes": model.stat().st_size if model.is_file() else None, "downloaded": False},
                    "serviceCode": str(REPO / "tools" / "laya"), "log": str(self.directory / "service.log"),
                    "health": self.last_health, "instantEncoders": dict(self.encoders)}

    def _warm_encoders(self):
        """Off the request path: wait until the backend serves, give the first page and sign-in a
        quiet moment, prime the encoders' files in a throwaway low-priority process, then load them
        here (now a short, cache-warm step)."""
        started = time.perf_counter()
        _SERVING.wait(timeout=float(os.environ.get("NEYVIA_LAYA_SERVE_WAIT_SECONDS", "120")))
        if self.stopping.wait(float(os.environ.get("NEYVIA_LAYA_WARMUP_DELAY_SECONDS", "5"))):
            return
        with self.lock:
            self.encoders = {'state': 'warming'}
        primed = self._prime_in_child()
        self._preload_encoders()
        with self.lock:
            self.encoders = {**self.encoders, 'primed': primed, 'sinceStartMs': (time.perf_counter()-started)*1000}

    def _prime_in_child(self) -> bool:
        code = "; ".join(["import sys", "sys.path.insert(0, %r)" % str(REPO / "src"),
                          "from grant_agent.laya_instant import encode, routing_encoder",
                          "encode('LAYA encoder warmup')", "routing_encoder()",
                          "from grant_agent.taste_vision import preload", "preload()"])
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
        try:
            child = subprocess.Popen([sys.executable, "-c", code], cwd=str(REPO), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
            self.job.add(child)
            return child.wait(timeout=float(os.environ.get("NEYVIA_LAYA_PRIME_TIMEOUT_SECONDS", "240"))) == 0
        except Exception:
            return False

    def _preload_encoders(self):
        started = time.perf_counter()
        result = {}
        for name in ('text', 'vision'):
            try:
                if name == 'text':
                    from .laya_instant import encode, store, routing_encoder
                    encode('LAYA encoder warmup')
                    routing_encoder()
                    encode('Route a request to its documented action', 'routing')
                    store(str(self.root)).refresh()
                    from .laya_instant_ingest import watch
                    watch(self.root)
                else:
                    from .taste_vision import preload
                    preload()
                result[name] = {'ready': True}
            except Exception as exc:
                result[name] = {'ready': False, 'reason': str(exc)[:240]}
        with self.lock:
            self.encoders = {**result, 'state': 'ready' if all(v['ready'] for v in result.values()) else 'partial',
                             'elapsedMs': (time.perf_counter()-started)*1000}

    # ----- internals
    def _paths(self):
        return _expand(self.config["python"]), _expand(self.config["model"])

    def _preflight(self) -> str:
        def fail(problem, reason, detail=""):
            self.problem, self.detail = problem, detail
            return reason
        if not self.config.get("enabled", True):
            return fail("off", "LAYA is switched off in config/laya.json", f'"enabled" is false in {REPO / "config" / "laya.json"}')
        if self.port in RESERVED or not 1024 <= self.port <= 65535:
            return fail("port-reserved", f"Port {self.port} is not allowed for LAYA", 'Choose another "port" in config/laya.json')
        python, model = self._paths()
        if self.config.get("_command"):
            return "" if not (_health(self.port) or _port_taken(self.port)) else fail("port-taken", f"Port {self.port} is taken")
        service = REPO / "tools" / "laya" / "laya_system1" / "service.py"
        if not service.is_file():
            return fail("code-missing", "The LAYA service code is missing from this install (tools/laya)", f"Expected {service}")
        if _health(self.port):
            self.state = "external"
            return ""  # adopt a healthy service already on the port (it is not ours to stop)
        if _port_taken(self.port):
            return fail("port-taken", f"Port {self.port} is used by another program that is not a LAYA service",
                        f"127.0.0.1:{self.port} is in use but does not answer as a LAYA service")
        if not python.is_file():
            return fail("runtime-missing", f"The LAYA Python runtime is missing: {python}", f'Expected {python} (config "python")')
        if self.config.get("architecture") in {"fast-cpu", "transformer"}:
            project = _expand(self.config["project"])
            if not (project / "evidence/r5/candidates.json").is_file():
                return fail("model-missing", "The calibrated LAYA CPU candidate is missing", str(project))
        if self.config.get("architecture") != "fast-cpu" and not (model / "model.safetensors").is_file():
            return fail("model-missing", f"The LAYA model weights are missing: {model}", f'Expected {model / "model.safetensors"} (config "model")')
        return ""

    def _spawn(self):
        python, model = self._paths()
        self.directory.mkdir(parents=True, exist_ok=True)
        database = self.directory / "system1.sqlite"
        seed = REPO / "tools" / "laya" / "memory-seed.sqlite"
        if seed.is_file() and not database.is_file():
            shutil.copyfile(seed, database)
        log = open(self.directory / "service.log", "ab")  # noqa: SIM115 - handed to the child
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "USE_TF": "0",
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "LAYA_WEIGHT_DTYPE": "float32" if self.config["device"] == "cpu" else "bfloat16",
               "LAYA_CUDA_GRAPHS": "0" if self.config["device"] == "cpu" else "1",
               "LAYA_CPU_THREADS": str(self.config["cpuThreads"]),
               "LAYA_SOURCE": str(REPO / "tools" / "laya"), "PYTHONPATH": str(REPO / "tools" / "laya")}
        if self.config["device"] == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        elif not env.get("CUDA_VISIBLE_DEVICES"):
            # An empty value hides every GPU; torch then fails each decision
            # with "Invalid device id" although the service reported ready.
            env.pop("CUDA_VISIBLE_DEVICES", None)
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        command = [str(python), "-m", "laya_system1.service", "--model", str(model), "--device", str(self.config["device"]),
                   "--port", str(self.port), "--database", str(database),
                   "--question-sets", str(REPO / "tools" / "laya" / "question_sets"),
                   "--calibration", str(REPO / "tools" / "laya" / "calibration-base.json"),
                   "--memory-capacity", str(int(self.config["memoryCapacity"]))]
        if self.config.get("architecture") in {"fast-cpu", "transformer"}:
            # Load the calibrated candidate through its existing identity-bound adapter.
            # The adapter loads its project package before the System 1 service imports.
            env["PYTHONPATH"] = str(REPO / "src")
            env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
            command = [str(python), "-m", "grant_agent.laya_app_service", "--project", str(_expand(self.config["project"])),
                       "--port", str(self.port), "--database", str(database),
                       "--question-sets", str(REPO / "tools/laya/question_sets"),
                       "--memory-capacity", str(int(self.config["memoryCapacity"]))]
            if self.config.get("architecture") == "transformer":
                command += ["--model", str(model), "--device", str(self.config["device"]),
                            "--calibration", str(REPO / "tools/laya/calibration-base.json")]
        command = self.config.get("_command") or command  # tests substitute a stand-in service
        process = subprocess.Popen(command, cwd=str(REPO / "tools" / "laya"), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   env=env, creationflags=flags, close_fds=True)
        log.close()
        self.job.add(process)
        try:
            from .local_network_policy import register_idle_child, stop_child
            register_idle_child(process, kind="LAYA service", busy=lambda: False, stop=lambda: stop_child(process))
        except Exception:
            pass
        with self.lock:
            self.process, self.pid, self.started_at = process, process.pid, time.time()

    def _probe(self):
        return _health(self.port)

    def _spawn_failure(self, exc):
        """Name the cause of a failed start, with the paths needed to fix it."""
        python, _ = self._paths()
        program = Path((self.config.get("_command") or [str(python)])[0])
        cwd = REPO / "tools" / "laya"
        lines = [f"{type(exc).__name__}: {exc}", f"Program: {program}", f"Working folder: {cwd}", f"Log: {self.directory / 'service.log'}"]
        if isinstance(exc, PermissionError):
            return ("local-only" if getattr(exc, "code", "") == "local_only" or "local" in str(exc).lower() else "spawn-failed"), "\n".join(lines)
        if isinstance(exc, FileNotFoundError):
            # Popen's WinError 2 does not say which file was missing; check the two it needs.
            if not program.is_file():
                return "runtime-missing", "\n".join([f"{program} does not exist", *lines])
            if not cwd.is_dir():
                return "code-missing", "\n".join([f"{cwd} does not exist", *lines])
        return "spawn-failed", "\n".join(lines)

    def _watch(self):
        deadline = time.monotonic()
        while not self.stopping.is_set():
            with self.lock:
                process, state = self.process, self.state
            if state == "external":
                health = _health(self.port)
                self.last_health = health
                if not health:
                    with self.lock:
                        self.state, self.reason = "unavailable", "The LAYA service on the configured port stopped answering"
                        self.problem, self.detail = "lost", f"No answer from {self.url}/v1/health"
                    return
                self.stopping.wait(5)
                continue
            if process is None:
                now = time.monotonic()
                self.restarts = [t for t in self.restarts if now - t < float(self.config["restartWindowSeconds"])]
                if len(self.restarts) >= int(self.config["maxRestarts"]):
                    with self.lock:
                        self.state, self.reason = "unavailable", f"The LAYA service crashed {len(self.restarts)} times in a row; see {self.directory / 'service.log'}"
                        self.problem, self.detail = "crashed", f"Log: {self.directory / 'service.log'}"
                    return
                if self.restarts:
                    delay = min(60, 2 ** len(self.restarts))
                    with self.lock:
                        self.state, self.reason = "restarting", f"Restarting after a crash in {delay} s"
                    if self.stopping.wait(delay):
                        return
                try:
                    self._spawn()
                except (OSError, PermissionError, ValueError) as exc:
                    with self.lock:
                        self.state = "unavailable"
                        self.problem, self.detail = self._spawn_failure(exc)
                        self.reason = ("Local-only mode does not allow Neyvia to start the LAYA service" if self.problem == "local-only"
                                       else f"The LAYA service could not start: {type(exc).__name__}: {exc}")
                    return
                deadline = time.monotonic() + float(self.config["startTimeoutSeconds"])
                with self.lock:
                    self.state, self.reason = "starting", "Loading the local model"
                continue
            if process.poll() is not None:
                with self.lock:
                    self.process, self.pid = None, None
                    self.state, self.reason = "restarting", f"The LAYA service exited with code {process.returncode}"
                self.restarts.append(time.monotonic())
                continue
            health = self._probe()
            self.last_health = health
            with self.lock:
                # stop() can detach the child while the health request is in flight.
                # Never revive its state or attempt to kill a detached process.
                if self.stopping.is_set() or self.process is not process:
                    return
                if health:
                    self.state, self.reason = "ready", ""
                elif self.state == "ready":
                    # One missed probe is not a crash; the process is alive, so say so.
                    self.reason = "The LAYA service is busy or slow to answer"
                elif time.monotonic() > deadline:
                    self.state, self.reason = "restarting", "The LAYA service did not become ready in time"
                    stuck, self.process = self.process, None
                    try:
                        from .local_network_policy import stop_child
                        stop_child(stuck)
                    except Exception:
                        stuck.kill()
                    self.restarts.append(time.monotonic())
            self.stopping.wait(3)


def host_for(root=None):
    return _HOST


def start(root) -> LayaHost:
    """Start (once per process) and return the host. Safe to call again; never raises."""
    global _HOST
    with _LOCK:
        if _HOST is None:
            try:
                _HOST = LayaHost(root).start()
            except Exception as exc:  # the backend must start whatever happens here
                _HOST = LayaHost(root)
                _HOST.state, _HOST.reason = "unavailable", f"{type(exc).__name__}: {str(exc)[:160]}"
            atexit.register(stop)
        return _HOST


def stop():
    with _LOCK:
        host = _HOST
    if host:
        host.stop()


def restart(root) -> LayaHost:
    """Stop the current host (and the child it owns) and start a fresh one with the current
    configuration. Never raises: the new host's state says what happened, including local-only
    mode refusing the child (the watcher reports that as problem "local-only")."""
    global _HOST
    with _LOCK:
        old, first = _HOST, _HOST is None
    if old:
        old.stop()
        if old.thread and old.thread.is_alive():
            old.thread.join(timeout=8)
    with _LOCK:
        try:
            fresh = LayaHost(root)
            if old and old.encoder_thread is not None:
                # The in-process encoders are already loaded (or loading); do not warm them twice.
                fresh.encoder_thread, fresh.encoders = old.encoder_thread, old.encoders
            _HOST = fresh.start()
        except Exception as exc:
            _HOST = LayaHost(root)
            _HOST.state, _HOST.reason = "unavailable", f"{type(exc).__name__}: {str(exc)[:160]}"
            _HOST.problem, _HOST.detail = "spawn-failed", f"{type(exc).__name__}: {exc}"
        if first:
            atexit.register(stop)
        host = _HOST
    # Give the watcher a moment to try the child, so the answer usually carries the outcome.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and host.state == "starting" and host.process is None and host.thread and host.thread.is_alive():
        time.sleep(0.05)
    return host


def current_url():
    """The loopback URL when the service is ready, else None."""
    host = _HOST
    return host.url if host and host.ready() else None


def status(root=None) -> dict:
    host = _HOST
    if host is None:
        config = load_config(root)
        return {"state": "not-started", "ready": False, "reason": "The backend has not started the LAYA service in this process",
                "port": config["port"], "enabled": config["enabled"]}
    return host.status()
