"""Run only owned local host/receipt/artifact journeys with compact source bindings."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", action="append")
    parser.add_argument("--category", action="append", choices=("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"))
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("Only explicitly assigned C7 ports 48741-48749 are permitted")
    root = REPO / ".agent_control/proofs/c7c-artifact-manual" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = root / "home" / key.lower(); folder.mkdir(parents=True)
        os.environ[key] = str(folder)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), PYTHONPATH=str(REPO / "src"), NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0")
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WEB_BACKEND_URL"):
        os.environ.pop(key, None)
    from grant_agent.proof_credential_guard import install
    install(root)
    def audit(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            raise PermissionError("Artifact/manual proof admits no network operations")
    sys.addaudithook(audit)
    from grant_agent import edge_fixture_artifact_manual as fixture
    contracts = {}
    for path in (REPO / "config/proofs").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("contracts", []):
            contracts[row["id"]] = row
    source_paths = ["src/grant_agent/edge_fixture_artifact_manual.py", "scripts/prove_C7c_artifact_manual.py",
                    "src/grant_agent/connected_sessions/codex_writer.py", "src/grant_agent/connected_sessions/plan_limits.py",
                    "src/grant_agent/nearby_send.py", "src/grant_agent/web_backend_workspace.py", "scripts/package_onboarding_packs.py",
                    "src/grant_agent/proofs_e_host.py", "src/grant_agent/proofs_d_host.py", "src/grant_agent/proof_credential_guard.py"]
    source_paths += ["src/grant_agent/neyvia_manuals.py", "src/grant_agent/manual_contracts.py", "src/grant_agent/manual_versions.py", "config/neyvia_manuals.json"]
    source_paths += [path.relative_to(REPO).as_posix() for folder, pattern in (("manuals", "*.manual.json"), ("manuals/cl", "*.cl")) for path in (REPO / folder).glob(pattern)]
    bindings = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in source_paths}
    if args.family:
        fixture.FAMILIES = {key: value for key, value in fixture.FAMILIES.items() if key in args.family}
    rows = fixture.run(root, contracts, args.category or ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"))
    stable = bindings == {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in source_paths}
    report = {"ok": stable and all(row["status"] == "passed" for row in rows), "sourceStable": stable, "explicitPort": args.port,
              "sourceBindings": bindings, "rows": rows, "scratch": str(root), "networkDenied": True,
              "pairs": sum(len(row["contracts"]) for row in rows)}
    target = args.output.resolve(); target.relative_to(REPO)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "pairs": report["pairs"], "failed": [row["id"] for row in rows if row["status"] != "passed"]}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
