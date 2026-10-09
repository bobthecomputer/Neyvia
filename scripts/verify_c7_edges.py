"""Generate and execute adversarial contracts in owned, isolated state."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from c7_dependencies import configure as configure_dependencies
DEPENDENCY_ROOT = configure_dependencies()


def main():
    from grant_agent.edge_fixture_catalog import BUILDERS
    from grant_agent.proof_ports import c7_port_block, c7_run_root
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True, help="Explicit assigned loopback C7 worker port (48731-48739 or 48741-48749)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--semantic-fixtures", action="store_true")
    parser.add_argument("--family", action="append", choices=tuple(BUILDERS))
    args = parser.parse_args()
    try:
        assigned_ports = c7_port_block(args.port)
    except ValueError as error:
        parser.error(str(error))
    if args.family and not args.semantic_fixtures:
        parser.error("--family requires --semantic-fixtures")
    root = c7_run_root() / uuid.uuid4().hex
    root.mkdir(parents=True)
    # Isolate host discovery before importing any product modules.
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / key.lower()
        directory.mkdir(parents=True)
        os.environ[key] = str(directory)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", NEYVIA_C7_PORT=str(args.port), PYTHONIOENCODING="utf-8", NEYVIA_NAS_ROOT=str(root))
    os.environ["PYTHONPATH"] = str(REPO / "src")
    from grant_agent.proof_credential_guard import install
    install(root)

    def audit(event, values):
        if event in {"socket.connect", "socket.bind"}:
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"} or address[1] not in assigned_ports:
                raise PermissionError("C7 network fixture must use the explicit assigned loopback port")
    sys.addaudithook(audit)
    from grant_agent.proof_contracts import REPO as SOURCE, source_digest
    sources = ["src/grant_agent/edge_contracts.py", "src/grant_agent/native_tools.py", "src/grant_agent/native_arguments.py", "scripts/verify_c7_edges.py", "scripts/c7_dependencies.py", "uv.lock"]
    if not args.schema_only:
        sources += ["src/grant_agent/edge_journeys.py", "src/grant_agent/edge_notes.py", "src/grant_agent/neyvia_notes_tools.py", "src/grant_agent/proofs_notes_files.py", "config/proofs/notes-files.json",
                    "src/grant_agent/neyvia_agent.py", "src/grant_agent/action_receipts.py", "src/grant_agent/neyvia_settings.py", "src/grant_agent/proofs_settings.py",
                    "src/grant_agent/neyvia_awareness.py", "src/grant_agent/proofs_awareness.py", "src/grant_agent/neyvia_files_tools.py", "src/grant_agent/ui_command_bus.py",
                    "src/grant_agent/durability.py", "src/grant_agent/proof_credential_guard.py", "src/grant_agent/proof_contracts.py", "src/grant_agent/neyvia_mcp.py"]
    sources += ["src/grant_agent/neyvia_workspace_tools.py", "src/grant_agent/neyvia_manuals.py", "src/grant_agent/neyvia_mcp_stdio.py", "config/neyvia_manuals.json", "scripts/build_C7_manual.py"]
    sources += [path.relative_to(SOURCE).as_posix() for folder, pattern in (("config/proofs", "*.json"), ("manuals/cl", "*.cl"), ("manuals", "*.manual.json")) for path in (SOURCE / folder).glob(pattern)]
    if args.semantic_fixtures:
        from grant_agent.proof_ports import configure_ports
        configure_ports(assigned_ports)
        # Bind production owners as well as builders, so a changed owner cannot
        # retain a passing receipt from an earlier implementation.
        from grant_agent.proof_contracts import source_bindings
        sources += list(source_bindings())
        sources += ["src/grant_agent/edge_fixture_catalog.py"]
        sources += ["src/" + name.replace(".", "/") + ".py" for name in BUILDERS.values()]
    sources = sorted(set(sources))
    before = {name: source_digest(SOURCE / name) for name in sources}
    from grant_agent.edge_contracts import run
    report = run(root, include_journeys=not args.schema_only, semantic_fixtures=args.semantic_fixtures, families=args.family)
    report["sourceBindings"] = before
    report["sourceStable"] = before == {name: source_digest(SOURCE / name) for name in sources}
    report["ok"] = report["ok"] and report["sourceStable"]
    report["complete"] = report["complete"] and report["sourceStable"]
    report["explicitPort"] = args.port
    report["schemaOnly"] = args.schema_only
    report["dependencyRoot"] = str(DEPENDENCY_ROOT) if DEPENDENCY_ROOT else None
    if args.semantic_fixtures:
        from grant_agent.edge_fixture_catalog import summarize, completed_receipts
        report["semanticSummary"] = summarize(report["semanticCoverage"])
        report["familyReceipts"] = completed_receipts(root / "semantic-fixtures")
        baseline_path = REPO / "scripts/evidence/C7.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        import hashlib
        current = {(row["contract"], row["category"]): row for row in report["semanticCoverage"]}
        missing = [(row["contract"], row["category"]) for row in baseline["semanticCoverage"] if (row["contract"], row["category"]) not in current]
        if missing:
            raise ValueError("Baseline obligations disappeared: " + str(missing[:5]))
        report["baseline"] = {"path": "scripts/evidence/C7.json", "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "blockedPairs": sum(row["status"] == "blocked" for row in baseline["semanticCoverage"]),
            "reconciledPairs": len(baseline["semanticCoverage"]), "droppedPairs": 0,
            "formerlyBlocked": dict(__import__("collections").Counter(current[(row["contract"], row["category"])]["status"]
                for row in baseline["semanticCoverage"] if row["status"] == "blocked"))}
    output = args.output.resolve()
    if not output.is_relative_to(REPO):
        output.relative_to(c7_run_root())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("ok", "complete", "durationMs", "inventory", "counts")}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
