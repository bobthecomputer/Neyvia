"""Seal exact current-source/native receipts without upgrading blocked gates."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"scripts/evidence"
def read(name):return json.loads((EVIDENCE/name).read_text(encoding="utf-8"))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def archive(path):
 raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
 target=EVIDENCE/"C1b-runs"/(digest+path.suffix)
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  if target.read_bytes()!=raw:raise RuntimeError("Immutable archive mismatch: "+str(target))
 else:target.write_bytes(raw)
 return {"path":target.relative_to(ROOT).as_posix(),"sha256":digest}

native=read("C1b-native.json")
for path,expected in native["sourceSha256"].items():
 if sha(ROOT/path)!=expected:raise RuntimeError("Native proof is stale: "+path)
if not native["ok"] or len(native["runs"])!=5 or not all(r["passed"] for r in native["runs"]):raise RuntimeError("Native action proof is incomplete")
if sha(ROOT/native["capture"]["path"])!=native["capture"]["sha256"]:raise RuntimeError("Capture bytes changed")
apps=read("C1b-apps.json")
if apps["taskManifestSha256"]!=sha(EVIDENCE/"C1-tasks.json"):raise RuntimeError("App task manifest changed")
sources=["src/grant_agent/cua_fast.py","src/grant_agent/cua_native.py","src/grant_agent/cua_adaptation.py",
 "src/grant_agent/neyvia_cua.py","tools/cua-driver-win/NativeWorker.cs","tools/cua-driver-win/json-host.cs",
 "tools/cua-driver-win/c1-probe.cs","manuals/cl/computer-use.cl","manuals/computer-use.manual.json",
 "scripts/prove_c1b_native.py","scripts/verify_c1b_apps.py","scripts/measure_c1_clients.py",
 "pyproject.toml","uv.lock","src-tauri/resources/backend-requirements.txt"]
receipts=["C1-client-comparison.json","C1-competitor-openai.json","C1-desktop.json","C1-tasks.json",
 "C1b-apps-first.json","C1b-apps-second.json","C1b-apps.json","C1b-contracts.json","C1b-native.json","C1b-native.png",
 "C1b-capture-first.json","C1b-native-basic.json","C1b-native-protection-first.json","C1b-native-verifier-first.json",
 "C1b-native-toggle-first.json","C1b-native-message-first.json","C1b-native-safety-before-cache.json",
 "C1b-native-capture-deadline.json","C1b-packaging.json"]
report={"schema":"neyvia.c1b.v1","at":datetime.now(timezone.utc).isoformat(),"status":"incomplete-blocked",
 "branch":"track/c1-cua","baseCommit":"e325acf0","sourceSha256":{p:sha(ROOT/p) for p in sources},
 "receipts":[{"path":"scripts/evidence/"+p,"sha256":sha(EVIDENCE/p)} for p in receipts],
 "proven":{"nativeEditApplyRuns":5,"atomicActions":native["atomicLatency"],"checkboxToggle":native["toggle"]["check"]["status"],
  "refusals":native["refusals"],"foreignTokenRefused":native["foreignTokenRefused"],"PrintWindowCapture":native["capture"]},
 "installedApps":apps["summary"],"installedAppAtomicLatencies":[{"app":r["app"],"status":r["status"],"latency":r["latency"]} for r in apps["apps"]],
 "clientChoice":"Python comtypes keeps the client in-process; both C# and Python timed out in the matched probe, so no faster-client claim is made.",
 "missing":["15+ installed apps with actual actions and p50/p95; current cohort sent zero actions",
  "Active-desktop focus/cursor preservation; the input desktop is Screen-saver and preservation was unobservable",
  "Successful UIA cached-pattern and event-diff runs, general MSAA action/traversal runs, SendInput restore journey and automatic T18 fallback",
  "Matched public-suite and Claude/OpenAI action evaluations; OpenAI list_windows timed out on three attempts"],
 "needsPaul":["Dismiss the screen saver/unlock the desktop; retain existing apps/helpers. Then rerun scripts/verify_c1b_apps.py and the Claude arm from C1-tasks.json."]}
(EVIDENCE/"C1b.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
spec={"schema":"neyvia.efficiency-result.v1","id":"C1b-bounded-native-2026-10-04",
 "study":"C1b bounded native fallback: real app mechanism; installed-app and active-desktop gates blocked",
 "method":"Source-bound compiled WinForms application; atomic native observe-act-verify, real app-written output, checkbox mutation, protection refusals and inspected PrintWindow capture. Independent installed-app/competitor failures retained.",
 "models":["No model in native action path; OpenAI computer-use plugin attempted separately"],
 "tasks":{"description":"Five edit-and-Apply repetitions plus checkbox and guard refusals in one real disposable native app; 22 installed-app tasks frozen but no installed-app action score.","repetitions":5,"independent_unit":"one disposable native application"},
 "limitations":report["missing"],"evidence_status":"raw-verified",
 "receipts":[{"id":"native","path":"scripts/evidence/C1b-native.json","kind":"raw"},{"id":"report","path":"scripts/evidence/C1b.json","kind":"aggregate"}],
 "metrics":[{"name":"fixture_atomic_"+q,"unit":"ms","calculation":{"receipt":"native","pointer":"/atomicLatency/"+q+"Ms"},"ci_request":{"method":"not-estimable","reason":"One native application, repeated actions; no independent app cohort"}} for q in ("p50","p95")]}
for item in spec["receipts"]:item.update(archive(ROOT/item["path"]))
(EVIDENCE/"C1b-result-spec.json").write_text(json.dumps(spec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"sealed":"scripts/evidence/C1b.json","status":report["status"],"atomicLatency":native["atomicLatency"]}))
