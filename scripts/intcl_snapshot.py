"""Copy current tracked source bytes to a task-local pytest snapshot."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--base", type=Path,
                        help="Prior task-local snapshot; hardlink unchanged historical receipts and copy ordinary source, then overlay current source bytes")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    target = repo / ".agent_control/INTCL" / (args.label + "-src")
    if target.exists():
        parser.error("snapshot path exists; use a fresh label")
    target.mkdir(parents=True)
    hashes = {}
    if args.base:
        base = args.base.resolve()
        if not base.is_relative_to(repo / ".agent_control/INTCL"):
            parser.error("base must be a task-local INTCL snapshot")
        previous = base.parent / (base.name.removesuffix("-src") + "-snapshot.json")
        manifest = json.loads(previous.read_text(encoding="utf-8"))
        for name, digest in manifest["hashes"].items():
            source = base / name
            if not source.is_file():
                continue
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name.startswith("scripts/evidence/"):
                os.link(source, destination)
            else:
                shutil.copy2(source, destination)
            hashes[name] = digest
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repo).decode("utf-8").split("\0")
    excluded = []
    overlaid = []
    for name in sorted(set(names)):
        if not name:
            continue
        normalized = name.lower()
        if normalized.startswith(".agent_control/") or any(word in normalized for word in ("nas_access_runbook", "nas_codex2_", "auth.json", "credentials.json", "admin_password")):
            excluded.append(name)
            continue
        source = repo / name
        if not source.is_file():
            continue
        destination = target / name
        if args.base and name.startswith("scripts/evidence/"):
            continue  # Historical raw receipts are irrelevant to implementation overlays.
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if args.base and hashes.get(name) == digest:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".intcl-copy")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        hashes[name] = digest
        overlaid.append(name)
    manifest = {"snapshot": str(target), "files": len(hashes), "hashes": hashes,
                "excluded": excluded, "overlaid": overlaid,
                "base": str(args.base.resolve()) if args.base else None,
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()}
    (target.parent / (args.label + "-snapshot.json")).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(target), "files": len(hashes), "excluded": excluded,
                      "overlaid": overlaid if args.base else len(overlaid)}))


if __name__ == "__main__":
    main()
