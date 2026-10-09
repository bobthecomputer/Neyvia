"""Verified, non-invasive module lifecycle for the Neyvia marketplace.

Marketplace packages never patch Neyvia's application bundle. A module is
verified in quarantine, installed into an immutable version directory, and
enabled only by atomically replacing a small activation pointer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import cmp_to_key, wraps
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from .durability import append_jsonl_durable, atomic_write_json, atomic_write_text
from .marketplace_toolchain import MarketplaceToolchainUpdateManager
from .subprocess_utils import hidden_windows_subprocess_kwargs


MODULE_MANIFEST_SCHEMA = "neyvia.module-manifest/v1"
MODULE_INSPECTION_SCHEMA = "neyvia.module-package-inspection/v2"
MODULE_INSTALL_PLAN_SCHEMA = "neyvia.module-install-plan/v2"
MODULE_INSTALL_RECEIPT_SCHEMA = "neyvia.module-install-receipt/v1"
MODULE_GATE_RECEIPT_SCHEMA = "neyvia.module-gate-receipt/v1"
MODULE_PERMISSION_REVIEW_SCHEMA = "neyvia.module-permission-review/v1"
MODULE_PUBLISHER_TRUST_SCHEMA = "neyvia.publisher-trust/v1"
MODULE_ACTIVATION_POINTER_SCHEMA = "neyvia.module-activation-pointer/v1"
MODULE_CATALOG_SCHEMA = "neyvia.installed-module-catalog/v1"
MODULE_BUILD_RECEIPT_SCHEMA = "neyvia.module-build-receipt/v1"
MODULE_PUBLISH_RECEIPT_SCHEMA = "neyvia.module-publish-receipt/v1"
MODULE_OCI_PLAN_SCHEMA = "neyvia.module-oci-artifact-plan/v1"
MODULE_OCI_INSPECTION_SCHEMA = "neyvia.module-oci-artifact-inspection/v1"
MODULE_OCI_EVIDENCE_SCHEMA = "neyvia.module-oci-security-evidence/v1"
MODULE_OCI_STAGED_POINTER_SCHEMA = "neyvia.module-oci-staged-pointer/v1"
OCI_IMAGE_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
OCI_MODULE_ARTIFACT_TYPE = "application/vnd.neyvia.module.v1"
OCI_MODULE_CONFIG_MEDIA_TYPE = "application/vnd.neyvia.module.config.v1+json"
OCI_MODULE_LAYER_MEDIA_TYPE = "application/vnd.neyvia.module+zip"
OCI_SECURITY_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.neyvia.module.security-evidence.v1+json"
)
OCI_REQUIRED_SECURITY_GATES = (
    "publisher-trust",
    "cosign-bundle-verification",
    "dependency-resolution",
    "sbom-policy",
    "vulnerability-scan",
    "malware-scan",
    "permission-review",
    "isolated-smoke-test",
)
OCI_EVIDENCE_ATTESTATION_SCHEMA = "neyvia.oci-gate-attestation/v1"
OCI_EVIDENCE_POLICY_VERSION = "neyvia.oci-evidence-policy/v1"
OCI_VERIFIER_TRUST_SCHEMA = "neyvia.oci-verifier-trust/v1"
OCI_ACTIVATION_TRANSACTION_SCHEMA = "neyvia.oci-activation-transaction/v1"
DEFAULT_OCI_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_ARCHIVE_ENTRIES = 20_000
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
MAX_SIGNATURE_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_GATE_OUTPUT_CHARS = 12_000
FORBIDDEN_MANIFEST_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "credential",
        "credentials",
        "password",
        "privatekey",
        "private_key",
        "secret",
        "token",
    }
)
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
MARKETPLACE_MODULE_ID = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$"
)
OCI_REGISTRY_REF = re.compile(
    r"^(?P<registry>(?:localhost|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)"
    r"(?::[1-9][0-9]{0,4})?)/"
    r"(?P<repository>[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*)"
    r":(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})$"
)
SPDX_LICENSE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*(?:\s+(?:AND|OR|WITH)\s+[A-Za-z0-9][A-Za-z0-9.+-]*)*$")
SEVERITY_ORDER = {
    "unknown": 0,
    "negligible": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_member_sha256(archive: Path, member: str) -> str:
    digest = hashlib.sha256()
    with ZipFile(archive) as package, package.open(member) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_file(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                output_handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(temporary, destination)
        destination.chmod(stat.S_IREAD)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "sha256": digest.hexdigest(),
        "bytes": size,
    }


def _snapshot_content_addressed(
    source: Path,
    destination_root: Path,
    *,
    suffix: str,
) -> dict[str, Any]:
    """Copy one source read into an immutable SHA-256-addressed path."""

    destination_root.mkdir(parents=True, exist_ok=True)
    temporary = destination_root / f".intake-{uuid.uuid4().hex}.tmp"
    snapshot = _snapshot_file(source, temporary)
    digest = snapshot["sha256"]
    destination = (
        destination_root
        / "sha256"
        / digest[:2]
        / f"{digest}{suffix}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.exists():
            if (
                not destination.is_file()
                or destination.stat().st_size != snapshot["bytes"]
                or _sha256(destination) != digest
            ):
                raise ValueError(
                    f"Hash-addressed snapshot collision at {destination}"
                )
            temporary.chmod(stat.S_IWRITE | stat.S_IREAD)
            temporary.unlink()
        else:
            os.replace(temporary, destination)
            destination.chmod(stat.S_IREAD)
    except BaseException:
        if temporary.exists():
            temporary.chmod(stat.S_IWRITE | stat.S_IREAD)
            temporary.unlink(missing_ok=True)
        raise
    snapshot["path"] = str(destination)
    return snapshot


def _installed_archive_path(target: Path, archive_sha256: str) -> Path:
    digest = str(archive_sha256 or "")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Installed archive digest is invalid")
    return (
        target
        / ".neyvia"
        / "archives"
        / "sha256"
        / digest[:2]
        / f"{digest}.nymod"
    )


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    return _canonical_json_bytes(payload)


def _canonical_manifest_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_manifest_bytes(payload)).hexdigest()


def _oci_descriptor(media_type: str, content: bytes) -> dict[str, Any]:
    return {
        "mediaType": media_type,
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "size": len(content),
    }


def _payload_tree_proof(
    payload_root: Path,
    entrypoint: object,
) -> dict[str, Any]:
    root = payload_root.resolve()
    if not root.is_dir():
        raise ValueError("installed payload root is missing")
    entries: list[dict[str, Any]] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".neyvia":
            continue
        if path.is_symlink():
            raise ValueError(
                f"installed payload contains symbolic link {relative.as_posix()!r}"
            )
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            entries.append(
                {
                    "path": relative.as_posix(),
                    "type": "directory",
                    "mode": mode,
                }
            )
            continue
        if not path.is_file():
            raise ValueError(
                f"installed payload contains unsupported node "
                f"{relative.as_posix()!r}"
            )
        size = path.stat().st_size
        entries.append(
            {
                "path": relative.as_posix(),
                "type": "file",
                "mode": mode,
                "bytes": size,
                "sha256": _sha256(path),
            }
        )
        file_count += 1
        total_bytes += size
    entrypoint_path = _safe_child(
        root,
        entrypoint,
        name="runtime.entrypoint",
    )
    if not entrypoint_path.is_file() or entrypoint_path.is_symlink():
        raise ValueError("installed runtime entrypoint is missing or unsafe")
    return {
        "schema": "neyvia.module-payload-tree-proof/v1",
        "treeSha256": hashlib.sha256(
            _canonical_json_bytes(entries)
        ).hexdigest(),
        "entrypointPath": _relative_package_path(
            entrypoint,
            name="runtime.entrypoint",
        ).as_posix(),
        "entrypointSha256": _sha256(entrypoint_path),
        "fileCount": file_count,
        "totalBytes": total_bytes,
    }


def _forbidden_key_paths(value: object, *, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold().replace("-", "_")
            if normalized in FORBIDDEN_MANIFEST_KEYS:
                findings.append(f"{prefix}.{key}")
            findings.extend(_forbidden_key_paths(item, prefix=f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(
                _forbidden_key_paths(item, prefix=f"{prefix}[{index}]")
            )
    return findings


def _relative_package_path(value: object, *, name: str) -> PurePosixPath:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise ValueError(f"{name} must be a safe package-relative path")
    return path


def _safe_child(base: Path, relative: object, *, name: str) -> Path:
    package_path = _relative_package_path(relative, name=name)
    target = (base / Path(*package_path.parts)).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"{name} escapes its allowed root") from exc
    return target


def _bounded(value: object, limit: int = MAX_GATE_OUTPUT_CHARS) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[-limit:]


def _safe_module_id(value: object) -> str:
    text = str(value or "").strip()
    if (
        len(text) not in range(3, 161)
        or not MARKETPLACE_MODULE_ID.fullmatch(text)
    ):
        raise ValueError(f"Invalid module identifier: {value!r}")
    return text


def _publisher_namespace(payload: dict[str, Any]) -> str:
    publisher = payload.get("publisher")
    publisher_id = str(
        publisher.get("id") if isinstance(publisher, dict) else ""
    ).strip()
    if (
        len(publisher_id.split(".")) < 2
        or not MARKETPLACE_MODULE_ID.fullmatch(publisher_id)
    ):
        raise ValueError(
            "publisher.id must contain at least two dot-qualified segments"
        )
    return publisher_id


def _module_namespace_claims(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return the extension identifiers that become live on activation."""

    claims: list[dict[str, str]] = []
    for capability in payload.get("capabilities", []):
        if not isinstance(capability, dict):
            continue
        identifier = str(capability.get("operationId") or "").strip()
        if identifier:
            claims.append({"kind": "operation", "id": identifier})
    for surface in payload.get("surfaces", []):
        if not isinstance(surface, dict):
            continue
        surface_id = str(surface.get("surfaceId") or "").strip()
        route = str(surface.get("route") or "").strip()
        if surface_id:
            claims.append({"kind": "surface", "id": surface_id})
        if route:
            claims.append({"kind": "route", "id": route.casefold()})
    return sorted(claims, key=lambda item: (item["kind"], item["id"]))


@contextmanager
def _module_file_lock(module_directory: Path):
    module_directory.mkdir(parents=True, exist_ok=True)
    lock_path = module_directory / ".lifecycle.lock"
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    deadline = time.monotonic() + 30
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring module lifecycle lock: {lock_path}"
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _module_scoped(method):
    @wraps(method)
    def wrapped(self, module_or_manifest, *args, **kwargs):
        module_id = (
            module_or_manifest.get("moduleId")
            if isinstance(module_or_manifest, dict)
            else module_or_manifest
        )
        safe_id = _safe_module_id(module_id)
        with _module_file_lock(self.module_root / safe_id):
            return method(self, module_or_manifest, *args, **kwargs)

    return wrapped


def _semver_parts(
    value: str,
) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = SEMVER.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid semantic version: {value!r}")
    prerelease = (
        tuple(match.group(4).split("."))
        if match.group(4) is not None
        else None
    )
    if prerelease and any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease
    ):
        raise ValueError(
            f"invalid semantic version prerelease identifier: {value!r}"
        )
    return (
        tuple(int(match.group(index)) for index in (1, 2, 3)),
        prerelease,
    )


