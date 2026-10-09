"""Measure the real source-impact path, without invoking a desktop or provider."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tempfile
import cProfile
import pstats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def summary(samples):
    ordered = sorted(samples)
    return {"samplesMs": samples, "p50Ms": statistics.median(ordered),
            "p95Ms": ordered[max(0, math.ceil(.95 * len(ordered)) - 1)]}


def measure(warm_samples):
    from grant_agent import neyvia_impact as module
    source_hash = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    phases = []
    for name in ("_stamp", "_files", "_build", "_dependents"):
        original = getattr(module, name)
        def traced(*args, _original=original, _name=name, **kwargs):
            started = time.perf_counter()
            value = _original(*args, **kwargs)
            phases.append({"phase": _name, "subject": str(args[1]) if len(args) > 1 else str(args[0]),
                           "ms": round((time.perf_counter() - started) * 1000, 3),
                           "count": len(value) if hasattr(value, "__len__") else None})
            return value
        setattr(module, name, traced)
    samples = []
    for _ in range(1 + warm_samples):
        started = time.perf_counter()
        result = module.impact(["docs/manuals/notes.md"], gaps=False)
        samples.append(round((time.perf_counter() - started) * 1000, 3))
    return {"sourceSha256": source_hash, "coldMs": samples[0], "warm": summary(samples[1:]) if warm_samples else None,
            "phases": phases, "index": result["index"], "fileCount": len(result["files"])}


def mechanism_check():
    from grant_agent import neyvia_impact as module
    with tempfile.TemporaryDirectory(prefix="fixcl-impact-") as temporary:
        repo = Path(temporary)
        owner = repo / "scripts" / "owner.py"
        owner.parent.mkdir()
        owner.write_text("VALUE = 1\n", encoding="utf-8")
        first_stamp, first_index = module._stamp(repo), module.index(repo)
        generated = repo / "scripts" / "evidence" / "generated-project" / "owner.py"
        generated.parent.mkdir(parents=True)
        generated.write_text("VALUE = 2\n", encoding="utf-8")
        evidence_stamp, evidence_index = module._stamp(repo), module.index(repo)
        owner.write_text("VALUE = 'source changed'\n", encoding="utf-8")
        changed_stamp, changed_index = module._stamp(repo), module.index(repo)
        boundary = {"evidenceDoesNotInvalidate": first_stamp == evidence_stamp and first_index is evidence_index,
                    "sourceDoesInvalidate": first_stamp != changed_stamp and changed_index is not first_index,
                    "actualSourceOwners": [row[0] for row in changed_stamp]}
        if not all(boundary[key] for key in ("evidenceDoesNotInvalidate", "sourceDoesInvalidate")):
            raise RuntimeError(boundary)
    samples = []
    started = time.perf_counter()
    first = module.impact_enrichment(["docs/manuals/notes.md"])
    samples.append(round((time.perf_counter() - started) * 1000, 3))
    while time.perf_counter() - started < 180:
        call_started = time.perf_counter()
        result = module.impact_enrichment(["docs/manuals/notes.md"])
        samples.append(round((time.perf_counter() - call_started) * 1000, 3))
        if result["status"] in {"ready", "error"}:
            break
        time.sleep(.1)
    if result["status"] != "ready" or not result["files"]:
        raise RuntimeError(result)
    outside = str(REPO.parent / "outside-fixcl-latency-probe.txt")
    module.impact_enrichment([outside])
    deadline = time.perf_counter() + 30
    while time.perf_counter() < deadline:
        failed = module.impact_enrichment([outside])
        if failed["status"] == "error":
            break
        time.sleep(.1)
    if failed["status"] != "error":
        raise RuntimeError(failed)
    pressure = [module.impact_enrichment([f"docs/manuals/nonexistent-{number}.md"])["status"] for number in range(32)]
    if "busy" not in pressure or len(module._ENRICHMENT_PENDING) > module._ENRICHMENT_LIMIT:
        raise RuntimeError(pressure)
    return {"sourceBoundary": boundary, "first": first, "enrichmentCalls": summary(samples),
            "timeToReadyMs": result["elapsedMs"], "result": result,
            "outsideRepository": failed, "pressureStatuses": pressure,
            "pendingBound": module._ENRICHMENT_LIMIT, "daemon": module._ENRICHMENT_WORKER.daemon}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mechanism-check", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--cold-samples", type=int, default=3)
    parser.add_argument("--warm-samples", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profile:
        from grant_agent import neyvia_impact as module
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.runcall(module.impact, ["docs/manuals/notes.md"], gaps=False)
        rows = [{"file": key[0], "line": key[1], "function": key[2], "calls": value[1],
                 "ownMs": round(value[2] * 1000, 3), "cumulativeMs": round(value[3] * 1000, 3)}
                for key, value in pstats.Stats(profiler).stats.items()]
        result = {"elapsedMs": round((time.perf_counter() - started) * 1000, 3),
                  "topOwn": sorted(rows, key=lambda row: row["ownMs"], reverse=True)[:30],
                  "topCumulative": sorted(rows, key=lambda row: row["cumulativeMs"], reverse=True)[:30]}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return
    if args.mechanism_check:
        result = mechanism_check()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return
    if args.worker:
        print(json.dumps(measure(args.warm_samples)))
        return
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    runs = []
    for number in range(args.cold_samples):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--warm-samples",
                                  str(args.warm_samples)], cwd=REPO, capture_output=True, text=True, timeout=600,
                                 **hidden_windows_subprocess_kwargs())
        if process.returncode:
            raise RuntimeError(process.stderr or process.stdout)
        run = json.loads(process.stdout)
        runs.append(run)
        print(json.dumps({"sample": number + 1, "coldMs": run["coldMs"], "warm": run["warm"]}), flush=True)
    result = {"sourceSha256": hashlib.sha256((REPO / "src/grant_agent/neyvia_impact.py").read_bytes()).hexdigest(),
              "cold": summary([run["coldMs"] for run in runs]),
              "warm": summary([value for run in runs for value in run["warm"]["samplesMs"]]), "runs": runs}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
