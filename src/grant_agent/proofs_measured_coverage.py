"""Contract for execution-traced coverage receipts and incremental admission."""
from __future__ import annotations

import json
import hashlib
import os
import runpy
import sys
import time
import uuid
from pathlib import Path

CONTRACT = "p22.measured-coverage"
CONTRACTS = (CONTRACT,)
REPOSITORY = Path(__file__).resolve().parents[2]


def _exercise_measurement_runtime(scratch: Path, repository: Path) -> dict:
    """Drive the same trace, cache, source-binding and line-admission APIs as gate.py."""
    from .contract_coverage import classify, uncovered_by_surface
    from .contract_execution import start
    from .contract_measurements import (admission, digest, fresh, impacted, measured_record,
                                        read_cache, spec_digest, write_cache)

    scratch = Path(scratch).resolve()
    repository = Path(repository).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((repository / "config/proofs/measured-coverage.json").read_text(encoding="utf-8"))
    contract = manifest["contracts"][0]
    contracts = {CONTRACT: contract}
    target = "src/grant_agent/proofs_measured_coverage.py"
    policy = json.loads((repository / "config/contract_path_policy.json").read_text(encoding="utf-8"))

    # Mark a real executable line in this adapter; only execute it after tracing starts.
    import inspect
    source, first_line = inspect.getsourcelines(_exercise_measurement_runtime)
    anchor = next(first_line + offset for offset, text in enumerate(source)
                   if text.lstrip().startswith("TRACE_ANCHOR = 1"))
    second_anchor = next(first_line + offset for offset, text in enumerate(source)
                         if text.lstrip().startswith("TRACE_SECOND = 2"))
    out_of_scope_anchor = next(first_line + offset for offset, text in enumerate(source)
                               if text.lstrip().startswith("TRACE_OUT_OF_SCOPE = 1"))
    trace_root = Path("D:/NeyviaRuns/P22/measurement/measured-coverage-runtime") / uuid.uuid4().hex
    trace_root.mkdir(parents=True, exist_ok=False)
    trace_a_root = trace_root / "trace-a"
    trace_a = start(repository, trace_a_root, [CONTRACT], scope={target: [anchor, second_anchor]})
    try:
        TRACE_OUT_OF_SCOPE = 1  # noqa: F841 - the scoped stream must omit this executed line.
        TRACE_ANCHOR = 1  # noqa: F841 - the changed line must be observed by sys.monitoring.
        TRACE_SECOND = 2  # noqa: F841 - DISABLE at the first location must not suppress this one.
        classification = classify(target, policy)
        observed_policy = json.loads((repository / "config/contract_path_policy.json").read_text(encoding="utf-8"))
    finally:
        first_trace = trace_a.stop()

    row = first_trace.get("files", {}).get(target)
    scope_receipt = first_trace.get("traceScope", {})
    scope_path = Path(scope_receipt.get("path", "")).resolve()
    scope_bytes = scope_path.read_bytes() if scope_path.is_relative_to(trace_a_root.resolve()) and scope_path.is_file() else b""
    if (first_trace.get("ok") is not True or first_trace.get("sourceStable") is not True
            or first_trace.get("contracts") != [CONTRACT] or classification.get("kind") != "behaviour"
            or row is None or anchor not in row.get("lines", []) or second_anchor not in row.get("lines", [])
            or out_of_scope_anchor in row.get("lines", [])
            or scope_receipt.get("schema") != "neyvia.python-trace-scope.v1"
            or scope_receipt.get("files") != {target: {"lineData": True, "lines": [anchor, second_anchor]}}
            or not scope_bytes or len(scope_bytes) > 65536
            or hashlib.sha256(scope_bytes).hexdigest() != scope_receipt.get("sha256")):
        raise AssertionError(f"The trace did not record the passing outcome's executable changed line: "
                             f"trace={first_trace!r}, classification={classification!r}, anchor={anchor}")

    stream_files = sorted(trace_a_root.rglob("*.jsonl"))
    stream_events = set()
    stream_bytes = 0
    for stream_file in stream_files:
        stream_bytes += stream_file.stat().st_size
        if stream_bytes > 1024 * 1024:
            raise AssertionError("Scoped trace JSONL exceeded the fixture's 1 MiB inspection cap")
        for line in stream_file.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            stream_events.add((event.get("file"), event.get("line")))
    if (stream_events != {(target, anchor), (target, second_anchor)}
            or (target, out_of_scope_anchor) in stream_events or len(stream_files) != 1 or stream_bytes == 0):
        raise AssertionError("D-backed JSONL did not retain both scoped hits and filter the out-of-scope line")

    execution_receipt = scratch / "execution-a.json"
    execution_receipt.write_text(json.dumps(first_trace, indent=2) + "\n", encoding="utf-8")
    record = measured_record(repository, "measured-coverage", [CONTRACT], first_trace, contracts,
                             receipt=execution_receipt, manifest=manifest)
    cache_path = scratch / "coverage-cache.json"
    write_cache(cache_path, [record])
    cached = read_cache(cache_path)["records"]
    if len(cached) != 1 or not fresh(cached[0], repository, contracts):
        raise AssertionError("The source-bound coverage cache did not reuse its unchanged passing receipt")
    scope_bytes = scope_path.read_bytes()
    try:
        scope_path.write_bytes(b"{}\n")
        if fresh(cached[0], repository, contracts):
            raise AssertionError("A changed trace-scope file left cached coverage fresh")
    finally:
        scope_path.write_bytes(scope_bytes)
    if not fresh(cached[0], repository, contracts):
        raise AssertionError("Restoring the exact scope bytes did not restore cache freshness")
    wrong_policy_digest = dict(cached[0])
    wrong_policy_digest["scopeBinding"] = dict(cached[0]["scopeBinding"])
    wrong_policy_digest["scopeBinding"]["pathPolicy"] = dict(
        cached[0]["scopeBinding"]["pathPolicy"])
    wrong_policy_digest["scopeBinding"]["pathPolicy"]["sha256"] = "0" * 64
    if fresh(wrong_policy_digest, repository, contracts):
        raise AssertionError("A mismatched path-policy digest in the cache record was admitted")

    changed = {target: {"status": "changed", "lines": [anchor], "lineData": True}}
    passed = admission(repository, changed, cached, contracts)
    if passed["coverage"].get(target) != [CONTRACT] or passed["uncovered"]:
        raise AssertionError(f"A traced changed line failed measured admission: {passed!r}")
    policy_name = "config/contract_path_policy.json"
    input_only = admission(repository, {policy_name: {"status": "changed", "lines": [], "lineData": False}}, cached, contracts)
    if not observed_policy or policy_name not in input_only["uncovered"]:
        raise AssertionError("A configuration read or hash was mistaken for executed behaviour")

    self_check_source, self_check_line = inspect.getsourcelines(self_check)
    unexecuted_line = next(self_check_line + offset for offset, text in enumerate(self_check_source)
                            if text.lstrip().startswith("cases = []"))
    missing = admission(repository, {target: {"status": "changed", "lines": [unexecuted_line], "lineData": True}}, cached, contracts)
    if target not in missing["uncovered"] or missing["unexecutedChangedLines"].get(target) != [unexecuted_line]:
        raise AssertionError("An unexecuted changed line gained measured coverage")

    stale_source = dict(cached[0])
    stale_source["sourceBindings"] = dict(stale_source["sourceBindings"])
    stale_source["sourceBindings"][target] = "0" * 64
    stale_spec = dict(contract, claim=contract["claim"] + " changed")
    if fresh(stale_source, repository, contracts) or fresh(cached[0], repository, {CONTRACT: stale_spec}):
        raise AssertionError("Changed source bytes or a changed contract specification stayed cache-fresh")

    other_id = "p22.measured-coverage.unrelated"
    other_spec = {"id": other_id, "phase": "post", "claim": "Independent unrelated witness",
                  "checkedAt": ["grant_agent.contract_execution.start"], "impact": []}
    unrelated = dict(cached[0])
    unrelated["contracts"] = [other_id]
    unrelated["specs"] = {other_id: spec_digest(other_spec)}
    unrelated["files"] = {"src/grant_agent/contract_execution.py": {
        "sha256": digest(repository / "src/grant_agent/contract_execution.py"), "lines": [1], "lineData": True}}
    unrelated["sourceBindings"] = {"src/grant_agent/contract_execution.py": unrelated["files"]["src/grant_agent/contract_execution.py"]["sha256"]}
    unrelated["receipt"] = None
    selected = impacted([cached[0], unrelated], [target], {**contracts, other_id: other_spec})
    if selected != {CONTRACT}:
        raise AssertionError(f"Incremental impact selection ran unrelated outcomes: {sorted(selected)!r}")

    # Trace an exact source line in freshness validation and require that
    # scoped execution remains useful to cached admission.
    measurement_source, measurement_first_line = inspect.getsourcelines(fresh)
    measurement_anchor = next(measurement_first_line + offset for offset, text in enumerate(measurement_source)
                              if text.lstrip().startswith("for identity in record['contracts']"))
    measurement_path = "src/grant_agent/contract_measurements.py"
    trace_b = start(repository, trace_root / "trace-b", [CONTRACT],
                    scope={measurement_path: [measurement_anchor]})
    try:
        repeated = read_cache(cache_path)["records"]
        reused = fresh(repeated[0], repository, contracts)
        second_admission = admission(repository, changed, repeated, contracts)
        second_selection = impacted(repeated, [target], contracts)
    finally:
        second_trace = trace_b.stop()
    measurement_lines = second_trace.get("files", {}).get(measurement_path, {}).get("lines", [])
    if (not reused or second_admission["coverage"].get(target) != [CONTRACT]
            or second_selection != {CONTRACT} or measurement_anchor not in measurement_lines
            or any(line != measurement_anchor for line in measurement_lines)):
        raise AssertionError("The measured cache/admission functions were not executed successfully")

    corrupt_root = trace_root / "corrupt-child"
    corrupt_trace = start(repository, corrupt_root, [CONTRACT], scope={target: [anchor]})
    (corrupt_root / "child-corrupt.json").write_text("{truncated", encoding="utf-8")
    corrupt_result = corrupt_trace.stop()
    if corrupt_result.get("ok") is not False or not corrupt_result.get("childErrors"):
        raise AssertionError("A malformed child execution receipt was silently admitted")

    missing_repo = scratch / "late-owner"
    source = missing_repo / "scripts/observed.py"
    source.parent.mkdir(parents=True)
    source.write_text("result = 7391\n", encoding="utf-8")
    missing_spec = {CONTRACT: {"id": CONTRACT, "checkedAt": ["scripts/observed.py"], "claim": "Late owner invalidates evidence"}}
    missing_manifest = {"sourceFiles": ["scripts/future.py"]}
    missing_trace = start(missing_repo, trace_root / "late-owner-trace", [CONTRACT],
                          scope={"scripts/observed.py": [1]})
    observed_result = runpy.run_path(str(source))["result"]
    observed_trace = missing_trace.stop()
    missing_receipt = missing_repo / ".agent_control/p22/execution.json"
    missing_receipt.parent.mkdir(parents=True)
    missing_receipt.write_text(json.dumps(observed_trace), encoding="utf-8")
    missing_record = measured_record(missing_repo, "late-owner", [CONTRACT], observed_trace,
                                     missing_spec, receipt=missing_receipt, manifest=missing_manifest)
    if (observed_result != 7391 or "scripts/future.py" not in missing_record["absentSources"]
            or not fresh(missing_record, missing_repo, missing_spec)):
        raise AssertionError("The passing observation with an absent future owner was not recorded")
    (missing_repo / "scripts/future.py").write_text("result = 42\n", encoding="utf-8")
    if fresh(missing_record, missing_repo, missing_spec):
        raise AssertionError("A later-created declared owner left old evidence fresh")

    # Exercise the pure cutoff predicate with tiny synthetic values; no large
    # allocation or additional child process is needed to check its boundary.
    from .contract_resources import memory_limit_exceeded
    if (memory_limit_exceeded(9, 9, 10) or memory_limit_exceeded(10, 10, 10)
            or not memory_limit_exceeded(11, 9, 10)
            or not memory_limit_exceeded(9, 11, 10)):
        raise AssertionError("The private-memory and working-set cutoffs are not strict and bounded")

    shared_a, shared_b = "src/grant_agent/surface-a.py", "src/grant_agent/surface-b.py"
    generated, generator = "generated/scroll-output.py", "scripts/scroll-generator.py"
    fallback = "misc/unregistered-surface.py"
    surface_paths = [shared_a, shared_b, generated, fallback, shared_a]
    surface_classes = {
        shared_a: {"kind": "behaviour"},
        shared_b: {"kind": "behaviour"},
        generated: {"kind": "generated", "generator": generator},
        fallback: {"kind": "unknown"},
    }
    surface_owners = {shared_a: "module.proofs-a", shared_b: "module.proofs-b",
                      generator: "module.scroll-generator"}
    surface_modules = {
        "module.proofs-a": {"id": "module.proofs-a", "manual": "proofs"},
        "module.proofs-b": {"id": "module.proofs-b", "manual": "proofs"},
        "module.scroll-generator": {"id": "module.scroll-generator", "manual": "scroll-generator"},
    }
    surface_groups = uncovered_by_surface(surface_paths, surface_classes, surface_owners, surface_modules)
    expected_surface_groups = {
        "manual:proofs": [shared_a, shared_b],
        "manual:scroll-generator": [generated],
        "unmapped:misc": [fallback],
    }
    if (surface_groups != expected_surface_groups
            or uncovered_by_surface(list(reversed(surface_paths)), surface_classes,
                                    surface_owners, surface_modules) != expected_surface_groups
            or sum(map(len, surface_groups.values())) != len(set(surface_paths))
            or sorted(path for group in surface_groups.values() for path in group) != sorted(set(surface_paths))):
        raise AssertionError("Surface grouping lost ownership, fallback, uniqueness, or determinism")

    return {"executedSource": target, "executedChangedLine": anchor,
            "secondExecutedChangedLine": second_anchor,
            "independentScopedLinesCaptured": len(stream_events) == 2,
            "outOfScopeLineIgnored": out_of_scope_anchor not in row.get("lines", []),
            "traceStreamFiles": len(stream_files), "traceStreamBytes": stream_bytes,
            "coverageAdmission": passed["coverage"][target],
            "unexecutedChangedLineRemainsUncovered": missing["uncovered"] == [target],
            "staleSourceAndSpecInvalidated": True, "incrementalSelection": sorted(selected),
            "cacheReused": reused, "measurementImplementationLines": len(set(measurement_lines)),
            "scopeTamperInvalidatedAndRestoreRefreshed": True,
            "wrongPolicyDigestRejected": True,
            "tinyResourceCutoffVerified": True,
            "surfaceGroupingPreservesManualGeneratorAndFallback": True,
            "surfaceGroupingIsUniqueAndDeterministic": True}


