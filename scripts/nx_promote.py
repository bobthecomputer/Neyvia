"""Promote sandbox work (Neyvia-next) into the main working tree, gated and reversible.

The sandbox is a plain copy of the main tree with a local git repo whose first
commit is the snapshot it was copied from. Promotion three-way merges each file
the sandbox changed (base = that snapshot, ours = main tree now, theirs =
sandbox), so edits made in the main tree meanwhile are kept. Nothing is written
until every file merges cleanly; every overwritten file is backed up first.

    python scripts/nx_promote.py status
    python scripts/nx_promote.py apply            # dry-run unless --write
    python scripts/nx_promote.py rollback <stamp>
    python scripts/nx_promote.py release          # freeze main tree into a release
    python scripts/nx_promote.py serve <release-dir> [--restart-supervisor]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[1]
MAIN = Path(os.environ.get("NX_MAIN_TREE", r"C:\Users\user\Projects\Neyvia"))
PROMOTIONS = MAIN / ".agent_control" / "promotions"

# Sandbox-only material that must never reach the main tree.
EXCLUDE_PREFIXES = (
    ".sandbox-scratch/", ".agent_runs_test/", ".agent_control/", "node_modules/", ".venv/",
    "web/dist/", "src-tauri/target/",
    # Evidence and proof receipts stay in the sandbox: they are large and never product code.
    "scripts/evidence/", "docs/evidence/", "proof/",
)
EXCLUDE_FILES = {
    "SANDBOX.md", ".agent_memory_test.json", "web/src/neyvia/next/provider-marks-preview.html",
}


sys.path.insert(0, str(SANDBOX / "src"))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs  # noqa: E402


def _hidden() -> dict:
    return hidden_windows_subprocess_kwargs()


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(SANDBOX), *args], capture_output=True, check=check, **_hidden())


def _base_commit() -> str:
    return _git("rev-list", "--max-parents=0", "HEAD").stdout.decode().split()[0]


# Only product folders are promotable; test runs write scratch folders at the root.
INCLUDE_PREFIXES = ("src/", "web/", "tests/", "scripts/", "docs/", "config/", "src-tauri/", "plugins/", ".claude-plugin/", "manuals/",
                    "modules/", "tools/", "apps/", "templates/", "packages/", "rust/", "third_party/")
# Top-level files a change may legitimately need (the build config and the declared dependencies).
INCLUDE_ROOT_FILES = frozenset({"vite.config.mjs", "package.json", "package-lock.json", "pyproject.toml", "uv.lock", ".gitattributes", "MODULES.md"})


def _excluded(path: str) -> bool:
    return ((not path.startswith(INCLUDE_PREFIXES) and path not in INCLUDE_ROOT_FILES) or path in EXCLUDE_FILES or path.startswith(EXCLUDE_PREFIXES)
            or "/__pycache__/" in path or path.endswith(".pyc"))


def changed_paths() -> list[tuple[str, str]]:
    """(status, path) for every sandbox change since the base snapshot, including untracked files."""
    base = _base_commit()
    rows: dict[str, str] = {}
    diff = _git("diff", "--name-status", "--no-renames", base, "--").stdout.decode("utf-8", "replace")
    for line in diff.splitlines():
        status, _, path = line.partition("\t")
        rows[path.replace("\\", "/")] = status[:1]
    untracked = _git("ls-files", "--others", "--exclude-standard").stdout.decode("utf-8", "replace")
    for path in untracked.splitlines():
        rows.setdefault(path.replace("\\", "/"), "A")
    return sorted((status, path) for path, status in rows.items() if not _excluded(path))


_BASE_READER = None
_BASE_COMMIT = None


def _base_bytes(path: str) -> bytes | None:
    """Read a file at the base snapshot through one long-lived `git cat-file --batch` process."""
    global _BASE_READER, _BASE_COMMIT
    if _BASE_COMMIT is None:
        _BASE_COMMIT = _base_commit()
    if _BASE_READER is None or _BASE_READER.poll() is not None:
        _BASE_READER = subprocess.Popen(["git", "-C", str(SANDBOX), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, **_hidden())
    _BASE_READER.stdin.write((_BASE_COMMIT + ":" + path + chr(10)).encode("utf-8"))
    _BASE_READER.stdin.flush()
    header = _BASE_READER.stdout.readline().decode("utf-8", "replace").split()
    if len(header) < 3 or header[-1] == "missing":
        return None
    data = _BASE_READER.stdout.read(int(header[2]))
    _BASE_READER.stdout.read(1)
    return data


def _eol(data: bytes) -> bytes:
    return b"\r\n" if data.count(b"\r\n") * 2 >= max(1, data.count(b"\n")) else b"\n"


def _to_eol(data: bytes, eol: bytes) -> bytes:
    normalized = data.replace(b"\r\n", b"\n")
    return normalized.replace(b"\n", eol) if eol == b"\r\n" else normalized


def _norm(data: bytes | None) -> bytes | None:
    return data.replace(b"\r\n", b"\n") if data is not None else None


def _promoted_hashes() -> dict[str, set[str]]:
    """Content hashes each earlier promotion wrote, per path."""
    written: dict[str, set[str]] = {}
    for manifest in PROMOTIONS.glob("*/manifest.json"):
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8")).get("files", [])
        except (OSError, ValueError):
            continue
        for row in rows:
            if row.get("after"):
                written.setdefault(row["path"], set()).add(row["after"])
    return written


def plan() -> list[dict]:
    """Classify every change without writing anything.

    Comparisons ignore line endings (the sandbox repo stores LF; the main
    tree keeps CRLF on disk), and results keep the main file's line endings.
    """
    entries = []
    promoted = _promoted_hashes()
    for status, path in changed_paths():
        target = MAIN / path
        theirs_path = SANDBOX / path
        base = _base_bytes(path)
        ours = target.read_bytes() if target.is_file() else None
        if status == "D":
            if ours is None:
                action = "already-absent"
            elif base is not None and _norm(ours) == _norm(base):
                action = "delete"
            else:
                action = "conflict-delete-modified"
            entries.append({"path": path, "action": action})
            continue
        theirs = theirs_path.read_bytes()
        if ours is None:
            action = "add" if base is None else "conflict-deleted-in-main"
            entries.append({"path": path, "action": action, "result": theirs if action == "add" else None})
            continue
        if _norm(ours) == _norm(theirs):
            entries.append({"path": path, "action": "identical"})
            continue
        if base is not None and _norm(ours) == _norm(base):
            entries.append({"path": path, "action": "copy", "result": _to_eol(theirs, _eol(ours))})
            continue
        if _sha(ours) in promoted.get(path, set()):
            # Still exactly what an earlier promotion wrote: nobody edited it since.
            entries.append({"path": path, "action": "copy", "result": _to_eol(theirs, _eol(ours))})
            continue
        if False:
            entries.append({"path": path, "action": "identical"})
            continue
        if base is None:
            entries.append({"path": path, "action": "conflict-added-both"})
            continue
        eol = _eol(ours)
        with tempfile.TemporaryDirectory() as scratch:
            files = []
            for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
                file = Path(scratch) / name
                file.write_bytes(_to_eol(data, eol))
                files.append(str(file))
            merged = subprocess.run(["git", "merge-file", "-p", *files], capture_output=True, **_hidden())
        if merged.returncode == 0:
            entries.append({"path": path, "action": "merge", "result": merged.stdout})
        else:
            entries.append({"path": path, "action": "conflict", "conflicts": merged.returncode})
    return entries


def _sha(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def apply(write: bool) -> int:
    entries = plan()
    conflicts = [entry for entry in entries if entry["action"].startswith("conflict")]
    summary = {}
    for entry in entries:
        summary[entry["action"]] = summary.get(entry["action"], 0) + 1
    print(json.dumps({"files": len(entries), "actions": summary}, indent=1))
    for entry in conflicts:
        print(f"CONFLICT {entry['action']}: {entry['path']}")
    if conflicts:
        print("Nothing written: resolve the conflicts in the sandbox first.")
        return 2
    if not write:
        print("Dry run only. Re-run with --write to apply.")
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = PROMOTIONS / stamp
    backup = folder / "backup"
    manifest = {"stamp": stamp, "sandboxHead": _git("rev-parse", "HEAD").stdout.decode().strip(), "files": []}
    for entry in entries:
        path = entry["path"]
        target = MAIN / path
        before = target.read_bytes() if target.is_file() else None
        if entry["action"] in {"identical", "already-absent"}:
            continue
        if before is not None:
            saved = backup / path
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(before)
        if entry["action"] == "delete":
            target.unlink()
            after = None
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.nx-promote")
            temporary.write_bytes(entry["result"])
            os.replace(temporary, target)
            after = entry["result"]
        manifest["files"].append({"path": path, "action": entry["action"], "before": _sha(before), "after": _sha(after), "existed": before is not None})
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Applied {len(manifest['files'])} files. Rollback: python scripts/nx_promote.py rollback {stamp}")
    return 0


def rollback(stamp: str) -> int:
    folder = PROMOTIONS / stamp
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    changed_since = []
    for row in manifest["files"]:
        target = MAIN / row["path"]
        current = target.read_bytes() if target.is_file() else None
        if _sha(current) != row["after"]:
            changed_since.append(row["path"])
    if changed_since:
        print("These files changed after promotion; not rolling back to avoid losing that work:")
        for path in changed_since:
            print(f"  {path}")
        return 2
    for row in manifest["files"]:
        target = MAIN / row["path"]
        if row["existed"]:
            shutil.copy2(folder / "backup" / row["path"], target)
        elif target.exists():
            target.unlink()
    print(f"Rolled back {len(manifest['files'])} files from promotion {stamp}.")
    return 0


# ---------------------------------------------------------------- gate

GATE_DIR = SANDBOX / ".sandbox-scratch" / "gate"


GATE_WORKERS = max(2, min(8, (os.cpu_count() or 4) // 2))
NEW_TEST_FILE_SECONDS = 5.0


def _junit_cases(files: list[Path]):
    """(key, seconds, failed) for every test case in these junit reports."""
    import xml.etree.ElementTree as ET
    for file in files:
        if file.is_file():
            for case in ET.parse(file).getroot().iter("testcase"):
                failed = case.find("failure") is not None or case.find("error") is not None
                yield f"{case.get('classname')}::{case.get('name')}", float(case.get("time") or 0), failed


def _python_failures(junit: Path | list[Path]) -> tuple[int, set[str]]:
    cases = list(_junit_cases(junit if isinstance(junit, list) else [junit]))
    return len(cases), {key for key, _, failed in cases if failed}


def _node_failures(tap: Path) -> tuple[int, set[str]]:
    total, failed = 0, set()
    for line in tap.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text.startswith("ok ") or text.startswith("not ok "):
            total += 1
            if text.startswith("not ok "):
                failed.add(text.split(" - ", 1)[-1].strip())
    return total, failed


def _baseline_junit() -> list[Path]:
    return sorted(GATE_DIR.glob("baseline-py*.xml"))


def _durations() -> dict[str, float]:
    """Measured seconds per test: the last recorded runs, seeded from every junit report on hand."""
    store = GATE_DIR / "durations.json"
    if store.is_file():
        return json.loads(store.read_text(encoding="utf-8"))
    return {key: seconds for key, seconds, _ in _junit_cases(sorted(GATE_DIR.glob("*-py*.xml")))}


def _gate_plan(tree: Path, workers: int, skip: set[str]) -> tuple[dict, list[list[str]]]:
    """Give each test to one worker so all workers finish together (longest tests placed first).

    Tests are split one by one, not by file: three test files hold two thirds of the
    suite's time, so a split by file leaves one worker running long after the others.
    """
    files = sorted(path.relative_to(tree).as_posix() for path in (tree / "tests").glob("test_*.py"))
    modules = {name[:-3].replace("/", "."): name for name in files}

    def file_of(key: str) -> str | None:
        parts = key.split("::", 1)[0].split(".")
        for end in range(len(parts), 0, -1):
            if ".".join(parts[:end]) in modules:
                return modules[".".join(parts[:end])]
        return None

    known = [(seconds, key, file_of(key)) for key, seconds in _durations().items() if key not in skip]
    known = [row for row in known if row[2]]
    timed_files = {name for _, _, name in known}
    work = known + [(NEW_TEST_FILE_SECONDS, "", name) for name in files if name not in timed_files]
    loads = [0.0] * workers
    assign: dict[str, int] = {}
    owners: dict[str, int] = {}
    worker_files: list[set[str]] = [set() for _ in range(workers)]
    for seconds, key, name in sorted(work, reverse=True):
        worker = loads.index(min(loads))
        loads[worker] += seconds
        if key:
            assign[key] = worker
        owners.setdefault(name, worker)  # the owner also runs the file's tests no report has timed yet
        worker_files[worker].add(name)
    plan = {"assign": assign, "owners": owners, "skip": sorted(skip), "estimatedSeconds": [round(x) for x in loads]}
    return plan, [sorted(names) for names in worker_files]


def run_gate(tree: Path, label: str, workers: int = GATE_WORKERS) -> dict:
    """Run both test suites and a production build in `tree` at once; compare with the baseline.

    Tests the baseline already fails are not run: they cannot change the verdict.
    """
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    python = str(MAIN / ".venv" / "Scripts" / "python.exe")
    plugin_dir = GATE_DIR / "plugin"
    plugin_dir.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("nx_gate_shard.py"), plugin_dir / "nx_gate_shard.py")
    base_py = _python_failures(_baseline_junit())[1]
    plan, worker_files = _gate_plan(tree, workers, base_py)
    plan_path = GATE_DIR / f"{label}-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    for old in GATE_DIR.glob(f"{label}-py*.xml"):
        old.unlink()
    junit = [GATE_DIR / f"{label}-py-{index}.xml" for index in range(workers)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tree / "src"), str(plugin_dir)]),
           "PYTHONDONTWRITEBYTECODE": "1", "NX_GATE_PLAN": str(plan_path)}
    procs = [subprocess.Popen([python, "-m", "pytest", *names, "-q", "-p", "no:cacheprovider", "-p", "nx_gate_shard",
                               "-o", "faulthandler_timeout=600", f"--junitxml={junit[index]}"],
                              cwd=tree, env={**env, "NX_GATE_WORKER": str(index)}, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, **_hidden())
             for index, names in enumerate(worker_files) if names]
    # The node tests and the production build run alongside: they need little of what pytest uses.
    tap = GATE_DIR / f"{label}-node.tap"
    build_log = GATE_DIR / f"{label}-build.log"
    tests = sorted(str(path.relative_to(tree)) for path in (tree / "tests").glob("*.mjs"))
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    with tap.open("wb") as tap_out, build_log.open("wb") as build_out:
        node = subprocess.Popen(["node", "--test", "--test-reporter=tap", *tests], cwd=tree, stdout=tap_out,
                                stderr=subprocess.STDOUT, **_hidden())
        build = subprocess.Popen([npx, "vite", "build", "--config", "vite.config.mjs", "--outDir", str(GATE_DIR / f"{label}-dist"),
                                  "--emptyOutDir"], cwd=tree, stdout=build_out, stderr=subprocess.STDOUT, **_hidden())
        for proc in (*procs, node, build):
            proc.wait()
    ran = list(_junit_cases(junit))
    durations = _durations()
    durations.update({key: seconds for key, seconds, _ in ran})
    (GATE_DIR / "durations.json").write_text(json.dumps(durations, indent=0, sort_keys=True), encoding="utf-8")
    py_total, py_failed = len(ran), {key for key, _, failed in ran if failed}
    if not py_total:
        py_failed = {"<pytest did not run>"}
    node_total, node_failed = _node_failures(tap)
    base_node = _node_failures(GATE_DIR / "baseline-node.tap")[1] if (GATE_DIR / "baseline-node.tap").is_file() else set()
    build_text = build_log.read_text(encoding="utf-8", errors="replace")
    report = {
        "tree": str(tree),
        "seconds": round(time.monotonic() - started),
        "python": {"total": py_total, "failed": len(py_failed), "newFailures": sorted(py_failed - base_py),
                   "notRunBaselineFailures": len(base_py)},
        "node": {"total": node_total, "failed": len(node_failed), "newFailures": sorted(node_failed - base_node), "fixed": sorted(base_node - node_failed)},
        "build": {"ok": build.returncode == 0, "tail": build_text[-1500:] if build.returncode else ""},
    }
    report["passed"] = bool(py_total) and not report["python"]["newFailures"] and not report["node"]["newFailures"] and report["build"]["ok"]
    (GATE_DIR / f"{label}-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


# ---------------------------------------------------------------- releases

RELEASES = MAIN / ".agent_control" / "releases"
SUPERVISOR_STATE = Path(os.environ.get("LOCALAPPDATA", "")) / "Neyvia" / "controller-supervisor"
SUPERVISOR_TASK = "Neyvia Remote Controller Backend"


def build_release(source: Path = MAIN, releases: Path = RELEASES) -> Path:
    """Freeze the backend and a fresh web build into releases/<stamp>/."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = releases / stamp
    backend = folder / "backend"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(source / "src", backend / "src", ignore=ignore)
    shutil.copytree(source / "config", backend / "config", ignore=ignore)
    # The model reads the manuals at run time, and Claude Code loads Neyvia's plugin from here.
    for extra in ("manuals", "docs/manuals", "plugins", ".claude-plugin", "modules", "packages", "apps", "templates", "tools"):
        if (source / extra).is_dir():
            shutil.copytree(source / extra, backend / extra, ignore=ignore)
    (backend / "scripts").mkdir(parents=True)
    shutil.copy2(source / "scripts" / "run_web_backend.py", backend / "scripts" / "run_web_backend.py")
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    build = subprocess.run(
        [npx, "vite", "build", "--config", "vite.config.mjs", "--outDir", str(folder / "web-release"), "--emptyOutDir"],
        cwd=source, capture_output=True, text=True, encoding="utf-8", errors="replace", **_hidden(),
    )
    if build.returncode != 0:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError(f"Web build failed:\n{build.stdout[-3000:]}\n{build.stderr[-3000:]}")
    manifest = {
        "stamp": stamp,
        "entry": str(backend / "scripts" / "run_web_backend.py"),
        "staticRoot": str(folder / "web-release"),
        "source": str(source),
    }
    (folder / "release.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Built release {stamp} at {folder}")
    return folder


