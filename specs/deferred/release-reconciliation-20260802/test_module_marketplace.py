from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from grant_agent.module_marketplace import ModuleMarketplace
from grant_agent.sdk import (
    check_module_marketplace_toolchain_updates,
    disable_module,
    get_active_module_context,
    get_module_marketplace_browse,
    get_module_marketplace_toolchain,
    inspect_module_package,
    install_module_package,
    list_installed_modules,
    plan_module_install,
    review_module_permissions,
    rollback_module,
    trust_module_publisher,
    validate_module_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _archive(path: Path, *, unsafe: bool = False) -> Path:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "module/index.json",
            b'{"kind":"reference-content","resources":["context/index.json"]}',
        )
        package.writestr("context/index.json", b'{"summary":"proof"}')
        package.writestr(
            "sbom.spdx.json",
            b"""{
              "spdxVersion":"SPDX-2.3",
              "SPDXID":"SPDXRef-DOCUMENT",
              "dataLicense":"CC0-1.0",
              "name":"reference-proof",
              "documentNamespace":"https://example.test/spdx/reference-proof",
              "creationInfo":{
                "created":"2026-07-24T00:00:00Z",
                "creators":["Tool: reference-test"]
              },
              "packages":[]
            }""",
        )
        if unsafe:
            package.writestr("../escape.txt", b"blocked")
    path.with_name(f"{path.name}.sigstore.json").write_text(
        "{}",
        encoding="utf-8",
    )
    return path


def _manifest(archive: Path, *, version: str = "1.2.3") -> dict:
    return {
        "schema": "neyvia.module-manifest/v1",
        "moduleId": "community.reference-proof",
        "version": version,
        "name": "Reference proof",
        "summary": "A signed, sandboxed reference capability.",
        "publisher": {
            "id": "community.reference",
            "name": "Reference Publisher",
            "identity": (
                "https://github.com/example/reference/"
                ".github/workflows/release.yml@refs/heads/main"
            ),
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
            "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archiveBytes": archive.stat().st_size,
            "mediaType": "application/vnd.neyvia.module+zip",
            "sbomPath": "sbom.spdx.json",
            "license": "Apache-2.0",
            "sourceUrl": "https://github.com/example/reference",
        },
        "signature": {
            "scheme": "sigstore-cosign-bundle",
            "bundlePath": f"{archive.name}.sigstore.json",
            "bundleLocation": "detached",
            "payload": "canonical-manifest",
            "identity": (
                "https://github.com/example/reference/"
                ".github/workflows/release.yml@refs/heads/main"
            ),
            "issuer": "https://token.actions.githubusercontent.com",
        },
        "permissions": [
            {
                "permission": "artifact.read",
                "scope": "selected-workspace-files",
                "reason": "Read the artifact selected by the operator.",
                "required": True,
            }
        ],
        "capabilities": [
            {
                "operationId": "reference.inspect",
                "name": "Inspect reference",
                "description": "Inspect one selected artifact.",
                "inputSchema": {"type": "object"},
                "outputSchema": {"type": "object"},
                "permissions": ["artifact.read"],
            }
        ],
        "surfaces": [
            {
                "surfaceId": "reference.panel",
                "kind": "embedded",
                "title": "Reference panel",
                "route": "app://reference/panel",
            }
        ],
        "distribution": {
            "registryRef": (
                f"registry.example/neyvia/community.reference-proof:{version}"
            ),
            "p2pEligible": True,
            "pinPolicy": "nas-and-installed-peers",
            "mirrors": ["ipfs://private-mesh/by-sha256"],
        },
        "update": {
            "channel": "stable",
            "rollback": True,
            "migrations": [],
        },
        "context": {
            "summaryIndex": "context/index.json",
            "lazyResources": True,
            "maxBootstrapBytes": 8192,
        },
    }


def test_marketplace_manifest_and_archive_are_inspected_before_activation(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path / "reference.nymod")
    manifest = _manifest(archive)
    marketplace = ModuleMarketplace(ROOT)

    validation = marketplace.validate_manifest(manifest)
    inspection = marketplace.inspect_package(manifest, archive)
    plan = marketplace.build_install_plan(manifest, archive)

    assert validation["valid"] is True, validation
    assert inspection["safeToVerify"] is True, inspection
    assert inspection["activationReady"] is False
    assert inspection["signatureStatus"] == "verification_required"
    assert plan["canStage"] is True
    assert plan["canActivate"] is False
    assert plan["distribution"]["p2pEligible"] is True
    assert "cosign-bundle-verification" in plan["blockedBy"]
    assert "publisher-trust" in plan["blockedBy"]
    assert plan["targetPath"].endswith(
        "community.reference-proof\\versions\\1.2.3"
    ) or plan["targetPath"].endswith(
        "community.reference-proof/versions/1.2.3"
    )

    sdk_validation = validate_module_manifest(manifest, workspace_root=ROOT)
    sdk_inspection = inspect_module_package(
        manifest,
        archive,
        workspace_root=ROOT,
    )
    sdk_plan = plan_module_install(
        manifest,
        archive,
        workspace_root=ROOT,
        current_version="1.2.2",
    )
    assert sdk_validation["valid"] is True
    assert sdk_inspection["safeToVerify"] is True
    assert sdk_plan["currentVersion"] == "1.2.2"
    assert sdk_plan["canActivate"] is False


