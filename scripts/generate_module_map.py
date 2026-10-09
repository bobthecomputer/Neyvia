"""Generate or check the source-derived module registry; no test framework."""
import argparse
import hashlib
import json
import sys
import shutil
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.module_map import REPO, REGISTRY, check, generate, documentation

GENERATION_RECEIPT = Path(r"D:\NeyviaRuns\P22\module-generator\canonical.json")
GENERATION_RECEIPT_SCHEMA = "neyvia.module-map-generation-receipt.v1"


def write_changed(path, content):
    """Preserve unchanged generated documents and their timestamps."""
    if path.is_file() and path.read_text(encoding='utf-8') == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8', newline='\n')
    return True


def generation_receipt(result, registry_content, docs):
    """Describe bytes and semantic docs from this completed real generation."""
    registry_bytes = registry_content.encode("utf-8")
    generated_docs = {
        path.relative_to(REPO).as_posix(): hashlib.sha256(
            content.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest()
        for path, content in docs.items()
    }
    return {
        "schema": GENERATION_RECEIPT_SCHEMA,
        "registry": {
            "path": REGISTRY.relative_to(REPO).as_posix(),
            "canonicalLf": True,
            "bytes": len(registry_bytes),
            "sha256": hashlib.sha256(registry_bytes).hexdigest(),
        },
        "sourceHashes": result["sourceHashes"],
        "generatorSources": result["generatorSources"],
        "configurationHashes": result["configurationHashes"],
        "generatedDocCount": len(generated_docs),
        "generatedDocs": generated_docs,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check()))
    else:
        previous = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.is_file() else {"modules": []}
        result = generate()
        expected = {row["id"] for row in result["modules"]}
        # An incoming merge can add generated documents absent from both the
        # current registry and its previous version. Inspect actual generated
        # folders too; Windows paths compare module-name casing correctly.
        module_root = (REGISTRY.parents[1] / 'modules').resolve()
        expected_folders = {module_root / identity for identity in expected}
        folders = {module_root / row['id'] for row in previous['modules']}
        folders.update(path.parent for path in module_root.glob('*/README.md'))
        for folder in folders:
            if folder in expected_folders:
                continue
            folder = folder.resolve()
            folder.relative_to((REGISTRY.parents[1] / "modules").resolve())
            retired_root = Path('D:/NeyviaRuns/P22/module-map-retired').resolve()
            retired = (retired_root / (folder.name + "-" + uuid.uuid4().hex)).resolve()
            retired.relative_to(retired_root)
            if folder.is_dir():
                retired.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(folder), str(retired))
        registry_content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        write_changed(REGISTRY, registry_content)
        updated = 0
        docs = documentation(result)
        for path, content in docs.items():
            updated += write_changed(path, content)
        checked = check()
        if checked.get("ok") is not True:
            raise RuntimeError("Generated module registry failed its post-write check")
        receipt = generation_receipt(result, registry_content, docs)
        GENERATION_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        write_changed(GENERATION_RECEIPT, json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"modules": len(result["modules"]), "updatedDocuments": updated,
                          "path": str(REGISTRY), "generationReceipt": str(GENERATION_RECEIPT)}))
