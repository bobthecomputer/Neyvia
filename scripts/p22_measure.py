"""Run existing proof areas once and index passing execution-trace receipts.

This is the bounded measurement driver used by the coverage model. It never
turns a failed, timed-out, or untraced contract run into coverage evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# These procedures cannot run under the authorized measurement runtime. They
# remain visible as not available and never count as passing witnesses.
from grant_agent.contract_gate import RUNNER_LIMITS as NOT_AVAILABLE


def _inventory():
    from grant_agent.contract_gate import inventory
    from grant_agent.proof_verifier import ADAPTERS, RUNNERS

    contracts, manifests = inventory()
    areas = {}
    for area in sorted(ADAPTERS.keys() | RUNNERS.keys()):
        if area in {"build", "fast-ui"}:
            continue
        ids = sorted(identity for identity, row in contracts.items()
                     if area in row.get("areas", []))
        if ids:
            areas[area] = ids
    return areas, manifests


def _source_bindings(paths):
    bindings = {}
    for name in sorted(set(paths)):
        path = ROOT / name
        try:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            bindings[name] = digest.hexdigest()
        except OSError:
            bindings[name] = None
    return bindings


def _run_area(area, identities, unavailable, root, timeout, state_root, scope_path):
    if not identities:
        return {"area": area, "requestedContracts": [], "passedContracts": [],
                "notAvailableContracts": unavailable, "status": "not available",
                "ok": False, "reason": "No requested contracts can run in the authorized measurement runtime."}
    folder = root / area
    folder.mkdir(parents=True, exist_ok=False)
    area_state = state_root / area
    area_state.mkdir(parents=True, exist_ok=False)
    spec = folder / "job.json"
    spec.write_text(json.dumps({"area": area, "contracts": identities,
                                "measure": True, "stateRoot": str(area_state), "traceScope": str(scope_path)},
                               separators=(",", ":")), encoding="utf-8")
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "NEYVIA_TOOL_AUTO_UPDATE": "0",
                "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0",
                "NEYVIA_GATE_ASSIGNED_PORTS": "49081-49089",
                "NEYVIA_BROWSER_PROOF_PORTS": "49081-49089",
                'PYTHONDONTWRITEBYTECODE': '1',
                'TEMP': str(area_state/'temp'), 'TMP': str(area_state/'temp')})
    (area_state/'temp').mkdir(exist_ok=True)
    started = time.perf_counter()
    from grant_agent.contract_resources import capture_resource_bounded
    captured = capture_resource_bounded([sys.executable, str(ROOT / "scripts/gate.py"),
                                       "--worker", str(spec)], cwd=ROOT, env=env,
                                      input_text=None, timeout=timeout, logs_root=folder / 'process', acquire_slot=False)
    timed_out = captured["timedOut"]
    exit_code = captured["returncode"]
    stdout, stderr = captured["stdout"][-12000:], captured["stderr"][-12000:]
    elapsed = round((time.perf_counter() - started) * 1000)
    (folder / "driver.stdout.log").write_text(stdout, encoding="utf-8")
    (folder / "driver.stderr.log").write_text(stderr, encoding="utf-8")
    outcomes_path = folder / "outcomes.json"
    # The worker may put its receipt beside job.json or under its state root.
    # Accept both during the transition, preferring the stable public location.
    trace_candidates = (folder / "execution.json", folder / "state" / "execution.json")
    trace_path = next((path for path in trace_candidates if path.is_file()), trace_candidates[0])
    try:
        outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        outcomes = None
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        trace = None
    requested = set(identities)
    passed = set()
    if isinstance(outcomes, dict):
        for case in outcomes.get("cases", []):
            if isinstance(case, dict) and case.get("ok") is True:
                identity = case.get("id")
                if identity in requested:
                    passed.add(identity)
                passed.update(value for value in case.get("contracts", []) if value in requested)
        for row in outcomes.get("outcomes", []):
            if isinstance(row, dict) and row.get("status") in {"PASS", "passed"}:
                identity = row.get("id")
                if identity in requested:
                    passed.add(identity)
        for row in outcomes.get("contracts", []):
            if isinstance(row, str) and row in requested:
                passed.add(row)
            elif isinstance(row, dict) and row.get("status") == "passed" and row.get("id") in requested:
                passed.add(row["id"])
    trace_contracts = set(trace.get("contracts", [])) if isinstance(trace, dict) else set()
    positive = (not timed_out and not captured.get('memoryExceeded') and exit_code == 0 and isinstance(outcomes, dict)
                and outcomes.get("ok") is True and not requested - passed
                and isinstance(trace, dict) and trace.get("ok") is True
                and trace.get("sourceStable") is True
                and isinstance(trace.get("files"), dict)
                and requested == trace_contracts)
    row = {"area": area, "requestedContracts": sorted(requested),
           "passedContracts": sorted(requested & passed) if positive else [],
           "ok": bool(positive), "timedOut": timed_out, "exitCode": exit_code,
           "durationMs": elapsed, "outcomes": str(outcomes_path),
           "stateRoot": str(state_root / area),
           "execution": str(trace_path) if trace is not None else None,
           "processTreeStopped": captured.get("processTreeStopped"),
           "memoryExceeded": captured.get('memoryExceeded', False),
           "peakPrivateBytes": captured.get('peakPrivateBytes'),
           "notAvailableContracts": unavailable,
           "sourceStable": trace.get("sourceStable") if isinstance(trace, dict) else None}
    row["status"] = "passed" if positive and not unavailable else "partial" if positive else "failed"
    if not positive:
        row["reason"] = ("deadline exceeded" if timed_out else
                         "worker failed" if exit_code not in (0, None) else
                         "outcome or execution-trace receipt missing, failed, or incomplete")
    return row


def main(argv=None):
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/NeyviaRuns/P22/measurement"))
    parser.add_argument("--state-root", type=Path, default=Path('D:/NeyviaRuns/P22/state/measure'),
                        help="Disposable proof state under D:/NeyviaRuns/P22")
    parser.add_argument('--since', default=os.environ.get('NEYVIA_P22_TRACE_SINCE', 'd4ff0c717cbf437bef0d305eb95dc5aed5a0bdf3'))
    parser.add_argument("--coverage-map", type=Path,
                        help="Optional source-bound cache to update from passing area traces")
    parser.add_argument("--areas", nargs="+", help="Selected proof areas; defaults to all authored runnable areas")
    parser.add_argument("--workers", type=int, default=1,
                        help='Default leaves the second heavy slot for a traced backend/worker child')
    parser.add_argument("--job-timeout", type=float, default=55)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.job_timeout <= 0:
        parser.error("--workers and --job-timeout must be positive")
    if args.workers > 2: parser.error('At most two traced runs may execute concurrently')
    run_id = args.run_id or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        parser.error("--run-id must be a simple 1-64 character identifier")
    target = args.root.expanduser().resolve()
    allowed = Path("D:/NeyviaRuns").resolve()
    if not target.is_relative_to(allowed):
        parser.error("measurement receipts must stay under D:/NeyviaRuns")
    state_base = args.state_root.expanduser().resolve()
    state_allowed = Path('D:/NeyviaRuns/P22').resolve()
    if not state_base.is_relative_to(state_allowed):
        parser.error("measurement state must stay under D:/NeyviaRuns/P22")
    coverage_path = args.coverage_map.expanduser().resolve() if args.coverage_map else None
    if coverage_path is not None and not any(
            coverage_path.is_relative_to(parent.resolve())
            for parent in (Path("D:/NeyviaRuns"), ROOT / ".agent_control/p22")):
        parser.error("coverage map must stay under D:/NeyviaRuns or the repo's .agent_control/p22 directory")
    available, manifests = _inventory()
    requested = set(args.areas or available)
    unknown = sorted(requested - set(available))
    if unknown:
        parser.error("unknown or non-runnable proof area(s): " + ", ".join(unknown))
    run_root = target / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    state_run = state_base / run_root.name
    state_run.mkdir(parents=True, exist_ok=False)
    from grant_agent.contract_diff import trace_scope
    scope_path = run_root / 'trace-scope.json'
    scope_path.write_text(json.dumps(trace_scope(ROOT, args.since), separators=(',', ':')), encoding='utf-8')

    # Port-using proof areas hold one shared assigned-port lock inside the
    # existing worker. Keep those jobs serial so a queued worker cannot spend
    # its entire short deadline waiting for another area's ports.
    network = set()
    for area in requested:
        manifest = manifests.get(area, {})
        from grant_agent.proof_verifier import ADAPTERS, RUNNERS
        owner = ROOT / RUNNERS[area] if area in RUNNERS else ROOT / "src" / Path(*ADAPTERS[area].split(".")).with_suffix(".py")
        try:
            uses_assigned_ports = bool(re.search(r"\b(?:proof_port|proofPort)\(", owner.read_text(encoding="utf-8")))
        except OSError:
            uses_assigned_ports = False
        if uses_assigned_ports or (manifest.get("networkContracts") and set(available[area]) & set(manifest["networkContracts"])):
            network.add(area)
    parallel = sorted(requested - network)
    rows = []
    results_path = run_root / 'area-results.jsonl'
    def remember(row):
        with results_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
        rows.append(row)
    active_by_area, unavailable_by_area = {}, {}
    for area in requested:
        policies = NOT_AVAILABLE.get(area, {})
        unavailable = {identity: policies.get(identity, policies.get("*"))
                       for identity in available[area]
                       if identity in policies or "*" in policies}
        unavailable_by_area[area] = unavailable
        active_by_area[area] = sorted(set(available[area]) - unavailable.keys())
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_area, area, active_by_area[area], unavailable_by_area[area],
                               run_root, args.job_timeout, state_run, scope_path): area for area in parallel}
        for future in as_completed(futures):
            try:
                remember(future.result())
            except Exception as error:
                remember({"area": futures[future], "ok": False, "status": "failed",
                             "requestedContracts": active_by_area[futures[future]],
                             "passedContracts": [],
                             "reason": type(error).__name__ + ": " + str(error)[:500]})
    for area in sorted(network):
        try:
            remember(_run_area(area, active_by_area[area], unavailable_by_area[area],
                                  run_root, args.job_timeout, state_run, scope_path))
        except Exception as error:
            remember({"area": area, "ok": False, "status": "failed",
                         "requestedContracts": active_by_area[area], "passedContracts": [],
                         "reason": type(error).__name__ + ": " + str(error)[:500]})
    rows.sort(key=lambda row: row["area"])
    positive = [row for row in rows if row.get("ok") is True]
    coverage = {}
    input_bindings = {}
    for row in positive:
        trace_path = Path(row["execution"])
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        # Store only source rows reported by the tracer. Its line list comes
        # from executed Python source; lineData=false explicitly means that
        # only file execution, not changed-line coverage, was measured.
        for name, source in trace["files"].items():
            if isinstance(source, dict) and name:
                if source.get('kind') == 'configuration-read':
                    input_bindings.setdefault(name, []).append({'area': row['area'], 'sha256': source.get('sha256'),
                                                               'kind': 'configuration-read', 'receipt': str(trace_path)})
                    continue
                coverage.setdefault(name, []).append({
                    "area": row["area"], "contracts": row["passedContracts"],
                    "executedLineCount": len(source.get("lines", [])),
                    "linesReceipt": str(trace_path),
                    "lineData": source.get("lineData") is True,
                    "sha256": source.get("sha256")})
    report = {"schema": "neyvia.execution-measurement.v1",
              "runId": run_root.name, "areasRequested": sorted(requested),
              "stateRoot": str(state_run),
              "areaResultsStream": str(results_path),
              "traceScope": str(scope_path), "since": args.since,
              "resourcePolicy": {'maxConcurrentHeavy': 2, 'maxProcessBytes': 3 * 1024**3, 'logsAndState': 'D:/NeyviaRuns/P22'},
              "areasPassing": [row["area"] for row in positive if row["status"] == "passed"],
              "areasPartial": [row for row in positive if row["status"] == "partial"],
              "areaResults": [{key: row.get(key) for key in
                               ("area", "status", "ok", "durationMs", "requestedContracts",
                                "passedContracts", "stateRoot", "outcomes", "execution", "sourceStable")}
                              for row in rows],
              "contractsNotAvailable": {row["area"]: row["notAvailableContracts"] for row in rows
                                        if row.get("notAvailableContracts")},
              "areasFailed": [row for row in rows if row["status"] == "failed"],
              "coverage": coverage,
              "inputBindings": input_bindings,
              "sourceBindings": {name: sorted({entry.get("sha256") for entry in entries if entry.get("sha256")})
                                 for name, entries in coverage.items()},
              "durationMs": round((time.perf_counter() - started) * 1000),
              "claims": "Only PASS areas with complete execution.json receipts contribute coverage."}
    coverage_write_errors = []
    if coverage_path is not None:
        from grant_agent.contract_gate import inventory
        from grant_agent.contract_measurements import measured_record, read_cache, write_cache
        contracts, current_manifests = inventory()
        cache = read_cache(coverage_path)
        records = list(cache["records"])
        seen = {(row.get("area"), tuple(row.get("contracts", [])),
                 row.get("receipt", {}).get("sha256")) for row in records}
        imported = []
        for row in positive:
            identities = row["passedContracts"]
            if not identities:
                continue
            try:
                execution_path = Path(row["execution"])
                trace = json.loads(execution_path.read_text(encoding="utf-8"))
                record = measured_record(ROOT, row["area"], identities, trace, contracts,
                                         receipt=execution_path,
                                         manifest=current_manifests.get(row["area"]))
                key = (record["area"], tuple(record["contracts"]), record["receipt"]["sha256"])
                if key not in seen:
                    records.append(record)
                    imported.append({"area": row["area"], "contracts": identities,
                                     "receipt": record["receipt"]})
                    seen.add(key)
            except (OSError, ValueError, KeyError, TypeError) as error:
                coverage_write_errors.append({"area": row["area"],
                                              "reason": type(error).__name__ + ": " + str(error)[:500]})
        if imported:
            write_cache(coverage_path, records)
        report["coverageMap"] = {"path": str(coverage_path), "imported": imported,
                                 "errors": coverage_write_errors,
                                 "recordCount": len(records),
                                 "sourceGuard": "contract_measurements.measured_record checked current source hashes and the passing execution receipt"}
    out = run_root / "measurement-index.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    complete = (len(positive) == len(rows) and all(row["status"] == "passed" for row in rows)
                and not coverage_write_errors)
    print(json.dumps({"ok": complete, "index": str(out),
                      "passingAreas": len(report["areasPassing"]), "partialAreas": len(report["areasPartial"]),
                      "failedAreas": len(report["areasFailed"]),
                      "durationMs": report["durationMs"]}, indent=2))
    return int(not complete)


if __name__ == "__main__":
    raise SystemExit(main())
