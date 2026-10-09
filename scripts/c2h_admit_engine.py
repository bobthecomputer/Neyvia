"""Admit the opacity-cull Obscura build after the real-engine ability suite passes on it.

Usage: python scripts/c2h_admit_engine.py C2g-engine-opacity-build.json

Stages the offline build's engine and companion under .agent_control/C2g/obscura-capabilities,
runs tests/test_obscura_browser_abilities.py against that exact binary (explicit ports
48725-48728, headless, no other browser), and only then writes
scripts/evidence/C2h-engine-admission.json, which managed_executable() prefers.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
evidence = repo / "scripts/evidence"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


name = sys.argv[1] if len(sys.argv) > 1 else "C2g-engine-opacity-build.json"
build_path = evidence / name
build = json.loads(build_path.read_text(encoding="utf-8"))
if build.get("exitCode") != 0 or build.get("stealth") is not False or build.get("cargoNetwork") is not False:
    raise SystemExit("A completed non-stealth offline build is required")
artifacts = build["artifacts"]
if len(artifacts) != 2:
    raise SystemExit("Engine and companion are both required")
for artifact in artifacts:
    if sha256(repo / artifact["path"]) != artifact["sha256"]:
        raise SystemExit("Build artifact changed: " + artifact["path"])
directory = repo / ".agent_control/C2g/obscura-capabilities" / "-".join(a["sha256"][:12] for a in artifacts)
directory.mkdir(parents=True, exist_ok=True)
staged = []
for artifact in artifacts:
    target = directory / Path(artifact["path"]).name
    if not target.exists():
        shutil.copy2(repo / artifact["path"], target)
    if sha256(target) != artifact["sha256"]:
        raise SystemExit("Staged artifact changed: " + str(target))
    staged.append({**artifact, "path": target.relative_to(repo).as_posix()})
engine = next(a for a in staged if a["path"].endswith("/obscura.exe"))
worker = next(a for a in staged if a["path"].endswith("/obscura-worker.exe"))

junit = repo / ".agent_control/C2h/admission-junit.xml"
junit.parent.mkdir(parents=True, exist_ok=True)
started = time.time()
run = subprocess.run([sys.executable, "-m", "pytest", "tests/test_obscura_browser_abilities.py", "-q", "-p", "no:cacheprovider",
                      "--junitxml", str(junit)], cwd=repo, env={**__import__("os").environ, "NEYVIA_OBSCURA_EXE": str(repo / engine["path"])},
                     capture_output=True, text=True)
suite = ET.parse(junit).getroot().find("testsuite")
counts = {key: int(suite.get(key)) for key in ("tests", "failures", "errors", "skipped")}
if run.returncode != 0 or counts["failures"] or counts["errors"]:
    sys.stderr.write(run.stdout[-3000:])
    raise SystemExit("Ability suite failed on the candidate engine; not admitted")

patches = [("scripts/obscura-v024-C2g-capabilities.patch", "Routed incremental SSE, EventSource, CSS and matchMedia dark preference, same-document anchors"),
           ("scripts/obscura-v024-C2g-fragment-render-key.patch", "Fragment-insensitive prepared screenshot resource base"),
           ("scripts/obscura-v024-C2h-opacity-cull.patch", "Skip opacity groups whose whole subtree is far outside the paint surface")]
report = {
    "schema": "neyvia.C2h.source-fork-admission@1",
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "sourceTag": "v0.2.4", "upstream": "https://github.com/h4ckf0r0day/obscura/tree/v0.2.4",
    "engineVersion": build.get("engineVersion"), "buildReceipt": "scripts/evidence/" + name, "buildReceiptSha256": sha256(build_path),
    "buildExitCode": build["exitCode"],
    "patches": [{"path": path, "sha256": sha256(repo / path), "mechanism": why} for path, why in patches],
    "engineBinary": {k: engine[k] for k in ("path", "bytes", "sha256")},
    "workerBinary": {k: worker[k] for k in ("path", "bytes", "sha256")},
    "stealth": False, "cargoNetwork": False, "systemInstall": False,
    "runtimeProof": {"suite": "tests/test_obscura_browser_abilities.py", "counts": counts, "seconds": round(time.time() - started, 1),
                     "ports": "48725-48728", "engineSha256": engine["sha256"]},
}
out = evidence / "C2h-engine-admission.json"
out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"admitted": True, "engine": engine["path"], "counts": counts, "receipt": out.relative_to(repo).as_posix()}))
