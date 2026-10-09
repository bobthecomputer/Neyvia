"""Package the declared local add-on components for the existing verified downloader.

No sources are copied and no runtimes are downloaded. Manifests pin source bytes;
rerun this command when a payload changes. Packages need the core Python runtime.
"""
from __future__ import annotations

import ast
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "config/onboarding_packs.json"


def import_closure(paths: list[str], *, root: Path | None = None) -> list[str]:
    """Include module-level local imports; optional dynamic adapters remain core dependencies."""
    selected = set(paths)
    repository = root or REPO
    pending = [path for path in paths if path.startswith("src/grant_agent/") and path.endswith(".py")]
    selected.add("src/grant_agent/__init__.py")
    while pending:
        path = pending.pop()
        tree = ast.parse((repository / path).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or not node.level or not node.module:
                continue
            source = Path(path).parent.joinpath(node.module.replace(".", "/")).as_posix() + ".py"
            if (repository / source).is_file() and source not in selected:
                selected.add(source)
                pending.append(source)
    output = sorted(selected)
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    from grant_agent.proofs_e_host import check_import_closure
    check_import_closure(repository, paths, output)
    return output


def build(pack_ids: set[str] | None = None, *, manifest_only: bool = False) -> list[dict]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    packages = registry["packages"]
    selected = set(pack_ids) if pack_ids is not None else None
    if selected is not None:
        unknown = selected - packages.keys()
        if unknown:
            raise ValueError(f"Unknown package ids: {', '.join(sorted(unknown))}")
        non_local = sorted(identity for identity in selected if not packages[identity].get("localComponents"))
        if non_local:
            raise ValueError(f"Packages are not local components: {', '.join(non_local)}")
    elif manifest_only:
        raise ValueError("--manifest-only requires at least one --pack-id")
    summary = []
    for identity, definition in packages.items():
        if selected is not None and identity not in selected:
            continue
        if not definition.get("localComponents"):
            continue
        folder = REPO / "config/onboarding_packs" / identity
        folder.mkdir(parents=True, exist_ok=True)
        descriptor = {"schema": "neyvia.local-components/v1", "packId": identity,
                      "scope": "local-components", "requires": "Installed Neyvia core Python >=3.11 and its declared dependencies",
                      **{key: definition[key] for key in ("description", "entrypoints", "missing")}}
        if not manifest_only:
            (folder / "package.json").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
        files = []
        for relative in import_closure(definition["contents"]) + [f"config/onboarding_packs/{identity}/package.json"]:
            source = (REPO / relative).resolve()
            if not source.is_relative_to(REPO) or not source.is_file():
                raise ValueError(f"Missing or out-of-scope source: {relative}")
            payload = source.read_bytes()
            files.append({"path": "package.json" if source.name == "package.json" else relative,
                          "url": "../../../" + relative, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        total = sum(row["size"] for row in files)
        if total > 200 * 1024 * 1024:
            raise ValueError(f"{identity} exceeds 200 MiB")
        version = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
        manifest = {"schema": "neyvia.base-pack/v1", "packId": identity, "version": version,
                    "channel": "local-components", "files": files, "totalSize": total}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        summary.append({"packId": identity, "files": len(files), "bytes": total, "version": version})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerate local onboarding package manifests; no archive is created.")
    parser.add_argument("--pack-id", action="append", dest="pack_ids",
                        help="Build only this local component package (repeat to select more than one).")
    parser.add_argument("--manifest-only", action="store_true",
                        help="Write only selected manifest.json files; requires --pack-id.")
    args = parser.parse_args()
    print(json.dumps(build(set(args.pack_ids) if args.pack_ids else None,
                           manifest_only=args.manifest_only), indent=2))
