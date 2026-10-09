"""Offline outcome contract for the actual local onboarding-pack generator."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import time
import uuid
from pathlib import Path

CONTRACT = "p22.pack-generator.local-components"
CONTRACTS = (CONTRACT,)
REPO = Path(__file__).resolve().parents[2]
GENERATOR = "scripts/package_onboarding_packs.py"


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(f"Contract {CONTRACT}: {message}")


def _copy_source_inputs(repo: Path, scratch: Path, registry: dict) -> None:
    """Create a confined source mirror sufficient for the generator's real API."""
    shutil.copytree(repo / "src/grant_agent", scratch / "src/grant_agent",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for definition in registry["packages"].values():
        if not definition.get("localComponents"):
            continue
        for relative in definition.get("contents", []):
            source = (repo / relative).resolve()
            _require(source.is_relative_to(repo) and source.is_file(),
                     f"declared local component is missing or outside the checkout: {relative}")
            target = scratch / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _entrypoint_exists(scratch: Path, manifest: dict, entrypoint: str) -> bool:
    module, symbol = entrypoint.split(":", 1)
    relative = "src/" + module.replace(".", "/") + ".py"
    row = next((item for item in manifest["files"] if item["path"] == relative), None)
    if row is None:
        return False
    source = (scratch / row["url"].removeprefix("../../../")).read_text(encoding="utf-8")
    tree = ast.parse(source)
    parts = symbol.split(".")
    if len(parts) == 1:
        return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[0]
                   for node in tree.body)
    return any(isinstance(node, ast.ClassDef) and node.name == parts[0]
               and any(isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and member.name == parts[1] for member in node.body)
               for node in tree.body)


def check_local_build(scratch: Path, built: list[dict], registry: dict) -> list[dict]:
    """Open the emitted packages and check their semantic component bindings."""
    expected = {name: definition for name, definition in registry["packages"].items()
                if definition.get("localComponents")}
    emitted = [row["packId"] for row in built]
    _require(len(emitted) == len(set(emitted)) and set(emitted) == set(expected),
             "generator omitted, duplicated, or added a local-component package")
    semantic = []
    for row in built:
        base = scratch / "config/onboarding_packs" / row["packId"]
        descriptor = json.loads((base / "package.json").read_text(encoding="utf-8"))
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        names = [item["path"] for item in manifest["files"]]
        ok = (descriptor.get("schema") == "neyvia.local-components/v1"
              and descriptor.get("scope") == "local-components"
              and descriptor.get("entrypoints") == expected[row["packId"]].get("entrypoints")
              and descriptor.get("description") == expected[row["packId"]].get("description")
              and descriptor.get("missing") == expected[row["packId"]].get("missing")
              and manifest.get("schema") == "neyvia.base-pack/v1"
              and manifest.get("channel") == "local-components"
              and manifest.get("packId") == row["packId"]
              and descriptor.get("packId") == row["packId"]
              and manifest.get("version") == row["version"]
              and manifest.get("totalSize") == row["bytes"]
              and len(manifest["files"]) == row["files"]
              and manifest.get("totalSize") == sum(item["size"] for item in manifest["files"])
              and "package.json" in names
              and len(names) == len(set(names))
              and all("\\" not in name and not name.startswith("/") for name in names))
        for item in manifest["files"]:
            target = (scratch / item["url"].removeprefix("../../../")).resolve()
            ok = ok and target.is_relative_to(scratch) and target.is_file()
            if ok:
                payload = target.read_bytes()
                ok = (len(payload) == item["size"]
                      and hashlib.sha256(payload).hexdigest() == item["sha256"])
        for entrypoint in descriptor["entrypoints"]:
            ok = ok and _entrypoint_exists(scratch, manifest, entrypoint)
        _require(ok, f"generated component meaning or source binding changed for {row['packId']}")
        semantic.append({"packId": row["packId"], "fileCount": len(names),
                         "bytes": manifest["totalSize"], "entrypoints": descriptor["entrypoints"],
                         "openedAndBound": True})
    _require(bool(semantic), "generator emitted no local-component packages")
    return semantic


def self_check(root=None):
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = REPO.resolve()
    root = (Path(root).resolve() if root is not None
            else repo / ".agent_control/p22/pack-generator-outcomes")
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / uuid.uuid4().hex
    scratch.mkdir()
    registry = json.loads((repo / "config/onboarding_packs.json").read_text(encoding="utf-8"))
    (scratch / "config").mkdir()
    scratch_registry = scratch / "config/onboarding_packs.json"
    scratch_registry.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    _copy_source_inputs(repo, scratch, registry)

    spec = importlib.util.spec_from_file_location("p22_actual_onboarding_pack_generator",
                                                  repo / GENERATOR)
    _require(spec is not None and spec.loader is not None, "actual generator could not be loaded")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.REPO = scratch
    generator.REGISTRY = scratch_registry

    # Exercise the production build() API in process; all output paths are scratch-local.
    built = generator.build()
    components = check_local_build(scratch, built, registry)

    # Re-run against a scratch-only malicious registry and require production refusal.
    bad_registry = json.loads(scratch_registry.read_text(encoding="utf-8"))
    identity = next(name for name, value in bad_registry["packages"].items()
                    if value.get("localComponents"))
    bad_registry["packages"][identity]["contents"].append("../../outside.txt")
    bad_path = (scratch / "../../outside.txt").resolve()
    _require(not bad_path.exists(), "unsafe-path sentinel already exists outside the scratch tree")
    scratch_registry.write_text(json.dumps(bad_registry), encoding="utf-8")
    refused = False
    try:
        generator.build()
    except ValueError as error:
        refused = "out-of-scope" in str(error)
    _require(refused and not bad_path.exists(), "generator accepted an out-of-scope component path or wrote outside scratch")

    case = {"id": CONTRACT, "contracts": list(CONTRACTS), "ok": True,
            "generatedPackCount": len(built), "components": components,
            "badPathRefused": True, "scratchOnly": True}
    return {"ok": True, "contracts": list(CONTRACTS),
            "outcomes": [{"id": CONTRACT, "status": "PASS"}],
            "cases": [case], "failures": [],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "stateRoot": str(scratch),
            "frontier": "Exercises local package generation, generated semantic bindings, and path refusal only; no downloads, installs, activation, or external delivery."}