def test_marketplace_rejects_traversal_and_secret_bearing_manifests(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path / "unsafe.nymod", unsafe=True)
    manifest = _manifest(archive)
    marketplace = ModuleMarketplace(ROOT)

    inspection = marketplace.inspect_package(manifest, archive)
    manifest["password"] = "must-never-enter-a-module-manifest"
    validation = marketplace.validate_manifest(manifest)

    assert inspection["safeToVerify"] is False
    assert any("safe package-relative path" in item for item in inspection["errors"])
    assert validation["valid"] is False
    assert any("secret-bearing" in item for item in validation["errors"])


class _PassingGateMarketplace(ModuleMarketplace):
    """Use real lifecycle code while replacing only slow external gate calls."""

    def _publisher_trust_receipt(self, payload):
        return (
            self._gate_receipt(
                "publisher-trust",
                "passed",
                module_id=payload["moduleId"],
                version=payload["version"],
                evidence={"bindingId": "unit-test-binding"},
            ),
            {"bindingId": "unit-test-binding"},
        )

    def _signature_receipt(self, payload, inspection, binding, work_root):
        return self._gate_receipt(
            "cosign-bundle-verification",
            "passed",
            module_id=payload["moduleId"],
            version=payload["version"],
            evidence={"manifestSha256": inspection["manifestSha256"]},
        )

    def _malware_receipt(self, payload, archive, extracted):
        return self._gate_receipt(
            "malware-scan",
            "passed",
            module_id=payload["moduleId"],
            version=payload["version"],
        )

    def _sbom_receipt(self, payload, extracted, receipt_root):
        generated = receipt_root / "generated.spdx.json"
        generated.write_text(
            (
                extracted / payload["package"]["sbomPath"]
            ).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return (
            self._gate_receipt(
                "sbom-policy",
                "passed",
                module_id=payload["moduleId"],
                version=payload["version"],
            ),
            generated,
        )

    def _vulnerability_receipt(self, payload, generated_sbom):
        return self._gate_receipt(
            "vulnerability-scan",
            "passed",
            module_id=payload["moduleId"],
            version=payload["version"],
        )


def test_marketplace_activates_disables_and_rolls_back_without_patching_host(
    tmp_path: Path,
) -> None:
    module_root = tmp_path / "modules"
    marketplace = _PassingGateMarketplace(ROOT, module_root=module_root)

    first_archive = _archive(tmp_path / "reference-1.2.3.nymod")
    first_manifest = _manifest(first_archive, version="1.2.3")
    first_review = marketplace.build_permission_review(
        first_manifest,
        approved_by="operator@example.test",
        accepted_permissions=["artifact.read"],
    )
    first = marketplace.install_package(
        first_manifest,
        first_archive,
        permission_review=first_review,
    )

    second_archive = _archive(tmp_path / "reference-1.2.4.nymod")
    second_manifest = _manifest(second_archive, version="1.2.4")
    second_review = marketplace.build_permission_review(
        second_manifest,
        approved_by="operator@example.test",
        accepted_permissions=["artifact.read"],
    )
    second = marketplace.install_package(
        second_manifest,
        second_archive,
        permission_review=second_review,
    )

    catalog = marketplace.installed_catalog()
    context = marketplace.active_context_snapshot()
    disabled = marketplace.disable_module(
        first_manifest["moduleId"],
        requested_by="operator@example.test",
        reason="Verify reversible disable.",
    )
    rolled_back = marketplace.rollback_module(
        first_manifest["moduleId"],
        requested_by="operator@example.test",
        reason="Verify prior-version rollback.",
    )
    pointer = marketplace._read_json(
        module_root / first_manifest["moduleId"] / "current.json"
    )

    assert first["activated"] is True
    assert second["activated"] is True
    assert catalog["activeCount"] == 1
    assert catalog["modules"][0]["version"] == "1.2.4"
    assert context["moduleCount"] == 1
    assert context["modules"][0]["capabilities"][0]["operationId"] == "reference.inspect"
    assert disabled["passed"] is True
    assert rolled_back["passed"] is True
    assert pointer["currentVersion"] == "1.2.3"
    assert pointer["previousVersion"] == "1.2.4"
    assert not (ROOT / "community.reference-proof").exists()


def test_sdk_exposes_marketplace_lifecycle_without_hidden_activation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = _archive(tmp_path / "sdk-reference.nymod")
    manifest = _manifest(archive)
    module_root = tmp_path / "sdk-modules"
    review = review_module_permissions(
        manifest,
        approved_by="sdk-operator",
        accepted_permissions=["artifact.read"],
        workspace_root=ROOT,
        module_root=module_root,
    )

    assert review["archiveSha256"] == manifest["package"]["archiveSha256"]
    assert list_installed_modules(
        workspace_root=ROOT,
        module_root=module_root,
    )["moduleCount"] == 0
    assert get_active_module_context(
        workspace_root=ROOT,
        module_root=module_root,
    )["moduleCount"] == 0
    snapshot = get_module_marketplace_toolchain(
        workspace_root=ROOT,
        module_root=module_root,
    )
    assert snapshot["tools"]["cosign"]["version"] == "3.1.2"
    assert snapshot["tools"]["wasmtime"]["version"] == "47.0.2"
    assert callable(install_module_package)
    assert callable(check_module_marketplace_toolchain_updates)
    assert callable(trust_module_publisher)
    assert callable(disable_module)
    assert callable(rollback_module)


def test_creator_build_is_deterministic_and_publish_seed_is_content_addressed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "module").mkdir(parents=True)
    (source / "context").mkdir()
    (source / "module" / "index.json").write_text(
        '{"kind":"reference-content","resources":["context/index.json"]}',
        encoding="utf-8",
    )
    (source / "context" / "index.json").write_text(
        '{"summary":"proof"}',
        encoding="utf-8",
    )
    (source / "sbom.spdx.json").write_text(
        json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "SPDXID": "SPDXRef-DOCUMENT",
                "dataLicense": "CC0-1.0",
                "name": "reference-proof",
                "documentNamespace": "https://example.test/spdx/reference-proof",
                "creationInfo": {
                    "created": "2026-07-24T00:00:00Z",
                    "creators": ["Tool: reference-test"],
                },
                "packages": [],
            }
        ),
        encoding="utf-8",
    )
    placeholder = _archive(tmp_path / "placeholder.nymod")
    draft = _manifest(placeholder)
    draft["signature"]["bundlePath"] = "built.nymod.sigstore.json"
    draft["package"]["archiveSha256"] = "0" * 64
    draft["package"]["archiveBytes"] = 1
    module_root = tmp_path / "modules"
    marketplace = _PassingGateMarketplace(ROOT, module_root=module_root)

    first = marketplace.build_package(
        source,
        draft,
        tmp_path / "built.nymod",
    )
    second = marketplace.build_package(
        source,
        draft,
        tmp_path / "built-again.nymod",
    )
    (tmp_path / "built.nymod.sigstore.json").write_text(
        "{}",
        encoding="utf-8",
    )
    manifest = first["manifest"]
    review = marketplace.build_permission_review(
        manifest,
        approved_by="creator",
        accepted_permissions=["artifact.read"],
    )
    installed = marketplace.install_package(
        manifest,
        first["archivePath"],
        permission_review=review,
    )
    published = marketplace.publish_to_local_registry(
        manifest,
        first["archivePath"],
        install_receipt=installed,
        published_by="creator",
        registry_root=tmp_path / "registry",
    )

    assert first["archiveSha256"] == second["archiveSha256"]
    assert installed["activated"] is True
    assert published["status"] == "published"
    assert Path(published["contentPath"], "package.nymod").is_file()
    assert first["archiveSha256"] in published["contentPath"]
    assert first["manifestSha256"] in published["contentPath"]


