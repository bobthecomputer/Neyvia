"""Validate CL manual sources and regenerate their JSON and Markdown artifacts."""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import document, records, validate
from manual_procedures import audit_content
from render_manuals import main as render_views

TOOL_MANUALS = {
    "neyvia.sidebar.tidy": "neyvia",
    "neyvia.sidebar.policy": "neyvia",
    "neyvia.plan.update": "agents",
    "neyvia.terminal.list": "workspace",
    "neyvia.terminal.read": "workspace",
    "neyvia.dictation.status": "dictation",
    "neyvia.dictation.transcribe": "dictation",
}

def refresh_schemas(data, registry):
    """Refresh only tool contracts; authored guards and procedures stay intact."""
    for chapter in data["chapters"].values():
        for action in chapter["actions"].values():
            # Availability probes can inspect remote mounts or launch discovery.
            # A schema refresh needs only the registered static tool contract.
            data["schemas"][action["schema"]] = registry._specs[action["tool"]].input_schema

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Scratch registry root")
    parser.add_argument("--check", action="store_true", help="Check views without writing them")
    parser.add_argument("--refresh-schemas", action="store_true", help="Regenerate embedded schemas from live tools, then validate and render")
    args = parser.parse_args()
    if args.check and args.refresh_schemas:
        parser.error("--check cannot be combined with --refresh-schemas")
    root = args.root or Path(tempfile.mkdtemp(prefix="neyvia-manual-content-"))
    registry = NativeToolRegistry(root)
    results = []
    documents = []
    coverage = {}
    for row in records():
        data = document(row)[1]
        if args.refresh_schemas:
            refresh_schemas(data, registry)
        audit_content(data)
        try:
            results.append(validate(data, registry))
        except ValueError as exc:
            raise ValueError(f"{row['path']}: {exc}; inspect tool changes, then run scripts/build_grounded_manuals.py --refresh-schemas") from exc
        documents.append((row, data))
        for chapter in data["chapters"].values():
            for action in chapter["actions"].values():
                coverage.setdefault(action["tool"], set()).add(row["id"])
    required = {**TOOL_MANUALS, **{name: "cross-pc" for name in registry._handlers if name.startswith("neyvia.devices.")}}
    missing = [f"{tool} in {manual}" for tool, manual in required.items() if manual not in coverage.get(tool, set())]
    if missing:
        raise ValueError("Manual tool coverage missing: " + ", ".join(missing))
    if args.refresh_schemas:
        for row, data in documents:
            if row.get("clSource"):
                from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
                metadata = {name: {"mutability_class": spec.mutability_class} for name, spec in registry._specs.items()}
                source = manual_to_cl(data, metadata)
                if cl_to_manual(source) != data:
                    raise ValueError("Schema refresh changed authored manual semantics: " + row["id"])
                (REPO / row["clSource"]).write_text(source, encoding="utf-8")
            (REPO / row["path"]).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"grounded": True, "manuals": len(results), "chapters": sum(row["chapters"] for row in results)}))
    return render_views()

if __name__ == "__main__":
    raise SystemExit(main())
