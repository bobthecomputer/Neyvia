from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.durability import atomic_write_json, atomic_write_text  # noqa: E402
from grant_agent.module_marketplace import ModuleMarketplace  # noqa: E402
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _spdx_document() -> dict[str, object]:
    return {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "dataLicense": "CC0-1.0",
        "name": "neyvia-marketplace-activation-proof",
        "documentNamespace": (
            "https://neyvia.local/spdx/marketplace-activation-proof/"
            f"{secrets.token_hex(8)}"
        ),
        "creationInfo": {
            "created": datetime.now(timezone.utc).isoformat(),
            "creators": ["Tool: Neyvia marketplace proof builder"],
        },
        "packages": [],
    }


def run_proof(output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=False)
    archive = output_root / "signed-content-proof.nymod"
    bundle = output_root / f"{archive.name}.sigstore.json"
    public_key = output_root / "publisher.pub"
    module_root = output_root / "modules"

    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "module/index.json",
            json.dumps(
                {
                    "kind": "neyvia.qa.signed-content-proof",
                    "message": "Verified package activation is real.",
                },
                separators=(",", ":"),
            ),
        )
        package.writestr(
            "context/index.json",
            json.dumps(
                {
                    "summary": (
                        "Signed marketplace proof capability. It exposes no "
                        "host permissions and remains lazy-loadable."
                    ),
                    "keywords": ["marketplace", "signature", "rollback"],
                },
                separators=(",", ":"),
            ),
        )
        package.writestr(
            "sbom.spdx.json",
            json.dumps(_spdx_document(), separators=(",", ":")),
        )

    manifest: dict[str, object] = {
        "schema": "neyvia.module-manifest/v1",
        "moduleId": "neyvia.qa.signed-content-proof",
        "version": "0.1.0",
        "name": "Signed marketplace activation proof",
        "summary": (
            "A real, permissionless content module used to verify the complete "
            "Neyvia marketplace activation transaction."
        ),
        "publisher": {
            "id": "neyvia.qa",
            "name": "Neyvia QA",
            "identity": "key:neyvia.qa.marketplace-proof",
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
            "keyId": "neyvia.qa.marketplace-proof",
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
                "route": "app://marketplace/neyvia.qa.signed-content-proof",
            }
        ],
        "distribution": {
            "registryRef": (
                "local://neyvia.qa.signed-content-proof@"
                f"sha256:{_sha256(archive)}"
            ),
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
    manifest_path = output_root / "manifest.json"
    canonical_path = output_root / "manifest.canonical.json"
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

    marketplace = ModuleMarketplace(ROOT, module_root=module_root)
    toolchain = marketplace.toolchain_snapshot()
    cosign = str(toolchain["tools"]["cosign"]["path"])
    if not toolchain["tools"]["cosign"]["healthy"]:
        raise RuntimeError("Pinned Cosign is not healthy")

    with tempfile.TemporaryDirectory(prefix="neyvia-marketplace-sign-") as temp:
        prefix = Path(temp) / "publisher"
        environment = dict(os.environ)
        environment["COSIGN_PASSWORD"] = secrets.token_urlsafe(32)
        key_generation = _run(
            [
                cosign,
                "generate-key-pair",
                "--output-key-prefix",
                str(prefix),
            ],
            env=environment,
        )
        public_key.write_bytes(prefix.with_suffix(".pub").read_bytes())
        signing = _run(
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
    trust = marketplace.trust_publisher(
        manifest,
        approved_by="neyvia.qa.proof-runner",
        public_key_path=public_key,
    )
    permission_review = marketplace.build_permission_review(
        manifest,
        approved_by="neyvia.qa.proof-runner",
        accepted_permissions=[],
    )
    install = marketplace.install_package(
        manifest,
        archive,
        permission_review=permission_review,
    )
    if not install["activated"]:
        raise RuntimeError(
            f"marketplace activation blocked by {install['blockedBy']}"
        )
    context = marketplace.active_context_snapshot()
    catalog = marketplace.installed_catalog()
    pointer = (
        module_root
        / str(manifest["moduleId"])
        / "current.json"
    )
    if context["moduleCount"] != 1 or catalog["activeCount"] != 1:
        raise RuntimeError("activated module is not discoverable")

    proof = {
        "schema": "neyvia.marketplace-activation-proof/v1",
        "passed": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "archivePath": str(archive),
        "archiveSha256": _sha256(archive),
        "manifestPath": str(manifest_path),
        "manifestSha256": validation["manifestSha256"],
        "bundlePath": str(bundle),
        "bundleSha256": _sha256(bundle),
        "publicKeyPath": str(public_key),
        "publicKeySha256": _sha256(public_key),
        "privateKeyRetained": False,
        "keyGeneration": key_generation,
        "signing": signing,
        "toolchain": toolchain,
        "publisherTrust": trust,
        "permissionReview": permission_review,
        "install": install,
        "catalog": catalog,
        "activeContext": context,
        "activationPointerPath": str(pointer),
        "activationPointerSha256": _sha256(pointer),
    }
    atomic_write_json(output_root / "proof-summary.json", proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real signed Neyvia marketplace activation proof."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=(
            ROOT
            / ".agent_control"
            / "capability_os"
            / "qa"
            / "marketplace-activation-proof"
            / datetime.now().strftime("%Y%m%d-%H%M%S")
        ),
    )
    args = parser.parse_args()
    proof = run_proof(args.output_root.resolve())
    print(
        json.dumps(
            {
                "passed": proof["passed"],
                "outputRoot": str(args.output_root.resolve()),
                "archiveSha256": proof["archiveSha256"],
                "manifestSha256": proof["manifestSha256"],
                "activeModules": proof["catalog"]["activeCount"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
