"""Run a pinned scratch Neyvia against this candidate, with a strict release gate.

Exit 0 means complete coverage; exit 2 means a valid blocked release report.
Missing journey bindings never become successful backend-only substitutions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_inception import inventory, aggregate, validate_bindings, source_files
from c8_scope import assigned_ports, run_root

ENV = {"NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0",
       "FLUXIO_WATCHDOG_AUTOSTART": "0", "FLUXIO_RUNTIME_AUTO_UPDATE": "0",
       "PYTHONDONTWRITEBYTECODE": "1", "NEYVIA_PROOF_CREDENTIAL_GUARD": "1"}
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True, **HIDDEN).strip()


def port(value):
    value = int(value)
    if value not in assigned_ports():
        raise argparse.ArgumentTypeError("C8 port must be explicitly declared in NEYVIA_C8_PORTS")
    return value


def journey_port(value):
    journey, chosen = value.split("=", 1)
    if journey not in {"notes", "settings"}:
        raise argparse.ArgumentTypeError("Unknown authored journey")
    return journey, port(chosen)


def confined(path):
    path = Path(path).resolve()
    if not path.is_relative_to(REPO / ".agent_control") and not path.is_relative_to(run_root(REPO)):
        raise ValueError("Scratch state must stay inside the explicitly owned C8 run root")
    return path


def pin_source(commit, directory):
    directory.mkdir(parents=True, exist_ok=False)
    archive = directory.parent / "stable-source.tar"
    selected = ["src", "manuals", "config/neyvia_manuals.json", "config/neyvia_apps.json",
                "tools/cua-driver-win", "scripts/run_web_backend.py", "scripts/install_cua_driver.py"]
    for name in ("scripts/build_fixcl_manual_cache.py", "config/fixcl_manual_cache.json"):
        if subprocess.run(["git", "cat-file", "-e", commit + ":" + name], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN).returncode == 0:
            selected.append(name)
    subprocess.run(["git", "archive", "--format=tar", "--output=" + str(archive), commit, *selected],
                   cwd=REPO, check=True, **HIDDEN)
    with tarfile.open(archive) as package:
        package.extractall(directory, filter="data")
    # Git archive applies this Windows checkout's text attributes. Restore
    # canonical blobs so the tester's source bytes are exactly the pinned Git
    # objects, rather than accepting a normalized comparison as proof.
    entries = subprocess.check_output(["git", "ls-tree", "-rz", commit, "--", *selected], cwd=REPO, **HIDDEN)
    objects = []
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, identity = header.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("Pinned source must contain regular public files only")
        objects.append((identity, name.decode("utf-8")))
    blobs = subprocess.run(["git", "cat-file", "--batch"], cwd=REPO,
                           input=b"".join(identity + b"\n" for identity, _ in objects),
                           capture_output=True, check=True, **HIDDEN).stdout
    offset = 0
    for identity, name in objects:
        end = blobs.index(b"\n", offset)
        found, kind, size = blobs[offset:end].split()
        if found != identity or kind != b"blob":
            raise RuntimeError("Git returned an unexpected pin object")
        size = int(size)
        payload = blobs[end + 1:end + 1 + size]
        target = (directory / name).resolve()
        target.relative_to(directory.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        offset = end + 2 + size
    files = ["src/grant_agent/cua_upstream.py", "src/grant_agent/cua_native.py",
             "src/grant_agent/perception_browser.py", "src/grant_agent/neyvia_perception.py"]
    hashes = {}
    for name in files:
        actual = (directory / name).read_bytes()
        expected = subprocess.check_output(["git", "cat-file", "blob", commit + ":" + name], cwd=REPO, **HIDDEN)
        if actual != expected:
            raise RuntimeError("Pinned source differs from Git: " + name)
        hashes[name] = hashlib.sha256(actual).hexdigest()
    cache = directory / 'scripts/build_fixcl_manual_cache.py'
    cache_report = None
    if cache.is_file():
        # Canonical Git blobs have LF bytes. Rebuild only their derived admission
        # manifest so Windows checkout hashes cannot invalidate the pinned code.
        with (directory.parent / 'stable-cache.log').open('wb') as log:
            subprocess.run([sys.executable, '-B', str(cache)], cwd=directory,
                           env={**os.environ, **ENV, 'PYTHONPATH': str(directory / 'src')}, stdout=log, stderr=log, check=True, timeout=300, **HIDDEN)
        cache_report = {'compilerSha256': hashlib.sha256(cache.read_bytes()).hexdigest(),
                        'manifestSha256': hashlib.sha256((directory / 'config/fixcl_manual_cache.json').read_bytes()).hexdigest(),
                        'boundary': 'Derived admission cache rebuilt from canonical pinned source; runtime code remains exact Git blobs'}
    return {"commit": commit, "source": str(directory), "verifiedSourceHashes": hashes, "derivedCache": cache_report,
            "driver": "not launched: headless until isolated C11 is ready", "canonicalGitBlobCount": len(objects)}


def launch(source, state, static, chosen_port, logs):
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", chosen_port)) == 0:
            raise RuntimeError(f"Port {chosen_port} occupied; refusing to attach or stop its owner")
    handle = logs.open("wb")
    process = subprocess.Popen([sys.executable, "-B", str(REPO / "scripts/c8_backend.py"), "--source", str(source),
                                "--port", str(chosen_port), "--root", str(state), "--static-root", str(static)],
                               cwd=source, env={**os.environ, **ENV}, stdout=handle, stderr=handle, **HIDDEN)
    url = f"http://127.0.0.1:{chosen_port}"
    deadline = time.monotonic() + 55
    try:
        while process.poll() is None and time.monotonic() < deadline:
            try:
                with urlopen(url + "/api/health", timeout=1) as response:
                    if json.load(response).get("ok") is True:
                        return process, handle, url
            except OSError:
                pass
            time.sleep(.15)
        raise RuntimeError("Owned backend failed to become healthy; inspect " + str(logs))
    except Exception:
        stop(process)
        handle.close()
        raise


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            # The still-owned Popen PID identifies this tree, never a process
            # name or a port owner discovered elsewhere on the computer.
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def worker(journey, binding, stable, candidate_url, state, run_id, evidence, session_cookies, engine_executable, engine_port):
    # Every contract keeps its own replay and log, even when several bindings
    # share the same manual executor. Later runs must not overwrite receipts.
    output = evidence / journey / hashlib.sha256(binding['id'].encode()).hexdigest()[:16]
    output.mkdir(parents=True, exist_ok=True)
    with (output / "worker.log").open("wb") as log:
        journey_env = {**os.environ, **ENV, "NEYVIA_C8_ENGINE": "obscura",
                       "NEYVIA_OBSCURA_EXE": str(engine_executable),
                       "NEYVIA_C8_ENGINE_PORT": str(engine_port)}
        process = subprocess.Popen([sys.executable, "-B", str(REPO / "scripts/c8_journey.py"),
                                    "--stable-source", str(stable), "--candidate-url", candidate_url,
                                    "--run-id", run_id, "--journey", journey, "--candidate-state", str(state),
                                    "--output", str(output), "--session-input"],
                                   cwd=REPO, env=journey_env, stdin=subprocess.PIPE, stdout=log, stderr=log, **HIDDEN)
        try:
            process.communicate(json.dumps({"cookies": session_cookies, "binding": binding}).encode("utf-8"), timeout=420)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            stop(process)
            return {"id": binding["id"], "sourceHash": binding["sourceHash"], "status": "blocked", "error": "Journey exceeded 420-second budget"}
    result_path = output / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {"status": "blocked", "error": "Worker exited without a receipt"}
    return {**result, "id": binding["id"], "sourceHash": binding["sourceHash"], "exitCode": exit_code,
            "binding": binding, "candidateState": str(state), "workerReceipt": str(result_path)}


def execute_bindings(bindings, catalog, stable, scratch, build, assigned, run_id, evidence, engine, engine_port):
    """Give every admitted binding fresh backend state, fixtures and cookies."""
    from c8_journey import Candidate, prepare_manual_binding, UnsupportedRoute
    rows = {row['id']: row for row in catalog['rows']}
    results, targets = [], {}
    for key, authored in bindings.items():
        binding = {'id': key, **authored, 'contracts': rows[key]['checkContracts']}
        if binding['journey'] == 'manual':
            try:
                # Admission is a source-only operation; blocked authority never
                # launches a product, creates a fixture or contacts a provider.
                prepare_manual_binding(binding, REPO, catalog['rows'])
            except UnsupportedRoute as error:
                results.append({'id': key, 'sourceHash': binding['sourceHash'], 'status': 'blocked',
                                'coverageGap': 'unsupported-or-unauthorized-route', 'error': str(error)})
                continue
        identity = hashlib.sha256(key.encode()).hexdigest()[:16]
        state = scratch / 'binding-state' / identity
        process, handle, url = launch(REPO, state, build, assigned[binding['journey']], evidence / (identity + '-backend.log'))
        targets[key] = url
        try:
            candidate = Candidate(url)
            results.append(worker(binding['journey'], binding, stable, url, state, run_id, evidence,
                                  candidate.cookies(), engine, engine_port))
        finally:
            stop(process)
            handle.close()
    return results, targets


def run(args):
    if args.stable_port == args.candidate_port:
        raise ValueError("Stable and candidate require separate explicit ports")
    build = Path(args.build_dir).resolve()
    args.output = Path(args.output).resolve()
    if not args.output.is_relative_to(REPO / "scripts/evidence") and not args.output.is_relative_to(run_root(REPO)):
        raise ValueError("C8 receipts must stay inside the worktree or declared run root")
    if not (build / "index.html").is_file():
        raise ValueError("Build directory must contain index.html")
    commit = git("rev-parse", "--verify", args.stable_ref + "^{commit}")
    candidate_commit = git("rev-parse", "HEAD")
    run_id = uuid.uuid4().hex
    scratch = confined(run_root(REPO) / run_id)
    evidence = scratch / "evidence"
    evidence.mkdir(parents=True)
    print(json.dumps({"runId": run_id, "executionMode": "headless", "evidence": str(evidence)}), flush=True)
    stable = scratch / "stable"
    catalog = inventory()
    bindings = json.loads((REPO / "config/inception_journeys.json").read_text(encoding="utf-8"))
    validation = validate_bindings(catalog, bindings)
    if not validation["valid"]:
        provenance = {"runId": run_id, "stableCommit": commit, "candidateCommit": candidate_commit,
                      "candidateUrl": f"http://127.0.0.1:{args.candidate_port}", "executionMode": "headless",
                      "runErrors": validation["errors"], "candidateSourceHashes": {
                          name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in source_files()}}
        report = {**aggregate(catalog, [], provenance), "bootstrapFailed": True,
                  "preflight": {"bindings": validation, "journeysExecuted": 0,
                                "stableSourcePinned": False, "desktopGuardStarted": False}}
        write(evidence / "report.json", report)
        write(args.output, report)
        print(json.dumps({"releaseGate": False, "preflightFailed": True,
                          "invalidBindings": len(validation["errors"]), "receipt": str(args.output)}), flush=True)
        return 2
    engine_executable = Path(args.obscura_exe).resolve() if args.obscura_exe else None
    recovery_root = Path("D:/NeyviaRuns/INTN/obscura-recovery").resolve()
    engine_error = None
    if not engine_executable or not engine_executable.is_file():
        engine_error = "C8 user journeys require the recovered, admitted Obscura executable; Chromium fallback is disabled"
    elif not engine_executable.is_relative_to(recovery_root):
        engine_error = "C8 accepts only the task's recovered Obscura build under D:/NeyviaRuns/INTN/obscura-recovery"
    if engine_error:
        reason = engine_error
        provenance = {"runId": run_id, "stableCommit": commit, "candidateCommit": candidate_commit,
                      "executionMode": "headless", "runErrors": [reason],
                      "candidateSourceHashes": {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                                                 for name in source_files()}}
        report = {**aggregate(catalog, [], provenance), "bootstrapFailed": True,
                  "preflight": {"bindings": validation, "journeysExecuted": 0,
                                "stableSourcePinned": False, "desktopGuardStarted": False,
                                "obscuraExecutable": None, "chromiumFallback": False}}
        write(evidence / "report.json", report)
        write(args.output, report)
        print(json.dumps({"releaseGate": False, "preflightFailed": True,
                          "invalidBindings": len(validation["errors"]),
                          "unboundBindings": len(validation["unbound"]),
                          "receipt": str(args.output)}), flush=True)
        return 2
    if args.workers != 1:
        raise ValueError("C8 Obscura CDP transport currently requires one journey worker so its assigned port is never shared")
    pin = pin_source(commit, stable)
    overrides = dict(args.journey_port)
    assigned = {binding["journey"]: overrides.get(binding["journey"], args.candidate_port) for binding in bindings.values()}
    if args.stable_port in assigned.values() or (args.workers > 1 and len(set(assigned.values())) != len(assigned)):
        raise ValueError("Parallel journeys require distinct explicit --journey-port values and separate candidate state")
    reserved = {int(p) for p in os.environ.get("NEYVIA_C8_RESERVED_PORTS", "").split(",") if p}
    reserved.update({args.stable_port, args.candidate_port, *assigned.values()})
    os.environ["NEYVIA_C8_RESERVED_PORTS"] = ",".join(map(str, sorted(reserved)))
    running, handles, results = [], [], []
    from c8_desktop_guard import DesktopGuard
    desktop = DesktopGuard()
    desktop.start()
    started = time.time()
    report = None
    try:
        proc, log, stable_url = launch(stable, stable / ".agent_control/proofs/state", scratch / "stable-static", args.stable_port, evidence / "stable.log")
        running.append(proc); handles.append(log)
        proc, log, candidate_url = launch(REPO, scratch / "candidate", build, args.candidate_port, evidence / "candidate.log")
        running.append(proc); handles.append(log)
        from c8_scope import fixture_port
        engine_port = fixture_port()
        from c8_journey import Candidate
        candidate_client = Candidate(candidate_url)
        # Keep the independent negative-goal probe alive only on the stable
        # probe root. Reuse its port sequentially for isolated binding roots.
        stop(proc)
        log.close()
        binding_results, targets = execute_bindings(bindings, catalog, stable, scratch, build, assigned,
                                                    run_id, evidence, engine_executable, engine_port)
        results.extend(binding_results)
        proc, log, candidate_url = launch(REPO, scratch / "candidate", build, args.candidate_port, evidence / "candidate-final.log")
        running.append(proc); handles.append(log)
        candidate_client = Candidate(candidate_url)
        for row in catalog["rows"]:
            if row["id"] not in bindings:
                results.append({"id": row["id"], "sourceHash": row["sourceHash"], "status": "blocked",
                                "coverageGap": "no-binding", "error": "No source-bound user journey and disposable fixture authored", "requires": {"inputs": row.get("inputs"), "judges": row.get("judges")}})
        provenance = {"runId": run_id, "stableCommit": commit, "candidateCommit": candidate_commit,
                      "candidateUrl": candidate_url, "stable": {**pin, "url": stable_url},
                      "journeyTargets": targets,
                      "candidateStateIsolation": "Fresh disposable backend state and authenticated session per binding; one sequential Obscura worker",
                      "candidate": {"commit": candidate_commit, "url": candidate_url, "build": str(build),
                                    "buildIndexSHA256": hashlib.sha256((build / "index.html").read_bytes()).hexdigest(),
                                    "buildHashes": {str(p.relative_to(build)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in sorted(build.rglob("*")) if p.is_file()},
                                    "dirtySource": git("status", "--short")},
                      "workers": args.workers, "startedAt": started, "finishedAt": time.time(),
                      "authority": "Task-owned scratch only; empty connected-harness scope; no credentials, NAS, live service, external providers or downloads",
                      "executionMode": "headless", "driverRoute": "Pinned T18 DOM observer and revision-guarded browser actions over the recovered Obscura CDP engine",
                      "obscura": {"executable": str(engine_executable), "sha256": hashlib.sha256(engine_executable.read_bytes()).hexdigest(), "port": engine_port}}
        provenance["socketBoundary"] = {"ports": sorted(assigned_ports()), "requests": "candidate origin only", "engine": "obscura"}
        provenance["candidateSourceHashes"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                                               for name in source_files()}
        report = aggregate(catalog, results, provenance)
        state_root = confined(args.state_root) if args.state_root else scratch / "candidate"
        # The negative probe reads actual candidate state again and applies a
        # deliberately wrong expectation through the production verifier.
        from grant_agent.neyvia_manuals import expect
        actual = candidate_client.tool("settings.get")
        negative_check = {"path": "network.enforced", "op": "eq", "value": False}
        negative_passed = expect(actual, negative_check, {}, {}, scratch / "candidate")
        negative_proof = evidence / "negative-goal.json"
        write(negative_proof, {"source": "fresh candidate settings.get", "target": candidate_url,
                               "expected": negative_check, "observed": actual["network"], "passed": negative_passed})
        report["failurePaths"] = {"wrongGoal": {"proof": str(negative_proof), "sha256": hashlib.sha256(negative_proof.read_bytes()).hexdigest(),
                                                "refused": not negative_passed}}
        write(evidence / "report.json", report)
        write(args.output, report)
        write(state_root / ".neyvia/inception/latest.json", {"results": results, "provenance": provenance})
        if state_root != scratch / "candidate":
            write(scratch / "candidate/.neyvia/inception/latest.json", {"results": results, "provenance": provenance})
        executed = [r for r in results if r.get("checks")]
        negative = json.loads(json.dumps(executed))
        if negative:
            negative[0]["checks"][0]["passed"] = negative_passed
        selected = {r["id"] for r in executed}
        subset = {"rows": [r for r in catalog["rows"] if r["id"] in selected]}
        control_report = aggregate(subset, executed, provenance)
        negative_report = aggregate(subset, negative, provenance)
        failure_paths = {"controlWebGate": control_report["webCoverageGate"],
                         "negativeWebGate": negative_report["webCoverageGate"],
                         "exercised": bool(executed),
                         "failedCheckRejected": control_report["webCoverageGate"] and not negative_report["webCoverageGate"],
                         "nativeReleaseGate": negative_report["releaseGate"],
                         "rows": negative_report["rows"]}
        write(evidence / "failed-check.json", failure_paths)
        report["failurePaths"]["failedCheck"] = {key: value for key, value in failure_paths.items() if key != "rows"}
        write(evidence / "report.json", report)
        write(args.output, report)
    except Exception as error:
        provenance = {"runId": run_id, "stableCommit": commit, "candidateCommit": candidate_commit,
                      "candidateUrl": f"http://127.0.0.1:{args.candidate_port}", "executionMode": "headless",
                      "startedAt": started, "finishedAt": time.time(), "stable": pin}
        provenance["runErrors"] = [str(error)]
        report = aggregate(catalog, results, provenance)
        report["errors"].append(str(error))
        report.update(releaseGate=False, webCoverageGate=False, bootstrapFailed=True)
    finally:
        for process in running:
            stop(process)
        for handle in handles:
            handle.close()
        guard = desktop.finish()
        if report is not None:
            provenance["desktopGuard"] = guard
            extra = {key: value for key, value in report.items() if key in {"failurePaths", "bootstrapFailed"}}
            report = {**aggregate(catalog, results, provenance), **extra}
            report["desktopGuard"] = guard
            if not guard["passed"]:
                report.update(releaseGate=False, webCoverageGate=False)
            write(evidence / "report.json", report)
            write(args.output, report)
            final_root = confined(args.state_root) if args.state_root else scratch / "candidate"
            write(final_root / ".neyvia/inception/latest.json", {"results": results, "provenance": provenance})
            ledger = {"schema": "neyvia.inception-result.v1", "id": "C8-" + run_id,
                      "study": "C8 pinned scratch Neyvia tests candidate", "evidence_status": "real-run",
                      "receipt": str(args.output.relative_to(REPO)) if args.output.is_relative_to(REPO) else str(args.output), "stableCommit": commit, "candidateCommit": candidate_commit,
                      "counts": report["counts"], "releaseGate": report["releaseGate"], "desktopGuardPassed": guard["passed"],
                      "parallel": {"workers": args.workers, "executed": [{k: r.get(k) for k in ("id", "startedAt", "finishedAt", "status")} for r in results if "startedAt" in r]}}
            with (REPO / "docs/research/results.jsonl").open("a", encoding="utf-8", newline="\n") as log:
                log.write(json.dumps(ledger, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"releaseGate": report["releaseGate"], "counts": report["counts"], "receipt": str(args.output),
                      "runId": run_id, "errors": report["errors"], "desktopGuardPassed": guard["passed"]}))
    return 0 if report and report["releaseGate"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-ref", required=True, help="Exact local Git commit/ref to pin; never fetches")
    parser.add_argument("--stable-port", type=port, required=True)
    parser.add_argument("--candidate-port", type=port, required=True)
    parser.add_argument("--journey-port", type=journey_port, action="append", default=[], help="Separate explicit candidate port from NEYVIA_C8_PORTS, e.g. settings=48873")
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--state-root", help="Task-local root for the inspectable report")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--obscura-exe", help="Recovered, admitted Obscura executable for the real journey transport")
    parser.add_argument("--output", default=str(REPO / "scripts/evidence/C8c.json"))
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
