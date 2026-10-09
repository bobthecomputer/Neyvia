"""Run existing Python files six at a time in disposable, guarded state on D:."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import hashlib
import json
import queue
import os
import site
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
OUT = Path(r"D:\NeyviaRuns\INTN\python")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="pre-seal")
    parser.add_argument("--file-timeout", type=int, default=1800)
    parser.add_argument("--test-timeout", type=int, default=300)
    parser.add_argument('--local-small-state', action='store_true', help='Use owned C fixtures and databases; all outcome logs and receipts remain on D')
    parser.add_argument("--out", default=str(OUT), help="Root for receipts and large outputs")
    parser.add_argument("--ports", default="48871-48889", help="Inclusive localhost port range assigned to fixtures")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--port-slots", type=int, default=0,
                        help="Split --ports into N disjoint slices, one per concurrent file (sets --workers N), so parallel files never race for a port")
    parser.add_argument("--exclusive", action="append", default=[],
                        help="Test file run alone after the parallel phase with the whole port range (repeatable)")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum():
        parser.error("Invalid label")
    low, high = (int(part) for part in args.ports.split("-"))
    if not 1024 <= low <= high <= 65535 or low <= 47881 <= high:
        parser.error("Invalid port range")
    ports = list(range(low, high + 1))
    if args.port_slots:
        if not 1 <= args.port_slots <= len(ports):
            parser.error("Invalid --port-slots")
        args.workers = args.port_slots
        size, extra = divmod(len(ports), args.port_slots)
        slots, start = [], 0
        for index in range(args.port_slots):
            end = start + size + (index < extra)
            slots.append(ports[start:end])
            start = end
    else:
        slots = [ports] * args.workers
    free_slots = queue.Queue()
    for slot in slots:
        free_slots.put(slot)
    run = Path(args.out) / args.label
    run.mkdir(parents=True, exist_ok=True)
    small_root = ROOT / '.agent_control/INTN/python-state' / args.label if args.local_small_state else run
    small_root.mkdir(parents=True, exist_ok=True)
    guard = run / "guard"
    guard.mkdir(exist_ok=True)
    tokenizer = run / "tokenizer-cache"
    tokenizer.mkdir(exist_ok=True)
    cache_name = hashlib.sha1(b"https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken").hexdigest()
    existing_cache = Path(os.environ.get("TEMP", "")) / "data-gym-cache" / cache_name
    if existing_cache.is_file():
        shutil.copyfile(existing_cache, tokenizer / cache_name)
    (guard / "sitecustomize.py").write_text("import int3_pytest_guard\nfrom grant_agent.subprocess_utils import install_hidden_subprocess_default\ninstall_hidden_subprocess_default()\n", encoding="utf-8")
    tests = args.files or [str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").rglob("test_*.py"))]
    start_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, creationflags=FLAGS).strip()
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "src").rglob("*.py")}
    rows = []
    started = time.time()

    def one(name, assigned=None):
        slot = assigned or free_slots.get()
        try:
            return run_file(name, slot)
        finally:
            if assigned is None:
                free_slots.put(slot)

    def run_file(name, slot):
        spec = f"{slot[0]}-{slot[-1]}"
        key = name.replace("\\", "_").replace("/", "_").removesuffix(".py")
        folder = run / key
        folder.mkdir(exist_ok=True)
        # Keep fixture paths below Windows MAX_PATH and prevent Git from
        # discovering the integration repository above a non-repository fixture.
        runtime = ROOT / '.agent_control/INTN/py' / hashlib.sha256((args.label + ':' + name).encode()).hexdigest()[:16] if args.local_small_state else small_root / key
        runtime.mkdir(parents=True, exist_ok=True)
        fixture = runtime / ".agent_control/int3/pytest-temp"
        fixture.mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in os.environ.items() if not any(token in key.upper() for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH_FILE"))}
        env.pop('XDG_CONFIG_HOME', None)
        env.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_MOBILE_PROBE_DEVICES='0', NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", FLUXIO_RUNTIME_AUTO_UPDATE="0",
                   GIT_CEILING_DIRECTORIES=str(runtime),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1", INT3_WORKSPACE_ROOT=str(runtime), INT3_LINE_COVERAGE="0", INT3_NO_BROWSER_LAUNCH="1",
                   INT3_ALLOWED_PORTS=json.dumps(slot), INT3_MAP_EPHEMERAL_BIND="1", INT3_TEST_DEADLINE=str(args.test_timeout),
                   NEYVIA_PROOF_SOCKETPAIR_PORTS=",".join(map(str, slot if args.port_slots else slot[-6:])),
                   NEYVIA_OBSCURA_PROOF_PORTS=spec, NEYVIA_BROWSER_PROOF_PORTS=spec,
                   TIKTOKEN_CACHE_DIR=str(tokenizer), INT3_GUARD_LOG=str(runtime / "guard.jsonl"), INT3_OUTCOME_LOG=str(runtime / "outcomes.json"), TEMP=str(fixture), TMP=str(fixture),
                   PYTHONPATH=os.pathsep.join((str(guard), str(ROOT / "scripts"), str(ROOT / "src"), site.getusersitepackages())))
        for key in ("HOME", "USERPROFILE", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "HERMES_HOME", "APPDATA", "LOCALAPPDATA"):
            home = runtime / "home" / key.lower()
            home.mkdir(parents=True, exist_ok=True)
            env[key] = str(home)
        log = folder / "pytest.log"
        command = [sys.executable, "-s", "-m", "pytest", "-p", "int3_pytest_guard", "-p", "no:cacheprovider", "-q", "-ra", "--tb=short", "--continue-on-collection-errors", "--basetemp", str(fixture / "pytest"), name]
        stamp = time.time()
        timed_out = False
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, creationflags=FLAGS)
            try:
                code = process.wait(timeout=args.file_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
                code = process.wait()
        if runtime != folder:
            for metadata in ('guard.jsonl','outcomes.json','outcomes.json.active.json','outcomes.json.coverage.json'):
                if (runtime / metadata).is_file():
                    shutil.copyfile(runtime / metadata, folder / metadata)
        outcome = folder / "outcomes.json"
        data = json.loads(outcome.read_text(encoding='utf-8')) if outcome.exists() else {}
        row = {"file": name, "exitCode": code, "timedOut": timed_out, "seconds": round(time.time() - stamp, 2), "receipt": str(log),
               "runtimeStateRoot":str(runtime), "ports": spec,
               "outcomes": str(outcome) if outcome.exists() else None, "collected": len(data.get("collected_ids", [])), "failed": data.get("failed_ids", [])}
        write(folder / "receipt.json", row)
        return row

    exclusive = {Path(name).as_posix() for name in args.exclusive}
    parallel = [name for name in tests if Path(name).as_posix() not in exclusive]
    alone = [name for name in tests if Path(name).as_posix() in exclusive]

    def finished(name, job):
        try:
            row = job.result()
        except Exception as exc:
            row = {'file': name, 'exitCode': 99, 'infrastructureError': str(exc), 'traceback': traceback.format_exc()}
            write(run / (name.replace('\\', '_').replace('/', '_') + '.error.json'), row)
        rows.append(row)
        write(run / "progress.json", {"totalFiles": len(tests), "finishedFiles": len(rows), "failedFiles": sum(row["exitCode"] != 0 for row in rows), "last": row})
        print(json.dumps({"finished": len(rows), "total": len(tests), "file": row["file"], "exitCode": row["exitCode"]}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(one, name): name for name in parallel}
        for job in as_completed(jobs):
            finished(jobs[job], job)
    # Files that need the whole range run one at a time after the parallel phase.
    with ThreadPoolExecutor(max_workers=1) as executor:
        for name in alone:
            finished(name, executor.submit(one, name, ports))
    changed = [name for name, digest in source_hashes.items() if not (ROOT / name).is_file() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    receipt = {"schema": "neyvia.intn.python-suite.v1", "label": args.label, "commit": start_commit, "started": started, "finished": time.time(), "workers": args.workers, "ports": args.ports,
               "portSlots": [f"{slot[0]}-{slot[-1]}" for slot in dict.fromkeys(map(tuple, slots))], "exclusiveFiles": sorted(exclusive),
               'runtimeStateRoot':str(small_root), 'largeOutputsRoot':str(run),
               "testTimeoutSeconds": args.test_timeout, "fileTimeoutSeconds": args.file_timeout,
               "totalFiles": len(tests), "finishedFiles": len(rows), "sourceChangedDuringRun": changed, "sourceHashes": source_hashes, "complete": len(rows) == len(tests),
               "ok": len(rows) == len(tests) and not changed and all(row["exitCode"] == 0 for row in rows), "rows": sorted(rows, key=lambda row: row["file"])}
    write(run / "receipt.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("complete", "ok", "totalFiles", "sourceChangedDuringRun")}), flush=True)
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
