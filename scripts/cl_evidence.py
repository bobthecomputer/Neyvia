"""Export and verify the bounded CL handoff from task-owned real-run receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO / ".agent_control/cl"
PACKET = REPO / "scripts/evidence/cl"
MASTER = REPO / "scripts/evidence/CL.json"
INPUTS = {
    "canonical-summary.json": "benchmark/canonical-summary.json",
    "benchmark-history.json": "benchmark/aggregate.json",
    "provider-configuration-audit.json": "benchmark/configuration-audit.json",
    "transport-proof.json": "transport-proof.json",
    "http-proof.json": "http-proof.json",
    "model-proof.json": "model-proof-current/receipt.json",
    "conformance.json": "conformance-current.json",
    "manual-compile.json": "manual-compile-current.json",
    "manual-context-meter.json": "manual-context-meter.json",
    "provisional-meter.json": "provisional-meter.json",
    "inventory.json": "inventory-current.json",
    "cua-install.json": "benchmark/cua-install.json",
}
OWNERS = ["src/grant_agent/neyvia_cl.py", "src/grant_agent/neyvia_agent.py",
          "src/grant_agent/neyvia_workspace_tools.py", "src/grant_agent/neyvia_mcp_stdio.py",
          "src/grant_agent/neyvia_manuals.py", "src/grant_agent/manual_first.py",
          "src/grant_agent/neyvia_intent_plan.py", "src/grant_agent/desktop_bridge.py",
          "plugins/neyvia/mcp/neyvia_mcp.py", "config/neyvia_manuals.json",
          "config/cl_benchmark_tasks.json", "pyproject.toml",
          "docs/standard/connected-language.md", "docs/standard/primer.md"]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def export():
    assets = []
    def retain(source, target):
        source.resolve().relative_to(LOCAL.resolve())
        raw = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        assets.append({"path": target.relative_to(REPO).as_posix(), "bytes": len(raw), "sha256": digest(raw),
                       "original": source.relative_to(REPO).as_posix()})
    for name, source in INPUTS.items():
        retain(LOCAL / source, PACKET / name)
    canonical = load(PACKET / "canonical-summary.json")
    provider_rows = []
    roots = [LOCAL / "benchmark/canonical-small", LOCAL / "benchmark/canonical-large", LOCAL / "model-proof-current"]
    allowed = {"answer.txt", "events.jsonl", "prompt.txt", "receipt.json", "stderr.txt"}
    for root in roots:
        for turn in sorted(root.rglob("turn-*")):
            if not turn.is_dir():
                continue
            files = []
            for source in sorted(turn.iterdir()):
                if source.name in allowed and source.is_file():
                    raw = source.read_bytes()
                    files.append({"name": source.name, "bytes": len(raw), "sha256": digest(raw), "text": raw.decode("utf-8")})
            if files:
                provider_rows.append({"original": turn.relative_to(REPO).as_posix(), "files": files})
    write(PACKET / "provider-runs.json", {"schema": "neyvia.cl.provider-runs.v1", "turns": provider_rows})
    provider_raw = (PACKET / "provider-runs.json").read_bytes()
    assets.append({"path": "scripts/evidence/cl/provider-runs.json", "bytes": len(provider_raw), "sha256": digest(provider_raw),
                   "original": "Canonical provider turns and final-source model proof; original bytes hashed before UTF-8 embedding"})
    images = set()
    for row in canonical["runs"]:
        if row.get("proofImage"):
            images.add(Path(row["proofImage"]["path"]))
    for source_summary in canonical["sourceSummaries"]:
        source = REPO / source_summary
        chart = load(source).get("chartObservation")
        if chart:
            folder = Path(chart["provenance"]["receipt"]).parent
            for name in sorted(allowed):
                path = folder / name
                if path.exists() and not any(row["original"] == path.relative_to(REPO).as_posix() for row in assets):
                    retain(path, PACKET / "chart-transcription" / name)
            images.add(folder.parent / "chart.png")
    for source in sorted(images):
        retain(source, PACKET / "images" / (digest(source.read_bytes())[:16] + source.suffix))
    source_paths = {REPO / name for name in OWNERS}
    source_paths.update((REPO / "src/grant_agent/cl").glob("*.py"))
    source_paths.update((REPO / "manuals/cl").glob("*.cl"))
    source_paths.update(REPO / ("scripts/" + name) for name in ("prove_cl.py", "prove_cl_http.py", "prove_cl_model.py", "cl_compile_manuals.py", "cl_conformance.py", "cl_benchmark.py"))
    sources = [{"path": path.relative_to(REPO).as_posix(), "utf8LfSha256": digest(path.read_bytes().replace(b"\r\n", b"\n"))} for path in sorted(source_paths)]
    small = canonical["cohorts"]["canonical-small"]["arms"]
    large = canonical["cohorts"]["canonical-large"]["arms"]
    syntax = load(PACKET / "conformance.json")["summary"]
    transport, http, model = [load(PACKET / name) for name in ("transport-proof.json", "http-proof.json", "model-proof.json")]
    inventory = load(PACKET / "inventory.json")
    gates = {"referenceConformance": syntax["semantic_pass"] == syntax["documents"],
             "completeLayerMigration": False,
             "realModelBenchmarkComplete": canonical["complete"] and canonical["runsCount"] == 30,
             "contextReductionAtLeast50Percent": all(arms["b"]["serializedStartO200k"] <= .5 * arms["a"]["serializedStartO200k"] for arms in (small, large)),
             "equalOrBetterSuccess": {name: arms["b"]["passed"] >= arms["a"]["passed"] for name, arms in (("gpt-6-luna", small), ("gpt-6.1-sol", large))},
             "smallClBeatsBigNoManualTotalTokens": small["b"]["providerTotalTokens"] < large["c"]["providerTotalTokens"],
             "allTasksCompletedAfterInlineChecks": small["b"]["goalIncompleteAfterPassedInlineCheck"] == 0 and large["b"]["goalIncompleteAfterPassedInlineCheck"] == 0,
             "matchedExternalHarnessComparison": False,
             "productionCheckedPath": transport["allPassed"] and http["allPassed"] and model["allPassed"]}
    result = {"schema": "neyvia.cl.evidence.v2", "status": "partial-implementation-benchmark-gates-failed",
              "worktree": str(REPO), "branch": "track/cl",
              "implementationCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
              "acceptance": gates,
              "proofs": {"stdioChecks": len(transport["passed"]), "httpChecks": len(http["passed"]), "modelChecks": len(model["checks"]), "allPassed": gates["productionCheckedPath"]},
              "commands": {"neyvia.cl": ["neyvia_cl.DEFINITIONS", "WorkspaceTools.call and NativeToolRegistry registration", "manual_first.core_tools and CompactNeyviaMCPServer", "plugin PORTED and scoped Server tools/call", "SDK cl_tool", "existing authenticated /api/ui/tools/call", "desktop_bridge explicit persistent-service forwarding", "existing Tauri call_native_tool_command registration; source wiring only"], "neyvia.cl.describe": ["neyvia_cl.DEFINITIONS", "WorkspaceTools.call and NativeToolRegistry registration", "manual_first.core_tools and CompactNeyviaMCPServer", "plugin PORTED", "existing authenticated /api/ui/tools/call", "desktop_bridge explicit persistent-service forwarding", "existing Tauri call_native_tool_command registration; source wiring only"]},
              "baseline": {"tools": 293, "logicalFamilies": 63, "manuals": 25},
              "current": {"tools": len(inventory["tools"]), "logicalFamilies": len(inventory["families"]), "manuals": len(inventory["manuals"]), "groundedManuals": sum(row["grounding"]["ok"] for row in inventory["manuals"]), "compiledExactly": 25, "staticConformance": syntax},
              "benchmark": {"models": {"gpt-6-luna": small, "gpt-6.1-sol": large}, "taskSetSha256": canonical["taskSetSha256"], "cohort": "canonical, compact matched five-layer manuals, one attempt per task", "successes": 26, "cases": 30, "separateTestsRunByArmB": 0, "boundary": canonical["caveats"]},
              "migration": {"manualSources": "25 CL sources compile exactly through an archival conditional/schema bridge", "schemas": "295 canonical JSON MCP contracts and 29 first-component families roundtrip", "stdioPluginHttp": "Actual CL text, progressive describe, retained context aliases and original authority", "T18": "CL gateway exposes immutable T18 states/deltas; file source proven via HTTP; legacy JSON API retained", "T16": "CL gateway renders inspected UIA state; fixture models used real scoped UIA; direct legacy driver output retained", "receipts": "CL checked action R/D/I plus immutable raw receipts; legacy receipt consumers retained", "runPlans": "Generic CL state view and primer injection; legacy plan mutation/publication and managed gateways remain", "systemContext": "Approved primer plus L0; legacy gateway tool schemas still available; SDK and connected wiring not full live session proof"},
              "missing": ["47 static observer-check gaps across 18 manuals; conservative procedure-bound inventory has 49 occurrences", "Independent arbitrary pure-CL procedures and complete expression typing", "Complete realized dependency-aware impacts and live K/Q/V awareness/routing semantics", "Approved example codex-run.cl has invalid numeric qname segment step.1", "Complete managed/SDK, direct T16 and run-plan migration", "Matched standalone Claude Code/Codex/Cursor comparisons", "50-percent cold-start efficiency and small-model total-token targets"],
              "proposals": "docs/standard/CHANGES-from-codex.md",
              "preservation": {"nas": "not accessed or synchronized for this handoff; prohibited by plan12 section0", "push": False, "merge": False, "publicServicesTouched": False, "ownedBackendStopped": True, "rawHistory": ".agent_control/cl/benchmark", "agentsClosed": True, "largestDownloadBytes": 30882682, "globalInstallsOrConfigEdits": False},
              "sourceHashes": sources, "evidence": assets}
    write(MASTER, result)
    return result


def check():
    master = load(MASTER)
    for row in master["evidence"]:
        raw = (REPO / row["path"]).read_bytes()
        if digest(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("Evidence changed: " + row["path"])
    for row in master["sourceHashes"]:
        if digest((REPO / row["path"]).read_bytes().replace(b"\r\n", b"\n")) != row["utf8LfSha256"]:
            raise ValueError("Source changed since handoff: " + row["path"])
    for turn in load(PACKET / "provider-runs.json")["turns"]:
        for row in turn["files"]:
            raw = row["text"].encode("utf-8")
            if digest(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise ValueError("Embedded original provider bytes changed")
    benchmark = load(PACKET / "canonical-summary.json")
    if len(benchmark["runs"]) != 30 or sum(row["passed"] for row in benchmark["runs"]) != master["benchmark"]["successes"]:
        raise ValueError("Canonical case totals changed")
    for cohort in benchmark["cohorts"].values():
        for arm, reported in cohort["arms"].items():
            rows = [row for row in benchmark["runs"] if row["requestedModel"] == cohort["requestedModel"] and row["arm"] == arm]
            if len(rows) != reported["runs"] or sum(row["passed"] for row in rows) != reported["passed"] or sum(row["providerTotalTokens"] for row in rows) != reported["providerTotalTokens"] or sum(row["startContext"]["o200k_tokens"] for row in rows) != reported["serializedStartO200k"]:
                raise ValueError("Canonical arm aggregate disagrees with raw cases")
    return master


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Write the reviewable packet; otherwise only verify it")
    args = parser.parse_args()
    result = export() if args.export else check()
    print(json.dumps({"status": result["status"], "evidenceFiles": len(result["evidence"]), "sourceFiles": len(result["sourceHashes"]), "proofs": result["proofs"]}))


if __name__ == "__main__":
    main()
