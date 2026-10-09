"""Measured, read-only outcomes for Neyvia's three source generators."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import time
import uuid


REPO = Path(__file__).resolve().parents[2]
CONTRACTS = {
    "p22.manual-compiler": ("scripts/cl_compile_manuals.py", "manual-compiler"),
    "p22.module-registry": ("scripts/generate_module_map.py", "module-registry"),
    "p22.manual-cache": ("scripts/build_fixcl_manual_cache.py", "manual-cache"),
}
GENERATION_RECEIPT = Path(r"D:\NeyviaRuns\P22\module-generator\canonical.json")
GENERATION_RECEIPT_SCHEMA = "neyvia.module-map-generation-receipt.v1"


def _run_check(script: str) -> tuple[dict | None, dict]:
    """Run the actual CLI module in-process so sys.monitoring sees its lines."""
    source = REPO / script
    if not source.is_file():
        raise FileNotFoundError(f"Generator check script is missing: {script}")
    original_argv = list(sys.argv)
    original_path = list(sys.path)
    old_cache_bypass = os.environ.get("NEYVIA_MANUAL_CACHE_BYPASS")
    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = 0
    error = None
    try:
        sys.argv[:] = [str(source), "--check"]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                runpy.run_path(str(source), run_name="__main__")
            except SystemExit as caught:
                if caught.code not in (None, 0):
                    exit_code = caught.code if isinstance(caught.code, int) else 1
                    error = f"generator exited with status {caught.code}"
            except Exception as caught:  # Preserve the real failing command and its message.
                exit_code = 1
                error = f"{type(caught).__name__}: {caught}"
    finally:
        sys.argv[:] = original_argv
        sys.path[:] = original_path
        if old_cache_bypass is None:
            os.environ.pop("NEYVIA_MANUAL_CACHE_BYPASS", None)
        else:
            os.environ["NEYVIA_MANUAL_CACHE_BYPASS"] = old_cache_bypass

    lines = [line.strip() for line in stdout.getvalue().splitlines() if line.strip()]
    payload = None
    if exit_code == 0:
        try:
            payload = json.loads(lines[-1]) if lines else None
        except (ValueError, IndexError):
            error = "check returned no JSON summary"
            exit_code = 1
    return payload, {"exitCode": exit_code, "error": error,
                     "stdout": stdout.getvalue()[-2500:], "stderr": stderr.getvalue()[-2500:]}


def _validate_generation_receipt(receipt: dict, registry_bytes: bytes, actual: dict,
                                 docs: dict, checked: dict) -> None:
    """Bind a real-generation receipt to current canonical registry and docs."""
    if not isinstance(receipt, dict) or receipt.get("schema") != GENERATION_RECEIPT_SCHEMA:
        raise ValueError("Missing or unsupported real module generation receipt")
    expected_registry = (json.dumps(actual, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    registry = receipt.get("registry")
    if (registry_bytes != expected_registry or not isinstance(registry, dict)
            or registry.get("path") != "config/neyvia.modules.json"
            or registry.get("canonicalLf") is not True
            or registry.get("bytes") != len(registry_bytes)
            or registry.get("sha256") != hashlib.sha256(registry_bytes).hexdigest()):
        raise ValueError("Real-generation receipt does not bind the canonical registry bytes")
    expected_docs = {
        path.relative_to(REPO).as_posix(): hashlib.sha256(
            content.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest()
        for path, content in docs.items()
    }
    if (receipt.get("generatedDocCount") != len(expected_docs)
            or receipt.get("generatedDocs") != expected_docs):
        raise ValueError("Real-generation receipt does not bind generated documentation semantics")
    for key in ("sourceHashes", "generatorSources", "configurationHashes"):
        if receipt.get(key) != actual.get(key):
            raise ValueError("Real-generation receipt has stale " + key)
    if checked.get("ok") is not True:
        raise ValueError("Current module-map source and documentation check failed")


def _assert_receipt_rejections(root: Path, receipt: dict, registry_bytes: bytes,
                               actual: dict, docs: dict, checked: dict) -> list[dict]:
    """Exercise the receipt verifier against three isolated tampered receipts."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch = (root / ("module-map-receipt-" + uuid.uuid4().hex)).resolve()
    scratch.relative_to(root)
    scratch.mkdir(parents=True)
    mutations = {
        "module-map.receipt-rejects-registry-change": lambda row: row["registry"].update(sha256="0" * 64),
        "module-map.receipt-rejects-document-change": lambda row: row["generatedDocs"].update(
            {next(iter(row["generatedDocs"]), "MODULES.md"): "0" * 64}),
        "module-map.receipt-rejects-source-binding-change": lambda row: row["sourceHashes"].update(
            {next(iter(row["sourceHashes"]), "src/example.py"): "0" * 64}),
    }
    cases = []
    try:
        for identity, mutate in mutations.items():
            changed = json.loads(json.dumps(receipt))
            mutate(changed)
            path = scratch / (identity.rsplit(".", 1)[-1] + ".json")
            path.write_text(json.dumps(changed), encoding="utf-8")
            tampered = json.loads(path.read_text(encoding="utf-8"))
            rejected = False
            try:
                _validate_generation_receipt(tampered, registry_bytes, actual, docs, checked)
            except ValueError:
                rejected = True
            if not rejected:
                raise ValueError("Generation receipt mutation was accepted: " + identity)
            cases.append({"id": identity, "ok": True})
        return cases
    finally:
        if scratch.is_relative_to(root) and scratch.exists():
            shutil.rmtree(scratch)


