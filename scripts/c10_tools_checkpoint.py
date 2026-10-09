"""Seal real tool evidence and append the research ledger without promotion."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile
from c10_tools import EVIDENCE, REPO, report
from finalize_c10d import usage

report()
result = json.loads((EVIDENCE/"C10-tools.json").read_text(encoding="utf-8"))
if not result["allMeasured"]: raise ValueError("Every selected source tool needs twenty measured cases")
measured = usage()
cpu = {}
for path in (EVIDENCE/"C10-tools-runs").glob("*/*.json"):
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("rows",[]):
        decision = row.get("decision") or {}
        model = decision.get("decision") or decision
        if model.get("decision_id") and model.get("usage"):
            cpu[model["decision_id"]] = model["usage"]
cpu_tokens = sum(u.get("input_tokens",0)+u.get("output_tokens",0) for u in cpu.values())
measured.update(observedToolCpuCalls=len(cpu),observedToolCpuTokens=cpu_tokens)
measured["combinedObservedTokenLowerBound"] += cpu_tokens
(EVIDENCE/"C10-tools-usage.json").write_text(json.dumps(measured,indent=2)+"\n",encoding="utf-8")
owners = ["src/grant_agent/"+name for name in ("native_tools.py","proof_contracts.py","web_documents.py","pdf_document.py",
    "pdf_document_worker.py","neyvia_pdf_tools.py","neyvia_browser.py","browser_obscura.py","laya_client/browser_client.py")]
owners += ["scripts/"+name for name in ("c10_tools.py","c10_tools_mcp.py","c10_tools_manual.py","c10_tools_checkpoint.py")]
owners += ["manuals/cl/tools-depth.cl","manuals/tools-depth.manual.json"]
owners += ["manuals/cl/research-assistant.cl","manuals/research-assistant.manual.json"]
bindings = {name:hashlib.sha256((REPO/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest() for name in owners}
files = {REPO/name for name in owners}
files.update(EVIDENCE.glob("C10-tools*.json"))
files.update((EVIDENCE/"C10-tools.md", EVIDENCE/"C10d-harness-gaps.md"))
for path in (EVIDENCE/"C10-tools-runs").rglob("*"):
    if not path.is_file(): continue
    relative=path.relative_to(EVIDENCE/"C10-tools-runs")
    # Public observed documents, actual per-call receipts and pixels only.
    # Exclude engine logs, profile storage, authentication and runtime state.
    allowed = (len(relative.parts)==2 and path.suffix==".json") or path.name=="web_documents.sqlite3" \
        or (path.parent.name=="tool_receipts" and path.suffix==".json") \
        or (path.parent.name=="captures" and path.suffix==".png") \
        or (path.parent.name=="pdf-cache" and path.suffix==".pdf") \
        or (path.name=="receipt.json" and "receipts-runtime" in relative.parts)
    if allowed: files.add(path)
destination = EVIDENCE/"C10-tools-raw.zip"
if destination.exists(): raise ValueError("Retain the sealed tool archive; use a new version for another checkpoint")
with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in sorted(files):
        path.resolve().relative_to(REPO.resolve())
        archive.write(path,path.relative_to(REPO).as_posix())
with zipfile.ZipFile(destination) as archive:
    if archive.testzip(): raise ValueError("Archive CRC verification failed")
sealed = {"path":str(destination.relative_to(REPO)),"bytes":destination.stat().st_size,
          "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),"crcVerified":True,"files":len(files)}
row = {"track":"C10d","stage":"tool_gate","run":"C10-tools-20261005","updatedAt":datetime.now(timezone.utc).isoformat(),
       "allMeasured":True,"allPassed":result["allPassed"],"passedTools":result["passedTools"],"measuredTools":result["measuredTools"],
       "tools":result["selected"],"sourceBinding":bindings,"corpusSha256":result["casesSha256"],"archive":sealed,
       "usage":measured,"accuracyGate":result["accuracyGate"],"rejected":"Goal-aware CPU projection11/20 vs14/20; reverted",
       "remaining":result["remaining"],"needsPaul":result["needsPaul"]}
contracts = json.loads((EVIDENCE/"C10-tools-contracts.json").read_text(encoding="utf-8"))
row["verification"] = {"kind":"Connected Language contracts through real task-local MCP",
    "manual":"manuals/cl/research-assistant.cl","receipt":"scripts/evidence/C10-tools-contracts.json",
    "contracts":contracts["contracts"],"passed":contracts["passed"],"newTestFilesAddedSinceBase":0,
    "compilerCheck":"scripts/evidence/C10-tools-manual-check.json"}
ledger=REPO/"docs/research/results.jsonl"
existing=[json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
if any(r.get("stage")==row["stage"] and r.get("run")==row["run"] for r in existing):
    raise ValueError("Retain the measured ledger checkpoint; do not silently replace it")
with ledger.open("a",encoding="utf-8") as out: out.write(json.dumps(row,separators=(",",":"))+"\n")
(EVIDENCE/"C10-tools-checkpoint.json").write_text(json.dumps(row,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"measuredTools":row["measuredTools"],"passedTools":row["passedTools"],"allPassed":row["allPassed"],
                  "archive":sealed,"observedTokensAtCheckpoint":measured["combinedObservedTokenLowerBound"]}))
