"""Observe real workspace/job safety before reversible sidebar cleanup."""

from __future__ import annotations

import os
import json
import subprocess
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path

from ..subprocess_utils import hidden_windows_subprocess_kwargs

DEFAULT_POLICY = {"noFolderDays": 7, "projectDays": 30, "tidyThreshold": 30, "autoArchive": False}
MARKERS = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", ".project")
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOTS = OrderedDict()
_PENDING = set()
_QUEUE = deque()
_WORKER = None
_SNAPSHOT_TTL = 5.0


def _refresh_snapshots():
    global _WORKER
    while True:
        with _SNAPSHOT_LOCK:
            if not _QUEUE:
                _WORKER = None
                return
            key, observer, cwd = _QUEUE.popleft()
        try:
            result = observer.observe(cwd)
            with _SNAPSHOT_LOCK:
                _SNAPSHOTS[key] = (time.monotonic(), result)
                _SNAPSHOTS.move_to_end(key)
                while len(_SNAPSHOTS) > 512:
                    _SNAPSHOTS.popitem(last=False)
        except Exception:
            pass  # The display remains unknown; fresh archive checks still refuse.
        finally:
            with _SNAPSHOT_LOCK:
                _PENDING.discard(key)


def under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def normalize_policy(raw):
    raw = raw if isinstance(raw, dict) else {}
    policy = dict(DEFAULT_POLICY)
    for key in ("noFolderDays", "projectDays", "tidyThreshold"):
        value = raw.get(key, policy[key])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 365:
            raise ValueError(f"{key} must be between 1 and 365")
        policy[key] = int(value)
    policy["autoArchive"] = raw.get("autoArchive") is True
    return policy


