"""Reviewed publisher cases plus isolated HTTP ownership/integrity proof.

Signed test-verifier fixtures exercise admission logic, not production scanner
findings or provisioned publisher signatures. HTTP never activates a package.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import http.cookiejar
import importlib.util
import inspect
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SCRATCH = REPO / ".agent_control/follow-publisher"
STATE = SCRATCH / "http"
PORT = 48445
OLD_ID = "community.oci-proof"
OWNED_ID = "community.reference.oci-proof"
TEST = "tests/test_marketplace_oci.py"
BASE = "1940bb15"
OUTPUT = REPO / "scripts/evidence/FOLLOW-publisher.json"

def isolate():
    import verify_follow_failures as failure_proof
    failure_proof.SCRATCH = SCRATCH
    failure_proof.isolate()
    os.environ.update({"NEYVIA_MODULE_ROOT": str(STATE / "modules"), "NEYVIA_OCI_VERIFIER_TRUST_PATH": ""})

def load_cases():
    path = REPO / TEST
    spec = importlib.util.spec_from_file_location("follow_publisher_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def assertions_preserved():
    original = subprocess.check_output(["git", "show", BASE + ":" + TEST], cwd=REPO).decode("utf-8")
    current = (REPO / TEST).read_text(encoding="utf-8")
    assert current.count('"moduleId": "' + OWNED_ID + '"') == 1
    normalized = current.replace('"moduleId": "' + OWNED_ID + '"', '"moduleId": "' + OLD_ID + '"')
    normalized = normalized.replace('return ModuleMarketplace(\n        tmp_path / "workspace",', 'return ModuleMarketplace(\n        ROOT,')
    assert ast.dump(ast.parse(original), include_attributes=False) == ast.dump(ast.parse(normalized), include_attributes=False), "Only owned ID and bounded fixture root may change"
    config_path = "config/neyvia_marketplace_toolchain.json"
    old_config = json.loads(subprocess.check_output(["git", "show", BASE + ":" + config_path], cwd=REPO))
    new_config = json.loads((REPO / config_path).read_text(encoding="utf-8"))
    trust_policy = new_config["policy"].pop("ociVerifierTrust")
    assert trust_policy == {"state": "unprovisioned", "configurationSource": "external-runtime-only", "privateKeysAllowedInNeyviaProcess": False}
    assert new_config == old_config, "Existing policy, runtimes and tool paths must remain unchanged"
    product_path = "src/grant_agent/module_marketplace.py"
    original_product = subprocess.check_output(["git", "show", BASE + ":" + product_path], cwd=REPO)
    current_product = (REPO / product_path).read_bytes()
    assert original_product.replace(b"\r\n", b"\n") == current_product.replace(b"\r\n", b"\n"), "Publisher and provenance product guards must remain unchanged"
    return {"entireOriginalASTPreservedExceptOwnedFixtureLiteralAndBoundedRoot": True,
            "configurationMergedOnlyUnprovisionedTrustMetadata": True, "publisherAndProvenanceProductGuardsUnchanged": True,
            "originalAssertCount": sum(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(original))),
            "originalSha256": hashlib.sha256(original.encode()).hexdigest(), "currentSha256": hashlib.sha256(current.encode()).hexdigest()}

def replay(module):
    selected = [row for row in json.loads((REPO / "scripts/evidence/FOLLOW-failures.json").read_text())["cases"] if row["rootCauseGroup"] == "publisher-ownership-admission"]
    assert len(selected) == 7 and all(row["id"].startswith(TEST + "::") for row in selected)
    import pytest
    cases = []
    # This nearby case was already passing; retain its registry/path/semver checks.
    names = [row["id"].split("::")[-1] for row in selected] + ["test_identifiers_registry_refs_and_semver_ranges_fail_closed"]
    for name in names:
        with tempfile.TemporaryDirectory(prefix="publisher-case-") as folder, pytest.MonkeyPatch.context() as patch:
            function = getattr(module, name)
            values = {"tmp_path": Path(folder), "monkeypatch": patch}
            try:
                function(**{arg: values[arg] for arg in inspect.signature(function).parameters})
            except Exception as exc:
                cases.append({"id": TEST + "::" + name, "passed": False, "exceptionType": type(exc).__name__})
            else:
                cases.append({"id": TEST + "::" + name, "passed": True})
        print(name + ": " + ("passed" if cases[-1]["passed"] else "failed"), flush=True)
    return {"passed": all(row["passed"] for row in cases), "historicalCasesReplayed": 7, "neighborCasesReplayed": 1, "cases": cases,
            "boundary": "Original reviewed assertion functions called directly in disposable fixtures. Ed25519 signatures are verified under isolated test-verifier trust; no real scanner or production publisher-signature claim."}

def http_proof(module):
    STATE.mkdir(parents=True, exist_ok=True)
    config = STATE / "config"
    config.mkdir(exist_ok=True)
    (config / "neyvia_marketplace_toolchain.json").write_text(json.dumps({"schema": "neyvia.marketplace-toolchain/v1", "policy": {}, "tools": {}}), encoding="utf-8")
    archive = module._archive(STATE / "publisher.nymod")
    manifest = module._manifest(archive)
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(route, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}" + route, data=body, headers={"Content-Type": "application/json"})
        try:
            with client.open(req, timeout=30) as response: return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc: return exc.code, json.loads(exc.read())
    checks = []
    def check(name, value):
        assert value, name
        checks.append({"name": name, "passed": True})
    def command(name, payload): return request("/api/backend", {"command": name, "payload": payload})
    process = None
    try:
        with (SCRATCH / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--serve"], cwd=REPO, env=os.environ.copy(), stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None: raise RuntimeError("Owned publisher backend exited")
                try:
                    if request("/api/health")[1].get("ok"): break
                except OSError: pass
                time.sleep(.1)
            else: raise TimeoutError("Owned publisher backend not ready")
            check("authenticated task-local HTTP session", request("/api/auth/local-session", {})[0] == 200)
            status, value = command("validate_module_manifest_command", {"manifest": manifest})
            check("owned publisher module validates through real backend", status == 200 and value["data"]["valid"])
            for identity in [OLD_ID, "community.referenceevil.oci-proof", "community.other.oci-proof"]:
                changed = json.loads(json.dumps(manifest)); changed["moduleId"] = identity
                status, value = command("validate_module_manifest_command", {"manifest": changed})
                check("unowned module rejected: " + identity, status == 200 and not value["data"]["valid"] and any("owned by publisher.id" in e for e in value["data"]["errors"]))
            changed = json.loads(json.dumps(manifest)); changed["signature"]["identity"] = "https://example.invalid/forged-owner"
            status, value = command("validate_module_manifest_command", {"manifest": changed})
            check("signature identity substitution rejected", status == 200 and not value["data"]["valid"])
            status, value = command("trust_module_publisher_command", {"manifest": manifest, "approvedBy": "disposable-fixture-owner"})
            check("explicit owner publisher binding recorded only in disposable module root", status == 200 and value["data"]["passed"] and value["data"]["evidence"]["publisherId"] == manifest["publisher"]["id"])
            status, value = command("inspect_module_package_command", {"manifest": manifest, "archivePath": str(archive)})
            check("real archived content passes structural/hash inspection", status == 200 and value["data"]["safeToVerify"])
            status, value = command("plan_module_oci_activation_command", {"manifest": manifest, "archivePath": str(archive)})
            check("missing authenticated install evidence remains activation-blocked", status == 200 and value["data"]["activationReady"] is False)
            archive.write_bytes(archive.read_bytes() + b"actual-integrity-tamper")
            status, value = command("inspect_module_package_command", {"manifest": manifest, "archivePath": str(archive)})
            check("changed actual archive bytes rejected", status == 200 and value["data"]["safeToVerify"] is False)
            check("HTTP proof never creates activation pointers", not list((STATE / "modules").rglob("current.json")))
        return {"passed": True, "port": PORT, "checks": checks, "productionVerifierTrustProvisioned": False,
                "publicServicesTouched": False, "activationPerformed": False}
    finally:
        if process is not None:
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--serve", action="store_true"); parser.add_argument("--diagnose", action="store_true"); args = parser.parse_args()
    isolate()
    if args.serve:
        sys.argv = [str(REPO / "scripts/run_web_backend.py"), "--host", "127.0.0.1", "--port", str(PORT), "--root", str(STATE), "--skip-runtime-auto-update"]
        runpy.run_path(sys.argv[0], run_name="__main__"); return
    module = load_cases()
    if args.diagnose:
        with tempfile.TemporaryDirectory(prefix="publisher-baseline-") as folder:
            archive = module._archive(Path(folder) / "baseline.nymod")
            manifest = module._manifest(archive)
            validation = module._marketplace(Path(folder)).validate_manifest(manifest)
            print(json.dumps({"valid": validation["valid"], "ownershipError": any("owned by publisher.id" in e for e in validation["errors"]), "moduleId": manifest["moduleId"], "publisherId": manifest["publisher"]["id"]}))
        return
    evidence = {"schema": "neyvia.FOLLOW.publisher.v1", "preservation": assertions_preserved(), "replay": replay(module)}
    assert evidence["replay"]["passed"], "Original publisher case assertions remain failing"
    evidence["http"] = http_proof(module)
    evidence["passed"] = True
    evidence["ownedProcessesStopped"] = True
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUTPUT.relative_to(REPO)), "directCases": len(evidence["replay"]["cases"]), "httpChecks": len(evidence["http"]["checks"]), "passed": True}))

if __name__ == "__main__": main()