def self_check(scratch: str | Path) -> dict:
    """Run the tracer exercise in a child so it can test gate.py's live tracer safely."""
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            code = ("import json,sys; from pathlib import Path; "
                    "from grant_agent.proofs_measured_coverage import _exercise_measurement_runtime; "
                    "print(json.dumps(_exercise_measurement_runtime(Path(sys.argv[1]),Path(sys.argv[2]))))")
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join([str(REPOSITORY / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
            from .contract_resources import capture_resource_bounded
            child = capture_resource_bounded(
                [sys.executable, "-c", code, str(scratch / "runtime-probe"), str(REPOSITORY)],
                cwd=REPOSITORY, env=env, input_text=None, timeout=35,
                logs_root="D:/NeyviaRuns/P22/measurement/measured-coverage-probe-logs",
                acquire_slot=False)
            if child["returncode"] or child["timedOut"]:
                raise RuntimeError(f"Measured coverage probe failed: {child.get('reason') or child['stderr'][-1200:]}")
            memory = child.get("memory") or {}
            if (child.get("reason") is not None or memory.get("watchError") is not None
                    or memory.get("limitBytes") != 3 * 1024**3):
                raise RuntimeError("Measured coverage probe did not run under the expected live memory watcher")
            observed = json.loads(child["stdout"].strip().splitlines()[-1])
            observed["resourceWatcher"] = {
                "limitBytes": memory["limitBytes"],
                "peakPrivateBytes": memory["peakPrivateBytes"],
                "peakWorkingSetBytes": memory["peakWorkingSetBytes"],
                "logs": child["logs"],
            }
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
