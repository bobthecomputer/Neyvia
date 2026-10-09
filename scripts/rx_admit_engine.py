"""Admit the rebuilt C2h Obscura engine from its durable D: home.

Usage: python scripts/rx_admit_engine.py

Reads scripts/evidence/RX-browser-engine-build.json (scripts/rx_build_obscura_c2h.py), runs
the existing real-engine ability suite tests/test_obscura_browser_abilities.py against those
exact binaries on the release gate's ports 49025-49029, and only when it passes rewrites
scripts/evidence/C2h-engine-admission.json so managed_executable() resolves
D:/NeyviaRuns/engines/obscura-c2h/<engine12>-<worker12>/obscura.exe. The earlier admission
(binaries in a deleted worktree) is kept verbatim under "supersedes".
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
evidence = repo / "scripts/evidence"
work = Path(r"D:\NeyviaRuns\rx-browser\admission")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


build_path = evidence / "RX-browser-engine-build.json"
build = json.loads(build_path.read_text(encoding="utf-8"))
if build.get("exitCode") != 0 or build.get("stealth") is not False or build.get("cargoNetwork") is not False:
    raise SystemExit("A completed non-stealth offline rebuild is required")
engine, worker = (next(a for a in build["artifacts"] if a["path"].endswith(name)) for name in ("obscura.exe", "obscura-worker.exe"))
for artifact in (engine, worker):
    if sha256(artifact["path"]) != artifact["sha256"]:
        raise SystemExit("Staged artifact changed: " + artifact["path"])
previous = json.loads((evidence / "C2h-engine-admission.json").read_text(encoding="utf-8"))
original = previous.get("supersedes", previous)

work.mkdir(parents=True, exist_ok=True)
junit = work / "ability-junit.xml"
started = time.time()
run = subprocess.run([sys.executable, "-m", "pytest", "tests/test_obscura_browser_abilities.py", "-q", "-p", "no:cacheprovider",
                      "--basetemp", str(work / "pytest"), "--junitxml", str(junit)], cwd=repo,
                     env={**os.environ, "NEYVIA_OBSCURA_EXE": engine["path"], "NEYVIA_ABILITY_PORT_BASE": "49025"},
                     capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
(work / "ability.log").write_text(run.stdout + run.stderr, encoding="utf-8")
suite = ET.parse(junit).getroot()
suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
counts = {key: int(suite.get(key)) for key in ("tests", "failures", "errors", "skipped")}
if run.returncode != 0 or counts["failures"] or counts["errors"]:
    sys.stderr.write(run.stdout[-3000:])
    raise SystemExit(f"Ability suite failed on the rebuilt engine; not admitted: {counts}")

report = {
    "schema": "neyvia.C2h.source-fork-admission@1",
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "sourceTag": original["sourceTag"], "upstream": original["upstream"], "upstreamCommit": original.get("upstreamCommit"),
    "engineVersion": build.get("engineVersion"),
    "buildReceipt": "scripts/evidence/RX-browser-engine-build.json", "buildReceiptSha256": sha256(build_path),
    "buildExitCode": build["exitCode"],
    "engineBinary": {k: engine[k] for k in ("path", "bytes", "sha256")},
    "workerBinary": {k: worker[k] for k in ("path", "bytes", "sha256")},
    "home": str(Path(engine["path"]).parent),
    "stealth": False, "cargoNetwork": False, "systemInstall": False,
    "patches": original["patches"],
    "rebuild": {
        "why": "The admitted 33ec108e/b6fdbcbd binaries lived in the deleted nx-c2-browser worktree; no copy remained on disk.",
        "sameRecordedInputs": "v0.2.4 tag archive (C2f audit sha256), the same patch files (admission sha256, LF), admitted rusty_v8 simdutf archive and libclang wheel, cargo 1.91.0 --offline --locked",
        "bitIdentical": build.get("matchesAdmittedHashes") is True,
        "hashBoundary": "MSVC release builds embed the build paths, so a rebuild in another directory yields new hashes; the new binaries are admitted by rerunning the ability suite below, not by hash equality.",
    },
    "runtimeProof": {"suite": "tests/test_obscura_browser_abilities.py", "counts": counts, "seconds": round(time.time() - started, 1),
                     "ports": "49025-49029", "engineSha256": engine["sha256"], "log": str(work / "ability.log")},
    "supersedes": original,
}
(evidence / "C2h-engine-admission.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
(Path(report["home"]) / "ADMISSION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"admitted": True, "engine": engine["path"], "sha256": engine["sha256"], "counts": counts}))
