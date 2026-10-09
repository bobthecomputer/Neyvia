"""Compile authored Connected Language manuals to the existing JSON artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl


def is_skill(path: Path) -> bool:
    """A CL-Skill source (CL 1.1 skill format, e.g. manuals/cl/taste.cl) has no @manual header and no JSON artifact;
    it is checked by parsing it with the cl_skill runner instead of being compiled to a manual."""
    text = path.read_text(encoding="utf-8")
    return not text.startswith("-- @manual") and "\n-- @manual " not in text


def check_skill(path: Path) -> dict:
    from grant_agent.cl_skill import _parse_skill
    skill = _parse_skill(path)
    if not skill.checks or not skill.procedures:
        raise ValueError("CL-Skill without checks or procedures: " + str(path))
    source = path.read_text(encoding="utf-8")
    return {"id": skill.layer, "kind": "skill", "source": str(path), "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "checks": len(skill.checks), "judgements": len(skill.judges), "procedures": len(skill.procedures), "equal": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, help="Compile or check one owned authored manual or CL-Skill without rewriting other artifacts")
    parser.add_argument("--source-dir", type=Path, default=REPO / "manuals/cl")
    parser.add_argument("--artifact-dir", type=Path, default=REPO / "manuals")
    parser.add_argument("--index", type=Path, default=REPO / "config/neyvia_manuals.json")
    parser.add_argument("--bootstrap", action="store_true", help="Create CL sources from current JSON once; refuses to overwrite sources")
    parser.add_argument("--check", action="store_true", help="Compile in memory and compare artifacts, without writing")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.bootstrap and args.check:
        parser.error("--bootstrap and --check cannot be combined")
    if args.bootstrap:
        args.source_dir.mkdir(parents=True, exist_ok=True)
        existing = list(args.source_dir.glob("*.cl"))
        if existing:
            parser.error("Bootstrap refuses to overwrite existing CL sources")
        pending = []
        for path in sorted(args.artifact_dir.glob("*.manual.json")):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            source = manual_to_cl(data)
            if cl_to_manual(source) != data:
                raise ValueError("Manual roundtrip changed " + path.name)
            pending.append((args.source_dir / (data["id"] + ".cl"), source))
        for path, source in pending:
            path.write_text(source, encoding="utf-8", newline="\n")
    indexed = {}
    if not args.source_file and args.source_dir.resolve() == (REPO / "manuals/cl").resolve() and args.index.exists():
        entries = json.loads(args.index.read_text(encoding="utf-8"))["manuals"]
        identities = [row["id"] for row in entries]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate indexed manual identity")
        if any("clSource" in row for row in entries):
            for row in entries:
                if "clSource" not in row:
                    raise ValueError("Manual index lacks CL source: " + row["id"])
                path = (REPO / row["clSource"]).resolve()
                path.relative_to(args.source_dir.resolve())
                if path in indexed:
                    raise ValueError("Duplicate indexed CL source")
                indexed[path] = row
        if indexed:
            authored = {path for path in args.source_dir.glob("*.cl") if not is_skill(path)}
            if {path.resolve() for path in authored} != set(indexed):
                raise ValueError("CL sources and manual index differ")
            artifacts = {path.name for path in args.artifact_dir.glob("*.manual.json")}
            expected = {row["id"] + ".manual.json" for row in entries}
            if artifacts != expected:
                raise ValueError("JSON manual artifacts and CL index differ")
    skills = sorted(path for path in args.source_dir.glob("*.cl") if is_skill(path))
    sources = sorted(indexed) if indexed else sorted(path for path in args.source_dir.glob("*.cl") if not is_skill(path))
    if args.source_file:
        if not args.source_file.is_file(): parser.error("Selected source file does not exist")
        skills=[args.source_file] if is_skill(args.source_file) else []
        sources=[] if skills else [args.source_file]
    if not sources and not skills:
        parser.error("No authored CL sources found")
    results = []
    for path in sources:
        source = path.read_text(encoding="utf-8")
        data = cl_to_manual(source)
        if indexed and data["id"] != indexed[path]["id"]:
            raise ValueError("CL source identity differs from index: " + str(path))
        artifact = args.artifact_dir / (data["id"] + ".manual.json")
        if args.check or args.bootstrap:
            if not artifact.exists() or json.loads(artifact.read_text(encoding="utf-8-sig")) != data:
                raise ValueError("Compiled artifact differs: " + str(artifact))
        else:
            args.artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append({"id": data["id"], "source": str(path), "artifact": str(artifact), "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "chapters": len(data["chapters"]), "equal": True})
    skill_results = [check_skill(path) for path in skills]
    module_check = None
    if args.check and not args.source_file and args.source_dir.resolve() == (REPO / "manuals/cl").resolve():
        from grant_agent.module_map import check
        module_check = check()
    receipt = {"schema": "neyvia.cl.manual-compile.v1", "manuals": len(results), "results": results, "skills": skill_results,
               "mode": "bootstrap" if args.bootstrap else "check" if args.check else "compile", "modules": module_check}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manuals": len(results), "skills": len(skill_results), "equal": True, "mode": receipt["mode"]}))


if __name__ == "__main__":
    main()
