"""Reproduce T4 journeys and write the consolidated, source-bound release receipt."""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"
SOURCES = [
    "src/grant_agent/research.py", "src/grant_agent/native_tools.py", "src/grant_agent/native_access.py",
    "src/grant_agent/neyvia_agent.py", "src/grant_agent/operation_adapters.py", "src/grant_agent/workspace_patches.py",
    "src/grant_agent/web_documents.py", "src/grant_agent/mcp_broker.py", "src/grant_agent/mcp_http_transport.py",
    "src/grant_agent/model_tool_intelligence.py", "manuals/tools-depth.manual.json", "manuals/workspace.manual.json",
    "config/neyvia_manuals.json", "docs/manuals/tools-depth.md", "docs/evidence/T4-wiring.md",
    "scripts/build_t4_manual.py", "scripts/verify_t4.py", "scripts/verify_t4_core.py",
    "scripts/verify_t4_search.py", "scripts/verify_t4_mcp.py", "scripts/verify_t4_feedback.py",
]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-existing", action="store_true", help="Collect already observed component receipts without rerunning journeys")
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    base_commit = git("rev-parse", "HEAD")
    if args.collect_existing and (EVIDENCE / "T4.json").exists():
        base_commit = json.loads((EVIDENCE / "T4.json").read_text(encoding="utf-8"))["baseCommit"]
    if not args.collect_existing:
        subprocess.run([sys.executable, str(REPO / "scripts/verify_t4_core.py")], cwd=REPO, check=True)
        from verify_t4_search import verify as search
        (EVIDENCE / "T4-search.json").write_text(json.dumps(search(), indent=2) + "\n", encoding="utf-8")
        subprocess.run([sys.executable, str(REPO / "scripts/verify_t4_feedback.py"), "--root",
                        str(REPO / ".agent_control/T4" / ("feedback-" + uuid.uuid4().hex)),
                        "--output", str(EVIDENCE / "T4-feedback.json")], cwd=REPO, check=True, capture_output=True)
        subprocess.run([sys.executable, str(REPO / "scripts/verify_t4_mcp.py")], cwd=REPO, check=True)
    components = {name: json.loads((EVIDENCE / ("T4-" + name + ".json")).read_text(encoding="utf-8"))
                  for name in ("core", "search", "mcp", "feedback")}
    if not all(row.get("ok", row.get("passed", False)) for row in components.values()):
        raise RuntimeError("A component journey did not pass; preserve its failure receipt")
    hashes = {}
    for name in SOURCES:
        raw = (REPO / name).read_bytes()
        if name.endswith(".py"):
            ast.parse(raw, filename=name)
        if name.endswith(".json"):
            json.loads(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    forbidden = ["src/grant_agent/web_backend.py", "src/grant_agent/mission_control.py", "web/src/neyvia/NeyviaShell.jsx"]
    changed = git("diff", "--name-only").splitlines()
    if any(path in forbidden or Path(path).name == "NeyviaShell.jsx" for path in changed):
        raise RuntimeError("Forbidden shared source has changes")
    report = {"schema": "neyvia.T4.v1", "ok": True, "generatedAt": datetime.now(timezone.utc).isoformat(),
              "branch": git("branch", "--show-current"), "baseCommit": base_commit,
              "python": sys.executable, "portsUsed": [48141, 48142, 48148],
              "acceptance": {"ripgrepWithFallback": components["search"]["passed"],
                             "guardedRangesAndPatches": components["core"]["ok"],
                             "cachedDocumentsPassagesCitations": components["core"]["ok"],
                             "fiveObservedMcpStages": components["mcp"]["ok"],
                             "indexedFeedback": components["feedback"]["ok"]},
              "coreChecks": len(components["core"]["checks"]), "sourceSha256": hashes,
              "receipts": components,
              "limits": ["MCP interoperability observed against controlled real stdio/HTTP services; external providers were not certified",
                         "HTTP extraction accepts readable text/HTML; JavaScript and PDF extraction remain separate tools",
                         "Cooperative workspace writers are serialized; arbitrary external editors have only the immediate pre-replace hash check",
                         "No desktop rendering or model-quality claim; production backend HTTP and compact MCP are the proven tool paths"],
              "nas": {"status": "pending", "reason": "Configured NAS route uses Tailscale, explicitly excluded by this task; local recoverable snapshot verified"}}
    output = EVIDENCE / "T4.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    snapshot = REPO / ".agent_control/T4" / ("snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".zip")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    names = SOURCES + ["scripts/evidence/T4.json"] + ["scripts/evidence/T4-" + name + ".json" for name in components]
    with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(REPO / name, name)
    with zipfile.ZipFile(snapshot) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Local snapshot CRC verification failed")
        for name in names:
            if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256((REPO / name).read_bytes()).digest():
                raise RuntimeError("Local snapshot content mismatch: " + name)
    (snapshot.with_suffix(".receipt.json")).write_text(json.dumps({"ok": True, "snapshot": str(snapshot),
        "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(), "files": len(names), "contentVerified": True}, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "receipt": str(output), "coreChecks": report["coreChecks"], "snapshot": str(snapshot)}))


if __name__ == "__main__":
    main()