def _assert_generated_registry(catalog_root: str | Path) -> dict:
    """Reuse a real generator receipt, falling back to the pure generator if stale."""
    from .module_map import REGISTRY, REPO, check, documentation, generate

    receipt = None
    if GENERATION_RECEIPT.is_file():
        try:
            registry_bytes = REGISTRY.read_bytes()
            committed = json.loads(registry_bytes.decode("utf-8"))
            docs = documentation(committed)
            checked = check()
            receipt = json.loads(GENERATION_RECEIPT.read_text(encoding="utf-8"))
            _validate_generation_receipt(receipt, registry_bytes, committed, docs, checked)
            expected_readmes = {path.resolve() for path in docs if path.name == "README.md"}
            receipt_cases = _assert_receipt_rejections(
                Path(catalog_root), receipt, registry_bytes, committed, docs, checked)
            return {"semanticOutputEqual": True, "generatedModules": len(committed["modules"]),
                    "generatedDocuments": len(docs), "generatedModuleReadmes": len(expected_readmes),
                    "generationReceiptReused": True, "receiptBindingCases": receipt_cases}
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            receipt = None

    generated = generate(catalog_root=catalog_root)
    committed = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if generated != committed:
        raise ValueError("Generated module registry differs semantically from config/neyvia.modules.json")

    docs = documentation(generated)
    for path, content in docs.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            raise ValueError("Generated module documentation differs: " + str(path.relative_to(REPO)))
    expected_readmes = {path.resolve() for path in docs if path.name == "README.md"}
    actual_readmes = {path.resolve() for path in (REPO / "modules").glob("*/README.md")}
    if actual_readmes != expected_readmes:
        raise ValueError("Generated module documentation has missing or stale module READMEs")

    return {"semanticOutputEqual": True, "generatedModules": len(generated["modules"]),
            "generatedDocuments": len(docs), "generatedModuleReadmes": len(expected_readmes),
            "generationReceiptReused": False}


