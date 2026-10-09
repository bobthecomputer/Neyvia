"""Outcome contract for the real first-run onboarding snapshot projection."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

CONTRACT = "p22.onboarding.first-run-snapshot"
CONTRACTS = (CONTRACT,)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def _verify_local_portable_package(repo: Path, onboarding: Any) -> dict[str, Any]:
    """Bind the real local component package manifest to the current source bytes."""
    identity = "pack.creator-sdk"
    definition = onboarding._pack_definition(identity)
    require(definition.get("localComponents") is True, "creator SDK is no longer a local component pack")
    manifest = onboarding.load_pack_manifest(identity)
    require(manifest.get("packId") == identity and manifest.get("channel") == "local-components",
            "creator SDK manifest is not the declared local portable package")
    descriptor_path = repo / "config/onboarding_packs" / identity / "package.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    require(descriptor.get("packId") == identity and descriptor.get("scope") == "local-components"
            and descriptor.get("entrypoints") == definition.get("entrypoints"),
            "portable package descriptor lost its declared entrypoint meaning")
    rows = manifest["files"]
    paths = [row["path"] for row in rows]
    require(len(paths) == len(set(paths)) and "package.json" in paths
            and all(PurePosixPath(path).as_posix() == path and not PurePosixPath(path).is_absolute()
                    and ".." not in PurePosixPath(path).parts for path in paths),
            "package inventory is not unique and portable")
    total = 0
    for row in rows:
        parsed = urlparse(row["url"])
        require(parsed.scheme == "file", f"local component URL is not a file URI: {row['path']}")
        source = Path(urllib.request.url2pathname(parsed.path)).resolve()
        require(source.is_relative_to(repo) and source.is_file(),
                f"portable source is missing or outside the checkout: {row['path']}")
        body = source.read_bytes()
        require(len(body) == row["size"] and hashlib.sha256(body).hexdigest() == row["sha256"],
                f"portable source bytes disagree with manifest: {row['path']}")
        total += len(body)
    require(total == manifest["totalSize"] and total > 0, "portable package total does not match source bytes")
    return {"packId": identity, "fileCount": len(rows), "bytes": total,
            "entrypoints": descriptor["entrypoints"], "allSourceBytesVerified": True}


def self_check(root: str | Path) -> dict[str, Any]:
    """Observe initial and saved onboarding snapshots through production functions."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    fixture_root = Path(root).resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    state_root = fixture_root / ("installer-snapshot-" + uuid.uuid4().hex)
    state_root.mkdir(parents=True, exist_ok=False)
    old_urlopen = urllib.request.urlopen

    def deny_network(*_args, **_kwargs):
        raise AssertionError("network access attempted by onboarding snapshot contract")

    urllib.request.urlopen = deny_network
    try:
        from . import neyvia_onboarding as onboarding

        before = onboarding.snapshot(state_root)
        catalog = onboarding.load_catalog()
        apps = onboarding._known_apps()
        packs = onboarding._known_packs()
        statuses = {row["packId"]: row for row in onboarding.pack_status(state_root)["packs"]}
        require(before["state"]["firstRun"] is True, "fresh proof state did not open as first run")
        require(before["basePack"]["state"] == "idle" and before["basePack"]["doneBytes"] == 0,
                "fresh base-pack observer was not idle and empty")
        require(before["catalog"] == catalog, "snapshot catalog differs from the validated current catalog")
        require([row["id"] for row in before["apps"]] == list(apps),
                "snapshot omitted or reordered registered apps")
        require({row["id"] for row in before["packs"]} == set(packs)
                and set(statuses) == set(packs), "snapshot omitted a registered pack or its status")
        app_ids, pack_ids = set(apps), set(packs)
        for interest in catalog["interests"]:
            require(set(interest.get("apps", [])) <= app_ids and set(interest.get("packs", [])) <= pack_ids,
                    f"catalog interest points outside registered apps/packs: {interest['id']}")
        for row in before["packs"]:
            status = statuses[row["id"]]
            expected_ready = status["state"] != "unavailable"
            require(row["ready"] is expected_ready,
                    f"ready-to-install projection disagrees with retryable/available status for {row['id']}")
            require(row["deliveryScope"] == status["deliveryScope"]
                    and row["missing"] == status["missing"],
                    f"snapshot package details diverged from status for {row['id']}")

        # The unsigned remote source is a real failed row, but its retry remains available.
        ocr = statuses["pack.ocr-local"]
        ocr_row = next(row for row in before["packs"] if row["id"] == "pack.ocr-local")
        require(ocr["state"] == "failed"
                and ocr["error"] == "Remote manifests require an Ed25519 signature"
                and ocr_row["ready"] is True,
                "unsigned OCR failure was hidden or lost its explicit retryable state")

        # Verify an actual generated local package and every referenced source byte.
        package = _verify_local_portable_package(repo, onboarding)
        creator = statuses[package["packId"]]
        creator_row = next(row for row in before["packs"] if row["id"] == package["packId"])
        require(creator["state"] == "not-installed" and not creator.get("error")
                and creator["deliveryScope"] == "local-components" and creator_row["ready"] is True,
                "healthy local package is not exposed as available for staging")

        # Save valid authored choices, then reopen the same production snapshot.
        interest_id = catalog["interests"][0]["id"]
        app_id = next(iter(apps))
        saved = onboarding.save_state(state_root, {
            "interests": [interest_id], "apps": [app_id], "packs": [package["packId"]],
            "tier": catalog["tiers"][0]["id"],
        })
        after = onboarding.snapshot(state_root)
        require(after["state"]["firstRun"] is False
                and after["state"]["interests"] == [interest_id]
                and after["state"]["apps"] == [app_id]
                and after["state"]["packs"] == [package["packId"]]
                and after["state"]["tier"] == saved["tier"],
                "saved first-run choices did not appear in the reopened snapshot")
        require(after["catalog"] == before["catalog"] and after["packs"] == before["packs"]
                and after["basePack"] == before["basePack"],
                "saving choices changed catalog, package availability, or base-pack state")

        case = {"id": CONTRACT, "contracts": list(CONTRACTS), "ok": True,
                "catalogInterests": len(catalog["interests"]), "appCount": len(apps),
                "packCount": len(packs), "failedUnsignedRetryable": True,
                "healthyPortablePackage": package, "savedChoicesReopened": True,
                "networkBlocked": True, "scratchNonce": state_root.name}
        return {"schema": "neyvia.p22.installer-extra.v1", "area": "installer-extra",
                "ok": True, "contracts": list(CONTRACTS),
                "outcomes": [{"id": CONTRACT, "status": "PASS"}], "cases": [case],
                "failures": [], "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root),
                "frontier": "Verifies the production onboarding snapshot projection, retryable failure, local portable package bytes and persisted setup choices. No payload downloads, add-on staging or system installation occurs."}
    finally:
        urllib.request.urlopen = old_urlopen
