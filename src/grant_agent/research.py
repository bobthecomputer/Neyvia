from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path, PureWindowsPath
if __package__:
    from .subprocess_utils import hidden_windows_subprocess_kwargs
else:  # The bounded regex worker is also launched by this file's path.
    from subprocess_utils import hidden_windows_subprocess_kwargs


EXCLUDED_DIRS = {
    ".git",
    ".agent_control",
    ".agent_runs",
    ".agent_runs_test",
    "__pycache__",
    ".venv",
    "venv",
}
# Generated or downloaded trees are never entered: a Rust ``target`` folder or
# ``node_modules`` can hold gigabytes of build output and packages, and reading
# them made one search take many minutes while the agent waited on it.
GENERATED_DIRS = {
    "node_modules",
    "target",
    "site-packages",
    ".next",
    ".nuxt",
    ".turbo",
    ".gradle",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
}
MAX_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_TIME_BUDGET_SECONDS = 30.0


@dataclass
class SearchMatch:
    path: str
    line: int
    snippet: str


def _glob_matches(relative: str, pattern: str) -> bool:
    """Path.glob semantics: only ** crosses directories; **/ can be empty."""
    parts, patterns = tuple(relative.split("/")), tuple(pattern.split("/"))

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatch(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def search_workspace_detailed(
    root: Path,
    query: str,
    include_glob: str = "**/*",
    max_results: int = 25,
    case_sensitive: bool = False,
    time_budget: float | None = DEFAULT_TIME_BUDGET_SECONDS,
    *,
    engine: str = "auto",
) -> dict:
    """Bounded regex search with observable engine, limits, and fallback reason.

    The include glob is workspace-relative. Linked files/directories, generated
    trees, binary files and files over 4 MiB are excluded in both engines.
    Python validates regex syntax; rg-rejected expressions fall back to Python.
    Local-only mode uses an in-process engine before any child launch, with
    timed regex from the optional CL dependency or stdlib literal matching.
    Reaching the result limit conservatively reports incomplete coverage.
    """
    if engine not in {"auto", "rg", "python"}:
        raise ValueError("Search engine must be auto, rg or python.")
    if max_results < 1:
        raise ValueError("max_results must be positive.")
    max_results = min(max_results, 200)
    flags = 0 if case_sensitive else re.IGNORECASE
    re.compile(query, flags=flags)
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Search root must be an existing directory.")
    glob = (include_glob or "**/*").replace("\\", "/")
    if PureWindowsPath(glob).drive or glob.startswith("/") or ".." in glob.split("/"):
        raise ValueError("Search includeGlob must stay inside the workspace root.")
    glob = "/".join(part for part in glob.split("/") if part and part != ".") or "**/*"
    deadline = time.monotonic() + max(0, time_budget) if time_budget is not None else None
    report = {"matches": [], "count": 0, "complete": True, "engine": "python",
              "truncated": False, "timedOut": False, "fallbackReason": None,
              "filesConsidered": 0, "skipped": {"links": 0, "oversized": 0, "binary": 0, "unreadable": 0}}
    from .local_network_policy import enabled
    local_only = enabled()

    def expired() -> bool:
        if deadline is not None and time.monotonic() >= deadline:
            report.update(complete=False, timedOut=True)
            return True
        return False

    def confined(path: Path) -> bool:
        return not _linked(path) and path.resolve().is_relative_to(root)

    def finish() -> dict:
        report["count"] = len(report["matches"])
        from .proofs_d_ui_planning import check_search
        check_search(root, report, glob, max_results)
        return report

    def add(path: Path, line: int, text: str) -> bool:
        report["matches"].append(asdict(SearchMatch(str(path.relative_to(root)), line, text.strip()[:2000])))
        if len(report["matches"]) >= max_results:
            report.update(complete=False, truncated=True)
            return True
        return False

    # Start at root rather than the glob's fixed prefix: a fixed prefix can be
    # a junction or traverse a generated tree before os.walk has a chance to prune it.
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if expired():
            return finish()
        safe_dirs = []
        for name in sorted(dirnames):
            path = Path(dirpath, name)
            if name in EXCLUDED_DIRS or name in GENERATED_DIRS:
                continue
            if confined(path):
                safe_dirs.append(name)
            else:
                report["skipped"]["links"] += 1
        dirnames[:] = safe_dirs
        for name in sorted(filenames):
            if expired():
                return finish()
            path = Path(dirpath, name)
            if not _glob_matches(path.relative_to(root).as_posix(), glob):
                continue
            if not confined(path):
                report["skipped"]["links"] += 1
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    report["skipped"]["oversized"] += 1
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    report["skipped"]["oversized"] += 1
                    continue
                if b"\x00" in raw:
                    report["skipped"]["binary"] += 1
                    continue
            except OSError:
                report["skipped"]["unreadable"] += 1
                continue
            files.append(path)
    report["filesConsidered"] = len(files)
    if local_only:
        # Choose the permitted path before rg or the isolated fallback can hit
        # the child-process guard. The existing CL dependency provides a real
        # regex timeout in this process; literal search needs no dependency.
        report.update(engine="python-inprocess", fallbackReason="Local-only mode uses in-process search")
        try:
            import regex
        except ImportError:
            if any(char in query for char in r".^$*+?{}[]\|()"):
                raise ValueError("Local-only regular-expression search requires the optional 'cl' dependency (regex); use a literal query meanwhile.")
            pattern = re.compile(query, flags)
            timed_regex = False
        else:
            pattern = regex.compile(query, flags | regex.VERSION0)
            timed_regex = True
        for path in files:
            if expired():
                return finish()
            try:
                if not confined(path):
                    report["skipped"]["links"] += 1
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    report["skipped"]["oversized"] += 1
                    continue
                if b"\x00" in raw:
                    report["skipped"]["binary"] += 1
                    continue
            except OSError:
                report["skipped"]["unreadable"] += 1
                continue
            for number, line in enumerate(raw.decode("utf-8", errors="ignore").splitlines(), 1):
                if expired():
                    return finish()
                try:
                    # Never let a pathological expression hold the backend's
                    # GIL indefinitely, even with an unlimited traversal budget.
                    if timed_regex:
                        remaining = max(.001, deadline - time.monotonic()) if deadline else .05
                        matched = pattern.search(line, timeout=min(.05, remaining))
                    else:
                        matched = pattern.search(line)
                except TimeoutError:
                    report.update(complete=False, timedOut=True)
                    return finish()
                if matched and add(path, number, line):
                    return finish()
        return finish()
    rg = shutil.which("rg") if engine != "python" else None
    if engine != "python" and not rg:
        report["fallbackReason"] = "ripgrep executable unavailable"

    if rg and files:
        report["engine"] = "rg"
        # Explicit paths preserve Python glob semantics and avoid following links.
        # Small batches also stay below Windows' process command-line limit.
        batches: list[list[Path]] = []
        batch: list[Path] = []
        size = 0
        for path in files:
            if batch and size + len(str(path)) > 20000:
                batches.append(batch)
                batch, size = [], 0
            batch.append(path)
            size += len(str(path)) + 3
        if batch:
            batches.append(batch)
        for batch in batches:
            if expired():
                return finish()
            command = [rg, "--json", "--no-config", "--no-ignore", "--hidden", "--color=never", "--threads", "1",
                       "--max-filesize", str(MAX_FILE_BYTES), "--max-count", str(max_results)]
            if not case_sensitive:
                command.append("--ignore-case")
            command += ["--", query, *map(str, batch)]
            try:
                with tempfile.TemporaryFile() as errors:
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, cwd=root, **hidden_windows_subprocess_kwargs())
                    timer = None
                    if deadline is not None:
                        timer = threading.Timer(max(0, deadline - time.monotonic()), process.kill)
                        timer.daemon = True
                        timer.start()
                    try:
                        assert process.stdout is not None
                        for raw in process.stdout:
                            if expired():
                                return finish()
                            event = json.loads(raw)
                            if event["type"] != "match":
                                continue
                            data = event["data"]
                            path = Path(data["path"].get("text", ""))
                            if not confined(path):
                                continue
                            line = data["lines"].get("text")
                            if line is None:  # Non-UTF8 is still searched by the legacy Python path.
                                line = base64.b64decode(data["lines"]["bytes"]).decode("utf-8", errors="ignore")
                            # Do not re-run a potentially backtracking Python regex
                            # in the parent: rg already proved this line matches.
                            if add(path, data["line_number"], line):
                                return finish()
                        code = process.wait()
                    finally:
                        if timer:
                            timer.cancel()
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        process.stdout.close()
                    if expired():
                        return finish()
                    if code not in (0, 1):
                        errors.seek(0)
                        report["fallbackReason"] = "ripgrep rejected search: " + errors.read(2000).decode("utf-8", errors="replace").strip()
                        break
            except OSError as exc:
                report["fallbackReason"] = "ripgrep launch failed: " + str(exc)
                break
        else:
            return finish()
        report.update(engine="python", matches=[])

    if not files or expired():
        return finish()
    # Python regex can catastrophically backtrack. Isolating the fallback makes
    # its deadline enforceable even while the regex engine holds the GIL.
    payload = {"root": str(root), "files": list(map(str, files)), "query": query,
               "flags": flags, "maxResults": max_results}
    remaining = max(0.001, deadline - time.monotonic()) if deadline is not None else None
    try:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--search-worker"],
                                   input=json.dumps(payload), capture_output=True, text=True,
                                   encoding="utf-8", timeout=remaining, check=True, **hidden_windows_subprocess_kwargs())
        child = json.loads(completed.stdout)
        report.update(matches=child["matches"], truncated=child["truncated"], complete=not child["truncated"])
        for key, value in child["skipped"].items():
            report["skipped"][key] += value
    except subprocess.TimeoutExpired:
        report.update(complete=False, timedOut=True)
    return finish()


