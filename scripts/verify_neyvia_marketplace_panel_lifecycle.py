#!/usr/bin/env python3
"""User-like Marketplace panel lifecycle proof via the same backend commands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.durability import atomic_write_json  # noqa: E402
from grant_agent.module_marketplace import ModuleMarketplace  # noqa: E402
import importlib.util

_lifecycle_path = ROOT / "scripts" / "verify_neyvia_marketplace_lifecycle.py"
_lifecycle_spec = importlib.util.spec_from_file_location(
    "verify_neyvia_marketplace_lifecycle",
    _lifecycle_path,
)
if _lifecycle_spec is None or _lifecycle_spec.loader is None:
    raise RuntimeError(f"Unable to load {_lifecycle_path}")
_lifecycle = importlib.util.module_from_spec(_lifecycle_spec)
_lifecycle_spec.loader.exec_module(_lifecycle)
MODULE_ID = _lifecycle.MODULE_ID
_attest_install_receipt = _lifecycle._attest_install_receipt
_build_signed_package = _lifecycle._build_signed_package
_provision_external_verifier = _lifecycle._provision_external_verifier


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dispatch(marketplace: ModuleMarketplace, command: str, payload: dict) -> object:
    """Mirror the Marketplace panel command surface from FluxioWebBackend.dispatch."""

    if command == "get_installed_module_catalog_command":
        return marketplace.installed_catalog()
    if command == "get_module_marketplace_toolchain_command":
        return marketplace.toolchain_snapshot()
    if command == "install_module_package_from_paths_command":
        return marketplace.install_package_from_paths(
            manifest_path=str(payload.get("manifestPath") or ""),
            archive_path=str(payload.get("archivePath") or ""),
            permission_review=payload.get("permissionReview"),
            approved_by=str(payload.get("approvedBy") or ""),
            public_key_path=payload.get("publicKeyPath"),
            activate=payload.get("activate") is True,
        )
    if command == "activate_installed_module_command":
        return marketplace.activate_installed_module(
            str(payload.get("moduleId") or ""),
            requested_by=str(payload.get("requestedBy") or ""),
            version=str(payload.get("version") or ""),
        )
    if command == "disable_module_command":
        return marketplace.disable_module(
            str(payload.get("moduleId") or ""),
            requested_by=str(payload.get("requestedBy") or ""),
            reason=str(payload.get("reason") or ""),
        )
    if command == "rollback_module_command":
        return marketplace.rollback_module(
            str(payload.get("moduleId") or ""),
            requested_by=str(payload.get("requestedBy") or ""),
            reason=str(payload.get("reason") or ""),
            target_version=str(payload.get("targetVersion") or ""),
        )
    raise ValueError(f"Unsupported marketplace panel command: {command}")


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
    package_root = output_root / "packages"
    package_root.mkdir(parents=True, exist_ok=False)
    steps: list[dict[str, object]] = []

    packages = [
        _build_signed_package(
            marketplace,
            package_root,
            version="1.0.0",
            message="Panel lifecycle proof version 1.",
        ),
        _build_signed_package(
            marketplace,
            package_root,
            version="1.1.0",
            message="Panel lifecycle proof version 2.",
        ),
    ]

    for package in packages:
        install = _dispatch(
            marketplace,
            "install_module_package_from_paths_command",
            {
                "manifestPath": package["manifestPath"],
                "archivePath": package["archivePath"],
                "publicKeyPath": package["publicKeyPath"],
                "approvedBy": "marketplace-panel-proof",
                "activate": False,
            },
        )
        assert isinstance(install, dict)
        if install.get("blockedBy"):
            raise RuntimeError(f"panel install blocked: {install['blockedBy']}")
        _attest_install_receipt(marketplace, package, private_key)
        activation = _dispatch(
            marketplace,
            "activate_installed_module_command",
            {
                "moduleId": MODULE_ID,
                "version": package["version"],
                "requestedBy": "marketplace-panel-proof",
            },
        )
        assert isinstance(activation, dict)
        if activation.get("activated") is not True:
            raise RuntimeError(f"panel activate failed: {activation}")
        catalog = _dispatch(
            marketplace,
            "get_installed_module_catalog_command",
            {},
        )
        assert isinstance(catalog, dict)
        module = next(
            item
            for item in catalog["modules"]
            if item["moduleId"] == MODULE_ID
        )
        steps.append(
            {
                "action": "install+activate",
                "commandPath": [
                    "install_module_package_from_paths_command",
                    "activate_installed_module_command",
                    "get_installed_module_catalog_command",
                ],
                "version": package["version"],
                "catalogState": module["state"],
                "actions": module["actions"],
            }
        )

    catalog = _dispatch(marketplace, "get_installed_module_catalog_command", {})
    assert isinstance(catalog, dict)
    module = next(item for item in catalog["modules"] if item["moduleId"] == MODULE_ID)
    if module["state"] != "active" or module["version"] != "1.1.0":
        raise RuntimeError("panel catalog did not show active 1.1.0")

    disabled = _dispatch(
        marketplace,
        "disable_module_command",
        {
            "moduleId": MODULE_ID,
            "requestedBy": "marketplace-panel-proof",
            "reason": "Operator disabled module from Marketplace panel.",
        },
    )
    catalog = _dispatch(marketplace, "get_installed_module_catalog_command", {})
    assert isinstance(catalog, dict)
    module = next(item for item in catalog["modules"] if item["moduleId"] == MODULE_ID)
    if not isinstance(disabled, dict) or module["state"] != "disabled":
        raise RuntimeError("panel disable did not reflect disabled state")
    steps.append(
        {
            "action": "disable",
            "commandPath": [
                "disable_module_command",
                "get_installed_module_catalog_command",
            ],
            "catalogState": module["state"],
            "version": module["version"],
            "actions": module["actions"],
        }
    )

    activated = _dispatch(
        marketplace,
        "activate_installed_module_command",
        {
            "moduleId": MODULE_ID,
            "version": "1.1.0",
            "requestedBy": "marketplace-panel-proof",
        },
    )
    catalog = _dispatch(marketplace, "get_installed_module_catalog_command", {})
    assert isinstance(catalog, dict)
    module = next(item for item in catalog["modules"] if item["moduleId"] == MODULE_ID)
    if activated.get("activated") is not True or module["state"] != "active":
        raise RuntimeError("panel activate after disable failed")
    steps.append(
        {
            "action": "activate",
            "commandPath": [
                "activate_installed_module_command",
                "get_installed_module_catalog_command",
            ],
            "catalogState": module["state"],
            "version": module["version"],
            "previousVersion": module["previousVersion"],
            "actions": module["actions"],
        }
    )

    rollback = _dispatch(
        marketplace,
        "rollback_module_command",
        {
            "moduleId": MODULE_ID,
            "requestedBy": "marketplace-panel-proof",
            "reason": "Operator rolled back module from Marketplace panel.",
            "targetVersion": "1.0.0",
        },
    )
    catalog = _dispatch(marketplace, "get_installed_module_catalog_command", {})
    assert isinstance(catalog, dict)
    module = next(item for item in catalog["modules"] if item["moduleId"] == MODULE_ID)
    if (
        not isinstance(rollback, dict)
        or rollback.get("passed") is not True
        or module["state"] != "active"
        or module["version"] != "1.0.0"
    ):
        raise RuntimeError("panel rollback did not restore active 1.0.0")
    steps.append(
        {
            "action": "rollback",
            "commandPath": [
                "rollback_module_command",
                "get_installed_module_catalog_command",
            ],
            "catalogState": module["state"],
            "version": module["version"],
            "previousVersion": module["previousVersion"],
            "actions": module["actions"],
            "publisherTrust": module["publisherTrust"],
            "signatureReceipt": module["signatureReceipt"],
        }
    )

    proof = {
        "schema": "neyvia.marketplace-panel-lifecycle-proof/v1",
        "passed": True,
        "generatedAt": _utc_now(),
        "mode": "panel-command-workflow",
        "moduleId": MODULE_ID,
        "moduleRoot": str(module_root.resolve()),
        "verifierTrustPath": str(trust_path),
        "steps": steps,
        "finalModule": module,
        "notes": [
            "Commands match NeyviaMarketplacePanel.jsx / neyviaMarketplaceModel.js.",
            "Dispatch mirror matches FluxioWebBackend marketplace command handlers.",
            "External OCI verifier trust remains outside managed roots.",
            "No publish and no live NAS pointer changes were performed.",
        ],
    }
    atomic_write_json(output_root / "panel-lifecycle-proof.json", proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove Marketplace panel lifecycle commands end-to-end."
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
            / "marketplace-panel-lifecycle-proof"
            / stamp
        ),
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=(
            Path.home()
            / "AppData"
            / "Local"
            / "NeyviaG2MarketplacePanelProof"
            / stamp
        ),
    )
    args = parser.parse_args()
    proof = run_proof(args.output_root.resolve(), args.runtime_root.resolve())
    print(
        json.dumps(
            {
                "passed": proof["passed"],
                "outputRoot": str(args.output_root.resolve()),
                "finalState": proof["finalModule"]["state"],
                "finalVersion": proof["finalModule"]["version"],
                "actions": [item["action"] for item in proof["steps"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