def _assert_source_currency(root: Path) -> dict:
    """Prove public source changes stale currency while config content is never opened or hashed."""
    from unittest.mock import patch
    from .module_map import source_digest, source_hashes, source_texts

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch = (root / ("module-map-currency-" + uuid.uuid4().hex)).resolve()
    scratch.relative_to(root)
    scratch.mkdir()
    source = scratch / "public_surface.py"
    account_config = scratch / "synthetic-account-config.json"
    source.write_text("PUBLIC_REVISION = 1\n", encoding="utf-8")
    # Deliberately synthetic and never read by this proof.
    account_config.write_text('{"account":"synthetic","credential":"not-a-real-secret"}\n', encoding="utf-8")
    files = [source.name, account_config.name]
    original_text = Path.read_text
    original_bytes = Path.read_bytes
    protected_reads = []

    def refuse_config_read(path, *args, **kwargs):
        if path.resolve() == account_config:
            protected_reads.append("read_text")
            raise AssertionError("Synthetic account configuration was opened")
        return original_text(path, *args, **kwargs)

    def refuse_config_hash(path, *args, **kwargs):
        if path.resolve() == account_config:
            protected_reads.append("read_bytes")
            raise AssertionError("Synthetic account configuration was hashed")
        return original_bytes(path, *args, **kwargs)

    try:
        with patch.object(Path, "read_text", refuse_config_read), patch.object(Path, "read_bytes", refuse_config_hash):
            before_text = source_texts(files, repo=scratch)
            before_hashes = source_hashes(files, repo=scratch)
            rejected_direct_digest = False
            try:
                source_digest(account_config)
            except ValueError:
                rejected_direct_digest = True
            if (set(before_text) != {source.name} or set(before_hashes) != {source.name}
                    or not rejected_direct_digest or protected_reads):
                raise ValueError("Source currency inspected or hashed the synthetic account configuration")
            source.write_text("PUBLIC_REVISION = 2\n", encoding="utf-8")
            after_hashes = source_hashes(files, repo=scratch)
        if before_hashes == after_hashes:
            raise ValueError("A public source edit did not stale its source currency")
        return {"sourceEditStalesCurrency": True, "syntheticAccountConfigNeverRead": True,
                "syntheticAccountConfigNeverHashed": True, "fixtureSourceFiles": len(after_hashes),
                "fixtureOwnedInputFiles": len(files),
                "sourceCurrencyCases": [
                    {"id": "module-map.public-source-edit-stales-currency", "ok": True},
                    {"id": "module-map.synthetic-account-config-skipped", "ok": True,
                     "readAttempted": False, "hashed": False},
                ]}
    finally:
        if scratch.is_relative_to(root) and scratch.exists():
            shutil.rmtree(scratch)