def test_operator_browse_snapshot_is_honest_and_local_only(tmp_path: Path) -> None:
    module_root = tmp_path / "modules"
    marketplace = ModuleMarketplace(ROOT, module_root=module_root)
    snapshot = marketplace.operator_browse_snapshot()
    via_sdk = get_module_marketplace_browse(
        workspace_root=ROOT,
        module_root=module_root,
    )

    assert snapshot["schema"] == "neyvia.marketplace-operator-browse/v1"
    assert via_sdk["schema"] == snapshot["schema"]
    assert snapshot["availability"]["browse"] is True
    assert snapshot["availability"]["ociPublicRegistry"] is False
    assert snapshot["availability"]["installProgressStreaming"] is False
    assert snapshot["installProgress"]["available"] is False
    assert "OCI" in " ".join(snapshot["availability"]["reasons"])
    assert snapshot["evidencePolicy"]["humanReviews"]["available"] is False
    assert "humanReviews" in snapshot["evidencePolicy"]["humanReviews"]["fieldNamesChecked"]
    assert snapshot["summary"]["capabilityPacks"] >= 1
    assert snapshot["summary"]["installProfilePackages"] >= 1
    sources = {item["source"] for item in snapshot["listings"]}
    assert "capability-pack" in sources
    assert "install-profile" in sources
    assert all(item.get("installable") is False for item in snapshot["listings"])
    assert "hostileUnsignedPolicy" in snapshot["gates"]
    assert snapshot["gates"]["hostileUnsignedPolicy"]["requireMalwareScan"] is True
