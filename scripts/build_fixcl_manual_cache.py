"""Seal fully checked CL manual artifacts for fast, exact-byte cold admission."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compile-bytecode", action="store_true",
                        help="Provision ignored local Python bytecode for fresh-process startup")
    args = parser.parse_args()
    if args.check and args.compile_bytecode:
        parser.error("--check cannot write bytecode")
    os.environ["NEYVIA_MANUAL_CACHE_BYPASS"] = "1"
    from grant_agent.neyvia_manuals import _COMPILED_MANIFEST, _COMPILER_FILES, document, records
    from grant_agent.cl.integration import index_lines

    entries = {}
    tool_owners = {}
    procedure_owners = {}
    proof_ids = set()
    for record in records():
        if not record.get("clSource"):
            continue
        _, data = document(record)  # CL projection, artifact equality, schema validation.
        for declaration in data.get("proofs", {}).get("contracts", []):
            identity = declaration["id"]
            if identity in proof_ids:
                raise ValueError("Duplicate manual proof ID: " + identity)
            proof_ids.add(identity)
        for chapter in data["chapters"].values():
            for section in ("state", "actions", "checks"):
                for row in chapter[section].values():
                    tool_owners.setdefault(row["tool"], set()).add(record["id"])
            layer = "cua" if record["id"] == "computer-use" else record["id"]
            for name in chapter["procedures"]:
                procedure_owners.setdefault(layer + "." + name, set()).add(record["id"])
        entries[record["id"]] = {
            "source": record["clSource"],
            "sourceSha256": sha(REPO / record["clSource"]),
            "artifact": record["path"],
            "artifactSha256": sha(REPO / record["path"]),
        }
    manifest = {
        "schema": "neyvia.compiled-manual-cache.v1",
        "compiler": {name: sha(REPO / name) for name in _COMPILER_FILES},
        "indexSourceSha256": sha(REPO / "config/neyvia_manuals.json"),
        "indexLines": index_lines(),
        "manuals": entries,
        "toolOwners": {name: sorted(owners) for name, owners in sorted(tool_owners.items())},
        "procedureOwners": {name: sorted(owners) for name, owners in sorted(procedure_owners.items())},
    }
    output = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not _COMPILED_MANIFEST.is_file() or _COMPILED_MANIFEST.read_text(encoding="utf-8") != output:
            raise SystemExit("CL manual cache manifest is stale")
    else:
        _COMPILED_MANIFEST.write_text(output, encoding="utf-8")
    if args.compile_bytecode:
        from grant_agent.local_provisioning import ensure_bytecode
        if not ensure_bytecode(REPO)["ok"]:
            raise SystemExit("Python bytecode provisioning is disabled")
    print(json.dumps({"manuals": len(entries), "manifestSha256": hashlib.sha256(output.encode()).hexdigest(),
                      "checked": args.check, "bytecodeProvisioned": args.compile_bytecode}))


if __name__ == "__main__":
    main()
