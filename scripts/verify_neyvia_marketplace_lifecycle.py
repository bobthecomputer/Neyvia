#!/usr/bin/env python3
"""Real signed marketplace lifecycle proof: install → activate → disable → rollback."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.durability import atomic_write_json, atomic_write_text  # noqa: E402
from grant_agent.module_marketplace import (  # noqa: E402
    MODULE_INSTALL_RECEIPT_SCHEMA,
    OCI_EVIDENCE_ATTESTATION_SCHEMA,
    OCI_EVIDENCE_POLICY_VERSION,
    OCI_REQUIRED_SECURITY_GATES,
    OCI_VERIFIER_TRUST_SCHEMA,
    ModuleMarketplace,
    _payload_tree_proof,
    _sha256,
)
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs  # noqa: E402

MODULE_ID = "neyvia.qa.signed-content-proof"
PUBLISHER_ID = "neyvia.qa"
PUBLISHER_IDENTITY = "key:neyvia.qa.marketplace-proof"
KEY_ID = "neyvia.qa.marketplace-proof"
VERIFIER = {
    "identity": "neyvia.qa.external-oci-verifier",
    "version": "1.0.0",
    "implementationSha256": "a" * 64,
    "keyId": "neyvia-qa-g2-verifier",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(args: list[str], *, env: dict[str, str] | None = None) -> dict[str, object]:
    completed = subprocess.run(
        args,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{Path(args[0]).name} failed ({completed.returncode}): "
            f"{completed.stderr[-2000:]}"
        )
    return {
        "returnCode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _spdx_document(name: str) -> dict[str, object]:
    return {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "dataLicense": "CC0-1.0",
        "name": name,
        "documentNamespace": (
            f"https://neyvia.local/spdx/{name}/{secrets.token_hex(8)}"
        ),
        "creationInfo": {
            "created": _utc_now(),
            "creators": ["Tool: Neyvia marketplace lifecycle proof"],
        },
        "packages": [],
    }


def _build_signed_package(
    marketplace: ModuleMarketplace,
    output_root: Path,
    *,
    version: str,
    message: str,
) -> dict[str, object]:
    package_root = output_root / f"package-{version}"
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=False)
    archive = package_root / f"signed-content-proof-{version}.nymod"
    bundle = package_root / f"{archive.name}.sigstore.json"
    public_key = package_root / "publisher.pub"

    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "module/index.json",
            json.dumps(
                {
                    "kind": "neyvia.qa.signed-content-proof",
                    "version": version,
                    "message": message,
                },
                separators=(",", ":"),
            ),
        )
        package.writestr(
            "context/index.json",
            json.dumps(
                {
                    "summary": (
                        "Signed marketplace lifecycle proof capability. "
                        "It exposes no host permissions and remains lazy-loadable."
                    ),
                    "keywords": ["marketplace", "signature", "rollback", version],
                },
                separators=(",", ":"),
            ),
        )
        package.writestr(
            "sbom.spdx.json",
            json.dumps(
                _spdx_document(f"neyvia-marketplace-lifecycle-{version}"),
                separators=(",", ":"),
            ),
        )

    manifest: dict[str, object] = {
        "schema": "neyvia.module-manifest/v1",
        "moduleId": MODULE_ID,
        "version": version,
        "name": "Signed marketplace lifecycle proof",
        "summary": (
            "A real, permissionless content module used to verify install, "
            "activate, disable, and rollback."
        ),
        "publisher": {
            "id": PUBLISHER_ID,
            "name": "Neyvia QA",
            "identity": PUBLISHER_IDENTITY,
        },
        "compatibility": {
            "moduleApi": "neyvia.module-api/v1",
            "neyvia": ">=0.1.0 <0.2.0",
            "platforms": ["windows-x86_64", "linux-x86_64"],
        },
        "runtime": {
            "kind": "content-pack",
            "isolation": "bridge-only",
            "entrypoint": "module/index.json",
        },
        "package": {
            "archiveSha256": _sha256(archive),
            "archiveBytes": archive.stat().st_size,
            "mediaType": "application/vnd.neyvia.module+zip",
            "sbomPath": "sbom.spdx.json",
            "license": "Apache-2.0",
            "sourceUrl": "https://github.com/neyvia/neyvia",
        },
        "signature": {
            "scheme": "sigstore-cosign-key-bundle",
            "bundlePath": bundle.name,
            "bundleLocation": "detached",
            "payload": "canonical-manifest",
            "keyId": KEY_ID,
        },
        "permissions": [],
        "capabilities": [
            {
                "operationId": "qa.read-marketplace-proof",
                "name": "Read marketplace proof",
                "description": "Read the signed, permissionless proof payload.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                },
                "outputSchema": {"type": "object"},
                "permissions": [],
            }
        ],
        "surfaces": [
            {
                "surfaceId": "qa.marketplace-proof",
                "kind": "embedded",
                "title": "Marketplace proof",
                "route": f"app://marketplace/{MODULE_ID}",
            }
        ],
        "dependencies": [],
        "distribution": {
            "registryRef": f"registry.local/neyvia-qa-signed-content-proof:{version}",
            "p2pEligible": True,
            "pinPolicy": "private-mesh",
            "mirrors": [],
        },
        "update": {
            "channel": "project-pinned",
            "rollback": True,
            "migrations": [],
        },
        "context": {
            "summaryIndex": "context/index.json",
            "lazyResources": True,
            "maxBootstrapBytes": 8192,
        },
    }
    manifest_path = package_root / "manifest.json"
    canonical_path = package_root / "manifest.canonical.json"
    atomic_write_json(manifest_path, manifest)
    atomic_write_text(
        canonical_path,
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )

    toolchain = marketplace.toolchain_snapshot()
    cosign = str(toolchain["tools"]["cosign"]["path"])
    if not toolchain["tools"]["cosign"]["healthy"]:
        raise RuntimeError("Pinned Cosign is not healthy")

    with tempfile.TemporaryDirectory(prefix="neyvia-marketplace-sign-") as temp:
        prefix = Path(temp) / "publisher"
        environment = dict(os.environ)
        environment["COSIGN_PASSWORD"] = secrets.token_urlsafe(32)
        _run(
            [cosign, "generate-key-pair", "--output-key-prefix", str(prefix)],
            env=environment,
        )
        public_key.write_bytes(prefix.with_suffix(".pub").read_bytes())
        _run(
            [
                cosign,
                "sign-blob",
                "--yes",
                "--key",
                str(prefix.with_suffix(".key")),
                "--bundle",
                str(bundle),
                str(canonical_path),
            ],
            env=environment,
        )

    validation = marketplace.validate_manifest(manifest)
    if not validation["valid"]:
        raise RuntimeError(f"manifest validation failed: {validation['errors']}")
    return {
        "version": version,
        "manifest": manifest,
        "manifestPath": str(manifest_path),
        "archivePath": str(archive),
        "bundlePath": str(bundle),
        "publicKeyPath": str(public_key),
        "manifestSha256": validation["manifestSha256"],
        "archiveSha256": _sha256(archive),
    }


def _provision_external_verifier(runtime_root: Path) -> tuple[Path, Ed25519PrivateKey]:
    verifier_root = runtime_root / "external-verifier"
    if verifier_root.exists():
        shutil.rmtree(verifier_root)
    verifier_root.mkdir(parents=True, exist_ok=False)
    private_key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"neyvia-g2-marketplace-external-verifier").digest()
    )
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )
    public_path = verifier_root / "verifier-public.pem"
    private_path = verifier_root / "verifier-private.pem"
    public_path.write_bytes(public_pem)
    private_path.write_bytes(
        private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        )
    )
    trust_path = verifier_root / "oci-verifier-trust.json"
    atomic_write_json(
        trust_path,
        {
            "schema": OCI_VERIFIER_TRUST_SCHEMA,
            "policyVersion": OCI_EVIDENCE_POLICY_VERSION,
            "maxAgeSeconds": 3600,
            "verifiers": {
                gate: [VERIFIER] for gate in OCI_REQUIRED_SECURITY_GATES
            },
            "publicKeys": {
                VERIFIER["keyId"]: {
                    "path": str(public_path.resolve()),
                    "sha256": hashlib.sha256(public_pem).hexdigest(),
                }
            },
        },
    )
    return trust_path.resolve(), private_key


def _attest_install_receipt(
    marketplace: ModuleMarketplace,
    package: dict[str, object],
    private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    manifest = package["manifest"]
    assert isinstance(manifest, dict)
    target = (
        marketplace.module_root
        / MODULE_ID
        / "versions"
        / str(package["version"])
    )
    receipt_path = target / ".neyvia" / "install-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != MODULE_INSTALL_RECEIPT_SCHEMA:
        raise RuntimeError("install receipt missing after install")
    payload_proof = _payload_tree_proof(
        target,
        manifest["runtime"]["entrypoint"],
    )
    subject, _subject_manifest, _registry = marketplace._oci_subject(
        manifest,
        str(package["archiveSha256"]),
        int(manifest["package"]["archiveBytes"]),
        payload_proof,
    )
    attested_receipts: list[dict[str, object]] = []
    for item in receipt.get("gateReceipts", []):
        if not isinstance(item, dict):
            continue
        gate = str(item.get("gate") or "")
        if gate not in OCI_REQUIRED_SECURITY_GATES:
            attested_receipts.append(item)
            continue
        verified_at = str(item.get("recordedAt") or _utc_now())
        attestation = {
            "schema": OCI_EVIDENCE_ATTESTATION_SCHEMA,
            "subject": subject,
            "verifier": VERIFIER,
            "policyVersion": OCI_EVIDENCE_POLICY_VERSION,
            "verifiedAt": verified_at,
        }
        attestation["authentication"] = {
            "scheme": "ed25519",
            "keyId": VERIFIER["keyId"],
            "signature": base64.b64encode(
                private_key.sign(
                    ModuleMarketplace._oci_attestation_signature_input(
                        gate,
                        item.get("evidence"),
                        attestation,
                    )
                )
            ).decode("ascii"),
        }
        updated = dict(item)
        updated["attestation"] = attestation
        attested_receipts.append(updated)
    receipt["gateReceipts"] = attested_receipts
    receipt["ociSubject"] = subject
    receipt["payloadProof"] = payload_proof
    atomic_write_json(receipt_path, receipt)
    return receipt


def _catalog_state(marketplace: ModuleMarketplace) -> dict[str, object]:
    catalog = marketplace.installed_catalog()
    module = next(
        (
            item
            for item in catalog["modules"]
            if item.get("moduleId") == MODULE_ID
        ),
        None,
    )
    return {
        "moduleCount": catalog["moduleCount"],
        "activeCount": catalog["activeCount"],
        "module": module,
    }


def run_proof(output_root: Path, runtime_root: Path) -> dict[str, object]:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=False)

    module_root = runtime_root / "modules"
    trust_path, private_key = _provision_external_verifier(runtime_root)
    os.environ["NEYVIA_MODULE_ROOT"] = str(module_root.resolve())
    os.environ["NEYVIA_OCI_VERIFIER_TRUST_PATH"] = str(trust_path)

    marketplace = ModuleMarketplace(
        ROOT,
        module_root=module_root,
        verifier_trust_path=trust_path,
    )
    steps: list[dict[str, object]] = []

    packages = [
        _build_signed_package(
            marketplace,
            output_root,
            version="1.0.0",
            message="Lifecycle proof version 1.",
        ),
        _build_signed_package(
            marketplace,
            output_root,
            version="1.1.0",
            message="Lifecycle proof version 2.",
        ),
    ]

    for package in packages:
        marketplace.trust_publisher(
            package["manifest"],
            approved_by="neyvia.qa.lifecycle-proof",
            public_key_path=package["publicKeyPath"],
        )
        permission_review = marketplace.build_permission_review(
            package["manifest"],
            approved_by="neyvia.qa.lifecycle-proof",
            accepted_permissions=[],
        )
        install = marketplace.install_package(
            package["manifest"],
            package["archivePath"],
            permission_review=permission_review,
            activate=False,
        )
        if install.get("blockedBy"):
            raise RuntimeError(f"install blocked: {install['blockedBy']}")
        attested = _attest_install_receipt(marketplace, package, private_key)
        activation = marketplace.activate_installed_module(
            MODULE_ID,
            requested_by="neyvia.qa.lifecycle-proof",
            version=str(package["version"]),
        )
        if activation.get("activated") is not True:
            raise RuntimeError(
                "activation failed: "
                + json.dumps(
                    {
                        "blockedBy": activation.get("blockedBy"),
                        "securityEvidenceErrors": activation.get(
                            "securityEvidenceErrors"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        catalog = _catalog_state(marketplace)
        steps.append(
            {
                "step": f"install-activate-{package['version']}",
                "installStatus": install.get("status"),
                "activated": True,
                "version": package["version"],
                "catalogState": catalog["module"]["state"] if catalog["module"] else None,
                "catalogVersion": catalog["module"]["version"] if catalog["module"] else None,
                "attestedReceiptId": attested.get("receiptId"),
                "ociManifestDigest": activation.get("ociManifestDigest"),
            }
        )

    catalog_after_v2 = _catalog_state(marketplace)
    if (
        not catalog_after_v2["module"]
        or catalog_after_v2["module"]["state"] != "active"
        or catalog_after_v2["module"]["version"] != "1.1.0"
        or catalog_after_v2["module"]["previousVersion"] != "1.0.0"
    ):
        raise RuntimeError("catalog did not reflect active 1.1.0 with previous 1.0.0")

    disabled = marketplace.disable_module(
        MODULE_ID,
        requested_by="neyvia.qa.lifecycle-proof",
        reason="Lifecycle proof disable step.",
    )
    catalog_disabled = _catalog_state(marketplace)
    if (
        not disabled.get("passed")
        or not catalog_disabled["module"]
        or catalog_disabled["module"]["state"] != "disabled"
    ):
        raise RuntimeError("disable did not move catalog state to disabled")
    steps.append(
        {
            "step": "disable",
            "passed": True,
            "catalogState": catalog_disabled["module"]["state"],
            "catalogVersion": catalog_disabled["module"]["version"],
        }
    )

    reactivated = marketplace.activate_installed_module(
        MODULE_ID,
        requested_by="neyvia.qa.lifecycle-proof",
        version="1.1.0",
    )
    catalog_reactivated = _catalog_state(marketplace)
    if (
        reactivated.get("activated") is not True
        or not catalog_reactivated["module"]
        or catalog_reactivated["module"]["state"] != "active"
    ):
        raise RuntimeError("re-activate after disable failed")
    steps.append(
        {
            "step": "activate-after-disable",
            "activated": True,
            "catalogState": catalog_reactivated["module"]["state"],
            "catalogVersion": catalog_reactivated["module"]["version"],
        }
    )

    rollback = marketplace.rollback_module(
        MODULE_ID,
        requested_by="neyvia.qa.lifecycle-proof",
        reason="Lifecycle proof rollback to 1.0.0.",
        target_version="1.0.0",
    )
    catalog_rollback = _catalog_state(marketplace)
    if (
        rollback.get("passed") is not True
        or not catalog_rollback["module"]
        or catalog_rollback["module"]["state"] != "active"
        or catalog_rollback["module"]["version"] != "1.0.0"
    ):
        raise RuntimeError("rollback did not restore active 1.0.0")
    steps.append(
        {
            "step": "rollback",
            "passed": True,
            "catalogState": catalog_rollback["module"]["state"],
            "catalogVersion": catalog_rollback["module"]["version"],
            "previousVersion": catalog_rollback["module"].get("previousVersion"),
        }
    )

    panel_view = {
        "moduleId": catalog_rollback["module"]["moduleId"],
        "state": catalog_rollback["module"]["state"],
        "version": catalog_rollback["module"]["version"],
        "previousVersion": catalog_rollback["module"]["previousVersion"],
        "publisherTrust": catalog_rollback["module"]["publisherTrust"],
        "signatureReceipt": catalog_rollback["module"]["signatureReceipt"],
        "staging": catalog_rollback["module"]["staging"],
        "actions": catalog_rollback["module"]["actions"],
    }

    proof = {
        "schema": "neyvia.marketplace-lifecycle-proof/v1",
        "passed": True,
        "generatedAt": _utc_now(),
        "moduleId": MODULE_ID,
        "moduleRoot": str(module_root.resolve()),
        "verifierTrustPath": str(trust_path),
        "packages": [
            {
                "version": item["version"],
                "manifestPath": item["manifestPath"],
                "archivePath": item["archivePath"],
                "publicKeyPath": item["publicKeyPath"],
                "archiveSha256": item["archiveSha256"],
                "manifestSha256": item["manifestSha256"],
            }
            for item in packages
        ],
        "steps": steps,
        "finalCatalog": catalog_rollback,
        "panelVisibleState": panel_view,
        "privateKeyRetained": False,
        "notes": [
            "Cosign key pairs were generated ephemerally and discarded.",
            "OCI attestations were signed by an external verifier key outside managed roots.",
            "No publish and no live NAS pointer changes were performed.",
        ],
    }
    atomic_write_json(output_root / "proof-summary.json", proof)
    atomic_write_json(
        output_root / "panel-visible-state.json",
        panel_view,
    )
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove real marketplace install/activate/disable/rollback."
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=(
            ROOT
            / ".agent_control"
            / "capability_os"
            / "qa"
            / "marketplace-lifecycle-proof"
            / stamp
        ),
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "AppData" / "Local" / "NeyviaG2MarketplaceProof" / stamp,
    )
    args = parser.parse_args()
    proof = run_proof(args.output_root.resolve(), args.runtime_root.resolve())
    print(
        json.dumps(
            {
                "passed": proof["passed"],
                "outputRoot": str(args.output_root.resolve()),
                "runtimeRoot": str(args.runtime_root.resolve()),
                "finalState": proof["panelVisibleState"]["state"],
                "finalVersion": proof["panelVisibleState"]["version"],
                "steps": [item["step"] for item in proof["steps"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