def _port_owner(port: int) -> int | None:
    import psutil
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status == psutil.CONN_LISTEN and connection.laddr and connection.laddr.port == port:
            return connection.pid
    return None


def _command_line(pid: int) -> str:
    import psutil
    try:
        return " ".join(psutil.Process(pid).cmdline())
    except (psutil.Error, OSError):
        return ""


def _healthy(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            return 200 <= response.status < 300
    except OSError:
        return False


def _smoke(port: int) -> list[str]:
    """Checks a freshly served release must pass before it is kept."""
    import urllib.request
    failures = []
    for path in ("/health", "/", "/api/auth/status"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as response:
                if not 200 <= response.status < 300:
                    failures.append(f"{path} -> HTTP {response.status}")
        except OSError as exc:
            failures.append(f"{path} -> {exc}")
    return failures


def _stop(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, **hidden_windows_subprocess_kwargs())


def _wait_for(port: int, marker: str, timeout: float) -> int | None:
    """Wait until the port is healthy and served by a process whose command line contains marker."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = _port_owner(port)
        if pid and marker in _command_line(pid) and _healthy(port):
            return pid
        time.sleep(1)
    return None


def serve(folder: Path, *, port: int = 47881, state_dir: Path = SUPERVISOR_STATE, timeout: float = 420) -> int:
    """Point the supervisor at a release and swap the served process, rolling back on failure.

    The supervisor restarts whatever release.json names a few seconds after the
    served process exits; clients see a short reconnect, never a lost chat.
    """
    manifest = json.loads((folder / "release.json").read_text(encoding="utf-8"))
    pointer = state_dir / "release.json"
    previous = pointer.read_bytes() if pointer.is_file() else None
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_name("release.json.tmp")
    temporary.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    os.replace(temporary, pointer)
    old = _port_owner(port)
    if old:
        _stop(old)
    marker = manifest["stamp"]
    pid = _wait_for(port, marker, timeout)
    failures = _smoke(port) if pid else [f"release {marker} did not come up healthy within {int(timeout)}s"]
    if not failures:
        print(f"Serving release {marker} on port {port} (pid {pid}).")
        return 0
    print("Release failed its checks; rolling back:")
    for failure in failures:
        print(f"  {failure}")
    if previous is None:
        pointer.unlink(missing_ok=True)
    else:
        pointer.write_bytes(previous)
    bad = _port_owner(port)
    if bad:
        _stop(bad)
    prior = json.loads(previous)["stamp"] if previous else "run_web_backend.py"
    restored = _wait_for(port, prior, timeout)
    print(f"Rolled back to {prior}: {'healthy' if restored else 'NOT healthy, check the supervisor log'}.")
    return 3


def restart_supervisor() -> None:
    """Reload the supervisor script (needed once, when it gains release support)."""
    for action in ("/End", "/Run"):
        subprocess.run(["schtasks", action, "/TN", SUPERVISOR_TASK], capture_output=True, check=action == "/Run", **_hidden())
        time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--write", action="store_true")
    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("stamp")
    sub.add_parser("release")
    gate_parser = sub.add_parser("gate")
    gate_parser.add_argument("--tree", choices=["sandbox", "main"], default="sandbox")
    gate_parser.add_argument("--workers", type=int, default=GATE_WORKERS)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("release_dir")
    serve_parser.add_argument("--port", type=int, default=47881)
    serve_parser.add_argument("--state-dir", default=str(SUPERVISOR_STATE))
    serve_parser.add_argument("--restart-supervisor", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "gate":
        report = run_gate(SANDBOX if args.tree == "sandbox" else MAIN, args.tree, args.workers)
        print(json.dumps(report, indent=1))
        return 0 if report["passed"] else 4
    if args.command == "release":
        build_release()
        return 0
    if args.command == "serve":
        if args.restart_supervisor:
            restart_supervisor()
        return serve(Path(args.release_dir), port=args.port, state_dir=Path(args.state_dir))
    if args.command == "status":
        for entry in plan():
            print(f"{entry['action']:<24} {entry['path']}")
        return 0
    if args.command == "apply":
        return apply(args.write)
    return rollback(args.stamp)


if __name__ == "__main__":
    sys.exit(main())
