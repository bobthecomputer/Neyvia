"""Record the integration gates from their actual local receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[1]
BASE = "ea26c48809ffa590f5969ea8a7e55ccf3aca95a6"
TRACK = "0f915641"


def artifact(relative):
    path = REPO / relative
    if not path.is_file():
        return {"path": relative, "available": False}
    return {"path": relative, "available": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def seal(relative, name):
    """Keep a byte-preserved committed copy of otherwise task-local evidence."""
    path = REPO / relative
    if not path.is_file():
        return artifact(relative)
    target = REPO / "scripts/evidence/intcl/checks" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != target.resolve():
        shutil.copyfile(path, target)
    return {**artifact(target.relative_to(REPO).as_posix()), "observedPath": relative}


def read(relative):
    path = REPO / relative
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("verifying", "finished"), default="verifying")
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    paths = {
        "manuals": ".agent_control/INTCL/manuals/compile-final.json",
        "parentManuals": ".agent_control/INTCL/manuals/parent-preservation.json",
        "manualJourney": "docs/manuals/manual_first_contracts.json",
        "productionCL": "scripts/evidence/CL11-production.json",
        "productCompletion": "scripts/evidence/intcl/product-live.json",
        "nativeRecovery": "scripts/evidence/intcl/task22-direct-native-diagnostic-v2/receipt.json",
        "routes": "scripts/evidence/intcl/http.json",
        "dispatch": ".agent_control/INTCL/dispatch-returns.json",
        "lostLines": "scripts/evidence/intcl/lost-lines.json",
        "luna": "scripts/evidence/intcl/six-task-comparison.json",
        "pytest": "scripts/evidence/intcl/pytest-comparison.json",
        "pycompile": "scripts/evidence/intcl/checks/pycompile.json",
        "startupTestMigration": "scripts/evidence/intcl/readonly-cl-startup-migration.json",
        "cleanup": "scripts/evidence/intcl/cleanup.json",
    }
    data = {name: read(path) for name, path in paths.items()}
    smoke = data["luna"] or {}
    smoke_tokens = smoke.get("baselineTotalTokens", 0)
    smoke_change = (100 * (smoke.get("afterTotalTokens", 0) / smoke_tokens - 1)) if smoke_tokens else None
    compiled = data["pycompile"] or {}
    compiled_current = bool(compiled.get("files")) and all(
        artifact(row["path"]).get("sha256") == row["sha256"] for row in compiled.get("files", []))
    gates = {
        "pyCompile": bool(compiled.get("passed") and compiled.get("exitCode") == 0 and compiled_current),
        "manualSourceEquality": bool(data["manuals"] and data["manuals"].get("manuals") == 33
                                    and len(data["manuals"].get("results", [])) == 33
                                    and all(row.get("equal") and Path(row["source"]).resolve().is_relative_to(REPO)
                                            and hashlib.sha256(Path(row["source"]).read_text(encoding="utf-8").encode()).hexdigest() == row["source_sha256"]
                                            for row in data["manuals"].get("results", []))),
        "manualJourney": bool(data["manualJourney"] and data["manualJourney"].get("passed")),
        "parentManualPreservation": bool(data["parentManuals"] and data["parentManuals"].get("manuals") == 33 and all(
            row.get("night_structure") and row.get("parent_keyed_records_preserved")
            for row in data["parentManuals"].get("results", []))),
        "productionCL": bool(data["productionCL"] and data["productionCL"].get("allPassed")),
        "productCompletion": bool(data["productCompletion"] and data["productCompletion"].get("allPassed")),
        "nativeRecovery": bool(data["nativeRecovery"] and data["nativeRecovery"].get("passed")
                               and bool(data["nativeRecovery"].get("capture"))
                               and all(Path(row["path"]).resolve().is_relative_to(REPO)
                                       and Path(row["path"]).is_file()
                                       and hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]
                                       for row in data["nativeRecovery"].get("capture", []))),
        "allCLRoutes": bool(data["routes"] and data["routes"].get("allPassed")),
        "dispatchReturns": bool(data["dispatch"] and not data["dispatch"].get("missing")),
        "lostLineSemanticReview": bool(data["lostLines"] and not data["lostLines"].get("missingManualEntries")
                                       and read("scripts/evidence/intcl/lost-lines-review.json")["reviewedFindings"]
                                       == len(data["lostLines"].get("findings", []))),
        "lunaSixNoRegression": bool(data["luna"] and data["luna"].get("complete")
                                    and data["luna"].get("noNewFailures")),
        "fullPytestNoNewFailures": bool(data["pytest"] and data["pytest"].get("complete")
                                        and data["pytest"].get("noNewFailures")),
    }
    evidence = {name: seal(path, name + ".json") for name, path in paths.items()}
    logs = ["merge.vite.log", "final.vite.log", "verified.vite.log", "committed.vite.log", "merge.node.log", "node-full.log",
            "node-verified.log", "node-final.log", "node-baseline-two.log", "node-baseline-final.log",
            "grounded-final.log", "grounded-verified.log", "cl11.production.log", "cl11.verified.production.log",
            "cl11.final.production.log", "http-final-proof.log", "lost-lines-final.log",
            "product-live-idempotent-grants.log", "product-live-final.log", "node-before-committed-source.log",
            "node-before-tool-count-correction.log"]
    evidence["checks"] = [seal(".agent_control/INTCL/" + name, name) for name in logs]
    evidence["priorSmokeComparisons"] = [artifact("scripts/evidence/intcl/" + name + "/comparison.json")
        for name in ("luna-b", "luna-b-native-retry", "luna-b-final", "luna-b-verified", "luna-b-verified-retry")]
    for name in ("merge.vite.log", "final.vite.log", "verified.vite.log", "committed.vite.log"):
        path = REPO / ".agent_control/INTCL" / name
        gates[name] = path.is_file() and "built in" in path.read_text(encoding="utf-8", errors="replace")
    node = REPO / ".agent_control/INTCL/node-final.log"
    baseline_node = REPO / ".agent_control/INTCL/node-baseline-final.log"
    gates["nodeNoNewFailures"] = (node.is_file() and baseline_node.is_file()
        and all(text in node.read_text(encoding="utf-8", errors="replace")
                for text in ("tests 184", "pass 183", "fail 1"))
        and all(text in baseline_node.read_text(encoding="utf-8", errors="replace")
                for text in ("tests 5", "pass 4", "fail 1", "neyvia_browser_authority_contract.test.mjs")))
    if args.phase == "finished" and not all(gates.values()):
        parser.error("Cannot finish with unmet gates: " + ", ".join(name for name, passed in gates.items() if not passed))
    result = {
        "schema": "neyvia.intcl.integration.v1", "phase": args.phase,
        "branch": "track/integrate-cl", "integrationBaseline": BASE,
        "mergedTrack": TRACK, "observedHead": head,
        "boundaries": {"backend": "http://127.0.0.1:48521", "ports": [48521, 48529],
                       "localOnlyIntegration": True, "push": False, "promotion": False,
                       "nasAccess": False, "protectedCredentialReads": False},
        "gates": gates, "evidence": evidence,
        "smokeProviderTokenChangePercent": smoke_change,
        "commands": {
            "neyvia.cl": ["WorkspaceTools/native registry", "NeyviaToolGateway/SDK",
                          "CompactNeyviaMCPServer stdio", "Claude plugin MCP",
                          "/api/ui/tools/call", "/api/backend call_native_tool_command",
                          "desktop_bridge persistent service", "existing generic Tauri IPC"],
            "neyvia.cl.describe": ["same registration and transport routes as neyvia.cl"],
        },
        "limits": ["Existing Autopilot prose acceptance retains its explicit verifier; no hidden conversion to CL G.",
                   "Full-suite comparison records actual partitioned coverage, task-local safety guards, test deadlines, and source-specific affected-test reruns.",
                   "Six-task Luna smoke is a paired regression check, not the complete CL standard benchmark.",
                   "Smoke success and provider token change are recorded separately; no efficiency improvement is inferred from successful tasks.",
                   "Node checks excluded the credential-reading, ephemeral-port auth restart file; the remaining authoritative-venv failure reproduces on night with the required system Python.",
                   "Desktop forwarding was exercised through its real Python dispatch; the native Tauri UI was not launched.",
                   "Cold production impact-map indexing can be slow with the large inherited evidence corpus."],
    }
    destination = REPO / "scripts/evidence/INTCL.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"phase": args.phase, "gates": gates, "receipt": str(destination)}))


if __name__ == "__main__":
    main()