def _assert_summary(identity: str, value: dict | None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Generator check produced no structured summary")
    if identity == "p22.manual-compiler":
        if value.get("equal") is not True or value.get("mode") != "check":
            raise ValueError(f"CL compilation or semantic artifact equality failed: {value}")
        if not isinstance(value.get("manuals"), int) or value["manuals"] < 1:
            raise ValueError(f"No compiled CL manuals were checked: {value}")
        if not isinstance(value.get("skills"), int) or value["skills"] < 1:
            raise ValueError(f"No CL skills were checked: {value}")
    elif identity == "p22.module-registry":
        if value.get("ok") is not True or not isinstance(value.get("modules"), int) or value["modules"] < 1:
            raise ValueError(f"Source-derived module registry check failed: {value}")
        if not isinstance(value.get("files"), int) or value["files"] < 1:
            raise ValueError(f"No source files were checked against module ownership: {value}")
        if any(value.get(key) for key in ("missingFiles", "missingActions", "unownedFiles")):
            raise ValueError(f"Module map has missing or unowned sources/actions: {value}")
        if (value.get("semanticOutputEqual") is not True
                or value.get("generatedModules") != value.get("modules")
                or not isinstance(value.get("generatedDocuments"), int)
                or value["generatedDocuments"] < 1
                or not isinstance(value.get("generatedModuleReadmes"), int)):
            raise ValueError(f"Actual module generator output or rendered documents differ: {value}")
        if (value.get("sourceEditStalesCurrency") is not True
                or value.get("syntheticAccountConfigNeverRead") is not True
                or value.get("syntheticAccountConfigNeverHashed") is not True
                or value.get("fixtureOwnedInputFiles") != value.get("fixtureSourceFiles") + 1):
            raise ValueError(f"Source-only currency boundary failed: {value}")
        receipt_cases = value.get("receiptBindingCases")
        if value.get("generationReceiptReused") is True:
            if (not isinstance(receipt_cases, list) or len(receipt_cases) != 3
                    or any(row.get("ok") is not True for row in receipt_cases)
                    or {row.get("id") for row in receipt_cases} != {
                        "module-map.receipt-rejects-registry-change",
                        "module-map.receipt-rejects-document-change",
                        "module-map.receipt-rejects-source-binding-change"}):
                raise ValueError(f"Real-generation receipt binding C7 cases were incomplete: {value}")
        elif value.get("generationReceiptReused") is not False:
            raise ValueError(f"Generation receipt reuse state was not reported: {value}")
        currency_cases = value.get("sourceCurrencyCases")
        if (not isinstance(currency_cases, list) or len(currency_cases) != 2
                or any(row.get("ok") is not True for row in currency_cases)
                or {row.get("id") for row in currency_cases} != {
                    "module-map.public-source-edit-stales-currency",
                    "module-map.synthetic-account-config-skipped"}):
            raise ValueError(f"Source currency C7 cases were incomplete: {value}")
    elif identity == "p22.manual-cache":
        if value.get("checked") is not True or value.get("bytecodeProvisioned") is not False:
            raise ValueError(f"Compiled manual cache was stale or the check wrote bytecode: {value}")
        if not isinstance(value.get("manuals"), int) or value["manuals"] < 1:
            raise ValueError(f"No compiled manuals were included in the cache check: {value}")
        digest = value.get("manifestSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"Cache check did not report its compiled manifest SHA-256: {value}")
    else:
        raise KeyError(identity)
    return value


def self_check(root: str | Path) -> dict:
    """Execute selected source checks once and report only their real results."""
    from .contract_gate import wants

    root = Path(root).resolve()
    selected = [identity for identity in CONTRACTS if wants(identity)]
    started = time.perf_counter()
    cases = []
    for identity in selected:
        script, label = CONTRACTS[identity]
        case_started = time.perf_counter()
        command = None
        try:
            value, command = _run_check(script)
            if command["exitCode"] != 0:
                raise RuntimeError(command["error"] or f"{label} check exited nonzero")
            if identity == "p22.module-registry":
                value = {**(value or {}), **_assert_generated_registry(root),
                         **_assert_source_currency(root)}
            observed = _assert_summary(identity, value)
            cases.append({"id": identity, "contracts": [identity], "ok": True,
                          "observed": observed, "command": {"script": script, "args": ["--check"],
                          "mode": "in-process", "exitCode": 0},
                          "elapsedMs": round((time.perf_counter() - case_started) * 1000, 2)})
        except Exception as error:
            cases.append({"id": identity, "contracts": [identity], "ok": False,
                          "error": f"{type(error).__name__}: {error}",
                          "script": script, "args": ["--check"], "mode": "in-process",
                          **({"diagnostic": command} if command is not None else {}),
                          "elapsedMs": round((time.perf_counter() - case_started) * 1000, 2)})
    passed = [row["id"] for row in cases if row.get("ok") is True]
    return {"schema": "neyvia.p22.generator-outcomes.v1", "area": "generator-outcomes",
            "ok": bool(cases) and len(passed) == len(selected), "contracts": passed,
            "cases": cases, "runtimeState": str(root),
            "measurement": "Python sys.monitoring traces the actual in-process generator checks",
            "durationMs": round((time.perf_counter() - started) * 1000, 2)}
