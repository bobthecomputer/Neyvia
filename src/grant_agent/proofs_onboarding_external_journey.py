"""Outcome contract for authored external onboarding manifests and readiness."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CONTRACT = "p22.onboarding.external-source-readiness"
CONTRACTS = (CONTRACT,)
EXPECTED_PLATFORMS = {
    "pack.documents-office": ["windows-amd64", "python"],
    "pack.ocr-local": ["python", "python"],
    "pack.android-lab": ["windows-amd64"],
    "pack.developer-toolchains": ["windows-amd64", "python"],
    "pack.models-gpu": ["python", "python"],
    "pack.media-creative": ["windows-amd64", "windows-amd64"],
    "pack.mesh-control-plane": ["linux-amd64"],
}
EXPECTED_STATES = {
    "pack.documents-office": "unavailable",
    "pack.ocr-local": "failed",
    "pack.android-lab": "unavailable",
    "pack.developer-toolchains": "unavailable",
    "pack.models-gpu": "unavailable",
    "pack.media-creative": "unavailable",
    "pack.mesh-control-plane": "unavailable",
}


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def self_check(root: str | Path) -> dict[str, Any]:
    """Check the seven authored external manifests via production read-only APIs."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    fixture_root = Path(root).resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    state_root = fixture_root / ("onboarding-external-" + uuid.uuid4().hex)
    state_root.mkdir(parents=True, exist_ok=False)
    old_urlopen = urllib.request.urlopen

    def deny_network(*_args, **_kwargs):
        raise AssertionError("network access attempted in external manifest outcome")

    urllib.request.urlopen = deny_network
    try:
        from . import neyvia_onboarding as onboarding
        from .install_profiles import InstallProfileRegistry

        config_path = repo / "config/onboarding_packs.json"
        profiles_path = repo / "config/neyvia_install_profiles.json"
        catalog = InstallProfileRegistry(repo).catalog_snapshot()
        profile_rows = {row["packageId"]: row for row in catalog["optional"]}
        config = json.loads(config_path.read_text(encoding="utf-8"))
        manifest_map = config["manifests"]
        selected = {identity for identity, relative in manifest_map.items()
                    if relative.startswith("config/onboarding_packs/")
                    and "/manifest.json" in relative
                    and config.get("packages", {}).get(identity, {}).get("sourceInputs")}
        _require(selected == set(EXPECTED_PLATFORMS),
                 f"authored external manifest inventory changed: {sorted(selected)}")

        rows = []
        for identity in sorted(EXPECTED_PLATFORMS):
            relative = manifest_map[identity]
            manifest_path = (repo / relative).resolve()
            _require(manifest_path.is_relative_to(repo) and manifest_path.is_file(),
                     f"manifest path is missing or escapes the checkout: {relative}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            platforms = [str((entry.get("source") or {}).get("platform", ""))
                         for entry in manifest.get("files", [])]
            _require(manifest.get("packId") == identity
                     and manifest.get("channel") == "external-source-inputs",
                     f"authored manifest identity/channel changed: {identity}")
            _require(platforms == EXPECTED_PLATFORMS[identity],
                     f"declared platform metadata changed for {identity}: {platforms}")
            profile = profile_rows.get(identity)
            _require(isinstance(profile, dict), f"runtime profile missing for {identity}")
            result = onboarding.pack_status(state_root, identity)["packs"][0]
            _require(result.get("state") == EXPECTED_STATES[identity],
                     f"status for {identity} changed: {result.get('state')} ({result.get('error')})")
            _require(result.get("runtimeReady") is False and result.get("stagedOnly") is True
                     and result.get("doneBytes") == 0,
                     f"unavailable external source falsely appears ready or staged: {identity}")
            if identity == "pack.ocr-local":
                _require(profile.get("deliveryState") == "verified"
                         and result.get("error") == "Remote manifests require an Ed25519 signature",
                         "OCR profile/signature mismatch is no longer fail-closed and explicit")
            else:
                _require(profile.get("deliveryState") in {"foundation", "planned"},
                         f"unexpected delivery state for {identity}: {profile.get('deliveryState')}")
            rows.append({"packId": identity, "manifest": relative,
                         "platforms": platforms, "deliveryState": profile["deliveryState"],
                         "state": result["state"], "runtimeReady": result["runtimeReady"],
                         "stagedOnly": result["stagedOnly"], "error": result.get("error", "")})

        unsafe = json.loads(json.dumps(json.loads(
            (repo / manifest_map["pack.ocr-local"]).read_text(encoding="utf-8"))))
        unsafe["files"][0]["path"] = "../escape.whl"
        try:
            onboarding.parse_manifest(json.dumps(unsafe), str(repo / manifest_map["pack.ocr-local"]))
        except ValueError as error:
            unsafe_error = str(error)
            _require(unsafe_error.startswith("Unsafe manifest path"),
                     f"unsafe path refusal was not the production path check: {unsafe_error}")
        else:
            raise ValueError(f"Contract {CONTRACT}: parser accepted a traversal path")

        unsigned = json.loads((repo / manifest_map["pack.ocr-local"]).read_text(encoding="utf-8"))
        _require(not unsigned.get("signature"), "OCR external manifest unexpectedly gained a signature")
        try:
            onboarding.parse_manifest(json.dumps(unsigned), str(repo / manifest_map["pack.ocr-local"]))
        except ValueError as error:
            signature_error = str(error)
            _require(signature_error == "Remote manifests require an Ed25519 signature",
                     f"unsigned remote refusal changed: {signature_error}")
        else:
            raise ValueError(f"Contract {CONTRACT}: parser accepted unsigned remote sources")

        case = {"id": CONTRACT, "contracts": list(CONTRACTS), "ok": True,
                "manifestCount": len(rows), "packs": rows,
                "unsafePathRefused": True, "unsignedExternalManifestRefused": True,
                "networkBlocked": True, "scratchNonce": state_root.name}
        return {"schema": "neyvia.p22.onboarding-external-outcomes.v1",
                "area": "onboarding-external-journey", "ok": True,
                "contracts": list(CONTRACTS),
                "outcomes": [{"id": CONTRACT, "status": "PASS"}],
                "cases": [case], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root),
                "frontier": "Checks authored platform metadata and fail-closed readiness disclosure only; no host/runtime compatibility evaluator exists, and no installation or payload download is claimed."}
    finally:
        urllib.request.urlopen = old_urlopen
