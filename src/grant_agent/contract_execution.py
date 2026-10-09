"""Low-overhead Python line execution receipts for measured contract coverage.

This module is deliberately opt-in. ``start`` instruments the current Python
process and installs a temporary ``sitecustomize`` bootstrap so Python child
processes inherit the same bounded, source-hashed trace.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
from collections.abc import Mapping, Sequence
import sys
import threading
import uuid


_ACTIVE = None
_CHILD_CONFIG_REPO = None
_CHILD_CONFIG_BEFORE: dict[str, str] = {}
_CHILD_CONFIG_SCOPE: set[str] = set()
_AUDIT_HOOK_INSTALLED = False
_AUDIT_IO = threading.local()
_DEFAULT_SCOPE_REF = "d4ff0c717cbf437bef0d305eb95dc5aed5a0bdf3"
_EXCLUDED = (".agent_control/", "scripts/evidence/", "evidence/", "vendor/",
             "third_party/", "node_modules/")
_CONFIG_SUFFIXES = {".json", ".cl", ".toml", ".yaml", ".yml", ".xml"}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    previous = getattr(_AUDIT_IO, "internal", False)
    _AUDIT_IO.internal = True
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        _AUDIT_IO.internal = previous
    return digest.hexdigest()


def _read_only(mode, flags) -> bool:
    if isinstance(mode, str) and any(mark in mode for mark in "wax+"):
        return False
    if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        return False
    return True


def _config_relative(repo: Path, filename) -> tuple[str, Path] | None:
    if not isinstance(filename, (str, bytes, os.PathLike)):
        return None
    try:
        path = Path(os.fsdecode(filename)).resolve()
        rel = path.relative_to(repo).as_posix()
    except (OSError, ValueError, TypeError):
        return None
    parts = rel.split("/")
    if (path.suffix.lower() not in _CONFIG_SUFFIXES or not path.is_file()
            or any(part in {".agent_control", "node_modules", "vendor", "third_party", "fixtures", "fixture", "__fixtures__"} for part in parts)
            or rel.startswith(("docs/", "plans/", "scripts/evidence/", "evidence/", "generated-projects/", "tests/", "config/proofs/"))):
        return None
    return rel, path


def _scope_row(value):
    """Normalize one changed_lines row or direct line allowlist."""
    if isinstance(value, Mapping):
        if value.get("status") == "deleted":
            return None
        line_data = value.get("lineData") is True
        lines = value.get("lines", [])
    elif value is None:
        line_data, lines = False, []
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        line_data, lines = True, value
    else:
        raise ValueError("Trace scope entries must be line lists or changed-line rows")
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes, bytearray)):
        raise ValueError("Trace scope lines must be an integer sequence")
    normalized = []
    for line in lines:
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("Trace scope line numbers must be positive integers")
        normalized.append(line)
    return {"lineData": line_data, "lines": sorted(set(normalized)) if line_data else []}


def _path_policy(repo: Path):
    """Load the repo's declared policy, or this installed source's public default."""
    policy_path = repo / "config" / "contract_path_policy.json"
    origin = "repository"
    if not policy_path.is_file():
        policy_path = Path(__file__).resolve().parents[2] / "config" / "contract_path_policy.json"
        origin = "bundled-default"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema") != "neyvia.contract-path-policy.v1":
        raise ValueError("Trace path policy has an unknown schema")
    from .contract_coverage import classify
    return policy, classify, origin, hashlib.sha256(policy_path.read_bytes()).hexdigest()


def _load_scope(repo: Path, scope=None):
    """Return the exact Python/config allowlist and its persisted provenance."""
    source = "explicit"
    if scope is None:
        scope_path = os.environ.get("NEYVIA_P22_TRACE_SCOPE")
        if scope_path:
            document = json.loads(Path(scope_path).read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("schema") != "neyvia.python-trace-scope.v1":
                raise ValueError("Child execution trace scope has an unknown schema")
            scope = document.get("files")
            source = str(document.get("source") or "inherited")
        else:
            since = os.environ.get("NEYVIA_P22_TRACE_SINCE") or _DEFAULT_SCOPE_REF
            from .contract_diff import trace_scope
            scope = trace_scope(repo, since)
            source = "git:" + since
    elif isinstance(scope, (str, os.PathLike)):
        document = json.loads(Path(scope).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != "neyvia.python-trace-scope.v1":
            raise ValueError("Trace scope file has an unknown schema")
        scope = document.get("files")
        source = str(document.get("source") or "scope-file")
    if not isinstance(scope, Mapping):
        raise ValueError("Trace scope must be a repository-relative path mapping")

    policy, classify, policy_origin, policy_sha256 = _path_policy(repo)
    files = {}
    excluded = []
    python = {}
    config = set()
    for raw_name, raw_row in scope.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError("Trace scope contains an invalid path")
        name = raw_name.replace("\\", "/")
        path = Path(name)
        if path.is_absolute() or ":" in name or ".." in path.parts or name.startswith("/"):
            raise ValueError("Trace scope paths must stay repository-relative")
        rel = path.as_posix()
        row = _scope_row(raw_row)
        if row is None:
            continue
        classification = classify(rel, policy)
        if classification["kind"] != "behaviour":
            excluded.append({"file": rel, "kind": classification["kind"],
                             "reason": classification["reason"]})
            continue
        if (rel.startswith(_EXCLUDED + ("config/proofs/", "config/proofs-", "proof/", "web/proof/"))
                or any(part in {"node_modules", "vendor", "third_party", "fixtures", "fixture", "__fixtures__"}
                       for part in rel.split("/"))):
            excluded.append({"file": rel, "kind": "no behaviour", "reason": "Trace safety exclusion"})
            continue
        suffix = Path(rel).suffix.lower()
        if suffix not in {".py", ".pyw", *_CONFIG_SUFFIXES}:
            continue
        candidate = (repo / rel).resolve()
        try:
            candidate.relative_to(repo)
        except ValueError as error:
            raise ValueError("Trace scope path resolves outside the repository") from error
        if not candidate.is_file():
            continue
        files[rel] = row
        if suffix in {".py", ".pyw"}:
            python[rel] = None if not row["lineData"] else frozenset(row["lines"])
        else:
            config.add(rel)
    document = {"schema": "neyvia.python-trace-scope.v1", "source": source,
                "files": {name: files[name] for name in sorted(files)},
                "excluded": sorted(excluded, key=lambda item: item["file"]),
                "pathPolicy": {"origin": policy_origin, "sha256": policy_sha256}}
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return document, encoded, python, config


def _scoped_filename(repo: Path, filename, allowed_files) -> str | None:
    """Reject external and non-scoped names before resolving filesystem paths."""
    if not isinstance(filename, str) or not filename or filename.startswith(("<", "frozen ")):
        return None
    try:
        absolute = os.path.normcase(os.path.abspath(filename))
        root = os.path.normcase(str(repo))
        prefix = root + os.sep
        if not absolute.startswith(prefix):
            return None
        rel = os.path.relpath(absolute, root).replace("\\", "/")
        if rel not in allowed_files:
            return None
        resolved = Path(absolute).resolve()
        if resolved.relative_to(repo).as_posix() != rel or not resolved.is_file():
            return None
        return rel
    except (OSError, ValueError):
        return None


def _install_audit_hook():
    global _AUDIT_HOOK_INSTALLED
    if _AUDIT_HOOK_INSTALLED:
        return

    def opened(event, args):
        if event != "open" or getattr(_AUDIT_IO, "internal", False):
            return
        try:
            filename, mode, flags = args
            if not _read_only(mode, flags):
                return
            active = _ACTIVE
            repo = active.repo if active is not None and not active._stopped else _CHILD_CONFIG_REPO
            if repo is None:
                return
            item = _config_relative(repo, filename)
            if item is None:
                return
            rel, path = item
            config_scope = active.config_scope if active is not None and not active._stopped else _CHILD_CONFIG_SCOPE
            if rel not in config_scope:
                return
            rows = active.config_before if active is not None and not active._stopped else _CHILD_CONFIG_BEFORE
            if rel not in rows:
                rows[rel] = _sha(path)
        except Exception:
            return

    sys.addaudithook(opened)
    _AUDIT_HOOK_INSTALLED = True


def _relative(repo: Path, filename: str) -> str | None:
    if not filename or filename.startswith(("<", "frozen ")):
        return None
    try:
        path = Path(filename).resolve()
        rel = path.relative_to(repo).as_posix()
    except (OSError, ValueError):
        return None
    if any(part in (".agent_control", "node_modules", "vendor", "third_party")
           for part in rel.split("/")) or rel.startswith("scripts/evidence/") or rel.startswith("evidence/"):
        return None
    if not path.is_file() or path.suffix.lower() not in {".py", ".pyw"}:
        return None
    return rel


class TraceSession:
    def __init__(self, repo: Path, root: Path, contracts, *, scope=None, resources=None, resource_slot=None,
                 memory_watch_obj=None, child_only=False):
        if not child_only and not hasattr(sys, "monitoring"):
            raise RuntimeError("Python 3.12+ sys.monitoring is required for execution tracing")
        self.repo = repo.resolve()
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.contracts = tuple(contracts or ())
        self.scope, scope_bytes, self.python_scope, self.config_scope = _load_scope(self.repo, scope)
        self.scope_path = self.root / f"trace-scope-{uuid.uuid4().hex}.json"
        self.scope_path.write_bytes(scope_bytes)
        self.scope_sha256 = hashlib.sha256(scope_bytes).hexdigest()
        self.trace_id = uuid.uuid4().hex
        self.events_path = self.root / f"line-events-{os.getpid()}-{self.trace_id}.jsonl"
        # Receipts are admitted only after stop() flushes the complete stream.
        # Block buffering avoids one disk write per first-hit line on D: while
        # preserving the exact events, source hashes and final admission checks.
        self._events = self.events_path.open("a", encoding="utf-8", buffering=65536)
        self.lines: dict[str, set[int]] = {}
        self.config_before: dict[str, str] = {}
        self.before: dict[str, str] = {}
        self.file_names: dict[str, str | None] = {}
        self._resources = resources
        self.resource_slot = resource_slot
        self.memory_watch = memory_watch_obj
        self.child_only = bool(child_only)
        self.tool_id = None if self.child_only else self._tool_id()
        self._old_env = {name: os.environ.get(name) for name in
                         ("NEYVIA_P22_TRACE_ROOT", "NEYVIA_P22_TRACE_REPO", "NEYVIA_P22_TRACE_SRC", "NEYVIA_P22_TRACE_SCOPE", "NEYVIA_P22_TRACE_SCOPE_SHA256", "NEYVIA_P22_TRACE_ID", "PYTHONPATH")}
        self._child_records: set[Path] = set()
        self.child_count = 0
        self.child_errors = []
        self._stopped = False
        self._old_sitecustomize = (self.root / "sitecustomize.py").read_bytes() if (self.root / "sitecustomize.py").exists() else None
        self._install_child_bootstrap()
        _install_audit_hook()
        if not self.child_only:
            sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.LINE, self._line)
            sys.monitoring.restart_events()
            sys.monitoring.set_events(self.tool_id, sys.monitoring.events.LINE)

    @staticmethod
    def _tool_id() -> int:
        monitoring = sys.monitoring
        for candidate in range(5, -1, -1):
            try:
                monitoring.use_tool_id(candidate, "neyvia-contract-execution")
                return candidate
            except ValueError:
                continue
        raise RuntimeError("no free sys.monitoring tool id")

    def _install_child_bootstrap(self):
        os.environ["NEYVIA_P22_TRACE_ROOT"] = str(self.root)
        os.environ["NEYVIA_P22_TRACE_REPO"] = str(self.repo)
        os.environ["NEYVIA_P22_TRACE_SRC"] = str(self.repo / "src")
        os.environ["NEYVIA_P22_TRACE_SCOPE"] = str(self.scope_path)
        os.environ["NEYVIA_P22_TRACE_SCOPE_SHA256"] = self.scope_sha256
        os.environ["NEYVIA_P22_TRACE_ID"] = self.trace_id
        existing = os.environ.get("PYTHONPATH", "")
        pieces = [str(self.root), str(self.repo / "src")]
        if existing:
            pieces.append(existing)
        os.environ["PYTHONPATH"] = os.pathsep.join(pieces)
        code = '''import json, os, sys\n\n_src = os.environ.get("NEYVIA_P22_TRACE_SRC")\nif _src and _src not in sys.path: sys.path.insert(0, _src)\ntry:\n    from grant_agent.contract_resources import heavy_slot, memory_watch\n    _slot = heavy_slot(timeout=45); _slot_value = _slot.__enter__()\n    _watch = memory_watch(os.getpid(), logs_root=os.environ.get("NEYVIA_P22_TRACE_ROOT")); _watch_state = _watch.__enter__()\n    if not hasattr(sys, "monitoring"): raise RuntimeError("sys.monitoring unavailable")\n    from grant_agent.contract_execution import start_child\n    start_child(_resource_contexts=(_slot, _watch), _resource_slot=_slot_value, _memory_watch=_watch_state)\nexcept Exception as _error:\n    _root = os.environ.get("NEYVIA_P22_TRACE_ROOT")\n    if _root:\n        try:\n            _trace_id = os.environ.get("NEYVIA_P22_TRACE_ID", "unknown")\n            with open(os.path.join(_root, "child-bootstrap-errors-" + _trace_id + ".jsonl"), "a", encoding="utf-8") as _out:\n                _out.write(json.dumps({"pid": os.getpid(), "error": type(_error).__name__}) + "\\n")\n        except Exception:\n            pass\ndel _src\n'''
        (self.root / "sitecustomize.py").write_text(code, encoding="utf-8")

    def _line(self, code, line):
        filename = code.co_filename
        if filename not in self.file_names:
            rel = _scoped_filename(self.repo, filename, self.python_scope)
            if rel is None:
                return sys.monitoring.DISABLE
            self.file_names[filename] = rel
        name = self.file_names[filename]
        if name is None:
            return sys.monitoring.DISABLE
        line = int(line)
        allowed = self.python_scope[name]
        if allowed is not None and line not in allowed:
            return sys.monitoring.DISABLE
        hit = self.lines.setdefault(name, set())
        if line in hit:
            return sys.monitoring.DISABLE
        hit.add(line)
        self._events.write(json.dumps({"file": name, "line": line}, separators=(",", ":")) + "\n")
        if name not in self.before:
            try:
                self.before[name] = _sha(self.repo / name)
            except OSError:
                self.before[name] = ""
        return sys.monitoring.DISABLE

    def _read_children(self):
        errors = self.root / f"child-bootstrap-errors-{self.trace_id}.jsonl"
        if errors.exists():
            try:
                self.child_errors = [json.loads(line) for line in errors.read_text(encoding="utf-8").splitlines() if line]
            except (OSError, ValueError):
                self.child_errors = [{"error": "invalid child bootstrap receipt"}]
        for record in self.root.glob("child-*.json"):
            if record in self._child_records:
                continue
            self._child_records.add(record)
            try:
                child = json.loads(record.read_text(encoding="utf-8"))
                if not isinstance(child, dict):
                    raise ValueError("invalid child execution receipt")
                if child.get("traceId") != self.trace_id:
                    continue
                if (child.get("scopeSha256") != self.scope_sha256
                        or not isinstance(child.get("files"), dict) or not isinstance(child.get("config"), dict)):
                    raise ValueError("invalid child execution receipt")
                resource = child.get("resources")
                if (not isinstance(resource, dict) or resource.get("available") is not True
                        or resource.get("reason") is not None):
                    raise ValueError("child memory/resource guard was unavailable")
                for name, row in child.get("files", {}).items():
                    if not isinstance(row, dict) or not row.get("beforeSha256") or row.get("beforeSha256") != row.get("sha256"):
                        raise ValueError("child source changed during execution")
                    if _relative(self.repo, str(self.repo / name)) != name:
                        raise ValueError("child source path is outside the repository")
                    allowed = self.python_scope.get(name, "missing")
                    if allowed == "missing":
                        raise ValueError("child reported a file outside the active trace scope")
                event_name = child.get("events")
                if not isinstance(event_name, str) or Path(event_name).name != event_name:
                    raise ValueError("child event stream path is invalid")
                event_path = self.root / event_name
                if not event_name.startswith(f"line-events-") or not event_path.is_file():
                    raise ValueError("child event stream is missing")
                observed = {}
                with event_path.open("r", encoding="utf-8") as stream:
                    for raw in stream:
                        event = json.loads(raw)
                        if not isinstance(event, dict) or set(event) != {"file", "line"}:
                            raise ValueError("invalid child line event")
                        name, number = event["file"], event["line"]
                        if not isinstance(name, str) or isinstance(number, bool) or not isinstance(number, int):
                            raise ValueError("invalid child line event values")
                        allowed = self.python_scope.get(name, "missing")
                        if allowed == "missing":
                            raise ValueError("child reported a file outside the active trace scope")
                        number = int(number)
                        if allowed is not None and number not in allowed:
                            raise ValueError("child reported a line outside the active trace scope")
                        if number not in self.lines.setdefault(name, set()):
                            self.lines[name].add(number)
                            self._events.write(json.dumps({"file": name, "line": number}, separators=(",", ":")) + "\n")
                        observed.setdefault(name, set()).add(number)
                for name, row in child.get("files", {}).items():
                    if int(row.get("lineCount", -1)) != len(observed.get(name, set())):
                        raise ValueError("child event count does not match its source receipt")
                    if name not in self.before:
                        self.before[name] = str(row.get("beforeSha256", ""))
                for name, row in child.get("config", {}).items():
                    if _config_relative(self.repo, self.repo / name) is not None:
                        if name not in self.config_before:
                            self.config_before[name] = str(row.get("beforeSha256", ""))
                        if not row.get("stable", True):
                            self.child_errors.append({"error": "child configuration source changed during measurement", "path": name})
                self.child_count += 1
            except (OSError, ValueError, TypeError, AttributeError) as error:
                self.child_errors.append({"error": type(error).__name__, "receipt": record.name})

    def stop(self) -> dict:
        if self._stopped:
            raise RuntimeError("execution trace already stopped")
        self._stopped = True
        if self.tool_id is not None:
            monitoring = sys.monitoring
            monitoring.set_events(self.tool_id, 0)
            monitoring.register_callback(self.tool_id, sys.monitoring.events.LINE, None)
            monitoring.free_tool_id(self.tool_id)
        self._read_children()
        self._events.flush()
        self._events.close()
        files = {}
        stable = True
        for name, lines in sorted(self.lines.items()):
            try:
                digest = _sha(self.repo / name)
            except OSError:
                digest = ""
            if not digest or not self.before.get(name) or digest != self.before[name]:
                stable = False
            files[name] = {"sha256": digest, "lines": sorted(lines), "lineData": True}
        for name, before in sorted(self.config_before.items()):
            try:
                digest = _sha(self.repo / name)
            except OSError:
                digest = ""
            if not digest or not before or digest != before:
                stable = False
            files[name] = {"sha256": digest, "lines": [], "lineData": False,
                           "kind": "configuration-read"}
        for name, value in self._old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        bootstrap = self.root / "sitecustomize.py"
        if self._old_sitecustomize is None:
            bootstrap.unlink(missing_ok=True)
        else:
            bootstrap.write_bytes(self._old_sitecustomize)
        global _ACTIVE
        if _ACTIVE is self:
            _ACTIVE = None
        result = {"ok": not self.child_errors and stable and (not self.child_only or self.child_count > 0)
                  and bool(self.child_only or self.memory_watch is None or self.memory_watch.available)
                  and bool(self.memory_watch is None or self.memory_watch.reason is None), "files": files, "sourceStable": stable,
                "childErrors": self.child_errors,
                "contracts": list(self.contracts),
                "traceScope": {"schema": self.scope["schema"], "path": str(self.scope_path),
                               "sha256": self.scope_sha256, "files": self.scope["files"],
                               "excluded": self.scope.get("excluded", []),
                               "pathPolicy": self.scope.get("pathPolicy")},
                "lineEvents": str(self.events_path),
                "childProcesses": self.child_count,
                "resources": {"kind": "child-collector" if self.child_only else "parent-trace",
                              "slot": getattr(self, "resource_slot", None),
                              "memoryAvailable": bool(getattr(self, "memory_watch", None) and self.memory_watch.available),
                              "memoryError": getattr(getattr(self, "memory_watch", None), "error", None),
                              "memoryReason": getattr(getattr(self, "memory_watch", None), "reason", None),
                              "peakPrivateBytes": getattr(getattr(self, "memory_watch", None), "peak_private_bytes", 0),
                              "peakWorkingSetBytes": getattr(getattr(self, "memory_watch", None), "peak_working_set_bytes", 0)}}
        for resource in reversed(self._resources or ()):
            resource.__exit__(None, None, None)
        return result


def start(repo, root, contracts, *, scope=None) -> TraceSession:
    """Trace executed repository Python lines in this process and its children."""
    global _ACTIVE
    if _ACTIVE is not None:
        raise RuntimeError("an execution trace is already active in this process")
    from .contract_resources import heavy_slot, memory_watch
    lease = heavy_slot(timeout=45)
    slot = lease.__enter__()
    watcher = None
    watch_state = None
    try:
        watcher = memory_watch(os.getpid(), logs_root=root)
        watch_state = watcher.__enter__()
        session = TraceSession(Path(repo), Path(root), contracts, scope=scope,
                               resources=(lease, watcher), resource_slot=slot, memory_watch_obj=watch_state)
    except BaseException:
        if watcher is not None:
            watcher.__exit__(*sys.exc_info())
        lease.__exit__(*sys.exc_info())
        raise
    _ACTIVE = session
    return session


def start_children(repo, root, contracts, *, scope=None) -> TraceSession:
    """Collect scoped Python traces from instrumented child processes only.

    The host remains an untraced, unleased coordinator; child interpreters still
    acquire their own heavy-work slot and memory watcher before starting trace.
    """
    global _ACTIVE
    if _ACTIVE is not None:
        raise RuntimeError("an execution trace is already active in this process")
    session = TraceSession(Path(repo), Path(root), contracts, scope=scope, child_only=True)
    _ACTIVE = session
    return session


def start_child(*, _resource_contexts=None, _resource_slot=None, _memory_watch=None) -> None:
    """Initialize a child interpreter from the temporary sitecustomize hook."""
    if _ACTIVE is not None or not hasattr(sys, "monitoring"):
        return
    repo_text = os.environ.get("NEYVIA_P22_TRACE_REPO")
    root_text = os.environ.get("NEYVIA_P22_TRACE_ROOT")
    if not repo_text or not root_text:
        return
    repo, root = Path(repo_text).resolve(), Path(root_text).resolve()
    scope_path = Path(os.environ.get("NEYVIA_P22_TRACE_SCOPE", ""))
    scope_bytes = scope_path.read_bytes()
    scope_sha = hashlib.sha256(scope_bytes).hexdigest()
    if scope_sha != os.environ.get("NEYVIA_P22_TRACE_SCOPE_SHA256"):
        raise ValueError("Inherited trace scope failed its SHA-256 binding")
    scope = json.loads(scope_bytes.decode("utf-8"))
    if scope.get("schema") != "neyvia.python-trace-scope.v1" or not isinstance(scope.get("files"), dict):
        raise ValueError("Inherited trace scope has an invalid shape")
    inherited, _, python_scope, config_scope = _load_scope(repo, scope["files"])
    if scope.get("pathPolicy") != inherited.get("pathPolicy"):
        raise ValueError("Inherited trace path policy changed after scope creation")
    global _CHILD_CONFIG_REPO, _CHILD_CONFIG_BEFORE
    _CHILD_CONFIG_REPO, _CHILD_CONFIG_BEFORE = repo, {}
    global _CHILD_CONFIG_SCOPE
    _CHILD_CONFIG_SCOPE = config_scope
    _install_audit_hook()
    token = uuid.uuid4().hex
    lines: dict[str, set[int]] = {}
    before: dict[str, str] = {}
    file_names: dict[str, str | None] = {}
    trace_id = os.environ.get("NEYVIA_P22_TRACE_ID")
    if not trace_id:
        raise ValueError("Inherited trace id is missing")
    events_path = root / f"line-events-{os.getpid()}-{trace_id}.jsonl"
    events = events_path.open("a", encoding="utf-8", buffering=65536)
    monitoring = sys.monitoring
    tool_id = TraceSession._tool_id()

    def line(code, number):
        filename = code.co_filename
        if filename not in file_names:
            rel = _scoped_filename(repo, filename, python_scope)
            if rel is None:
                return monitoring.DISABLE
            file_names[filename] = rel
        name = file_names[filename]
        if name is None:
            return monitoring.DISABLE
        number = int(number)
        allowed = python_scope[name]
        if allowed is not None and number not in allowed:
            return monitoring.DISABLE
        hit = lines.setdefault(name, set())
        if number in hit:
            return monitoring.DISABLE
        hit.add(number)
        events.write(json.dumps({"file": name, "line": number}, separators=(",", ":")) + "\n")
        if name not in before:
            try:
                before[name] = _sha(repo / name)
            except OSError:
                before[name] = ""
        return monitoring.DISABLE

    def flush():
        try:
            monitoring.set_events(tool_id, 0)
            monitoring.register_callback(tool_id, monitoring.events.LINE, None)
            monitoring.free_tool_id(tool_id)
        except Exception:
            pass
        events.flush()
        events.close()
        files = {}
        config = {}
        for name, hit in lines.items():
            try:
                digest = _sha(repo / name)
            except OSError:
                digest = ""
            files[name] = {"beforeSha256": before.get(name, ""), "sha256": digest,
                           "lineCount": len(hit)}
        stable = True
        for name, start_hash in _CHILD_CONFIG_BEFORE.items():
            try:
                digest = _sha(repo / name)
            except OSError:
                digest = ""
            if not digest or not start_hash or digest != start_hash:
                stable = False
            config[name] = {"beforeSha256": start_hash, "sha256": digest, "stable": stable}
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"child-{os.getpid()}-{token}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps({"traceId": trace_id, "scopeSha256": scope_sha,
                                             "events": events_path.name, "files": files,
                                             "config": config,
                                             "resources": {"slot": _resource_slot,
                                                           "available": bool(_memory_watch and _memory_watch.available),
                                                           "reason": getattr(_memory_watch, "reason", None),
                                                           "error": getattr(_memory_watch, "error", None),
                                                           "peakPrivateBytes": getattr(_memory_watch, "peak_private_bytes", 0),
                                                           "peakWorkingSetBytes": getattr(_memory_watch, "peak_working_set_bytes", 0)}},
                                            separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, target)
        except Exception:
            pass
        _CHILD_CONFIG_REPO = None
        _CHILD_CONFIG_SCOPE.clear()
        for resource in reversed(_resource_contexts or ()):
            try:
                resource.__exit__(None, None, None)
            except Exception:
                pass

    monitoring.register_callback(tool_id, monitoring.events.LINE, line)
    monitoring.restart_events()
    monitoring.set_events(tool_id, monitoring.events.LINE)
    atexit.register(flush)