class SidebarSafetyObserver:
    def __init__(self, projects=(), *, excluded_roots=None, allowed_roots=None):
        self.projects = [Path(row["path"]).absolute() for row in projects if row.get("path")]
        self.excluded_roots = [Path(value).absolute() for value in (
            excluded_roots if excluded_roots is not None else json.loads(os.environ.get("NEYVIA_SIDEBAR_EXCLUDED_ROOTS", "[]")))]
        self.allowed_roots = [Path(value).absolute() for value in (
            allowed_roots if allowed_roots is not None else json.loads(os.environ.get("NEYVIA_SIDEBAR_ALLOWED_ROOTS", "[]")))]
        self.process_dirs = None
        self.cache = {}

    def observe_cached(self, cwd):
        """Sidebar display only. Archive/confirm paths must use fresh observe()."""
        global _WORKER
        if not cwd:
            return self.observe(cwd)
        scope = tuple(tuple(str(path) for path in paths) for paths in
                      (self.projects, self.excluded_roots, self.allowed_roots))
        key = (scope, os.path.normcase(os.path.abspath(str(cwd))))
        with _SNAPSHOT_LOCK:
            cached = _SNAPSHOTS.get(key)
            fresh = cached is not None and time.monotonic() - cached[0] < _SNAPSHOT_TTL
            if not fresh and key not in _PENDING:
                _PENDING.add(key)
                # A new observer keeps process observations fresh each refresh.
                observer = SidebarSafetyObserver(
                    [{"path": str(path)} for path in self.projects],
                    excluded_roots=self.excluded_roots, allowed_roots=self.allowed_roots)
                _QUEUE.append((key, observer, cwd))
                if _WORKER is None or not _WORKER.is_alive():
                    _WORKER = threading.Thread(target=_refresh_snapshots, name="sidebar-folders", daemon=True)
                    _WORKER.start()
            result = dict(cached[1]) if cached else {"project_known": False, "has_uncommitted": None,
                                                   "has_running_jobs": None}
            safety = dict(result.get("cleanup_safety") or {})
            safety.update(cached=True, refreshing=not fresh)
            if not fresh:
                # A cached display row is never sufficient authority to archive.
                safety["status"] = "refreshing"
            result["cleanup_safety"] = safety
            return result

    def _jobs(self, path):
        if self.process_dirs is None:
            try:
                import psutil
                self.process_dirs = []
                for process in psutil.process_iter(["pid", "cwd"], ad_value=None):
                    if process.info["pid"] != os.getpid() and process.info.get("cwd"):
                        self.process_dirs.append(Path(process.info["cwd"]).absolute())
            except (ImportError, OSError):
                return None
        return any(under(cwd, path) for cwd in self.process_dirs)

    def observe(self, cwd):
        key = str(cwd or "")
        if key in self.cache:
            return dict(self.cache[key])
        result = {"project_known": False, "has_uncommitted": None, "has_running_jobs": None,
                  "cleanup_safety": {"status": "unknown", "observedAt": time.time()}}
        if not cwd:
            result.update(has_uncommitted=False, has_running_jobs=False)
            result["cleanup_safety"]["status"] = "observed"
        else:
            path = Path(cwd).absolute()
            if any(under(path, root) for root in self.excluded_roots):
                result["cleanup_safety"]["status"] = "protected_path"
            elif self.allowed_roots and not any(under(path, root) for root in self.allowed_roots):
                result["cleanup_safety"]["status"] = "out_of_scope"
            elif not path.is_dir():
                result["cleanup_safety"]["status"] = "folder_unavailable"
            else:
                path = path.resolve()
                if any(under(path, root) for root in self.excluded_roots) or self.allowed_roots and not any(under(path, root.resolve()) for root in self.allowed_roots):
                    result["cleanup_safety"]["status"] = "out_of_scope"
                    self.cache[key] = result
                    return dict(result)
                result["project_known"] = any(under(path, root) for root in self.projects) or any((path / marker).exists() for marker in MARKERS)
                kwargs = dict(cwd=path, capture_output=True, text=True, timeout=5,
                              **hidden_windows_subprocess_kwargs())
                try:
                    top = subprocess.run(["git", "--no-optional-locks", "rev-parse", "--show-toplevel"], **kwargs)
                    if top.returncode == 0:
                        tree = Path(top.stdout.strip()).absolute()
                        if any(under(tree, root) for root in self.excluded_roots) or self.allowed_roots and not any(under(tree, root) for root in self.allowed_roots):
                            result["cleanup_safety"]["status"] = "protected_path"
                            self.cache[key] = result
                            return dict(result)
                        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"], **{**kwargs, "cwd": tree, **hidden_windows_subprocess_kwargs()})
                        result.update(project_known=True, has_uncommitted=bool(status.stdout) if status.returncode == 0 else None)
                        path = tree
                    else:
                        result["has_uncommitted"] = False if "not a git repository" in top.stderr.lower() else None
                except (OSError, subprocess.TimeoutExpired):
                    pass
                result["has_running_jobs"] = self._jobs(path)
                if result["has_uncommitted"] is not None and result["has_running_jobs"] is not None:
                    result["cleanup_safety"]["status"] = "observed"
        self.cache[key] = result
        return dict(result)


def archive_blocker(row, now=None):
    now = time.time() if now is None else now
    if row.get("pinned"):
        return "pinned"
    if row.get("status") in {"working", "waiting_approval", "waiting_input"}:
        return "running_or_needs_you"
    if row.get("status") == "failed" and now - updated_epoch(row) < 86400:
        return "recent_failure"
    if row.get("has_uncommitted"):
        return "dirty_worktree"
    if row.get("has_running_jobs"):
        return "running_jobs"
    if (row.get("cleanup_safety") or {}).get("status") != "observed":
        return "safety_unknown"
    return ""


def updated_epoch(row):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(row.get("updated_at") or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return time.time()


def stale(row, policy, now):
    project = row.get("projectOverride") if "projectOverride" in row else row.get("project_known")
    days = policy["projectDays" if project else "noFolderDays"]
    return now - updated_epoch(row) > days * 86400
