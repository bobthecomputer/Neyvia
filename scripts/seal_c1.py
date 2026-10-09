"""Archive exact C1 observations and prepare a receipt-backed ledger input."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "scripts/evidence"

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

def archive(receipt, name):
    capture = Path(receipt["capture"]["path"])
    capture.resolve().relative_to((ROOT / ".agent_control/c1").resolve())
    if sha(capture) != receipt["capture"]["sha256"]:
        raise ValueError("Captured PNG changed")
    destination = EVIDENCE / "C1-runs" / name
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(capture, destination / "native-final.png")
    workspace = capture.parents[2]
    if not (workspace / "manual-runs.jsonl").is_file():
        raise ValueError("Successful flow's raw manual traces are unavailable")
    for pattern in ("manual-runs.jsonl", "manual-runs/*.json", "manual-scripts/*.json",
                    "manual-patches/*.json", "manual-versions/computer-use/*",
                    "cua/adaptation/*.json", "cua/adaptation/*.cl", "cua/receipts.jsonl"):
        for source in workspace.glob(pattern):
            if not source.is_file():
                continue
            target = destination / "workspace" / source.relative_to(workspace)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return destination

mechanism = read(EVIDENCE / "C1-mechanism.json")
baseline = read(EVIDENCE / "C1-mechanism-baseline.json")
archive(baseline, "earlier")
archive(mechanism, "latest-success")
public = read(EVIDENCE / "C1-public-freeze.json")
fixture = Path(public["localWorkbook"])
fixture.resolve().relative_to((ROOT / ".agent_control/c1-native-benchmark").resolve())
if sha(fixture) != public["fixtureSha256"]:
    raise ValueError("Public fixture changed")
shutil.copyfile(fixture, EVIDENCE / "C1-runs" / fixture.name)
apps = sorted({row["app"] for path in EVIDENCE.glob("C1-native*.json")
               for row in read(path).get("apps", []) if row.get("status") == "observed"})
final_cohort = read(EVIDENCE / "C1-native-benchmark-final-probe.json")
flow_ms = [run["elapsed_ms"] for run in mechanism["runs"]]
current = mechanism.get("runtimeSourceSha256", {})
final_source_proven = bool(current) and all(sha(ROOT / path) == value for path, value in current.items())
sources = [*ROOT.glob("src/grant_agent/cua_*.py"),
    *[ROOT / "src/grant_agent" / (name + ".py") for name in
      ("neyvia_cua", "neyvia_cua_mcp", "neyvia_manuals", "manual_versions", "neyvia_workspace_tools")],
    ROOT / "tools/cua-driver-win/NativeWorker.cs", ROOT / "tools/cua-driver-win/json-host.cs",
    ROOT / "manuals/cl/computer-use.cl", ROOT / "manuals/computer-use.manual.json"]
limitations = [
    "C1 is incomplete: the latency, 15+ application task completion and public matched baseline gates are unmet.",
    "The installed-app cohort is read-only observation, not task completion; its final retry observed zero of three apps.",
    "Compiled JSON host is opt-in: status/hooks passed, but MTA and STA window-tree attempts timed out. Default transport remains legacy PowerShell.",
    "T18 visual adaptation and visual postconditions are wired but no real model-backed visual run was performed.",
    "The Excel OSWorld source and public fixture were acquired, but no fresh owned workbook window appeared; official harness and evaluation were not run.",
    "Claude/OpenAI specialized computer-use comparison routes were unavailable; no substitute or score was invented.",
    "Native desktop bridge dispatch and microphone/device behavior were not exercised; HTTP/MCP discovery and no-grant refusal were exercised.",
    "Five repetitions of one disposable WinForms workflow do not establish generalization; the two-step flow latency is not the requested atomic roundtrip metric.",
]
if not final_source_proven:
    limitations.append("The successful workflow receipt is from an earlier source iteration without a full runtime manifest; final default-transport attempt remains blocked. Do not treat historical success as final-source end-to-end proof.")
result = {"schema": "neyvia.c1-results.v1", "at": datetime.now(timezone.utc).isoformat(),
    "status": "incomplete", "finalSourceNativeProof": final_source_proven,
    "definingMechanism": "read-only UIA draft -> checked use -> workspace CL promotion -> three grounded runs -> compiled zero-model-token replay",
    "benchmark": {"workflowRuns": len(flow_ms), "workflowSuccess": sum(bool(r.get("ok")) for r in mechanism["runs"]),
        "twoStepFlowP50Ms": statistics.median(flow_ms), "twoStepFlowSamplesMs": flow_ms,
        "firstUseObservationMs": mechanism["firstObservationMs"], "modelTokens": mechanism["tokens"],
        "driverModelCostUsd": mechanism["costUsd"], "compiledReplay": mechanism["compiledReplay"],
        "distinctAppsObservedEarlier": apps, "finalCohortObserved": final_cohort["observed"],
        "finalCohortRequested": final_cohort["requested"], "officialPublicTasksScored": None,
        "matchedClaudeOpenAI": None},
    "gates": {"atomicRoundtripP50Below150Ms": "unmeasured", "unseenAppBelow500Ms": False,
        "15PlusAppsTaskSuccess": False, "publicMatchedBaselines": False,
        "focusAndCursorPreservedInHistoricalWorkflow": mechanism["foregroundPreserved"] and mechanism["cursorPreserved"],
        "historicalAmbiguousMissingTakeoverRefusal": mechanism["failures"]},
    "limitations": limitations,
    "runtimeSourceSha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in sources},
    "verificationStartupIncident": "Initial backend launch inadvertently started default broad self-check workers; Ctrl+C left its process tree. The exact owned tree was identified and stopped. Subsequent backend used --skip-proof-self-check on 48701. No inherited self-check readiness or port-isolation proof is claimed.",
    "retryLogs": ["scripts/evidence/C1-mta-attempt.log", "scripts/evidence/C1-sta-attempt.log", "scripts/evidence/C1-final-attempt.log"],
    "receipts": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p)}
        for p in sorted([*EVIDENCE.glob("C1-*.json"), *EVIDENCE.glob("C1-*.log"),
                         *[p for p in (EVIDENCE / "C1-runs").rglob("*") if p.is_file()]])
        if p.name != "C1-result-spec.json"]}
write(EVIDENCE / "C1.json", result)
ci = {"method": "not-estimable", "reason": "One native workflow, repeated five times; no independent application task panel"}
metrics = [{"name": "two_step_native_flow_p50", "unit": "ms", "calculation": {"op": "median", "args": [{"receipt": "mechanism", "pointer": "/runs", "field": "/elapsed_ms"}]}, "ci_request": ci},
    {"name": "successful_native_workflow_repetitions", "unit": "runs", "calculation": {"op": "sum", "args": [{"receipt": "mechanism", "pointer": "/runs", "field": "/ok"}]}, "ci_request": ci},
    {"name": "first_use_native_observation", "unit": "ms", "calculation": {"receipt": "mechanism", "pointer": "/firstObservationMs"}, "ci_request": ci},
    {"name": "final_installed_apps_observed", "unit": "apps", "calculation": {"receipt": "final-cohort", "pointer": "/observed"}, "ci_request": {"method": "not-estimable", "reason": "Failed bounded availability retry, not a success population sample"}}]
spec = {"schema": "neyvia.efficiency-result.v1", "id": "C1-native-adaptation-2026-10-04",
    "study": "C1 adaptive background computer use: verified native learning mechanism and incomplete performance/generalization gates",
    "method": "Owned real WinForms app, UIA values + app-written effect + independently inspected capture; quarantine/promotion/repeated grounded manual compilation; separate read-only installed-app cohort and real HTTP/MCP refusal",
    "models": ["No model in measured native workflow; deterministic CUA and existing grounded manual runner/compiler"],
    "tasks": {"description": "Set owned Task input and Apply; five repetitions of one workflow. Distinct installed apps observed separately. OSWorld Windows Excel source/fixture attempt unavailable.", "repetitions": 5, "independent_unit": "one native workflow; installed observation cohort is not task success"},
    "limitations": limitations, "evidence_status": "raw-verified", "metrics": metrics,
    "receipts": [{"id": name, "path": "scripts/evidence/" + filename, "sha256": sha(EVIDENCE / filename), "kind": kind}
        for name, filename, kind in [("mechanism", "C1-mechanism.json", "raw"), ("final-cohort", "C1-native-benchmark-final-probe.json", "raw"), ("summary", "C1.json", "aggregate")]]}
write(EVIDENCE / "C1-result-spec.json", spec)
print(json.dumps({"status": result["status"], "finalSourceNativeProof": final_source_proven, "workflowP50Ms": statistics.median(flow_ms), "distinctAppsObserved": len(apps), "archivedReceipts": len(result["receipts"])}))