def _compare_semver(left: str, right: str) -> int:
    left_core, left_pre = _semver_parts(left)
    right_core, right_pre = _semver_parts(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def _version_satisfies(version: str, expression: str) -> bool:
    """Evaluate the intentionally small, documented marketplace range syntax."""

    try:
        _semver_parts(version)
    except ValueError:
        return False
    tokens = [item for item in re.split(r"[\s,]+", expression.strip()) if item]
    if not tokens:
        return False
    for token in tokens:
        match = re.fullmatch(r"(>=|<=|>|<|==|=)?(.+)", token)
        if not match:
            return False
        operator = match.group(1) or "="
        try:
            comparison = _compare_semver(version, match.group(2))
        except ValueError:
            return False
        if operator in {"=", "=="} and comparison != 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
    return True


def _valid_semver_expression(expression: object) -> bool:
    tokens = [
        item
        for item in re.split(r"[\s,]+", str(expression or "").strip())
        if item
    ]
    if not tokens:
        return False
    for token in tokens:
        match = re.fullmatch(r"(>=|<=|>|<|==|=)?(.+)", token)
        if not match:
            return False
        try:
            _semver_parts(match.group(2))
        except ValueError:
            return False
    return True


def _platform_tag() -> str:
    machine = platform.machine().casefold()
    architecture = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if os.name == "nt":
        return f"windows-{architecture}"
    if sys_platform := platform.system().casefold():
        if sys_platform == "darwin":
            return f"macos-{architecture}"
    return f"linux-{architecture}"


def _parse_registry_ref(value: object, *, version: str) -> dict[str, str]:
    text = str(value or "").strip()
    match = OCI_REGISTRY_REF.fullmatch(text)
    if not match:
        raise ValueError(
            "distribution.registryRef must be a canonical "
            "registry/repository:tag reference"
        )
    registry = match.group("registry")
    host = registry
    if ":" in registry:
        host, port_text = registry.rsplit(":", 1)
        if int(port_text) > 65535:
            raise ValueError("distribution.registryRef port is out of range")
    if len(host) > 253 or any(
        len(label) not in range(1, 64)
        or label.startswith("-")
        or label.endswith("-")
        for label in host.split(".")
    ):
        raise ValueError("distribution.registryRef registry host is invalid")
    tag = match.group("tag")
    if tag != version:
        raise ValueError(
            "distribution.registryRef tag must exactly equal module version"
        )
    return {
        "registry": registry,
        "repository": match.group("repository"),
        "tag": tag,
        "taggedRef": text,
    }


class ModuleMarketplace:
    """Validate, verify, install, disable, and roll back Neyvia modules."""

    def __init__(
        self,
        root: str | Path,
        *,
        schema_path: str | Path | None = None,
        toolchain_path: str | Path | None = None,
        module_root: str | Path | None = None,
        neyvia_version: str | None = None,
        verifier_trust_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        local_schema = self.root / "config" / "neyvia_module_manifest_schema.json"
        selected_schema = Path(schema_path or local_schema)
        if not selected_schema.is_file():
            selected_schema = (
                project_root / "config" / "neyvia_module_manifest_schema.json"
            )
        self.schema_path = selected_schema.resolve()
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

        local_toolchain = (
            self.root / "config" / "neyvia_marketplace_toolchain.json"
        )
        selected_toolchain = Path(toolchain_path or local_toolchain)
        uses_local_toolchain = selected_toolchain.is_file()
        if not selected_toolchain.is_file():
            selected_toolchain = (
                project_root / "config" / "neyvia_marketplace_toolchain.json"
            )
        self.toolchain_path = selected_toolchain.resolve()
        self.toolchain = (
            json.loads(self.toolchain_path.read_text(encoding="utf-8"))
            if self.toolchain_path.is_file()
            else {"policy": {}, "tools": {}}
        )
        configured_module_root = str(self.toolchain.get("moduleRoot") or "").strip()
        if module_root:
            selected_module_root = Path(module_root)
        elif str(os.environ.get("NEYVIA_MODULE_ROOT") or "").strip():
            selected_module_root = Path(os.environ["NEYVIA_MODULE_ROOT"])
        elif uses_local_toolchain and configured_module_root:
            selected_module_root = Path(configured_module_root)
        else:
            selected_module_root = (
                self.root / ".agent_control" / "marketplace" / "modules"
            )
        self.module_root = selected_module_root.resolve()
        self.neyvia_version = str(
            neyvia_version or os.environ.get("NEYVIA_VERSION") or "0.1.0"
        ).strip()
        configured_trust = str(
            verifier_trust_path
            or os.environ.get("NEYVIA_OCI_VERIFIER_TRUST_PATH")
            or ""
        ).strip()
        self.verifier_trust_path = (
            Path(configured_trust).resolve() if configured_trust else None
        )

    @property
    def policy(self) -> dict[str, Any]:
        value = self.toolchain.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def trust_path(self) -> Path:
        return self.module_root / "trust" / "publishers.json"

    @property
    def ledger_path(self) -> Path:
        return self.module_root / "receipts" / "marketplace.jsonl"

    def operator_browse_snapshot(self) -> dict[str, Any]:
        """Return an honest local catalog without implying a public registry exists."""

        project_root = Path(__file__).resolve().parents[2]

        def load_config(name: str) -> dict[str, Any]:
            selected = self.root / "config" / name
            if not selected.is_file():
                selected = project_root / "config" / name
            if not selected.is_file():
                return {}
            try:
                payload = json.loads(selected.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return dict(payload) if isinstance(payload, dict) else {}

        capability_catalog = load_config("capability_packs.json")
        install_catalog = load_config("neyvia_install_profiles.json")
        packs = [
            dict(row)
            for row in capability_catalog.get("packs") or []
            if isinstance(row, dict)
        ]
        packages = [
            dict(row)
            for row in install_catalog.get("packages") or []
            if isinstance(row, dict)
        ]
        listings = [
            {
                "listingId": str(row.get("packId") or ""),
                "name": str(row.get("name") or row.get("packId") or ""),
                "summary": str(row.get("description") or ""),
                "source": "capability-pack",
                "state": "catalogued",
                "installable": False,
                "capabilityCount": len(row.get("capabilities") or []),
            }
            for row in packs
            if str(row.get("packId") or "").strip()
        ] + [
            {
                "listingId": str(row.get("packageId") or ""),
                "name": str(row.get("name") or row.get("packageId") or ""),
                "summary": str(row.get("gap") or "Local install-profile package."),
                "source": "install-profile",
                "state": str(row.get("deliveryState") or "catalogued"),
                "installable": False,
                "tier": str(row.get("tier") or ""),
            }
            for row in packages
            if str(row.get("packageId") or "").strip()
        ]
        policy = self.policy
        return {
            "schema": "neyvia.marketplace-operator-browse/v1",
            "generatedAt": _utc_now(),
            "availability": {
                "browse": bool(listings),
                "ociPublicRegistry": False,
                "installProgressStreaming": False,
                "reasons": [
                    "Browse uses verified local capability and install-profile catalogs.",
                    "No OCI public registry adapter is configured.",
                    "Install progress streaming is not implemented by this surface.",
                ],
            },
            "listings": listings,
            "summary": {
                "listingCount": len(listings),
                "capabilityPacks": len(packs),
                "installProfilePackages": len(packages),
            },
            "installProgress": {
                "available": False,
                "source": "not-configured",
            },
            "evidencePolicy": {
                "humanReviews": {
                    "available": False,
                    "fieldNamesChecked": ["humanReviews", "reviews", "ratings"],
                    "reason": "No trusted human-review provider is configured.",
                }
            },
            "gates": {
                "activationGateReady": False,
                "hostileUnsignedPolicy": {
                    "requireDeclaredSbom": bool(policy.get("requireDeclaredSbom", True)),
                    "requireGeneratedSbom": bool(policy.get("requireGeneratedSbom", True)),
                    "requireMalwareScan": bool(policy.get("requireMalwareScan", True)),
                    "blockVulnerabilitySeverity": str(
                        policy.get("blockVulnerabilitySeverity") or "high"
                    ),
                },
            },
        }

    def validate_manifest(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "valid": False,
                "errors": ["$: manifest must be an object"],
                "warnings": [],
            }
        errors = [
            f"{error.json_path}: {error.message}"
            for error in sorted(
                self.validator.iter_errors(payload),
                key=lambda item: (list(item.absolute_path), item.message),
            )
        ]
        errors.extend(
            f"{path}: secret-bearing manifest keys are forbidden"
            for path in _forbidden_key_paths(payload)
        )
        errors.extend(self._semantic_errors(payload))
        return {
            "valid": not errors,
            "errors": sorted(set(errors)),
            "warnings": self._warnings(payload),
            "schema": MODULE_MANIFEST_SCHEMA,
            "manifestSha256": (
                _canonical_manifest_sha256(payload) if not errors else ""
            ),
        }

    def require_valid_manifest(self, payload: object) -> dict[str, Any]:
        result = self.validate_manifest(payload)
        if not result["valid"]:
            raise ValueError("; ".join(result["errors"]))
        return dict(payload)

    @staticmethod
    def _semantic_errors(payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        try:
            module_id = _safe_module_id(payload.get("moduleId"))
        except ValueError as exc:
            module_id = ""
            errors.append(f"$.moduleId: {exc}")
        try:
            publisher_namespace = _publisher_namespace(payload)
        except ValueError as exc:
            publisher_namespace = ""
            errors.append(f"$.publisher.id: {exc}")
        if (
            module_id
            and publisher_namespace
            and module_id != publisher_namespace
            and not module_id.startswith(
                (f"{publisher_namespace}.", f"{publisher_namespace}-")
            )
        ):
            errors.append(
                "$.moduleId: module identifier must be owned by publisher.id"
            )
        try:
            _semver_parts(str(payload.get("version") or ""))
        except ValueError as exc:
            errors.append(f"$.version: {exc}")
        if not _valid_semver_expression(
            (payload.get("compatibility") or {}).get("neyvia")
        ):
            errors.append(
                "$.compatibility.neyvia: invalid semantic version expression"
            )
        try:
            _parse_registry_ref(
                (payload.get("distribution") or {}).get("registryRef"),
                version=str(payload.get("version") or ""),
            )
        except ValueError as exc:
            errors.append(f"$.distribution.registryRef: {exc}")
        runtime = payload.get("runtime") or {}
        kind = str(runtime.get("kind") or "")
        isolation = str(runtime.get("isolation") or "")
        entrypoint = str(runtime.get("entrypoint") or "")
        if kind == "wasm-component":
            if isolation != "wasmtime-wasi":
                errors.append(
                    "$.runtime.isolation: wasm-component modules require "
                    "wasmtime-wasi"
                )
            if entrypoint and not entrypoint.casefold().endswith(".wasm"):
                errors.append(
                    "$.runtime.entrypoint: wasm-component entrypoints must "
                    "end with .wasm"
                )
        if kind in {"isolated-service", "full-app"}:
            if isolation not in {"isolated-process", "container"}:
                errors.append(
                    "$.runtime.isolation: service and full-app modules require "
                    "isolated-process or container"
                )
            if not isinstance(runtime.get("healthcheck"), dict):
                errors.append(
                    "$.runtime.healthcheck: service and full-app modules "
                    "require a typed healthcheck"
                )
        if kind == "content-pack" and isolation != "bridge-only":
            errors.append(
                "$.runtime.isolation: content-pack modules require bridge-only"
            )
        if kind == "full-app":
            surface_kinds = {
                str(item.get("kind") or "")
                for item in payload.get("surfaces", [])
                if isinstance(item, dict)
            }
            if not surface_kinds.intersection(
                {"desktop", "mobile", "web", "embedded"}
            ):
                errors.append(
                    "$.surfaces: full-app modules require a user-facing surface"
                )

        package = payload.get("package") or {}
        if not str(package.get("sbomPath") or "").strip():
            errors.append(
                "$.package.sbomPath: marketplace modules require a declared SBOM"
            )
        license_expression = str(package.get("license") or "").strip()
        if not license_expression or not SPDX_LICENSE.fullmatch(license_expression):
            errors.append(
                "$.package.license: use a bounded SPDX license expression"
            )

        signature = payload.get("signature") or {}
        if signature.get("bundleLocation") != "detached":
            errors.append(
                "$.signature.bundleLocation: signature bundles must be detached "
                "to avoid a self-referential archive digest"
            )
        if signature.get("payload") != "canonical-manifest":
            errors.append(
                "$.signature.payload: signatures must bind the canonical manifest"
            )
        if (
            signature.get("scheme") == "sigstore-cosign-bundle"
            and signature.get("identity") != (payload.get("publisher") or {}).get("identity")
        ):
            errors.append(
                "$.signature.identity: keyless identity must equal publisher.identity"
            )

        declared_permissions = {
            str(item.get("permission") or "")
            for item in payload.get("permissions", [])
            if isinstance(item, dict)
        }
        for index, capability in enumerate(payload.get("capabilities", [])):
            if not isinstance(capability, dict):
                continue
            referenced = {
                str(item)
                for item in capability.get("permissions", [])
                if str(item)
            }
            unknown = sorted(referenced - declared_permissions)
            if unknown:
                errors.append(
                    f"$.capabilities[{index}].permissions: undeclared "
                    f"permissions {unknown}"
                )
        dependencies = [
            item
            for item in payload.get("dependencies", [])
            if isinstance(item, dict)
        ]
        dependency_ids = [str(item.get("moduleId") or "") for item in dependencies]
        if payload.get("moduleId") in dependency_ids:
            errors.append("$.dependencies: a module cannot depend on itself")
        duplicate_dependencies = sorted(
            item
            for item in set(dependency_ids)
            if item and dependency_ids.count(item) > 1
        )
        if duplicate_dependencies:
            errors.append(
                "$.dependencies: duplicate module dependencies "
                f"{duplicate_dependencies}"
            )
        for index, dependency in enumerate(dependencies):
            if not _valid_semver_expression(dependency.get("version")):
                errors.append(
                    f"$.dependencies[{index}].version: invalid semantic "
                    "version expression"
                )

        for collection, key in (
            ("capabilities", "operationId"),
            ("surfaces", "surfaceId"),
            ("update.migrations", "migrationId"),
        ):
            values = (
                (payload.get("update") or {}).get("migrations", [])
                if collection == "update.migrations"
                else payload.get(collection, [])
            )
            identifiers = [
                str(item.get(key) or "")
                for item in values
                if isinstance(item, dict)
            ]
            duplicates = sorted(
                value
                for value in set(identifiers)
                if value and identifiers.count(value) > 1
            )
            if duplicates:
                errors.append(
                    f"$.{collection}: duplicate {key} values {duplicates}"
                )
        if publisher_namespace:
            namespace_prefix = f"{publisher_namespace}."
            for index, capability in enumerate(payload.get("capabilities", [])):
                if not isinstance(capability, dict):
                    continue
                operation_id = str(
                    capability.get("operationId") or ""
                ).strip()
                if operation_id and not operation_id.startswith(namespace_prefix):
                    errors.append(
                        f"$.capabilities[{index}].operationId: must start with "
                        f"{namespace_prefix}"
                    )
            expected_route_prefix = f"app://{publisher_namespace}/"
            for index, surface in enumerate(payload.get("surfaces", [])):
                if not isinstance(surface, dict):
                    continue
                surface_id = str(surface.get("surfaceId") or "").strip()
                route = str(surface.get("route") or "").strip()
                if surface_id and not surface_id.startswith(namespace_prefix):
                    errors.append(
                        f"$.surfaces[{index}].surfaceId: must start with "
                        f"{namespace_prefix}"
                    )
                if route and not route.casefold().startswith(
                    expected_route_prefix.casefold()
                ):
                    errors.append(
                        f"$.surfaces[{index}].route: must start with "
                        f"{expected_route_prefix}"
                    )

        update = payload.get("update") or {}
        if update.get("rollback") is not True:
            errors.append(
                "$.update.rollback: marketplace modules must support rollback"
            )
        for index, migration in enumerate(update.get("migrations", [])):
            if not isinstance(migration, dict):
                continue
            if migration.get("reversible") is not True and (
                migration.get("requiresApproval") is not True
                or not str(migration.get("backupStrategy") or "").strip()
            ):
                errors.append(
                    f"$.update.migrations[{index}]: irreversible migrations "
                    "require approval and a backup strategy"
                )
        return errors

    @staticmethod
    def _warnings(payload: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        distribution = payload.get("distribution") or {}
        if distribution.get("p2pEligible") is not True:
            warnings.append(
                "Package is registry-only and cannot use private-mesh cache peers."
            )
        if (payload.get("update") or {}).get("channel") != "stable":
            warnings.append(
                "Non-stable update channels require explicit operator opt-in."
            )
        if (payload.get("runtime") or {}).get("kind") in {
            "isolated-service",
            "full-app",
        }:
            warnings.append(
                "Process and full-app activation stays blocked until a declared "
                "container or OS sandbox adapter is healthy."
            )
        return warnings

    def _compatibility_errors(self, payload: dict[str, Any]) -> list[str]:
        compatibility = payload.get("compatibility") or {}
        platforms = compatibility.get("platforms") or []
        errors: list[str] = []
        current_platform = _platform_tag()
        if platforms and current_platform not in platforms:
            errors.append(
                f"Module does not support {current_platform}; declared {platforms}"
            )
        expression = str(compatibility.get("neyvia") or "")
        if not _version_satisfies(self.neyvia_version, expression):
            errors.append(
                f"Module requires Neyvia {expression}; current version is "
                f"{self.neyvia_version}"
            )
        return errors

    def dependency_compatibility(
        self,
        manifest: object,
    ) -> dict[str, Any]:
        """Resolve declared dependencies against active immutable installs."""

        payload = self.require_valid_manifest(manifest)
        catalog = {
            item["moduleId"]: item
            for item in self.installed_catalog()["modules"]
            if item.get("state") == "active"
        }
        resolved: list[dict[str, Any]] = []
        errors: list[str] = []
        for dependency in payload.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            module_id = str(dependency.get("moduleId") or "")
            expression = str(dependency.get("version") or "")
            installed = catalog.get(module_id)
            matched = bool(
                installed
                and _version_satisfies(str(installed["version"]), expression)
            )
            resolved.append(
                {
                    "moduleId": module_id,
                    "requiredVersion": expression,
                    "installedVersion": (
                        str(installed["version"]) if installed else ""
                    ),
                    "required": dependency.get("required") is True,
                    "matched": matched,
                }
            )
            if dependency.get("required") is True and not matched:
                errors.append(
                    f"Required dependency {module_id} {expression} is not active"
                )
        return {
            "schema": "neyvia.module-dependency-compatibility/v1",
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "compatible": not errors,
            "dependencies": resolved,
            "errors": errors,
        }

    def inspect_package(
        self,
        manifest: object,
        archive_path: str | Path,
    ) -> dict[str, Any]:
        payload = self.require_valid_manifest(manifest)
        archive = Path(archive_path).resolve()
        if not archive.is_file():
            raise FileNotFoundError(archive)
        package = payload["package"]
        actual_bytes = archive.stat().st_size
        actual_hash = _sha256(archive)
        expected_bytes = int(package["archiveBytes"])
        expected_hash = str(package["archiveSha256"])
        errors: list[str] = self._compatibility_errors(payload)
        if actual_bytes != expected_bytes:
            errors.append(
                f"Archive size mismatch: expected {expected_bytes}, "
                f"received {actual_bytes}"
            )
        if not hmac.compare_digest(actual_hash, expected_hash):
            errors.append(
                "Archive SHA-256 does not match the signed manifest metadata"
            )

        entries: list[dict[str, Any]] = []
        total_uncompressed = 0
        names: set[str] = set()
        try:
            with ZipFile(archive) as package_zip:
                infos = package_zip.infolist()
                if len(infos) > MAX_ARCHIVE_ENTRIES:
                    errors.append(
                        f"Archive contains more than {MAX_ARCHIVE_ENTRIES} entries"
                    )
                for info in infos:
                    try:
                        path = _relative_package_path(
                            info.filename,
                            name="archive entry",
                        )
                    except ValueError as exc:
                        errors.append(f"{info.filename!r}: {exc}")
                        continue
                    normalized = path.as_posix()
                    if normalized in names:
                        errors.append(
                            f"Archive contains duplicate entry {normalized!r}"
                        )
                    names.add(normalized)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        errors.append(
                            f"Archive entry {normalized!r} is a symbolic link"
                        )
                    total_uncompressed += int(info.file_size)
                    if (
                        info.compress_size > 0
                        and info.file_size / info.compress_size
                        > MAX_COMPRESSION_RATIO
                    ):
                        errors.append(
                            f"Archive entry {normalized!r} exceeds the "
                            "compression-ratio safety limit"
                        )
                    entries.append(
                        {
                            "path": normalized,
                            "bytes": int(info.file_size),
                            "compressedBytes": int(info.compress_size),
                            "directory": info.is_dir(),
                        }
                    )
        except BadZipFile as exc:
            errors.append(f"Package is not a valid ZIP archive: {exc}")

        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            errors.append(
                "Archive expands beyond the maximum uncompressed package size"
            )
        required_paths = {
            _relative_package_path(
                payload["runtime"]["entrypoint"],
                name="runtime.entrypoint",
            ).as_posix(),
            _relative_package_path(
                payload["context"]["summaryIndex"],
                name="context.summaryIndex",
            ).as_posix(),
            _relative_package_path(
                package["sbomPath"],
                name="package.sbomPath",
            ).as_posix(),
        }
        missing = sorted(path for path in required_paths if path not in names)
        if missing:
            errors.append(f"Archive is missing required paths: {missing}")

        detached_bundle = _safe_child(
            archive.parent,
            payload["signature"]["bundlePath"],
            name="signature.bundlePath",
        )
        bundle_package_path = _relative_package_path(
            payload["signature"]["bundlePath"],
            name="signature.bundlePath",
        ).as_posix()
        if bundle_package_path in names:
            errors.append(
                "Detached signature bundle must not be embedded in the archive"
            )
        if not detached_bundle.is_file():
            errors.append(f"Detached signature bundle is missing: {detached_bundle}")
        elif detached_bundle.stat().st_size > MAX_SIGNATURE_BUNDLE_BYTES:
            errors.append("Detached signature bundle exceeds the size limit")
        else:
            try:
                bundle_payload = json.loads(
                    detached_bundle.read_text(encoding="utf-8")
                )
                if not isinstance(bundle_payload, dict):
                    errors.append("Detached signature bundle must be a JSON object")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"Detached signature bundle is invalid JSON: {exc}")

        return {
            "schema": MODULE_INSPECTION_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archivePath": str(archive),
            "archiveSha256": actual_hash,
            "archiveBytes": actual_bytes,
            "manifestSha256": _canonical_manifest_sha256(payload),
            "signatureBundlePath": str(detached_bundle),
            "entryCount": len(entries),
            "uncompressedBytes": total_uncompressed,
            "safeToVerify": not errors,
            "activationReady": False,
            "signatureStatus": "verification_required",
            "errors": errors,
            "entries": entries,
            "nextRequiredReceipts": [
                "publisher-trust",
                "cosign-bundle-verification",
                "dependency-resolution",
                "sbom-policy",
                "vulnerability-scan",
                "malware-scan",
                "permission-review",
                "isolated-smoke-test",
            ],
        }

    def build_install_plan(
        self,
        manifest: object,
        archive_path: str | Path,
        *,
        current_version: str = "",
    ) -> dict[str, Any]:
        inspection = self.inspect_package(manifest, archive_path)
        payload = self.require_valid_manifest(manifest)
        target = (
            self.module_root / payload["moduleId"] / "versions" / payload["version"]
        )
        blocked_by = (
            inspection["nextRequiredReceipts"]
            if inspection["safeToVerify"]
            else ["archive-inspection"]
        )
        return {
            "schema": MODULE_INSTALL_PLAN_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "currentVersion": current_version,
            "targetPath": str(target),
            "activationPointer": str(
                self.module_root / payload["moduleId"] / "current.json"
            ),
            "packageInspection": inspection,
            "canStage": inspection["safeToVerify"],
            "canActivate": False,
            "distribution": {
                "authoritative": payload["distribution"]["registryRef"],
                "p2pEligible": payload["distribution"]["p2pEligible"],
                "pinPolicy": payload["distribution"]["pinPolicy"],
                "integrityKey": payload["package"]["archiveSha256"],
            },
            "steps": [
                "inspect immutable archive and detached signature envelope",
                "verify trusted publisher identity and Cosign bundle",
                "resolve required module versions from active immutable installs",
                "extract only safe paths into quarantine",
                "compare declared and independently generated SBOM evidence",
                "block high or critical known vulnerabilities",
                "scan archive and extracted payload for malware",
                "bind permission approval to the exact manifest and archive hash",
                "smoke-test inside the declared runtime boundary",
                "move the verified version into immutable module storage",
                "atomically switch the activation pointer",
                "retain the prior pointer and receipts for rollback",
            ],
            "blockedBy": blocked_by,
        }

    @staticmethod
    def _is_sha256(value: object) -> bool:
        return bool(re.fullmatch(r"[a-f0-9]{64}", str(value or "")))

    def _oci_subject(
        self,
        payload: dict[str, Any],
        archive_sha256: str,
        archive_bytes: int,
        payload_proof: object,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
        proof = dict(payload_proof) if isinstance(payload_proof, dict) else {}
        registry = _parse_registry_ref(
            payload["distribution"]["registryRef"],
            version=payload["version"],
        )
        config_descriptor = _oci_descriptor(
            OCI_MODULE_CONFIG_MEDIA_TYPE,
            _canonical_manifest_bytes(payload),
        )
        archive_descriptor = {
            "mediaType": OCI_MODULE_LAYER_MEDIA_TYPE,
            "digest": f"sha256:{archive_sha256}",
            "size": archive_bytes,
            "annotations": {"io.neyvia.layer.role": "module-package"},
        }
        subject_manifest = {
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            "artifactType": OCI_MODULE_ARTIFACT_TYPE,
            "config": config_descriptor,
            "layers": [archive_descriptor],
            "annotations": {
                "org.opencontainers.image.ref.name": registry["taggedRef"],
                "org.opencontainers.image.version": payload["version"],
                "io.neyvia.module.id": payload["moduleId"],
                "io.neyvia.publisher.id": payload["publisher"]["id"],
                "io.neyvia.publisher.identity": payload["publisher"]["identity"],
                "io.neyvia.module.manifest.sha256": (
                    _canonical_manifest_sha256(payload)
                ),
                "io.neyvia.payload.tree.sha256": str(
                    proof.get("treeSha256") or ""
                ),
                "io.neyvia.payload.entrypoint.sha256": str(
                    proof.get("entrypointSha256") or ""
                ),
            },
        }
        descriptor = _oci_descriptor(
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            _canonical_json_bytes(subject_manifest),
        )
        subject = {
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": archive_sha256,
            "manifestSha256": _canonical_manifest_sha256(payload),
            "payloadTreeSha256": str(proof.get("treeSha256") or ""),
            "entrypointSha256": str(proof.get("entrypointSha256") or ""),
            "registryRef": registry["taggedRef"],
            "ociSubjectDigest": descriptor["digest"],
        }
        return subject, subject_manifest, registry

    def _oci_verifier_allowed(
        self,
        gate: str,
        verifier: object,
    ) -> bool:
        if not isinstance(verifier, dict):
            return False
        trust = self._external_verifier_trust()
        allowlist = trust.get("verifiers")
        if not isinstance(allowlist, dict):
            return False
        allowed = allowlist.get(gate)
        return bool(
            isinstance(allowed, list)
            and any(
                isinstance(item, dict) and item == verifier
                for item in allowed
            )
        )

    def _path_is_outside_managed_roots(self, path: Path) -> bool:
        resolved = path.resolve()
        for root in (self.root, self.module_root):
            try:
                resolved.relative_to(root.resolve())
                return False
            except ValueError:
                continue
        return True

    def _external_verifier_trust(self) -> dict[str, Any]:
        path = self.verifier_trust_path
        if (
            path is None
            or not path.is_absolute()
            or not path.is_file()
            or not self._path_is_outside_managed_roots(path)
        ):
            return {}
        try:
            trust = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if (
            not isinstance(trust, dict)
            or trust.get("schema") != OCI_VERIFIER_TRUST_SCHEMA
            or trust.get("policyVersion") != OCI_EVIDENCE_POLICY_VERSION
            or not isinstance(trust.get("verifiers"), dict)
            or not isinstance(trust.get("publicKeys"), dict)
        ):
            return {}
        return dict(trust)

    def _oci_verifier_public_key(
        self,
        key_id: object,
    ) -> Ed25519PublicKey | None:
        keys = self._external_verifier_trust().get("publicKeys")
        configured = keys.get(str(key_id or "")) if isinstance(keys, dict) else None
        if not isinstance(configured, dict):
            return None
        path = Path(str(configured.get("path") or "")).resolve()
        expected_sha256 = str(configured.get("sha256") or "")
        if (
            not path.is_absolute()
            or not self._path_is_outside_managed_roots(path)
            or not path.is_file()
            or path.stat().st_size not in range(32, 65_537)
            or not self._is_sha256(expected_sha256)
            or not hmac.compare_digest(_sha256(path), expected_sha256)
        ):
            return None
        try:
            key = load_pem_public_key(path.read_bytes())
        except (OSError, ValueError, TypeError):
            return None
        return key if isinstance(key, Ed25519PublicKey) else None

    @staticmethod
    def _oci_attestation_signature_input(
        gate: str,
        evidence: object,
        attestation: dict[str, Any],
    ) -> bytes:
        return _canonical_json_bytes(
            {
                "gate": gate,
                "evidenceSha256": hashlib.sha256(
                    _canonical_json_bytes(evidence)
                ).hexdigest(),
                "schema": attestation.get("schema"),
                "subject": attestation.get("subject"),
                "verifier": attestation.get("verifier"),
                "policyVersion": attestation.get("policyVersion"),
                "verifiedAt": attestation.get("verifiedAt"),
            }
        )

    def _oci_attestation_errors(
        self,
        gate: str,
        receipt: dict[str, Any],
        expected_subject: dict[str, Any],
    ) -> list[str]:
        attestation = receipt.get("attestation")
        if not isinstance(attestation, dict):
            return [f"OCI evidence gate {gate} has no authenticated attestation"]
        errors: list[str] = []
        trust = self._external_verifier_trust()
        if not trust:
            errors.append(
                f"OCI evidence gate {gate} has no externally provisioned "
                "verifier trust"
            )
        if attestation.get("schema") != OCI_EVIDENCE_ATTESTATION_SCHEMA:
            errors.append(f"OCI evidence gate {gate} attestation schema is invalid")
        if attestation.get("subject") != expected_subject:
            errors.append(f"OCI evidence gate {gate} is not bound to the OCI subject")
        policy_version = str(trust.get("policyVersion") or "")
        if attestation.get("policyVersion") != policy_version:
            errors.append(f"OCI evidence gate {gate} policy version is not accepted")
        verifier = attestation.get("verifier")
        if not self._oci_verifier_allowed(gate, verifier):
            errors.append(f"OCI evidence gate {gate} verifier is not allowlisted")
        authentication = attestation.get("authentication")
        if (
            not isinstance(authentication, dict)
            or authentication.get("scheme") != "ed25519"
            or not isinstance(verifier, dict)
            or authentication.get("keyId") != verifier.get("keyId")
        ):
            errors.append(f"OCI evidence gate {gate} is not authenticated")
        else:
            key = self._oci_verifier_public_key(authentication.get("keyId"))
            try:
                signature = base64.b64decode(
                    str(authentication.get("signature") or ""),
                    validate=True,
                )
                if key is None:
                    raise InvalidSignature
                key.verify(
                    signature,
                    self._oci_attestation_signature_input(
                        gate,
                        receipt.get("evidence"),
                        attestation,
                    ),
                )
            except (InvalidSignature, ValueError):
                errors.append(
                    f"OCI evidence gate {gate} authentication failed"
                )
        verified_at = str(attestation.get("verifiedAt") or "")
        if receipt.get("recordedAt") != verified_at:
            errors.append(
                f"OCI evidence gate {gate} collection time is not signed"
            )
        try:
            observed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("timezone required")
            age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc))
            max_age = int(
                trust.get("maxAgeSeconds")
                or DEFAULT_OCI_EVIDENCE_MAX_AGE_SECONDS
            )
            if age.total_seconds() < -300 or age.total_seconds() > max_age:
                errors.append(f"OCI evidence gate {gate} attestation is not fresh")
        except (TypeError, ValueError, OverflowError):
            errors.append(f"OCI evidence gate {gate} verifiedAt is invalid")
        return errors

    def _oci_evidence_errors(
        self,
        payload: dict[str, Any],
        evidence_bundle: object,
        *,
        expected_subject: dict[str, Any],
    ) -> list[str]:
        if not isinstance(evidence_bundle, dict):
            return ["OCI security evidence bundle is missing"]
        errors: list[str] = []
        if evidence_bundle.get("schema") != MODULE_OCI_EVIDENCE_SCHEMA:
            errors.append("OCI security evidence uses an unsupported schema")
        subject = evidence_bundle.get("subject")
        if subject != expected_subject:
            errors.append("OCI security evidence is not bound to this module subject")

        receipts = evidence_bundle.get("gateReceipts")
        if not isinstance(receipts, list):
            return errors + ["OCI security evidence has no gate receipts"]
        by_gate: dict[str, dict[str, Any]] = {}
        for receipt in receipts:
            if not isinstance(receipt, dict):
                continue
            gate = str(receipt.get("gate") or "")
            if gate in by_gate:
                errors.append(f"OCI security evidence duplicates gate {gate}")
            by_gate[gate] = receipt
        for gate in OCI_REQUIRED_SECURITY_GATES:
            receipt = by_gate.get(gate)
            if not receipt:
                errors.append(f"OCI security evidence is missing gate {gate}")
                continue
            if (
                receipt.get("schema") != MODULE_GATE_RECEIPT_SCHEMA
                or receipt.get("passed") is not True
                or receipt.get("status") != "passed"
                or receipt.get("moduleId") != payload["moduleId"]
                or receipt.get("version") != payload["version"]
            ):
                errors.append(
                    f"OCI security evidence gate {gate} is not a passing "
                    "receipt for this module version"
                )
            errors.extend(
                self._oci_attestation_errors(gate, receipt, expected_subject)
            )

        publisher = by_gate.get("publisher-trust", {}).get("evidence")
        if not isinstance(publisher, dict) or (
            publisher.get("publisherId") != payload["publisher"]["id"]
            or publisher.get("publisherIdentity")
            != payload["publisher"]["identity"]
            or not str(publisher.get("bindingId") or "")
        ):
            errors.append("Publisher trust evidence does not bind the declared identity")

        dependency = by_gate.get("dependency-resolution", {}).get("evidence")
        resolved_dependencies = (
            dependency.get("dependencies")
            if isinstance(dependency, dict)
            else None
        )
        declared_dependencies = {
            item["moduleId"]: item
            for item in payload.get("dependencies", [])
            if isinstance(item, dict)
        }
        resolved_by_id = {
            str(item.get("moduleId") or ""): item
            for item in resolved_dependencies or []
            if isinstance(item, dict)
        }
        if (
            not isinstance(resolved_dependencies, list)
            or set(resolved_by_id) != set(declared_dependencies)
            or any(
                resolved_by_id[module_id].get("requiredVersion")
                != declared["version"]
                or resolved_by_id[module_id].get("required")
                != (declared.get("required") is True)
                or (
                    declared.get("required") is True
                    and resolved_by_id[module_id].get("matched") is not True
                )
                for module_id, declared in declared_dependencies.items()
            )
        ):
            errors.append(
                "Dependency evidence does not bind every declared dependency"
            )

        signature = by_gate.get("cosign-bundle-verification", {}).get("evidence")
        declared_signature = payload["signature"]
        if not isinstance(signature, dict) or (
            signature.get("manifestSha256")
            != _canonical_manifest_sha256(payload)
            or not self._is_sha256(signature.get("bundleSha256"))
            or signature.get("identity", "")
            != declared_signature.get("identity", "")
            or signature.get("issuer", "")
            != declared_signature.get("issuer", "")
            or signature.get("keyId", "")
            != declared_signature.get("keyId", "")
        ):
            errors.append(
                "Signature evidence does not bind the manifest, bundle, and "
                "publisher credentials"
            )

        sbom = by_gate.get("sbom-policy", {}).get("evidence")
        if not isinstance(sbom, dict) or not all(
            self._is_sha256(sbom.get(field))
            for field in ("declaredSha256", "generatedSha256")
        ):
            errors.append(
                "SBOM evidence requires declared and independently generated digests"
            )

        vulnerability = by_gate.get("vulnerability-scan", {}).get("evidence")
        vulnerability_result = (
            vulnerability.get("commandResult")
            if isinstance(vulnerability, dict)
            else None
        )
        vulnerability_database = (
            vulnerability.get("database")
            if isinstance(vulnerability, dict)
            else None
        )
        vulnerability_input = (
            vulnerability.get("inputSbom")
            if isinstance(vulnerability, dict)
            else None
        )
        database_fresh = False
        if isinstance(vulnerability_database, dict):
            try:
                database_built = datetime.fromisoformat(
                    str(vulnerability_database.get("builtAt") or "").replace(
                        "Z",
                        "+00:00",
                    )
                )
                database_observed = datetime.fromisoformat(
                    str(vulnerability_database.get("observedAt") or "").replace(
                        "Z",
                        "+00:00",
                    )
                )
                if database_built.tzinfo is None or database_observed.tzinfo is None:
                    raise ValueError("timezone required")
                calculated_age = (
                    database_observed.astimezone(timezone.utc)
                    - database_built.astimezone(timezone.utc)
                ).total_seconds()
                current_age = (
                    datetime.now(timezone.utc)
                    - database_built.astimezone(timezone.utc)
                ).total_seconds()
                database_fresh = (
                    -300 <= calculated_age
                    <= int(vulnerability_database.get("maxAgeSeconds"))
                    and -300 <= current_age
                    <= int(vulnerability_database.get("maxAgeSeconds"))
                    and abs(
                        calculated_age
                        - float(vulnerability_database.get("ageSeconds"))
                    )
                    <= 600
                )
            except (TypeError, ValueError, OverflowError):
                database_fresh = False
        if (
            not isinstance(vulnerability, dict)
            or not isinstance(vulnerability.get("tool"), dict)
            or not vulnerability.get("tool")
            or not str(vulnerability.get("threshold") or "")
            or vulnerability.get("blockingFindingCount") != 0
            or not isinstance(vulnerability_result, dict)
            or vulnerability_result.get("returnCode") != 0
            or not isinstance(vulnerability_database, dict)
            or not self._is_sha256(
                vulnerability_database.get("identitySha256")
            )
            or not str(vulnerability_database.get("builtAt") or "")
            or not isinstance(
                vulnerability_database.get("maxAgeSeconds"), int
            )
            or vulnerability_database.get("ageSeconds") is None
            or vulnerability_database["ageSeconds"]
            > vulnerability_database["maxAgeSeconds"]
            or not database_fresh
            or not isinstance(vulnerability_input, dict)
            or vulnerability_input.get("sha256")
            != (
                sbom.get("generatedSha256")
                if isinstance(sbom, dict)
                else None
            )
        ):
            errors.append(
                "Vulnerability evidence requires an authenticated clean policy scan"
            )

        malware = by_gate.get("malware-scan", {}).get("evidence")
        scans = malware.get("scans") if isinstance(malware, dict) else None
        scans_by_role = {
            str(scan.get("targetRole") or ""): scan
            for scan in scans or []
            if isinstance(scan, dict)
        }
        archive_scan = scans_by_role.get("archive-snapshot")
        payload_scan = scans_by_role.get("extracted-payload")
        if (
            not isinstance(malware, dict)
            or not isinstance(malware.get("tool"), dict)
            or not malware.get("tool")
            or not isinstance(scans, list)
            or not scans
            or not isinstance(archive_scan, dict)
            or not isinstance(payload_scan, dict)
            or archive_scan.get("binding", {}).get("sha256")
            != expected_subject["archiveSha256"]
            or payload_scan.get("binding", {}).get("treeSha256")
            != expected_subject["payloadTreeSha256"]
            or any(
                not isinstance(scan, dict)
                or not isinstance(scan.get("result"), dict)
                or scan["result"].get("returnCode") != 0
                or scan.get("binding") != scan.get("postScanBinding")
                or not str(scan.get("observedAt") or "")
                for scan in scans
            )
        ):
            errors.append(
                "Malware evidence requires a named scanner and successful scan result"
            )

        permission = by_gate.get("permission-review", {}).get("evidence")
        if (
            not isinstance(permission, dict)
            or not str(permission.get("reviewId") or "")
            or not str(permission.get("approvedBy") or "")
            or not isinstance(permission.get("acceptedPermissions"), list)
        ):
            errors.append(
                "Permission evidence requires a bound operator approval"
            )

        isolation = by_gate.get("isolated-smoke-test", {}).get("evidence")
        runtime = payload["runtime"]
        if not isinstance(isolation, dict) or (
            isolation.get("runtimeKind") != runtime["kind"]
        ):
            errors.append("Isolation evidence does not bind the declared runtime")
        elif runtime["kind"] == "content-pack":
            if (
                isolation.get("isolation")
                != "non-executable content validation"
                or not self._is_sha256(isolation.get("contextSha256"))
            ):
                errors.append(
                    "Content-pack isolation evidence is incomplete"
                )
        elif runtime["kind"] == "wasm-component":
            command = isolation.get("commandResult")
            if (
                isolation.get("filesystemAccess") != "none"
                or isolation.get("inheritedEnvironment") != []
                or isolation.get("networkAccess") != "none"
                or not isinstance(command, dict)
                or command.get("returnCode") != 0
            ):
                errors.append("WASM isolation proof does not show a sealed runtime")
        else:
            errors.append(
                "Executable service/full-app OCI activation has no supported "
                "isolation proof contract"
            )
        return sorted(set(errors))

    def build_oci_artifact_plan(
        self,
        manifest: object,
        archive_path: str | Path,
        *,
        install_receipt: object | None = None,
    ) -> dict[str, Any]:
        """Plan an OCI artifact entirely from local, content-addressed inputs."""

        payload = self.require_valid_manifest(manifest)
        inspection = self.inspect_package(payload, archive_path)
        archive = Path(archive_path).resolve()
        module_id = _safe_module_id(payload["moduleId"])
        target = self.module_root / module_id / "versions" / payload["version"]
        stored_receipt_path = target / ".neyvia" / "install-receipt.json"
        stored_receipt = self._read_json(stored_receipt_path)
        actual_payload_proof: dict[str, Any] = {}
        payload_proof_error = ""
        try:
            actual_payload_proof = _payload_tree_proof(
                target,
                payload["runtime"]["entrypoint"],
            )
        except (OSError, ValueError) as exc:
            payload_proof_error = str(exc)
        gate_receipts = (
            install_receipt.get("gateReceipts")
            if isinstance(install_receipt, dict)
            else None
        )
        evidence_bundle: dict[str, Any] | None = None
        evidence_errors: list[str] = []
        valid_install_receipt = bool(
            isinstance(install_receipt, dict)
            and install_receipt.get("schema") == MODULE_INSTALL_RECEIPT_SCHEMA
            and install_receipt.get("moduleId") == payload["moduleId"]
            and install_receipt.get("version") == payload["version"]
            and install_receipt.get("archiveSha256")
            == payload["package"]["archiveSha256"]
            and install_receipt.get("manifestSha256")
            == _canonical_manifest_sha256(payload)
            and not install_receipt.get("blockedBy")
            and install_receipt.get("status")
            in {"activated", "installed", "already_installed"}
            and install_receipt == stored_receipt
            and install_receipt.get("payloadProof") == actual_payload_proof
        )
        subject, subject_manifest, registry = self._oci_subject(
            payload,
            inspection["archiveSha256"],
            inspection["archiveBytes"],
            actual_payload_proof if valid_install_receipt else {},
        )
        if gate_receipts is None or not valid_install_receipt:
            evidence_errors.append(
                "An exact locally stored install receipt and payload-tree proof "
                "are required to attach OCI security evidence"
            )
        if payload_proof_error:
            evidence_errors.append(
                f"Installed payload tree is unproven: {payload_proof_error}"
            )
        if gate_receipts is not None:
            evidence_bundle = {
                "schema": MODULE_OCI_EVIDENCE_SCHEMA,
                "subject": subject,
                "gateReceipts": [
                    dict(item)
                    for item in gate_receipts
                    if isinstance(item, dict)
                    and item.get("gate") in OCI_REQUIRED_SECURITY_GATES
                ],
            }
            evidence_errors.extend(
                self._oci_evidence_errors(
                    payload,
                    evidence_bundle,
                    expected_subject=subject,
                )
            )

        evidence_descriptor: dict[str, Any] | None = None
        oci_manifest = json.loads(json.dumps(subject_manifest))
        if evidence_bundle is not None:
            evidence_descriptor = _oci_descriptor(
                OCI_SECURITY_EVIDENCE_MEDIA_TYPE,
                _canonical_json_bytes(evidence_bundle),
            )
            evidence_descriptor["annotations"] = {
                "io.neyvia.layer.role": "security-evidence"
            }
            oci_manifest["layers"].append(evidence_descriptor)
        oci_manifest["annotations"]["io.neyvia.oci.subject.digest"] = subject[
            "ociSubjectDigest"
        ]
        manifest_descriptor = _oci_descriptor(
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            _canonical_json_bytes(oci_manifest),
        )
        final_resolved_ref = (
            f"{registry['registry']}/{registry['repository']}"
            f"@{manifest_descriptor['digest']}"
        )
        blocked_by = []
        if not inspection["safeToVerify"]:
            blocked_by.append("archive-inspection")
        if evidence_errors:
            blocked_by.extend(OCI_REQUIRED_SECURITY_GATES)
        dependency = self.dependency_compatibility(payload)
        if not dependency["compatible"]:
            blocked_by.append("dependency-resolution")
        return {
            "schema": MODULE_OCI_PLAN_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "ociManifest": oci_manifest,
            "ociManifestDescriptor": manifest_descriptor,
            "configBlob": payload,
            "archivePath": str(archive),
            "securityEvidence": evidence_bundle,
            "securityEvidenceDescriptor": evidence_descriptor,
            "securityEvidenceErrors": evidence_errors,
            "payloadProof": actual_payload_proof,
            "ociSubject": subject,
            "dependencyCompatibility": dependency,
            "distribution": {
                **registry,
                "resolvedRef": final_resolved_ref,
                "manifestDigest": manifest_descriptor["digest"],
                "evidenceSubjectDigest": subject["ociSubjectDigest"],
            },
            "canMaterialize": inspection["safeToVerify"],
            "activationReady": not blocked_by,
            "blockedBy": sorted(set(blocked_by)),
            "offlineOnly": True,
        }

    def inspect_oci_artifact(
        self,
        manifest: object,
        archive_path: str | Path,
        oci_manifest: object,
        *,
        security_evidence: object | None = None,
    ) -> dict[str, Any]:
        """Inspect a local OCI manifest and its local module/evidence blobs."""

        payload = self.require_valid_manifest(manifest)
        archive_inspection = self.inspect_package(payload, archive_path)
        errors: list[str] = list(archive_inspection["errors"])
        module_id = _safe_module_id(payload["moduleId"])
        target = self.module_root / module_id / "versions" / payload["version"]
        stored_receipt = self._read_json(
            target / ".neyvia" / "install-receipt.json"
        )
        expected_plan = self.build_oci_artifact_plan(
            payload,
            archive_path,
            install_receipt=stored_receipt or None,
        )
        evidence_errors = self._oci_evidence_errors(
            payload,
            security_evidence,
            expected_subject=expected_plan["ociSubject"],
        )
        evidence_errors.extend(expected_plan["securityEvidenceErrors"])
        if security_evidence != expected_plan["securityEvidence"]:
            evidence_errors.append(
                "OCI evidence does not equal the locally stored attested receipt set"
            )
        dependency = self.dependency_compatibility(payload)
        if isinstance(security_evidence, dict):
            receipts = {
                str(item.get("gate") or ""): item
                for item in security_evidence.get("gateReceipts", [])
                if isinstance(item, dict)
            }
            signature_evidence = receipts.get(
                "cosign-bundle-verification", {}
            ).get("evidence", {})
            actual_bundle = Path(archive_inspection["signatureBundlePath"])
            if (
                not actual_bundle.is_file()
                or not isinstance(signature_evidence, dict)
                or signature_evidence.get("bundleSha256")
                != _sha256(actual_bundle)
            ):
                evidence_errors.append(
                    "Signature evidence bundle digest does not match the "
                    "local detached bundle"
                )
            sbom_evidence = receipts.get("sbom-policy", {}).get("evidence", {})
            try:
                declared_sbom_sha = _zip_member_sha256(
                    Path(archive_path).resolve(),
                    _relative_package_path(
                        payload["package"]["sbomPath"],
                        name="package.sbomPath",
                    ).as_posix(),
                )
            except (OSError, KeyError, BadZipFile, ValueError):
                declared_sbom_sha = ""
            if (
                not isinstance(sbom_evidence, dict)
                or sbom_evidence.get("declaredSha256") != declared_sbom_sha
            ):
                evidence_errors.append(
                    "SBOM evidence digest does not match the declared local SBOM"
                )
            isolation_evidence = receipts.get(
                "isolated-smoke-test", {}
            ).get("evidence", {})
            try:
                context_sha = _zip_member_sha256(
                    Path(archive_path).resolve(),
                    _relative_package_path(
                        payload["context"]["summaryIndex"],
                        name="context.summaryIndex",
                    ).as_posix(),
                )
            except (OSError, KeyError, BadZipFile, ValueError):
                context_sha = ""
            if (
                not isinstance(isolation_evidence, dict)
                or isolation_evidence.get("contextSha256") != context_sha
            ):
                evidence_errors.append(
                    "Isolation proof does not bind the local context payload"
                )
        evidence_errors = sorted(set(evidence_errors))

        if not isinstance(oci_manifest, dict):
            errors.append("OCI artifact manifest must be an object")
            oci_manifest = {}
        expected_manifest = expected_plan["ociManifest"]
        if oci_manifest != expected_manifest:
            errors.append(
                "OCI artifact manifest is not the canonical manifest for these "
                "local module and evidence blobs"
            )

        descriptor = _oci_descriptor(
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            _canonical_json_bytes(oci_manifest),
        )
        blocked_by: list[str] = []
        if errors:
            blocked_by.append("oci-artifact-integrity")
        if evidence_errors:
            blocked_by.extend(OCI_REQUIRED_SECURITY_GATES)
        if not dependency["compatible"]:
            blocked_by.append("dependency-resolution")
        return {
            "schema": MODULE_OCI_INSPECTION_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "ociManifestDescriptor": descriptor,
            "archiveSha256": archive_inspection["archiveSha256"],
            "securityEvidenceDigest": (
                hashlib.sha256(
                    _canonical_json_bytes(security_evidence)
                ).hexdigest()
                if isinstance(security_evidence, dict)
                else ""
            ),
            "payloadProof": expected_plan["payloadProof"],
            "ociSubject": expected_plan["ociSubject"],
            "evidenceGatesPassed": not evidence_errors,
            "dependencyCompatibility": dependency,
            "activationReady": not blocked_by,
            "blockedBy": sorted(set(blocked_by)),
            "errors": sorted(set(errors + evidence_errors + dependency["errors"])),
            "registryContacted": False,
        }

    def build_package(
        self,
        source_root: str | Path,
        manifest: object,
        archive_path: str | Path,
        *,
        manifest_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Create a deterministic package and bind its final digest to a manifest."""

        source = Path(source_root).resolve()
        if not source.is_dir():
            raise NotADirectoryError(source)
        draft = dict(manifest) if isinstance(manifest, dict) else {}
        package = dict(draft.get("package") or {})
        package.setdefault("mediaType", "application/vnd.neyvia.module+zip")
        package["archiveSha256"] = "0" * 64
        package["archiveBytes"] = 1
        draft["package"] = package

        archive = Path(archive_path).resolve()
        archive.parent.mkdir(parents=True, exist_ok=True)
        try:
            archive.relative_to(source)
        except ValueError:
            pass
        else:
            raise ValueError("archive_path must be outside source_root")

        files: list[tuple[Path, str]] = []
        total_bytes = 0
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Package source contains a symbolic link: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            _relative_package_path(relative, name="package source path")
            total_bytes += path.stat().st_size
            if total_bytes > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Package source exceeds the uncompressed size limit")
            files.append((path, relative))
        if not files:
            raise ValueError("Package source contains no files")
        if len(files) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("Package source contains too many files")

        temporary = archive.with_name(f".{archive.name}.{uuid.uuid4().hex}.tmp")
        try:
            with ZipFile(
                temporary,
                "x",
                compression=ZIP_DEFLATED,
                compresslevel=9,
            ) as package_zip:
                for source_path, relative in files:
                    info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    with source_path.open("rb") as input_handle, package_zip.open(
                        info, "w"
                    ) as output_handle:
                        shutil.copyfileobj(
                            input_handle,
                            output_handle,
                            length=1024 * 1024,
                        )
            os.replace(temporary, archive)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        package["archiveSha256"] = _sha256(archive)
        package["archiveBytes"] = archive.stat().st_size
        draft["package"] = package
        validation = self.validate_manifest(draft)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        selected_manifest_path = Path(
            manifest_path or archive.with_name(f"{archive.name}.manifest.json")
        ).resolve()
        atomic_write_json(selected_manifest_path, draft)
        canonical_path = archive.with_name(
            f"{archive.name}.manifest.canonical.json"
        )
        atomic_write_text(
            canonical_path,
            _canonical_manifest_bytes(draft).decode("utf-8"),
        )
        receipt = {
            "schema": MODULE_BUILD_RECEIPT_SCHEMA,
            "receiptId": uuid.uuid4().hex,
            "status": "built",
            "moduleId": draft["moduleId"],
            "version": draft["version"],
            "sourceRoot": str(source),
            "archivePath": str(archive),
            "archiveSha256": package["archiveSha256"],
            "archiveBytes": package["archiveBytes"],
            "manifestPath": str(selected_manifest_path),
            "manifestSha256": validation["manifestSha256"],
            "canonicalManifestPath": str(canonical_path),
            "entryCount": len(files),
            "uncompressedBytes": total_bytes,
            "builtAt": _utc_now(),
            "manifest": draft,
        }
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    def sign_package(
        self,
        manifest: object,
        archive_path: str | Path,
        *,
        key_reference: str = "keyless",
    ) -> dict[str, Any]:
        """Sign the canonical manifest; private keys and passwords are never logged."""

        payload = self.require_valid_manifest(manifest)
        archive = Path(archive_path).resolve()
        if not archive.is_file():
            raise FileNotFoundError(archive)
        if (
            archive.stat().st_size != int(payload["package"]["archiveBytes"])
            or not hmac.compare_digest(
                _sha256(archive),
                payload["package"]["archiveSha256"],
            )
        ):
            raise ValueError("Archive no longer matches the manifest")
        bundle = _safe_child(
            archive.parent,
            payload["signature"]["bundlePath"],
            name="signature.bundlePath",
        )
        canonical_path = archive.with_name(
            f"{archive.name}.manifest.canonical.json"
        )
        atomic_write_text(
            canonical_path,
            _canonical_manifest_bytes(payload).decode("utf-8"),
        )
        cosign = self._tool("cosign")
        errors: list[str] = []
        if not cosign["healthy"]:
            errors.append("Pinned Cosign executable is unavailable or hash-mismatched")
        args = [
            cosign["path"],
            "sign-blob",
            "--yes",
        ]
        normalized_key = str(key_reference or "keyless").strip()
        if normalized_key.casefold() != "keyless":
            key_path = Path(normalized_key)
            resolved_key = (
                str(key_path.resolve()) if key_path.exists() else normalized_key
            )
            args.extend(["--key", resolved_key])
        args.extend(["--bundle", str(bundle), str(canonical_path)])
        result = (
            self._run_command(args, timeout=180, cwd=archive.parent)
            if not errors
            else {"returnCode": -1, "stdout": "", "stderr": "", "durationMs": 0}
        )
        if result["returnCode"] != 0 and not errors:
            errors.append("Cosign could not sign the canonical manifest")
        receipt = self._gate_receipt(
            "module-signing",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence={
                "tool": cosign,
                "keyMode": (
                    "keyless"
                    if normalized_key.casefold() == "keyless"
                    else "external-key-reference"
                ),
                "bundlePath": str(bundle),
                "bundleSha256": _sha256(bundle) if bundle.is_file() else "",
                "manifestSha256": _canonical_manifest_sha256(payload),
                "commandResult": result,
            },
        )
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    def publish_to_local_registry(
        self,
        manifest: object,
        archive_path: str | Path,
        *,
        install_receipt: object,
        published_by: str,
        registry_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Publish a verified package into a content-addressed local/NAS seed."""

        payload = self.require_valid_manifest(manifest)
        publisher = str(published_by or "").strip()
        if not publisher:
            raise ValueError("published_by is required")
        if not isinstance(install_receipt, dict):
            raise ValueError("A verified install receipt is required")
        if (
            install_receipt.get("status")
            not in {"installed", "already_installed", "activated"}
            or install_receipt.get("moduleId") != payload["moduleId"]
            or install_receipt.get("version") != payload["version"]
            or install_receipt.get("archiveSha256")
            != payload["package"]["archiveSha256"]
            or install_receipt.get("manifestSha256")
            != _canonical_manifest_sha256(payload)
            or install_receipt.get("blockedBy")
        ):
            raise ValueError(
                "Install receipt is not a successful proof for this exact package"
            )
        installed_target = Path(
            str(install_receipt.get("targetPath") or "")
        ).resolve()
        expected_target = (
            self.module_root
            / _safe_module_id(payload["moduleId"])
            / "versions"
            / payload["version"]
        ).resolve()
        if installed_target != expected_target:
            raise ValueError("Install receipt target is outside the module store")
        archive = _installed_archive_path(
            installed_target,
            payload["package"]["archiveSha256"],
        )
        if not archive.is_file():
            raise ValueError("Verified immutable package snapshot is unavailable")
        inspection = self.inspect_package(payload, archive)
        if not inspection["safeToVerify"]:
            raise ValueError("; ".join(inspection["errors"]))

        registry = Path(
            registry_root or self.module_root / "registry"
        ).resolve()
        digest = payload["package"]["archiveSha256"]
        manifest_digest = _canonical_manifest_sha256(payload)
        target = registry / "by-package" / digest / manifest_digest
        target.mkdir(parents=True, exist_ok=True)
        archive_target = target / "package.nymod"
        if archive_target.is_file() and not hmac.compare_digest(
            _sha256(archive_target), digest
        ):
            raise ValueError("Content-addressed registry target is corrupted")
        if not archive_target.is_file():
            shutil.copyfile(archive, archive_target)
        bundle_target = target / "signature.sigstore.json"
        if not bundle_target.is_file():
            shutil.copyfile(
                Path(inspection["signatureBundlePath"]),
                bundle_target,
            )
        atomic_write_json(target / "manifest.json", payload)

        index_path = registry / "index" / f"{payload['moduleId']}.json"
        index = self._read_json(index_path)
        versions = (
            [
                dict(item)
                for item in index.get("versions", [])
                if isinstance(item, dict)
                and item.get("version") != payload["version"]
            ]
            if isinstance(index.get("versions"), list)
            else []
        )
        version_record = {
            "version": payload["version"],
            "archiveSha256": digest,
            "manifestSha256": manifest_digest,
            "channel": payload["update"]["channel"],
            "registryRef": payload["distribution"]["registryRef"],
            "p2pEligible": payload["distribution"]["p2pEligible"],
            "pinPolicy": payload["distribution"]["pinPolicy"],
            "path": str(target),
            "publishedAt": _utc_now(),
            "publishedBy": publisher,
        }
        versions.append(version_record)
        versions.sort(
            key=cmp_to_key(
                lambda left, right: _compare_semver(
                    str(left["version"]),
                    str(right["version"]),
                )
            )
        )
        atomic_write_json(
            index_path,
            {
                "schema": "neyvia.local-module-index/v1",
                "moduleId": payload["moduleId"],
                "publisher": payload["publisher"],
                "versions": versions,
            },
        )
        receipt = {
            "schema": MODULE_PUBLISH_RECEIPT_SCHEMA,
            "receiptId": uuid.uuid4().hex,
            "status": "published",
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": digest,
            "manifestSha256": manifest_digest,
            "registryRoot": str(registry),
            "contentPath": str(target),
            "indexPath": str(index_path),
            "p2pEligible": payload["distribution"]["p2pEligible"],
            "pinPolicy": payload["distribution"]["pinPolicy"],
            "publishedAt": version_record["publishedAt"],
            "publishedBy": publisher,
        }
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    def _read_trust_store(self) -> dict[str, Any]:
        if not self.trust_path.is_file():
            return {
                "schema": MODULE_PUBLISHER_TRUST_SCHEMA,
                "bindings": [],
            }
        try:
            payload = json.loads(self.trust_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "schema": MODULE_PUBLISHER_TRUST_SCHEMA,
                "bindings": [],
            }
        bindings = payload.get("bindings")
        return {
            "schema": MODULE_PUBLISHER_TRUST_SCHEMA,
            "bindings": (
                [dict(item) for item in bindings if isinstance(item, dict)]
                if isinstance(bindings, list)
                else []
            ),
        }

    def trust_publisher(
        self,
        manifest: object,
        *,
        approved_by: str,
        public_key_path: str | Path | None = None,
    ) -> dict[str, Any]:
        payload = self.require_valid_manifest(manifest)
        approver = str(approved_by or "").strip()
        if not approver:
            raise ValueError("approved_by is required for publisher trust")
        signature = payload["signature"]
        binding: dict[str, Any] = {
            "bindingId": uuid.uuid4().hex,
            "moduleId": payload["moduleId"],
            "publisherId": payload["publisher"]["id"],
            "publisherIdentity": payload["publisher"]["identity"],
            "scheme": signature["scheme"],
            "approvedBy": approver,
            "approvedAt": _utc_now(),
            "enabled": True,
        }
        if signature["scheme"] == "sigstore-cosign-bundle":
            binding["identity"] = signature["identity"]
            binding["issuer"] = signature["issuer"]
        else:
            source_key = Path(public_key_path or "").resolve()
            if not source_key.is_file():
                raise ValueError(
                    "public_key_path is required for key-backed publisher trust"
                )
            if source_key.stat().st_size > 1024 * 1024:
                raise ValueError("publisher public key exceeds the size limit")
            key_id = signature["keyId"]
            key_directory = self.module_root / "trust" / "keys"
            key_directory.mkdir(parents=True, exist_ok=True)
            key_target = key_directory / f"{key_id}.pub"
            shutil.copyfile(source_key, key_target)
            binding["keyId"] = key_id
            binding["publicKeyPath"] = str(key_target)
            binding["publicKeySha256"] = _sha256(key_target)

        store = self._read_trust_store()
        store["bindings"] = [
            item
            for item in store["bindings"]
            if not (
                item.get("moduleId") == payload["moduleId"]
                and item.get("publisherId") == payload["publisher"]["id"]
                and item.get("scheme") == signature["scheme"]
            )
        ]
        store["bindings"].append(binding)
        atomic_write_json(self.trust_path, store)
        receipt = self._gate_receipt(
            "publisher-trust",
            "passed",
            module_id=payload["moduleId"],
            version=payload["version"],
            evidence=binding,
        )
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    def revoke_publisher_trust(
        self,
        module_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        requester = str(requested_by or "").strip()
        if not requester or not str(reason or "").strip():
            raise ValueError("requested_by and reason are required")
        store = self._read_trust_store()
        changed = 0
        for binding in store["bindings"]:
            if binding.get("moduleId") == module_id and binding.get("enabled") is not False:
                binding["enabled"] = False
                binding["revokedAt"] = _utc_now()
                binding["revokedBy"] = requester
                binding["revocationReason"] = reason
                changed += 1
        atomic_write_json(self.trust_path, store)
        receipt = self._gate_receipt(
            "publisher-trust-revocation",
            "passed" if changed else "not_found",
            module_id=module_id,
            evidence={"changed": changed, "requestedBy": requester, "reason": reason},
        )
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    def _trusted_binding(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        signature = payload["signature"]
        for binding in self._read_trust_store()["bindings"]:
            if (
                binding.get("enabled") is not False
                and binding.get("moduleId") == payload["moduleId"]
                and binding.get("publisherId") == payload["publisher"]["id"]
                and binding.get("publisherIdentity")
                == payload["publisher"]["identity"]
                and binding.get("scheme") == signature["scheme"]
            ):
                if signature["scheme"] == "sigstore-cosign-bundle" and (
                    binding.get("identity") != signature.get("identity")
                    or binding.get("issuer") != signature.get("issuer")
                ):
                    continue
                if signature["scheme"] == "sigstore-cosign-key-bundle" and (
                    binding.get("keyId") != signature.get("keyId")
                ):
                    continue
                return binding
        return None

    def build_permission_review(
        self,
        manifest: object,
        *,
        approved_by: str,
        accepted_permissions: list[str],
    ) -> dict[str, Any]:
        payload = self.require_valid_manifest(manifest)
        approver = str(approved_by or "").strip()
        if not approver:
            raise ValueError("approved_by is required for permission review")
        accepted = sorted({str(item).strip() for item in accepted_permissions if str(item).strip()})
        declared = {
            str(item["permission"]): item
            for item in payload["permissions"]
            if isinstance(item, dict)
        }
        unknown = sorted(set(accepted) - set(declared))
        if unknown:
            raise ValueError(f"permission review contains undeclared permissions: {unknown}")
        missing_required = sorted(
            permission
            for permission, claim in declared.items()
            if claim.get("required") is True and permission not in accepted
        )
        if missing_required:
            raise ValueError(
                f"required permissions were not accepted: {missing_required}"
            )
        return {
            "schema": MODULE_PERMISSION_REVIEW_SCHEMA,
            "reviewId": uuid.uuid4().hex,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": payload["package"]["archiveSha256"],
            "manifestSha256": _canonical_manifest_sha256(payload),
            "acceptedPermissions": accepted,
            "deniedOptionalPermissions": sorted(set(declared) - set(accepted)),
            "claims": [declared[item] for item in accepted],
            "approvedBy": approver,
            "approvedAt": _utc_now(),
        }

    def _permission_review_receipt(
        self,
        payload: dict[str, Any],
        review: object,
    ) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(review, dict):
            errors.append("A structured permission review is required")
            review = {}
        expected = {
            "schema": MODULE_PERMISSION_REVIEW_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": payload["package"]["archiveSha256"],
            "manifestSha256": _canonical_manifest_sha256(payload),
        }
        for key, value in expected.items():
            if review.get(key) != value:
                errors.append(f"Permission review {key} does not match")
        required = {
            str(item["permission"])
            for item in payload["permissions"]
            if isinstance(item, dict) and item.get("required") is True
        }
        accepted = {
            str(item)
            for item in review.get("acceptedPermissions", [])
            if str(item)
        }
        missing = sorted(required - accepted)
        if missing:
            errors.append(f"Required permissions are not approved: {missing}")
        if not str(review.get("approvedBy") or "").strip():
            errors.append("Permission review has no approving operator")
        return self._gate_receipt(
            "permission-review",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence={
                "reviewId": review.get("reviewId"),
                "approvedBy": review.get("approvedBy"),
                "acceptedPermissions": sorted(accepted),
            },
        )

    def _tool(self, name: str) -> dict[str, Any]:
        configured = (self.toolchain.get("tools") or {}).get(name) or {}
        env_path = str(os.environ.get(f"NEYVIA_{name.upper()}_PATH") or "").strip()
        if name == "defender":
            path = self._defender_path()
        else:
            configured_path = str(configured.get("path") or "").strip()
            candidate = env_path or configured_path
            path = Path(candidate).resolve() if candidate else None
            if not path or not path.is_file():
                discovered = shutil.which(name)
                path = Path(discovered).resolve() if discovered else None
        expected_hash = str(configured.get("executableSha256") or "").strip()
        actual_hash = _sha256(path) if path and path.is_file() else ""
        hash_verified = (
            bool(path)
            and (
                expected_hash in {"", "dynamic-platform-update"}
                or hmac.compare_digest(actual_hash, expected_hash)
            )
        )
        return {
            "name": name,
            "path": str(path) if path else "",
            "version": str(configured.get("version") or ""),
            "expectedSha256": expected_hash,
            "actualSha256": actual_hash,
            "healthy": bool(path and path.is_file() and hash_verified),
            "hashVerified": hash_verified,
        }

    @staticmethod
    def _defender_path() -> Path | None:
        if os.name != "nt":
            return None
        platform_root = Path(
            os.environ.get("ProgramData", "C:/ProgramData")
        ) / "Microsoft" / "Windows Defender" / "Platform"
        if platform_root.is_dir():
            candidates = sorted(
                (
                    item / "MpCmdRun.exe"
                    for item in platform_root.iterdir()
                    if item.is_dir()
                ),
                reverse=True,
            )
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()
        fallback = Path(
            os.environ.get("ProgramFiles", "C:/Program Files")
        ) / "Windows Defender" / "MpCmdRun.exe"
        return fallback.resolve() if fallback.is_file() else None

    def toolchain_snapshot(self) -> dict[str, Any]:
        tools = {
            name: self._tool(name)
            for name in ("cosign", "wasmtime", "syft", "grype", "defender")
        }
        return {
            "schema": "neyvia.marketplace-toolchain-snapshot/v1",
            "moduleRoot": str(self.module_root),
            "neyviaVersion": self.neyvia_version,
            "platform": _platform_tag(),
            "policy": self.policy,
            "tools": tools,
            "activationGateReady": all(
                tools[name]["healthy"] for name in ("cosign", "syft", "grype")
            )
            and (
                tools["defender"]["healthy"]
                or bool(shutil.which("clamscan"))
            ),
        }

    def check_toolchain_updates(
        self,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Discover hash-bound stable candidates without changing active tools."""

        manager = MarketplaceToolchainUpdateManager(
            self.root,
            toolchain_path=self.toolchain_path,
        )
        return {
            "schema": "neyvia.marketplace-toolchain-maintenance/v1",
            "localIntegrity": manager.local_integrity(),
            "latestReleases": manager.check_latest(force=force),
            "activationPolicy": (
                "Candidates activate only through a tested, signed Neyvia release."
            ),
        }

    @staticmethod
    def _run_command(
        args: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            return {
                "returnCode": completed.returncode,
                "stdout": _bounded(completed.stdout),
                "stderr": _bounded(completed.stderr),
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "returnCode": -1,
                "stdout": "",
                "stderr": _bounded(exc),
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
            }

    @staticmethod
    def _gate_receipt(
        gate: str,
        status: str,
        *,
        module_id: str,
        version: str = "",
        errors: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": MODULE_GATE_RECEIPT_SCHEMA,
            "receiptId": uuid.uuid4().hex,
            "gate": gate,
            "status": status,
            "passed": status == "passed",
            "moduleId": module_id,
            "version": version,
            "recordedAt": _utc_now(),
            "errors": list(errors or []),
            "evidence": dict(evidence or {}),
        }

    def _publisher_trust_receipt(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        binding = self._trusted_binding(payload)
        errors = [] if binding else [
            "Publisher identity is not explicitly trusted for this module ID"
        ]
        return (
            self._gate_receipt(
                "publisher-trust",
                "passed" if binding else "blocked",
                module_id=payload["moduleId"],
                version=payload["version"],
                errors=errors,
                evidence={
                    "bindingId": binding.get("bindingId") if binding else "",
                    "publisherId": payload["publisher"]["id"],
                    "publisherIdentity": payload["publisher"]["identity"],
                },
            ),
            binding,
        )

    def _dependency_receipt(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        compatibility = self.dependency_compatibility(payload)
        return self._gate_receipt(
            "dependency-resolution",
            "passed" if compatibility["compatible"] else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=compatibility["errors"],
            evidence={"dependencies": compatibility["dependencies"]},
        )

    def _signature_receipt(
        self,
        payload: dict[str, Any],
        inspection: dict[str, Any],
        binding: dict[str, Any] | None,
        work_root: Path,
    ) -> dict[str, Any]:
        tool = self._tool("cosign")
        errors: list[str] = []
        if not tool["healthy"]:
            errors.append("Pinned Cosign executable is unavailable or hash-mismatched")
        if not binding:
            errors.append("No trusted publisher binding is available")
        canonical_path = work_root / "manifest.canonical.json"
        atomic_write_text(
            canonical_path,
            _canonical_manifest_bytes(payload).decode("utf-8"),
        )
        bundle_path = Path(inspection["signatureBundlePath"])
        args = [
            tool["path"],
            "verify-blob",
            "--bundle",
            str(bundle_path),
        ]
        signature = payload["signature"]
        if signature["scheme"] == "sigstore-cosign-bundle":
            args.extend(
                [
                    "--certificate-identity",
                    signature["identity"],
                    "--certificate-oidc-issuer",
                    signature["issuer"],
                ]
            )
        elif binding:
            key_path = Path(str(binding.get("publicKeyPath") or ""))
            expected_key_hash = str(binding.get("publicKeySha256") or "")
            if (
                not key_path.is_file()
                or not expected_key_hash
                or not hmac.compare_digest(_sha256(key_path), expected_key_hash)
            ):
                errors.append("Trusted publisher public key is missing or changed")
            else:
                args.extend(["--key", str(key_path)])
        args.append(str(canonical_path))
        result = (
            self._run_command(args, timeout=60, cwd=work_root)
            if not errors
            else {"returnCode": -1, "stdout": "", "stderr": "", "durationMs": 0}
        )
        if result["returnCode"] != 0 and not errors:
            errors.append("Cosign rejected the detached signature bundle")
        return self._gate_receipt(
            "cosign-bundle-verification",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence={
                "tool": tool,
                "bundleSha256": _sha256(bundle_path) if bundle_path.is_file() else "",
                "manifestSha256": _canonical_manifest_sha256(payload),
                "identity": signature.get("identity", ""),
                "issuer": signature.get("issuer", ""),
                "keyId": signature.get("keyId", ""),
                "commandResult": result,
            },
        )

    @staticmethod
    def _extract_archive(archive: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        with ZipFile(archive) as package_zip:
            for info in package_zip.infolist():
                target = _safe_child(
                    destination,
                    info.filename,
                    name="archive entry",
                )
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with package_zip.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

    @staticmethod
    def _scan_target_binding(
        target: Path,
        *,
        entrypoint: str,
    ) -> dict[str, Any]:
        if target.is_file():
            return {
                "kind": "file",
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            }
        proof = _payload_tree_proof(target, entrypoint)
        return {
            "kind": "payload-tree",
            "treeSha256": proof["treeSha256"],
            "entrypointSha256": proof["entrypointSha256"],
            "fileCount": proof["fileCount"],
            "bytes": proof["totalBytes"],
        }

    def _malware_receipt(
        self,
        payload: dict[str, Any],
        archive: Path,
        extracted: Path,
    ) -> dict[str, Any]:
        defender = self._tool("defender")
        errors: list[str] = []
        evidence: dict[str, Any] = {"tool": defender, "scans": []}
        scanner_path = ""
        scanner_args: list[str] = []
        if defender["healthy"]:
            scanner_path = defender["path"]
            scanner_args = ["-Scan", "-ScanType", "3", "-File"]
        else:
            clamscan = shutil.which("clamscan")
            if not clamscan:
                errors.append("No healthy malware scanner is available")
            else:
                scanner_path = clamscan
                scanner_args = ["--recursive", "--infected"]
                evidence["tool"] = {
                    "name": "clamscan",
                    "path": clamscan,
                    "actualSha256": _sha256(Path(clamscan)),
                    "hashVerified": True,
                    "healthy": True,
                }
        if scanner_path:
            for target in (archive, extracted):
                before = self._scan_target_binding(
                    target,
                    entrypoint=payload["runtime"]["entrypoint"],
                )
                command = (
                    [scanner_path, *scanner_args, str(target), "-DisableRemediation"]
                    if defender["healthy"]
                    else [scanner_path, *scanner_args, str(target)]
                )
                result = self._run_command(command, timeout=300)
                after = self._scan_target_binding(
                    target,
                    entrypoint=payload["runtime"]["entrypoint"],
                )
                evidence["scans"].append(
                    {
                        "target": str(target),
                        "targetRole": (
                            "archive-snapshot"
                            if target == archive
                            else "extracted-payload"
                        ),
                        "binding": before,
                        "postScanBinding": after,
                        "observedAt": _utc_now(),
                        "result": result,
                    }
                )
                if result["returnCode"] != 0:
                    errors.append(
                        f"Malware scanner did not clear {target.name}"
                    )
                if before != after:
                    errors.append(
                        f"Malware scan changed its {target.name} input"
                    )
        return self._gate_receipt(
            "malware-scan",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence=evidence,
        )

    @staticmethod
    def _validate_spdx_document(document: object, *, label: str) -> list[str]:
        if not isinstance(document, dict):
            return [f"{label} SBOM is not a JSON object"]
        errors: list[str] = []
        if not str(document.get("spdxVersion") or "").startswith("SPDX-2."):
            errors.append(f"{label} SBOM has no supported spdxVersion")
        if document.get("SPDXID") != "SPDXRef-DOCUMENT":
            errors.append(f"{label} SBOM has no SPDXRef-DOCUMENT identifier")
        if document.get("dataLicense") != "CC0-1.0":
            errors.append(f"{label} SBOM dataLicense must be CC0-1.0")
        if not str(document.get("documentNamespace") or "").startswith(
            ("https://", "http://", "urn:")
        ):
            errors.append(f"{label} SBOM has no stable documentNamespace")
        creation = document.get("creationInfo")
        if not isinstance(creation, dict) or not creation.get("creators"):
            errors.append(f"{label} SBOM has no creationInfo.creators")
        if not isinstance(document.get("packages"), list):
            errors.append(f"{label} SBOM packages must be an array")
        return errors

    def _sbom_receipt(
        self,
        payload: dict[str, Any],
        extracted: Path,
        receipt_root: Path,
    ) -> tuple[dict[str, Any], Path | None]:
        errors: list[str] = []
        declared_path = _safe_child(
            extracted,
            payload["package"]["sbomPath"],
            name="package.sbomPath",
        )
        try:
            declared = json.loads(declared_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            declared = {}
            errors.append(f"Declared SBOM cannot be read: {exc}")
        errors.extend(self._validate_spdx_document(declared, label="Declared"))

        syft = self._tool("syft")
        generated_path = receipt_root / "generated.spdx.json"
        result: dict[str, Any] = {
            "returnCode": -1,
            "stdout": "",
            "stderr": "",
            "durationMs": 0,
        }
        generated: dict[str, Any] = {}
        if not syft["healthy"]:
            errors.append("Pinned Syft executable is unavailable or hash-mismatched")
        else:
            result = self._run_command(
                [
                    syft["path"],
                    f"dir:{extracted}",
                    "-o",
                    f"spdx-json={generated_path}",
                ],
                timeout=180,
            )
            if result["returnCode"] != 0 or not generated_path.is_file():
                errors.append("Syft failed to generate an independent SBOM")
            else:
                try:
                    generated = json.loads(
                        generated_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"Generated SBOM cannot be read: {exc}")
                errors.extend(
                    self._validate_spdx_document(generated, label="Generated")
                )

        declared_names = sorted(
            {
                str(item.get("name") or "")
                for item in declared.get("packages", [])
                if isinstance(item, dict) and str(item.get("name") or "")
            }
        )
        generated_names = sorted(
            {
                str(item.get("name") or "")
                for item in generated.get("packages", [])
                if isinstance(item, dict) and str(item.get("name") or "")
            }
        )
        return (
            self._gate_receipt(
                "sbom-policy",
                "passed" if not errors else "blocked",
                module_id=payload["moduleId"],
                version=payload["version"],
                errors=errors,
                evidence={
                    "tool": syft,
                    "declaredPath": str(declared_path),
                    "declaredSha256": (
                        _sha256(declared_path) if declared_path.is_file() else ""
                    ),
                    "declaredPackageCount": len(declared_names),
                    "generatedPath": str(generated_path),
                    "generatedSha256": (
                        _sha256(generated_path)
                        if generated_path.is_file()
                        else ""
                    ),
                    "generatedPackageCount": len(generated_names),
                    "generatedBy": result,
                },
            ),
            generated_path if generated_path.is_file() else None,
        )

    def _vulnerability_receipt(
        self,
        payload: dict[str, Any],
        generated_sbom: Path | None,
    ) -> dict[str, Any]:
        grype = self._tool("grype")
        errors: list[str] = []
        findings: list[dict[str, Any]] = []
        threshold = str(
            self.policy.get("blockVulnerabilitySeverity") or "high"
        ).casefold()
        result: dict[str, Any] = {
            "returnCode": -1,
            "stdout": "",
            "stderr": "",
            "durationMs": 0,
        }
        database_evidence: dict[str, Any] = {}
        sbom_binding: dict[str, Any] = {}
        if not grype["healthy"]:
            errors.append("Pinned Grype executable is unavailable or hash-mismatched")
        elif not generated_sbom:
            errors.append("Independent SBOM is unavailable for vulnerability scan")
        else:
            sbom_binding = {
                "sha256": _sha256(generated_sbom),
                "bytes": generated_sbom.stat().st_size,
            }
            environment = dict(os.environ)
            environment["GRYPE_DB_AUTO_UPDATE"] = "false"
            database_result = self._run_command(
                [grype["path"], "db", "status", "-o", "json"],
                timeout=60,
                env=environment,
            )
            try:
                database_status = json.loads(database_result["stdout"] or "{}")
            except json.JSONDecodeError:
                database_status = {}
            built_at = str(
                database_status.get("built")
                or database_status.get("builtAt")
                or database_status.get("buildDate")
                or ""
            )
            max_db_age = int(
                self.policy.get("vulnerabilityDbMaxAgeSeconds")
                or 24 * 60 * 60
            )
            try:
                built = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
                if built.tzinfo is None:
                    raise ValueError("timezone required")
                db_age = (
                    datetime.now(timezone.utc) - built.astimezone(timezone.utc)
                ).total_seconds()
            except (TypeError, ValueError, OverflowError):
                db_age = float("inf")
            database_evidence = {
                "identitySha256": hashlib.sha256(
                    _canonical_json_bytes(database_status)
                ).hexdigest(),
                "schemaVersion": str(
                    database_status.get("schemaVersion")
                    or database_status.get("schema")
                    or ""
                ),
                "location": str(
                    database_status.get("location")
                    or database_status.get("path")
                    or ""
                ),
                "checksum": str(
                    database_status.get("checksum")
                    or database_status.get("digest")
                    or ""
                ),
                "builtAt": built_at,
                "ageSeconds": round(db_age, 3) if db_age != float("inf") else None,
                "maxAgeSeconds": max_db_age,
                "observedAt": _utc_now(),
                "statusResult": database_result,
            }
            if database_result["returnCode"] != 0 or not database_status:
                errors.append("Grype vulnerability database status is unavailable")
            elif db_age < -300 or db_age > max_db_age:
                errors.append("Grype vulnerability database is stale")
            if not errors:
                result = self._run_command(
                    [
                        grype["path"],
                        f"sbom:{generated_sbom}",
                        "-o",
                        "json",
                        "--fail-on",
                        threshold,
                    ],
                    timeout=300,
                    env=environment,
                )
                if _sha256(generated_sbom) != sbom_binding["sha256"]:
                    errors.append(
                        "Generated SBOM changed during vulnerability scanning"
                    )
            try:
                report = json.loads(result["stdout"] or "{}")
            except json.JSONDecodeError:
                report = {}
            for item in report.get("matches", []) if isinstance(report, dict) else []:
                if not isinstance(item, dict):
                    continue
                vulnerability = item.get("vulnerability") or {}
                artifact = item.get("artifact") or {}
                severity = str(vulnerability.get("severity") or "unknown").casefold()
                if SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(
                    threshold, 4
                ):
                    findings.append(
                        {
                            "id": vulnerability.get("id"),
                            "severity": severity,
                            "package": artifact.get("name"),
                            "version": artifact.get("version"),
                            "fixVersions": vulnerability.get("fix", {}).get(
                                "versions", []
                            ),
                        }
                    )
            if result["returnCode"] not in {0, 2}:
                errors.append("Grype could not complete the vulnerability scan")
            if findings or result["returnCode"] == 2:
                errors.append(
                    f"Package has vulnerabilities at or above {threshold}"
                )
        return self._gate_receipt(
            "vulnerability-scan",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence={
                "tool": grype,
                "threshold": threshold,
                "blockingFindings": findings[:200],
                "blockingFindingCount": len(findings),
                "inputSbom": sbom_binding,
                "observedAt": _utc_now(),
                "database": database_evidence,
                "commandResult": result,
            },
        )

    def _smoke_receipt(
        self,
        payload: dict[str, Any],
        extracted: Path,
    ) -> dict[str, Any]:
        runtime = payload["runtime"]
        kind = runtime["kind"]
        errors: list[str] = []
        evidence: dict[str, Any] = {"runtimeKind": kind}
        context_path = _safe_child(
            extracted,
            payload["context"]["summaryIndex"],
            name="context.summaryIndex",
        )
        try:
            context_bytes = context_path.read_bytes()
            if len(context_bytes) > int(payload["context"]["maxBootstrapBytes"]):
                errors.append("Context summary exceeds maxBootstrapBytes")
            context = json.loads(context_bytes.decode("utf-8"))
            if not isinstance(context, dict):
                errors.append("Context summary index must be a JSON object")
            evidence["contextBytes"] = len(context_bytes)
            evidence["contextSha256"] = hashlib.sha256(context_bytes).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"Context summary index is invalid: {exc}")

        entrypoint = _safe_child(
            extracted,
            runtime["entrypoint"],
            name="runtime.entrypoint",
        )
        if not entrypoint.is_file():
            errors.append("Runtime entrypoint is missing after extraction")
        elif kind == "content-pack":
            if entrypoint.suffix.casefold() == ".json":
                try:
                    entrypoint_payload = json.loads(
                        entrypoint.read_text(encoding="utf-8")
                    )
                    if not isinstance(entrypoint_payload, (dict, list)):
                        errors.append(
                            "Content-pack JSON entrypoint has no structured content"
                        )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    errors.append(f"Content-pack entrypoint is invalid: {exc}")
            evidence["isolation"] = "non-executable content validation"
        elif kind == "wasm-component":
            wasmtime = self._tool("wasmtime")
            evidence["tool"] = wasmtime
            if not wasmtime["healthy"]:
                errors.append(
                    "Pinned Wasmtime executable is unavailable or hash-mismatched"
                )
            else:
                health = runtime.get("healthcheck") or {}
                target = str(health.get("target") or "").strip()
                timeout_seconds = int(health.get("timeoutSeconds") or 10)
                args = [
                    wasmtime["path"],
                    "run",
                    "--wasm-timeout",
                    f"{timeout_seconds}s",
                ]
                if target:
                    args.extend(["--invoke", target])
                args.append(str(entrypoint))
                result = self._run_command(
                    args,
                    timeout=timeout_seconds + 5,
                    cwd=extracted,
                    env={"PATH": os.environ.get("PATH", "")},
                )
                evidence["commandResult"] = result
                evidence["filesystemAccess"] = "none"
                evidence["inheritedEnvironment"] = []
                evidence["networkAccess"] = "none"
                if result["returnCode"] != 0:
                    errors.append("Wasmtime isolated smoke test failed")
        else:
            errors.append(
                "Executable service/full-app activation is blocked until its "
                "container or OS sandbox adapter is implemented and healthy"
            )
        return self._gate_receipt(
            "isolated-smoke-test",
            "passed" if not errors else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=errors,
            evidence=evidence,
        )

    def _blocked_install(
        self,
        payload: dict[str, Any],
        inspection: dict[str, Any],
        receipts: list[dict[str, Any]],
        *,
        quarantine_path: Path | None,
    ) -> dict[str, Any]:
        blocked = [
            receipt["gate"]
            for receipt in receipts
            if receipt.get("passed") is not True
        ]
        result = {
            "schema": MODULE_INSTALL_RECEIPT_SCHEMA,
            "receiptId": uuid.uuid4().hex,
            "status": "blocked",
            "activated": False,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": inspection.get("archiveSha256", ""),
            "manifestSha256": inspection.get("manifestSha256", ""),
            "quarantinePath": str(quarantine_path) if quarantine_path else "",
            "blockedBy": blocked,
            "gateReceipts": receipts,
            "completedAt": _utc_now(),
        }
        if quarantine_path:
            atomic_write_json(quarantine_path / "install-receipt.json", result)
        append_jsonl_durable(self.ledger_path, result)
        return result

    @_module_scoped
    def install_package(
        self,
        manifest: object,
        archive_path: str | Path,
        *,
        permission_review: object,
        activate: bool = True,
    ) -> dict[str, Any]:
        payload = self.require_valid_manifest(manifest)
        source_archive = Path(archive_path).resolve()
        quarantine = (
            self.module_root
            / ".quarantine"
            / payload["moduleId"]
            / f"{payload['version']}-{uuid.uuid4().hex}"
        )
        intake = quarantine / "intake"
        source_bundle = _safe_child(
            source_archive.parent,
            payload["signature"]["bundlePath"],
            name="signature.bundlePath",
        )
        snapshot = _snapshot_content_addressed(
            source_archive,
            intake,
            suffix=".nymod",
        )
        archive = Path(snapshot["path"])
        snapshot_bundle = _safe_child(
            archive.parent,
            payload["signature"]["bundlePath"],
            name="signature.bundlePath",
        )
        _snapshot_file(source_bundle, snapshot_bundle)
        inspection = self.inspect_package(payload, archive)
        inspection_receipt = self._gate_receipt(
            "archive-inspection",
            "passed" if inspection["safeToVerify"] else "blocked",
            module_id=payload["moduleId"],
            version=payload["version"],
            errors=inspection["errors"],
            evidence={
                "archiveSha256": inspection["archiveSha256"],
                "archiveBytes": inspection["archiveBytes"],
                "entryCount": inspection["entryCount"],
                "uncompressedBytes": inspection["uncompressedBytes"],
                "snapshotPath": str(archive),
                "snapshotSha256": snapshot["sha256"],
                "contentAddressed": (
                    archive.name == f"{snapshot['sha256']}.nymod"
                ),
            },
        )
        receipts = [inspection_receipt]
        if not inspection_receipt["passed"]:
            return self._blocked_install(
                payload,
                inspection,
                receipts,
                quarantine_path=quarantine,
            )

        extracted = quarantine / "payload"
        receipt_root = quarantine / "receipts"
        receipt_root.mkdir(parents=True, exist_ok=False)

        trust_receipt, binding = self._publisher_trust_receipt(payload)
        receipts.append(trust_receipt)
        signature_receipt = self._signature_receipt(
            payload,
            inspection,
            binding,
            receipt_root,
        )
        receipts.append(signature_receipt)
        receipts.append(self._dependency_receipt(payload))
        if any(not item["passed"] for item in receipts):
            return self._blocked_install(
                payload,
                inspection,
                receipts,
                quarantine_path=quarantine,
            )

        try:
            if _sha256(archive) != inspection["archiveSha256"]:
                raise ValueError("Immutable archive snapshot changed before extraction")
            self._extract_archive(archive, extracted)
            if _sha256(archive) != inspection["archiveSha256"]:
                raise ValueError("Immutable archive snapshot changed during extraction")
            extraction_receipt = self._gate_receipt(
                "quarantine-extraction",
                "passed",
                module_id=payload["moduleId"],
                version=payload["version"],
                evidence={
                    "path": str(extracted),
                    "archiveSnapshotPath": str(archive),
                    "archiveSha256": inspection["archiveSha256"],
                    "payloadProof": _payload_tree_proof(
                        extracted,
                        payload["runtime"]["entrypoint"],
                    ),
                },
            )
        except (OSError, ValueError, BadZipFile) as exc:
            extraction_receipt = self._gate_receipt(
                "quarantine-extraction",
                "blocked",
                module_id=payload["moduleId"],
                version=payload["version"],
                errors=[str(exc)],
            )
        receipts.append(extraction_receipt)
        if not extraction_receipt["passed"]:
            return self._blocked_install(
                payload,
                inspection,
                receipts,
                quarantine_path=quarantine,
            )

        if _sha256(archive) != inspection["archiveSha256"]:
            receipts.append(
                self._gate_receipt(
                    "archive-snapshot-integrity",
                    "blocked",
                    module_id=payload["moduleId"],
                    version=payload["version"],
                    errors=["Immutable archive snapshot changed before scanning"],
                )
            )
            return self._blocked_install(
                payload,
                inspection,
                receipts,
                quarantine_path=quarantine,
            )
        receipts.append(self._malware_receipt(payload, archive, extracted))
        sbom_receipt, generated_sbom = self._sbom_receipt(
            payload,
            extracted,
            receipt_root,
        )
        receipts.append(sbom_receipt)
        receipts.append(
            self._vulnerability_receipt(payload, generated_sbom)
        )
        receipts.append(
            self._permission_review_receipt(payload, permission_review)
        )
        receipts.append(self._smoke_receipt(payload, extracted))
        if _sha256(archive) != inspection["archiveSha256"]:
            receipts.append(
                self._gate_receipt(
                    "archive-snapshot-integrity",
                    "blocked",
                    module_id=payload["moduleId"],
                    version=payload["version"],
                    errors=["Immutable archive snapshot changed during verification"],
                )
            )
        if any(not item["passed"] for item in receipts):
            return self._blocked_install(
                payload,
                inspection,
                receipts,
                quarantine_path=quarantine,
            )

        target = (
            self.module_root / payload["moduleId"] / "versions" / payload["version"]
        )
        pointer_path = self.module_root / payload["moduleId"] / "current.json"
        previous = self._read_json(pointer_path)
        if target.exists():
            existing_manifest = self._read_json(
                target / ".neyvia" / "manifest.json"
            )
            if (
                existing_manifest.get("package", {}).get("archiveSha256")
                != payload["package"]["archiveSha256"]
            ):
                receipts.append(
                    self._gate_receipt(
                        "immutable-version-target",
                        "blocked",
                        module_id=payload["moduleId"],
                        version=payload["version"],
                        errors=[
                            "Installed version directory exists with a different "
                            "archive digest"
                        ],
                    )
                )
                return self._blocked_install(
                    payload,
                    inspection,
                    receipts,
                    quarantine_path=quarantine,
                )
            if _payload_tree_proof(
                target,
                payload["runtime"]["entrypoint"],
            ) != _payload_tree_proof(
                extracted,
                payload["runtime"]["entrypoint"],
            ):
                receipts.append(
                    self._gate_receipt(
                        "immutable-version-target",
                        "blocked",
                        module_id=payload["moduleId"],
                        version=payload["version"],
                        errors=[
                            "Installed version payload differs from the newly "
                            "verified archive"
                        ],
                    )
                )
                return self._blocked_install(
                    payload,
                    inspection,
                    receipts,
                    quarantine_path=quarantine,
                )
            installed_archive = _installed_archive_path(
                target,
                inspection["archiveSha256"],
            )
            if (
                not installed_archive.is_file()
                or _sha256(installed_archive) != inspection["archiveSha256"]
            ):
                receipts.append(
                    self._gate_receipt(
                        "immutable-version-target",
                        "blocked",
                        module_id=payload["moduleId"],
                        version=payload["version"],
                        errors=[
                            "Installed version has no matching immutable "
                            "archive snapshot"
                        ],
                    )
                )
                return self._blocked_install(
                    payload,
                    inspection,
                    receipts,
                    quarantine_path=quarantine,
                )
            status = "already_installed"
        else:
            metadata = extracted / ".neyvia"
            metadata.mkdir(parents=True, exist_ok=False)
            atomic_write_json(metadata / "manifest.json", payload)
            _snapshot_file(
                Path(inspection["signatureBundlePath"]),
                metadata / "signature.sigstore.json",
            )
            installed_archive = _installed_archive_path(
                extracted,
                inspection["archiveSha256"],
            )
            _snapshot_file(archive, installed_archive)
            _snapshot_file(
                Path(inspection["signatureBundlePath"]),
                _safe_child(
                    installed_archive.parent,
                    payload["signature"]["bundlePath"],
                    name="signature.bundlePath",
                ),
            )
            if generated_sbom and generated_sbom.is_file():
                shutil.copyfile(generated_sbom, metadata / "generated.spdx.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(extracted, target)
            status = "installed"

        payload_proof = _payload_tree_proof(
            target,
            payload["runtime"]["entrypoint"],
        )
        oci_subject, _subject_manifest, _registry = self._oci_subject(
            payload,
            inspection["archiveSha256"],
            inspection["archiveBytes"],
            payload_proof,
        )
        activation_pointer: dict[str, Any] | None = None
        activation_blocked_by = (
            ["oci-staged-activation-required"] if activate else []
        )

        result = {
            "schema": MODULE_INSTALL_RECEIPT_SCHEMA,
            "receiptId": uuid.uuid4().hex,
            "status": status,
            "activated": False,
            "activationRequested": activate,
            "activationBlockedBy": activation_blocked_by,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "archiveSha256": inspection["archiveSha256"],
            "manifestSha256": inspection["manifestSha256"],
            "payloadProof": payload_proof,
            "ociSubject": oci_subject,
            "targetPath": str(target),
            "archiveSnapshotPath": str(
                _installed_archive_path(
                    target,
                    inspection["archiveSha256"],
                )
            ),
            "activationPointer": activation_pointer,
            "previousVersion": str(previous.get("currentVersion") or ""),
            "blockedBy": [],
            "gateReceipts": receipts,
            "completedAt": _utc_now(),
        }
        metadata = target / ".neyvia"
        atomic_write_json(metadata / "install-receipt.json", result)
        append_jsonl_durable(self.ledger_path, result)
        return result

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _activation_namespace_report_unlocked(
        self,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        module_id = _safe_module_id(manifest.get("moduleId"))
        claims = _module_namespace_claims(manifest)
        wanted = {(item["kind"], item["id"]) for item in claims}
        conflicts: list[dict[str, str]] = []
        integrity_blockers: list[str] = []
        if self.module_root.is_dir():
            for module_directory in sorted(self.module_root.iterdir()):
                if (
                    not module_directory.is_dir()
                    or module_directory.name.startswith(".")
                    or module_directory.name == module_id
                ):
                    continue
                try:
                    active_module_id = _safe_module_id(module_directory.name)
                except ValueError:
                    continue
                pointer = self._read_json(module_directory / "current.json")
                if (
                    pointer.get("schema") != MODULE_ACTIVATION_POINTER_SCHEMA
                    or pointer.get("state") != "active"
                ):
                    continue
                active_version = str(pointer.get("currentVersion") or "")
                active_manifest = self._read_json(
                    module_directory
                    / "versions"
                    / active_version
                    / ".neyvia"
                    / "manifest.json"
                )
                if active_manifest.get("moduleId") != active_module_id:
                    integrity_blockers.append(
                        f"Active module {active_module_id} has no bound manifest"
                    )
                    continue
                for claim in _module_namespace_claims(active_manifest):
                    key = (claim["kind"], claim["id"])
                    if key in wanted:
                        conflicts.append(
                            {
                                "kind": claim["kind"],
                                "id": claim["id"],
                                "activeModuleId": active_module_id,
                                "activeVersion": active_version,
                            }
                        )
        return {
            "schema": "neyvia.module-namespace-report/v1",
            "moduleId": module_id,
            "ready": not conflicts and not integrity_blockers,
            "claims": claims,
            "conflicts": conflicts,
            "integrityBlockers": integrity_blockers,
        }

    def activation_namespace_report(
        self,
        manifest: object,
    ) -> dict[str, Any]:
        """Inspect collision state without changing an activation pointer."""

        payload = self.require_valid_manifest(manifest)
        with _module_file_lock(self.module_root / ".activation-registry"):
            return self._activation_namespace_report_unlocked(payload)

    def _require_activation_namespace_available(
        self,
        manifest: dict[str, Any],
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        report = self._activation_namespace_report_unlocked(manifest)
        if report["ready"]:
            return report
        receipt = self._gate_receipt(
            "module-namespace-collision",
            "blocked",
            module_id=str(manifest.get("moduleId") or ""),
            version=str(manifest.get("version") or ""),
            evidence={
                "requestedBy": requested_by,
                "claims": report["claims"],
                "conflicts": report["conflicts"],
                "integrityBlockers": report["integrityBlockers"],
            },
        )
        append_jsonl_durable(self.ledger_path, receipt)
        reasons = [
            (
                f"{item['kind']} {item['id']} is already active in "
                f"{item['activeModuleId']}@{item['activeVersion']}"
            )
            for item in report["conflicts"]
        ]
        reasons.extend(report["integrityBlockers"])
        raise ValueError(
            "Module activation namespace check failed: "
            + "; ".join(reasons)
            + f" (receipt {receipt['receiptId']})"
        )

    def _ledger_has_receipt(self, receipt_id: str) -> bool:
        if not receipt_id or not self.ledger_path.is_file():
            return False
        try:
            with self.ledger_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        isinstance(payload, dict)
                        and payload.get("receiptId") == receipt_id
                    ):
                        return True
        except OSError:
            return False
        return False

    @_module_scoped
    def stage_oci_activation(
        self,
        manifest: object,
        archive_path: str | Path,
        oci_manifest: object,
        *,
        security_evidence: object,
        requested_by: str,
    ) -> dict[str, Any]:
        """Stage a verified installed version without changing active state."""

        payload = self.require_valid_manifest(manifest)
        module_id = _safe_module_id(payload["moduleId"])
        requester = str(requested_by or "").strip()
        if not requester:
            raise ValueError("requested_by is required")
        target = (
            self.module_root / module_id / "versions" / payload["version"]
        )
        installed_manifest = self._read_json(
            target / ".neyvia" / "manifest.json"
        )
        install_receipt_path = target / ".neyvia" / "install-receipt.json"
        install_receipt = self._read_json(install_receipt_path)
        archive_path = _installed_archive_path(
            target,
            payload["package"]["archiveSha256"],
        )
        if (
            installed_manifest != payload
            or install_receipt.get("moduleId") != payload["moduleId"]
            or install_receipt.get("version") != payload["version"]
            or install_receipt.get("archiveSha256")
            != payload["package"]["archiveSha256"]
            or install_receipt.get("blockedBy")
            or install_receipt.get("status")
            not in {"activated", "installed", "already_installed"}
        ):
            raise ValueError(
                "OCI staging requires the exact verified immutable install target"
            )

        receipt_plan = self.build_oci_artifact_plan(
            payload,
            archive_path,
            install_receipt=install_receipt,
        )
        if security_evidence != receipt_plan["securityEvidence"]:
            raise ValueError(
                "OCI security evidence does not match the installed gate receipts"
            )
        inspection = self.inspect_oci_artifact(
            payload,
            archive_path,
            oci_manifest,
            security_evidence=security_evidence,
        )
        if not inspection["activationReady"]:
            raise ValueError(
                "OCI artifact is not activation-ready: "
                + "; ".join(inspection["errors"])
            )
        if self._trusted_binding(payload) is None:
            raise ValueError(
                "Publisher identity is no longer trusted for this module"
            )

        current = self._read_json(
            self.module_root / module_id / "current.json"
        )
        staged_path = self.module_root / module_id / "staged.json"
        staged = {
            "schema": MODULE_OCI_STAGED_POINTER_SCHEMA,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "state": "staged",
            "targetPath": str(target),
            "archiveSnapshotPath": str(archive_path),
            "archivePath": str(Path(archive_path).resolve()),
            "archiveSha256": payload["package"]["archiveSha256"],
            "manifestSha256": _canonical_manifest_sha256(payload),
            "ociManifest": dict(oci_manifest),
            "ociManifestDigest": inspection["ociManifestDescriptor"]["digest"],
            "securityEvidence": dict(security_evidence),
            "securityEvidenceDigest": inspection["securityEvidenceDigest"],
            "installReceiptSha256": _sha256(install_receipt_path),
            "payloadProof": inspection["payloadProof"],
            "ociSubject": inspection["ociSubject"],
            "resolvedRegistryRef": receipt_plan["distribution"]["resolvedRef"],
            "previousVersion": str(current.get("currentVersion") or ""),
            "stagedBy": requester,
            "stagedAt": _utc_now(),
        }
        atomic_write_json(staged_path, staged)
        receipt = self._gate_receipt(
            "oci-activation-staging",
            "passed",
            module_id=payload["moduleId"],
            version=payload["version"],
            evidence={
                "stagedPointerPath": str(staged_path),
                "ociManifestDigest": staged["ociManifestDigest"],
                "securityEvidenceDigest": staged["securityEvidenceDigest"],
                "installReceiptSha256": staged["installReceiptSha256"],
                "requestedBy": requester,
            },
        )
        append_jsonl_durable(self.ledger_path, receipt)
        return {
            "schema": MODULE_OCI_STAGED_POINTER_SCHEMA,
            "staged": True,
            "activated": False,
            "moduleId": payload["moduleId"],
            "version": payload["version"],
            "ociManifestDigest": staged["ociManifestDigest"],
            "securityEvidenceDigest": staged["securityEvidenceDigest"],
            "stagedPointerPath": str(staged_path),
            "receipt": receipt,
        }

    @_module_scoped
    def activate_staged_oci(
        self,
        module_id: str,
        *,
        expected_oci_manifest_digest: str,
        requested_by: str,
    ) -> dict[str, Any]:
        """Promote a staged OCI version through a durable retryable transaction."""

        module_id = _safe_module_id(module_id)
        requester = str(requested_by or "").strip()
        expected_digest = str(expected_oci_manifest_digest or "").strip()
        if not requester or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected_digest):
            raise ValueError(
                "requested_by and an exact sha256 OCI manifest digest are required"
            )
        module_dir = self.module_root / module_id
        staged_path = module_dir / "staged.json"
        staged = self._read_json(staged_path)
        if (
            staged.get("schema") != MODULE_OCI_STAGED_POINTER_SCHEMA
            or staged.get("moduleId") != module_id
            or staged.get("ociManifestDigest") != expected_digest
            or staged.get("state") not in {"staged", "promoted"}
        ):
            raise ValueError("No matching staged OCI activation is available")

        version = str(staged.get("version") or "")
        try:
            _semver_parts(version)
        except ValueError:
            raise ValueError("Staged OCI version is invalid")
        target = module_dir / "versions" / version
        expected_target = str(target.resolve())
        archive_path = Path(str(staged.get("archivePath") or "")).resolve()
        install_receipt_path = target / ".neyvia" / "install-receipt.json"
        install_receipt = self._read_json(install_receipt_path)
        manifest = self._read_json(target / ".neyvia" / "manifest.json")
        if (
            not target.is_dir()
            or staged.get("targetPath") != expected_target
            or not archive_path.is_file()
            or _sha256(archive_path) != staged.get("archiveSha256")
            or not install_receipt_path.is_file()
            or _sha256(install_receipt_path)
            != staged.get("installReceiptSha256")
            or manifest.get("moduleId") != module_id
            or manifest.get("version") != version
            or _canonical_manifest_sha256(manifest)
            != staged.get("manifestSha256")
            or manifest.get("package", {}).get("archiveSha256")
            != staged.get("archiveSha256")
        ):
            raise ValueError("Staged OCI target or install receipt changed")
        actual_payload_proof = _payload_tree_proof(
            target,
            manifest["runtime"]["entrypoint"],
        )
        if (
            actual_payload_proof != staged.get("payloadProof")
            or actual_payload_proof != install_receipt.get("payloadProof")
        ):
            raise ValueError("Staged installed payload tree or entrypoint changed")
        if self._trusted_binding(manifest) is None:
            raise ValueError("Publisher identity is no longer trusted")
        receipt_plan = self.build_oci_artifact_plan(
            manifest,
            archive_path,
            install_receipt=install_receipt,
        )
        if (
            staged.get("securityEvidence") != receipt_plan["securityEvidence"]
            or staged.get("ociManifest") != receipt_plan["ociManifest"]
            or staged.get("ociSubject") != receipt_plan["ociSubject"]
        ):
            raise ValueError(
                "Staged OCI manifest or evidence no longer matches the "
                "installed gate receipts"
            )
        refreshed = self.inspect_oci_artifact(
            manifest,
            archive_path,
            staged["ociManifest"],
            security_evidence=staged["securityEvidence"],
        )
        if not refreshed["activationReady"]:
            raise ValueError("Staged OCI artifact no longer passes local inspection")
        oci_descriptor = _oci_descriptor(
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            _canonical_json_bytes(staged.get("ociManifest")),
        )
        if (
            oci_descriptor["digest"] != expected_digest
            or hashlib.sha256(
                _canonical_json_bytes(staged.get("securityEvidence"))
            ).hexdigest()
            != staged.get("securityEvidenceDigest")
        ):
            raise ValueError("Staged OCI manifest or evidence was modified")

        pointer_path = module_dir / "current.json"
        transaction_path = module_dir / "activation-transaction.json"
        current = self._read_json(pointer_path)
        previous_activation = None
        previous_version = str(current.get("currentVersion") or "")
        if current.get("schema") == MODULE_ACTIVATION_POINTER_SCHEMA:
            if (
                str(current.get("currentVersion") or "") == version
                and current.get("archiveSha256") == staged["archiveSha256"]
                and current.get("manifestSha256") == staged["manifestSha256"]
            ):
                # Same-version re-activation (for example after disable) must
                # preserve the prior rollback chain instead of collapsing it.
                nested = current.get("previousActivation")
                previous_activation = (
                    dict(nested) if isinstance(nested, dict) else None
                )
                previous_version = str(current.get("previousVersion") or "")
            else:
                previous_activation = dict(current)
                previous_activation.pop("previousActivation", None)
        activation_pointer = {
            "schema": MODULE_ACTIVATION_POINTER_SCHEMA,
            "moduleId": module_id,
            "state": "active",
            "currentVersion": version,
            "previousVersion": previous_version,
            "archiveSha256": staged["archiveSha256"],
            "manifestSha256": staged["manifestSha256"],
            "payloadTreeSha256": actual_payload_proof["treeSha256"],
            "entrypointSha256": actual_payload_proof["entrypointSha256"],
            "payloadProof": actual_payload_proof,
            "targetPath": expected_target,
            "archivePath": str(archive_path),
            "ociManifest": staged["ociManifest"],
            "ociSubject": staged["ociSubject"],
            "ociManifestDigest": expected_digest,
            "resolvedRegistryRef": staged["resolvedRegistryRef"],
            "securityEvidence": staged["securityEvidence"],
            "securityEvidenceDigest": staged["securityEvidenceDigest"],
            "installReceiptSha256": staged["installReceiptSha256"],
            "namespaceClaims": _module_namespace_claims(manifest),
            "previousActivation": previous_activation,
            "activatedAt": _utc_now(),
            "activatedBy": requester,
        }
        transaction_core = {
            "moduleId": module_id,
            "version": version,
            "ociManifestDigest": expected_digest,
            "securityEvidenceDigest": staged["securityEvidenceDigest"],
            "payloadTreeSha256": actual_payload_proof["treeSha256"],
            "stagedAt": staged.get("stagedAt"),
        }
        transaction_id = hashlib.sha256(
            _canonical_json_bytes(transaction_core)
        ).hexdigest()
        transaction = self._read_json(transaction_path)
        idempotent = False
        if transaction.get("schema") == OCI_ACTIVATION_TRANSACTION_SCHEMA:
            if (
                transaction.get("transactionId") != transaction_id
                and transaction.get("phase") != "completed"
            ):
                raise ValueError("Another OCI activation transaction is incomplete")
            if transaction.get("transactionId") == transaction_id:
                stored_pointer = dict(transaction.get("nextPointer") or {})
                for key in (
                    "moduleId",
                    "currentVersion",
                    "archiveSha256",
                    "manifestSha256",
                    "payloadTreeSha256",
                    "entrypointSha256",
                    "payloadProof",
                    "targetPath",
                    "archivePath",
                    "ociManifest",
                    "ociSubject",
                    "ociManifestDigest",
                    "resolvedRegistryRef",
                    "securityEvidence",
                    "securityEvidenceDigest",
                    "installReceiptSha256",
                    "namespaceClaims",
                ):
                    if stored_pointer.get(key) != activation_pointer.get(key):
                        raise ValueError(
                            "OCI activation transaction provenance changed"
                        )
                activation_pointer = stored_pointer
                idempotent = True
        if not idempotent:
            receipt = self._gate_receipt(
                "oci-staged-activation",
                "passed",
                module_id=module_id,
                version=version,
                evidence={
                    "transactionId": transaction_id,
                    "ociManifestDigest": expected_digest,
                    "securityEvidenceDigest": staged["securityEvidenceDigest"],
                    "payloadTreeSha256": actual_payload_proof["treeSha256"],
                    "previousVersion": activation_pointer["previousVersion"],
                    "requestedBy": requester,
                    "namespaceClaims": activation_pointer["namespaceClaims"],
                },
            )
            transaction = {
                "schema": OCI_ACTIVATION_TRANSACTION_SCHEMA,
                "transactionId": transaction_id,
                "phase": "prepared",
                "previousPointer": current,
                "nextPointer": activation_pointer,
                "receipt": receipt,
                "preparedAt": _utc_now(),
            }
            atomic_write_json(transaction_path, transaction)
        else:
            receipt = dict(transaction.get("receipt") or {})

        with _module_file_lock(self.module_root / ".activation-registry"):
            self._require_activation_namespace_available(
                manifest,
                requested_by=requester,
            )
            current = self._read_json(pointer_path)
            previous_pointer = transaction.get("previousPointer") or {}
            if current != previous_pointer and current != activation_pointer:
                raise ValueError("Current pointer changed during OCI activation")
            if current != activation_pointer:
                atomic_write_json(pointer_path, activation_pointer)
        transaction["phase"] = "current-committed"
        atomic_write_json(transaction_path, transaction)
        staged["state"] = "promoted"
        staged["transactionId"] = transaction_id
        staged["promotedAt"] = staged.get("promotedAt") or _utc_now()
        staged["promotedBy"] = staged.get("promotedBy") or requester
        atomic_write_json(staged_path, staged)
        transaction["phase"] = "completed"
        transaction["completedAt"] = transaction.get("completedAt") or _utc_now()
        atomic_write_json(transaction_path, transaction)
        if receipt and not self._ledger_has_receipt(str(receipt.get("receiptId") or "")):
            append_jsonl_durable(self.ledger_path, receipt)
        return {
            "schema": MODULE_ACTIVATION_POINTER_SCHEMA,
            "activated": True,
            "idempotent": idempotent,
            "transactionId": transaction_id,
            "moduleId": module_id,
            "version": version,
            "ociManifestDigest": expected_digest,
            "activationPointer": activation_pointer,
            "receipt": receipt,
        }

    def install_package_from_paths(
        self,
        *,
        manifest_path: str | Path,
        archive_path: str | Path,
        permission_review: object | None = None,
        approved_by: str = "",
        public_key_path: str | Path | None = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        """Install a signed package using on-disk manifest and archive paths."""

        manifest_file = Path(manifest_path).resolve()
        if not manifest_file.is_file():
            raise FileNotFoundError(f"Manifest path not found: {manifest_file}")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Manifest path is not valid JSON: {exc}") from exc
        payload = self.require_valid_manifest(manifest)
        requester = str(approved_by or "").strip() or "marketplace-operator"
        if public_key_path:
            self.trust_publisher(
                payload,
                approved_by=requester,
                public_key_path=public_key_path,
            )
        review = permission_review
        if review is None:
            review = self.build_permission_review(
                payload,
                approved_by=requester,
                accepted_permissions=[],
            )
        install = self.install_package(
            payload,
            archive_path,
            permission_review=review,
            activate=activate,
        )
        return {
            "schema": MODULE_INSTALL_RECEIPT_SCHEMA,
            "manifestPath": str(manifest_file),
            "install": install,
            "moduleId": install.get("moduleId"),
            "version": install.get("version"),
            "status": install.get("status"),
            "activated": install.get("activated") is True,
            "blockedBy": list(install.get("blockedBy") or []),
        }

    def activate_installed_module(
        self,
        module_id: str,
        *,
        requested_by: str,
        version: str = "",
    ) -> dict[str, Any]:
        """Stage and activate an already-installed immutable module version."""

        module_id = _safe_module_id(module_id)
        requester = str(requested_by or "").strip()
        if not requester:
            raise ValueError("requested_by is required")
        module_dir = self.module_root / module_id
        selected = str(version or "").strip()
        if not selected:
            staged = self._read_json(module_dir / "staged.json")
            if (
                staged.get("schema") == MODULE_OCI_STAGED_POINTER_SCHEMA
                and staged.get("moduleId") == module_id
                and staged.get("state") in {"staged", "promoted"}
            ):
                selected = str(staged.get("version") or "")
            if not selected:
                pointer = self._read_json(module_dir / "current.json")
                if pointer.get("schema") == MODULE_ACTIVATION_POINTER_SCHEMA:
                    selected = str(pointer.get("currentVersion") or "")
            if not selected:
                installed = self._installed_version_dirs(module_dir)
                if not installed:
                    raise FileNotFoundError(
                        f"No installed module version for {module_id}"
                    )
                selected = installed[-1].name
        target = module_dir / "versions" / selected
        manifest = self._read_json(target / ".neyvia" / "manifest.json")
        install_receipt = self._read_json(
            target / ".neyvia" / "install-receipt.json"
        )
        if (
            not target.is_dir()
            or manifest.get("moduleId") != module_id
            or install_receipt.get("schema") != MODULE_INSTALL_RECEIPT_SCHEMA
        ):
            raise FileNotFoundError(
                f"Installed module {module_id}@{selected} was not found"
            )
        archive = _installed_archive_path(
            target,
            str(manifest["package"]["archiveSha256"]),
        )
        plan = self.build_oci_artifact_plan(
            manifest,
            archive,
            install_receipt=install_receipt,
        )
        if not plan.get("activationReady"):
            return {
                "schema": MODULE_OCI_PLAN_SCHEMA,
                "activated": False,
                "staged": False,
                "moduleId": module_id,
                "version": selected,
                "blockedBy": list(plan.get("blockedBy") or []),
                "securityEvidenceErrors": list(
                    plan.get("securityEvidenceErrors") or []
                ),
                "plan": plan,
            }
        staged = self.stage_oci_activation(
            manifest,
            archive,
            plan["ociManifest"],
            security_evidence=plan["securityEvidence"],
            requested_by=requester,
        )
        promoted = self.activate_staged_oci(
            module_id,
            expected_oci_manifest_digest=str(staged["ociManifestDigest"]),
            requested_by=requester,
        )
        return {
            "schema": MODULE_ACTIVATION_POINTER_SCHEMA,
            "activated": True,
            "staged": True,
            "moduleId": module_id,
            "version": selected,
            "ociManifestDigest": staged["ociManifestDigest"],
            "stagedReceipt": staged,
            "activation": promoted,
        }

    @_module_scoped
    def disable_module(
        self,
        module_id: str,
        *,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        module_id = _safe_module_id(module_id)
        requester = str(requested_by or "").strip()
        rationale = str(reason or "").strip()
        if not requester or not rationale:
            raise ValueError("requested_by and reason are required")
        pointer_path = self.module_root / module_id / "current.json"
        with _module_file_lock(self.module_root / ".activation-registry"):
            pointer = self._read_json(pointer_path)
            if pointer.get("schema") != MODULE_ACTIVATION_POINTER_SCHEMA:
                raise FileNotFoundError(f"No active module pointer for {module_id}")
            pointer["state"] = "disabled"
            pointer["disabledAt"] = _utc_now()
            pointer["disabledBy"] = requester
            pointer["disableReason"] = rationale
            atomic_write_json(pointer_path, pointer)
        receipt = self._gate_receipt(
            "module-disable",
            "passed",
            module_id=module_id,
            version=str(pointer.get("currentVersion") or ""),
            evidence={
                "requestedBy": requester,
                "reason": rationale,
                "pointerPath": str(pointer_path),
            },
        )
        append_jsonl_durable(self.ledger_path, receipt)
        return receipt

    @_module_scoped
    def rollback_module(
        self,
        module_id: str,
        *,
        requested_by: str,
        reason: str,
        target_version: str = "",
    ) -> dict[str, Any]:
        module_id = _safe_module_id(module_id)
        requester = str(requested_by or "").strip()
        rationale = str(reason or "").strip()
        if not requester or not rationale:
            raise ValueError("requested_by and reason are required")
        module_dir = self.module_root / module_id
        pointer_path = module_dir / "current.json"
        transaction_path = module_dir / "rollback-transaction.json"
        actual_current = self._read_json(pointer_path)
        if actual_current.get("schema") != MODULE_ACTIVATION_POINTER_SCHEMA:
            raise FileNotFoundError(f"No activation pointer for {module_id}")
        transaction = self._read_json(transaction_path)
        retry_transaction = bool(
            transaction.get("schema") == OCI_ACTIVATION_TRANSACTION_SCHEMA
            and transaction.get("kind") == "rollback"
            and transaction.get("requestedBy") == requester
            and transaction.get("reason") == rationale
            and (
                not target_version
                or transaction.get("toVersion") == target_version
            )
            and actual_current
            in {
                "previous": transaction.get("previousPointer"),
                "next": transaction.get("nextPointer"),
            }.values()
        )
        current = (
            dict(transaction.get("previousPointer") or {})
            if retry_transaction
            else actual_current
        )
        selected = str(
            transaction.get("toVersion")
            if retry_transaction
            else target_version or current.get("previousVersion") or ""
        ).strip()
        try:
            _semver_parts(selected)
        except ValueError:
            raise ValueError("No valid rollback version is available")
        target = self.module_root / module_id / "versions" / selected
        manifest = self._read_json(target / ".neyvia" / "manifest.json")
        receipt = self._read_json(target / ".neyvia" / "install-receipt.json")
        if (
            not target.is_dir()
            or manifest.get("moduleId") != module_id
            or receipt.get("blockedBy")
            or receipt.get("status") not in {"activated", "installed", "already_installed"}
        ):
            raise ValueError("Rollback target has no verified install receipt")
        payload_proof = _payload_tree_proof(
            target,
            manifest["runtime"]["entrypoint"],
        )
        if receipt.get("payloadProof") != payload_proof:
            raise ValueError("Rollback target payload tree or entrypoint changed")
        compatibility = self.dependency_compatibility(manifest)
        if not compatibility["compatible"]:
            raise ValueError(
                "Rollback dependency compatibility failed: "
                + "; ".join(compatibility["errors"])
            )
        prior_activation = current.get("previousActivation")
        if not isinstance(prior_activation, dict):
            prior_activation = {}
        prior_matches = (
            prior_activation.get("currentVersion") == selected
            and prior_activation.get("archiveSha256")
            == manifest["package"]["archiveSha256"]
            and prior_activation.get("manifestSha256")
            == _canonical_manifest_sha256(manifest)
            and prior_activation.get("targetPath") == str(target)
        )
        restored_oci_provenance = False
        if not prior_matches or not prior_activation.get("ociManifestDigest"):
            raise ValueError(
                "Legacy rollback has no verified OCI provenance; an explicit "
                "approval-gated migration is required"
            )
        if prior_matches and prior_activation.get("ociManifestDigest"):
            if self._trusted_binding(manifest) is None:
                raise ValueError("Rollback publisher identity is no longer trusted")
            archive_path = Path(
                str(prior_activation.get("archivePath") or "")
            ).resolve()
            if (
                not archive_path.is_file()
                or _sha256(archive_path)
                != manifest["package"]["archiveSha256"]
                or prior_activation.get("payloadProof") != payload_proof
                or prior_activation.get("installReceiptSha256")
                != _sha256(target / ".neyvia" / "install-receipt.json")
            ):
                raise ValueError("Rollback OCI provenance inputs changed")
            plan = self.build_oci_artifact_plan(
                manifest,
                archive_path,
                install_receipt=receipt,
            )
            inspection = self.inspect_oci_artifact(
                manifest,
                archive_path,
                prior_activation.get("ociManifest"),
                security_evidence=prior_activation.get("securityEvidence"),
            )
            if (
                not inspection["activationReady"]
                or prior_activation.get("ociSubject") != plan["ociSubject"]
                or prior_activation.get("ociManifest") != plan["ociManifest"]
                or prior_activation.get("securityEvidence")
                != plan["securityEvidence"]
                or prior_activation.get("securityEvidenceDigest")
                != hashlib.sha256(
                    _canonical_json_bytes(plan["securityEvidence"])
                ).hexdigest()
                or prior_activation.get("ociManifestDigest")
                != plan["ociManifestDescriptor"]["digest"]
                or prior_activation.get("resolvedRegistryRef")
                != plan["distribution"]["resolvedRef"]
            ):
                raise ValueError(
                    "Rollback OCI evidence or provenance no longer verifies"
                )
            restored_oci_provenance = True
        next_pointer = {
            "schema": MODULE_ACTIVATION_POINTER_SCHEMA,
            "moduleId": module_id,
            "state": "active",
            "currentVersion": selected,
            "previousVersion": str(current.get("currentVersion") or ""),
            "archiveSha256": manifest["package"]["archiveSha256"],
            "manifestSha256": _canonical_manifest_sha256(manifest),
            "payloadTreeSha256": payload_proof["treeSha256"],
            "entrypointSha256": payload_proof["entrypointSha256"],
            "payloadProof": payload_proof,
            "targetPath": str(target),
            "namespaceClaims": _module_namespace_claims(manifest),
            "activatedAt": _utc_now(),
            "rollback": {
                "requestedBy": requester,
                "reason": rationale,
            },
        }
        if restored_oci_provenance:
            for key in (
                "archivePath",
                "ociManifest",
                "ociSubject",
                "ociManifestDigest",
                "resolvedRegistryRef",
                "securityEvidence",
                "securityEvidenceDigest",
                "installReceiptSha256",
            ):
                if prior_activation.get(key):
                    next_pointer[key] = prior_activation[key]
        next_pointer["previousActivation"] = {
            key: current.get(key)
            for key in (
                "currentVersion",
                "archiveSha256",
                "manifestSha256",
                "payloadTreeSha256",
                "entrypointSha256",
                "payloadProof",
                "targetPath",
                "archivePath",
                "ociManifest",
                "ociSubject",
                "ociManifestDigest",
                "resolvedRegistryRef",
                "securityEvidence",
                "securityEvidenceDigest",
                "installReceiptSha256",
                "namespaceClaims",
            )
            if current.get(key)
        }
        transaction_core = {
            "kind": "rollback",
            "moduleId": module_id,
            "fromVersion": current.get("currentVersion"),
            "toVersion": selected,
            "requestedBy": requester,
            "reason": rationale,
            "payloadTreeSha256": payload_proof["treeSha256"],
            "ociManifestDigest": next_pointer.get("ociManifestDigest", ""),
        }
        transaction_id = hashlib.sha256(
            _canonical_json_bytes(transaction_core)
        ).hexdigest()
        if retry_transaction:
            if transaction.get("transactionId") != transaction_id:
                raise ValueError("Rollback transaction binding changed")
            stored_next = dict(transaction.get("nextPointer") or {})
            for key in (
                "currentVersion",
                "archiveSha256",
                "manifestSha256",
                "payloadTreeSha256",
                "entrypointSha256",
                "payloadProof",
                "targetPath",
                "archivePath",
                "ociManifest",
                "ociSubject",
                "ociManifestDigest",
                "resolvedRegistryRef",
                "securityEvidence",
                "securityEvidenceDigest",
                "installReceiptSha256",
                "namespaceClaims",
            ):
                if stored_next.get(key) != next_pointer.get(key):
                    raise ValueError("Rollback transaction target changed")
            next_pointer = stored_next
            gate = dict(transaction.get("receipt") or {})
        else:
            gate = self._gate_receipt(
                "module-rollback",
                "passed",
                module_id=module_id,
                version=selected,
                evidence={
                    "transactionId": transaction_id,
                    "fromVersion": current.get("currentVersion"),
                    "toVersion": selected,
                    "requestedBy": requester,
                    "reason": rationale,
                    "restoredOciProvenance": restored_oci_provenance,
                    "payloadTreeSha256": payload_proof["treeSha256"],
                    "namespaceClaims": next_pointer["namespaceClaims"],
                },
            )
            transaction = {
                "schema": OCI_ACTIVATION_TRANSACTION_SCHEMA,
                "kind": "rollback",
                "transactionId": transaction_id,
                "phase": "prepared",
                "requestedBy": requester,
                "reason": rationale,
                "fromVersion": current.get("currentVersion"),
                "toVersion": selected,
                "previousPointer": current,
                "nextPointer": next_pointer,
                "receipt": gate,
                "preparedAt": _utc_now(),
            }
            atomic_write_json(transaction_path, transaction)
        with _module_file_lock(self.module_root / ".activation-registry"):
            self._require_activation_namespace_available(
                manifest,
                requested_by=requester,
            )
            actual_current = self._read_json(pointer_path)
            if (
                actual_current != transaction.get("previousPointer")
                and actual_current != next_pointer
            ):
                raise ValueError("Current pointer changed during rollback")
            if actual_current != next_pointer:
                atomic_write_json(pointer_path, next_pointer)
        transaction["phase"] = "completed"
        transaction["completedAt"] = transaction.get("completedAt") or _utc_now()
        atomic_write_json(transaction_path, transaction)
        if gate and not self._ledger_has_receipt(str(gate.get("receiptId") or "")):
            append_jsonl_durable(self.ledger_path, gate)
        if retry_transaction:
            gate = json.loads(json.dumps(gate))
            gate.setdefault("evidence", {})["idempotentRetry"] = True
        return gate

    def _runtime_oci_errors(
        self,
        manifest: dict[str, Any],
        target: Path,
        pointer: dict[str, Any],
        payload_proof: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        if pointer.get("namespaceClaims") != _module_namespace_claims(manifest):
            errors.append(
                "activation pointer does not bind the module namespace claims"
            )
        if self._trusted_binding(manifest) is None:
            errors.append("publisher identity is no longer trusted")
        if not pointer.get("ociManifestDigest"):
            errors.append(
                "legacy activation has no OCI provenance; approved migration required"
            )
            return errors
        archive = _installed_archive_path(
            target,
            manifest["package"]["archiveSha256"],
        )
        receipt = self._read_json(target / ".neyvia" / "install-receipt.json")
        if (
            not archive.is_file()
            or _sha256(archive) != manifest["package"]["archiveSha256"]
            or receipt.get("payloadProof") != payload_proof
        ):
            errors.append("installed archive snapshot or receipt changed")
            return errors
        subject, subject_manifest, registry = self._oci_subject(
            manifest,
            manifest["package"]["archiveSha256"],
            int(manifest["package"]["archiveBytes"]),
            payload_proof,
        )
        gate_receipts = [
            dict(item)
            for item in receipt.get("gateReceipts", [])
            if isinstance(item, dict)
            and item.get("gate") in OCI_REQUIRED_SECURITY_GATES
        ]
        evidence = {
            "schema": MODULE_OCI_EVIDENCE_SCHEMA,
            "subject": subject,
            "gateReceipts": gate_receipts,
        }
        errors.extend(
            self._oci_evidence_errors(
                manifest,
                evidence,
                expected_subject=subject,
            )
        )
        evidence_descriptor = _oci_descriptor(
            OCI_SECURITY_EVIDENCE_MEDIA_TYPE,
            _canonical_json_bytes(evidence),
        )
        evidence_descriptor["annotations"] = {
            "io.neyvia.layer.role": "security-evidence"
        }
        oci_manifest = json.loads(json.dumps(subject_manifest))
        oci_manifest["layers"].append(evidence_descriptor)
        oci_manifest["annotations"]["io.neyvia.oci.subject.digest"] = subject[
            "ociSubjectDigest"
        ]
        descriptor = _oci_descriptor(
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            _canonical_json_bytes(oci_manifest),
        )
        resolved_ref = (
            f"{registry['registry']}/{registry['repository']}"
            f"@{descriptor['digest']}"
        )
        if (
            pointer.get("payloadProof") != payload_proof
            or pointer.get("ociSubject") != subject
            or pointer.get("ociManifest") != oci_manifest
            or pointer.get("ociManifestDigest") != descriptor["digest"]
            or pointer.get("securityEvidence") != evidence
            or pointer.get("securityEvidenceDigest")
            != hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()
            or pointer.get("resolvedRegistryRef") != resolved_ref
        ):
            errors.append("active OCI provenance does not match installed evidence")
        return sorted(set(errors))

    def _installed_version_dirs(self, module_directory: Path) -> list[Path]:
        versions_root = module_directory / "versions"
        if not versions_root.is_dir():
            return []
        targets: list[Path] = []
        for version_directory in sorted(versions_root.iterdir()):
            if not version_directory.is_dir():
                continue
            try:
                _semver_parts(version_directory.name)
            except ValueError:
                continue
            manifest = self._read_json(
                version_directory / ".neyvia" / "manifest.json"
            )
            receipt = self._read_json(
                version_directory / ".neyvia" / "install-receipt.json"
            )
            if (
                manifest.get("moduleId") == module_directory.name
                and manifest.get("version") == version_directory.name
                and receipt.get("schema") == MODULE_INSTALL_RECEIPT_SCHEMA
                and receipt.get("moduleId") == module_directory.name
                and receipt.get("version") == version_directory.name
                and not receipt.get("blockedBy")
                and receipt.get("status")
                in {"activated", "installed", "already_installed"}
            ):
                targets.append(version_directory)
        return targets

    def _catalog_evidence(
        self,
        manifest: dict[str, Any],
        target: Path,
        *,
        pointer: dict[str, Any],
        staged: dict[str, Any],
    ) -> dict[str, Any]:
        binding = self._trusted_binding(manifest)
        install_receipt = self._read_json(target / ".neyvia" / "install-receipt.json")
        signature_gate = next(
            (
                item
                for item in install_receipt.get("gateReceipts", [])
                if isinstance(item, dict)
                and item.get("gate") == "cosign-bundle-verification"
            ),
            None,
        )
        signature_state = "missing"
        signature_detail = (
            "No install receipt signature gate is stored for this version."
        )
        if isinstance(signature_gate, dict):
            if signature_gate.get("passed") is True:
                signature_state = "verified"
                signature_detail = (
                    "Install receipt records a passed Cosign bundle verification gate."
                )
            else:
                signature_state = "blocked"
                signature_detail = "; ".join(
                    str(item) for item in signature_gate.get("errors", [])
                ) or "Cosign bundle verification did not pass."
        staged_matches = (
            staged.get("schema") == MODULE_OCI_STAGED_POINTER_SCHEMA
            and staged.get("moduleId") == manifest["moduleId"]
            and staged.get("version") == manifest["version"]
            and staged.get("state") in {"staged", "promoted"}
        )
        previous_version = str(
            pointer.get("previousVersion")
            or staged.get("previousVersion")
            or install_receipt.get("previousVersion")
            or ""
        )
        return {
            "publisherTrust": {
                "trusted": binding is not None,
                "state": "trusted" if binding else "untrusted",
                "bindingId": str((binding or {}).get("bindingId") or ""),
                "detail": (
                    "Publisher identity is bound in the local trust store."
                    if binding
                    else "Publisher identity is not bound in the local trust store."
                ),
            },
            "signatureReceipt": {
                "state": signature_state,
                "detail": signature_detail,
                "receiptId": str((signature_gate or {}).get("receiptId") or ""),
            },
            "staging": {
                "state": "staged" if staged_matches else "none",
                "version": str(staged.get("version") or "") if staged_matches else "",
                "ociManifestDigest": (
                    str(staged.get("ociManifestDigest") or "")
                    if staged_matches
                    else ""
                ),
                "detail": (
                    "A staged OCI activation pointer is present for this version."
                    if staged_matches
                    else "No staged OCI activation pointer is present for this version."
                ),
            },
            "previousVersion": previous_version,
            "installStatus": str(install_receipt.get("status") or ""),
            "activationRequested": install_receipt.get("activationRequested") is True,
            "activationBlockedBy": list(install_receipt.get("activationBlockedBy") or []),
            "actions": {
                "disable": pointer.get("state") == "active",
                "rollback": bool(previous_version),
                "activate": bool(
                    staged_matches
                    or (
                        install_receipt.get("status")
                        in {"installed", "already_installed", "activated"}
                        and pointer.get("state") != "active"
                    )
                ),
            },
        }

    def installed_catalog(self) -> dict[str, Any]:
        modules: list[dict[str, Any]] = []
        if self.module_root.is_dir():
            for module_directory in sorted(self.module_root.iterdir()):
                if not module_directory.is_dir() or module_directory.name.startswith("."):
                    continue
                try:
                    _safe_module_id(module_directory.name)
                except ValueError:
                    continue
                pointer = self._read_json(module_directory / "current.json")
                staged = self._read_json(module_directory / "staged.json")
                installed_targets = self._installed_version_dirs(module_directory)
                has_pointer = (
                    pointer.get("schema") == MODULE_ACTIVATION_POINTER_SCHEMA
                )
                if has_pointer:
                    version = str(pointer.get("currentVersion") or "")
                    target = module_directory / "versions" / version
                    state = str(pointer.get("state") or "disabled")
                elif installed_targets:
                    target = installed_targets[-1]
                    version = target.name
                    if (
                        staged.get("schema") == MODULE_OCI_STAGED_POINTER_SCHEMA
                        and staged.get("version") == version
                        and staged.get("state") in {"staged", "promoted"}
                    ):
                        state = "staged"
                    else:
                        state = "installed"
                else:
                    continue
                manifest = self._read_json(target / ".neyvia" / "manifest.json")
                if not manifest:
                    continue
                integrity_error = ""
                proof: dict[str, Any] = {}
                try:
                    proof = _payload_tree_proof(
                        target,
                        manifest["runtime"]["entrypoint"],
                    )
                    if has_pointer and (
                        proof.get("treeSha256")
                        != pointer.get("payloadTreeSha256")
                        or proof.get("entrypointSha256")
                        != pointer.get("entrypointSha256")
                    ):
                        integrity_error = (
                            "active payload tree or entrypoint digest mismatch"
                        )
                except (KeyError, OSError, ValueError) as exc:
                    integrity_error = str(exc)
                if integrity_error and state == "active":
                    state = "integrity-blocked"
                runtime_errors: list[str] = []
                if state == "active":
                    runtime_errors = self._runtime_oci_errors(
                        manifest,
                        target,
                        pointer,
                        proof,
                    )
                    if runtime_errors:
                        state = "security-blocked"
                evidence = self._catalog_evidence(
                    manifest,
                    target,
                    pointer=pointer if has_pointer else {},
                    staged=staged,
                )
                modules.append(
                    {
                        "moduleId": manifest["moduleId"],
                        "name": manifest["name"],
                        "summary": manifest["summary"],
                        "version": version,
                        "state": state,
                        "integrityError": integrity_error,
                        "securityErrors": runtime_errors,
                        "_manifest": manifest,
                        "publisher": manifest["publisher"],
                        "runtime": manifest["runtime"],
                        "permissions": manifest["permissions"],
                        # Public, validated projection used by the Neyvia
                        # application registry after the private manifest is
                        # removed below. This keeps application surfaces and
                        # capabilities connected without exposing package
                        # signature or distribution internals.
                        "applicationProjection": {
                            "capabilities": manifest["capabilities"],
                            "surfaces": manifest["surfaces"],
                            "compatibility": manifest["compatibility"],
                        },
                        "capabilityCount": len(manifest["capabilities"]),
                        "surfaceCount": len(manifest["surfaces"]),
                        "namespaceClaims": _module_namespace_claims(manifest),
                        "targetPath": str(target),
                        "previousVersion": evidence["previousVersion"],
                        "p2pEligible": manifest["distribution"]["p2pEligible"],
                        "publisherTrust": evidence["publisherTrust"],
                        "signatureReceipt": evidence["signatureReceipt"],
                        "staging": evidence["staging"],
                        "installStatus": evidence["installStatus"],
                        "activationRequested": evidence["activationRequested"],
                        "activationBlockedBy": evidence["activationBlockedBy"],
                        "actions": evidence["actions"],
                        "installedVersions": [
                            item.name for item in installed_targets
                        ],
                    }
                )
        changed = True
        while changed:
            changed = False
            active_versions = {
                item["moduleId"]: item["version"]
                for item in modules
                if item["state"] == "active"
            }
            for item in modules:
                if item["state"] != "active":
                    continue
                dependency_errors: list[str] = []
                for dependency in item["_manifest"].get("dependencies", []):
                    installed_version = active_versions.get(
                        dependency["moduleId"]
                    )
                    if (
                        dependency.get("required") is True
                        and (
                            not installed_version
                            or not _version_satisfies(
                                installed_version,
                                dependency["version"],
                            )
                        )
                    ):
                        dependency_errors.append(
                            f"Required dependency {dependency['moduleId']} "
                            f"{dependency['version']} is not active"
                        )
                if dependency_errors:
                    item["state"] = "dependency-blocked"
                    item["securityErrors"].extend(dependency_errors)
                    changed = True
        for item in modules:
            item.pop("_manifest", None)
        from .source_marketplace import SourceMarketplace
        signed_ids = {item["moduleId"] for item in modules}
        modules.extend(item for item in SourceMarketplace(self.root).catalog()["items"] if item["id"] not in signed_ids)
        return {
            "schema": MODULE_CATALOG_SCHEMA,
            "moduleRoot": str(self.module_root),
            "moduleCount": len(modules),
            "activeCount": sum(item["state"] == "active" for item in modules),
            "disabledCount": sum(item["state"] == "disabled" for item in modules),
            "installedCount": sum(item["state"] == "installed" for item in modules),
            "modules": modules,
        }

    def active_context_snapshot(
        self,
        *,
        max_modules: int = 50,
        max_context_bytes: int = 256 * 1024,
    ) -> dict[str, Any]:
        catalog = self.installed_catalog()
        modules: list[dict[str, Any]] = []
        used_bytes = 0
        for row in catalog["modules"]:
            if row["state"] != "active" or row.get("origin") == "developer-source" or len(modules) >= max_modules:
                continue
            target = Path(row["targetPath"])
            manifest = self._read_json(target / ".neyvia" / "manifest.json")
            context_path = _safe_child(
                target,
                manifest["context"]["summaryIndex"],
                name="context.summaryIndex",
            )
            context_bytes = context_path.read_bytes()
            if used_bytes + len(context_bytes) > max_context_bytes:
                break
            context = json.loads(context_bytes.decode("utf-8"))
            modules.append(
                {
                    "moduleId": manifest["moduleId"],
                    "version": manifest["version"],
                    "summary": manifest["summary"],
                    "capabilities": manifest["capabilities"],
                    "surfaces": manifest["surfaces"],
                    "context": context,
                    "detailPath": str(target / ".neyvia" / "manifest.json"),
                }
            )
            used_bytes += len(context_bytes)
        return {
            "schema": "neyvia.active-module-context/v1",
            "moduleCount": len(modules),
            "contextBytes": used_bytes,
            "maxContextBytes": max_context_bytes,
            "lazyDetail": True,
            "modules": modules,
        }