def search_workspace_bounded(
    root: Path, query: str, include_glob: str = "**/*", max_results: int = 25,
    case_sensitive: bool = False, time_budget: float | None = DEFAULT_TIME_BUDGET_SECONDS,
) -> tuple[list[dict], bool]:
    """Compatibility API; False now also means the result limit stopped coverage."""
    result = search_workspace_detailed(root, query, include_glob, max_results, case_sensitive, time_budget)
    return result["matches"], result["complete"]


def search_workspace(
    root: Path,
    query: str,
    include_glob: str = "**/*",
    max_results: int = 25,
    case_sensitive: bool = False,
    time_budget: float | None = DEFAULT_TIME_BUDGET_SECONDS,
) -> list[dict]:
    rows, _ = search_workspace_bounded(root, query, include_glob, max_results, case_sensitive, time_budget)
    return rows


def _python_search_worker(payload: dict) -> dict:
    root = Path(payload["root"]).resolve()
    pattern = re.compile(payload["query"], payload["flags"])
    result = {"matches": [], "truncated": False, "skipped": {"links": 0, "oversized": 0, "binary": 0, "unreadable": 0}}
    for value in payload["files"]:
        path = Path(value)
        try:
            if _linked(path) or not path.resolve().is_relative_to(root):
                result["skipped"]["links"] += 1
                continue
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
        except OSError:
            result["skipped"]["unreadable"] += 1
            continue
        if len(raw) > MAX_FILE_BYTES:
            result["skipped"]["oversized"] += 1
            continue
        if b"\x00" in raw:
            result["skipped"]["binary"] += 1
            continue
        for number, line in enumerate(raw.decode("utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                result["matches"].append(asdict(SearchMatch(str(path.relative_to(root)), number, line.strip()[:2000])))
                if len(result["matches"]) >= payload["maxResults"]:
                    result["truncated"] = True
                    return result
    return result


if __name__ == "__main__" and sys.argv[1:] == ["--search-worker"]:
    print(json.dumps(_python_search_worker(json.load(sys.stdin))))
