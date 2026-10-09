"""Auditable update discovery for the portable marketplace security toolchain."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOOLCHAIN_UPDATE_SCHEMA = "neyvia.marketplace-toolchain-updates/v1"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _version_tuple(value: object) -> tuple[int, ...]:
    text = str(value or "").strip()
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", text)
    if not match:
        raise ValueError(f"Unsupported stable version: {text or '<empty>'}")
    return tuple(int(item) for item in match.group(1).split("."))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class MarketplaceToolchainUpdateManager:
    """Check official stable releases without mutating an active installation."""

    def __init__(
        self,
        root: str | Path,
        *,
        toolchain_path: str | Path | None = None,
        cache_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        project_root = Path(__file__).resolve().parents[2]
        selected = Path(
            toolchain_path
            or self.root / "config" / "neyvia_marketplace_toolchain.json"
        )
        if not selected.is_file():
            selected = (
                project_root / "config" / "neyvia_marketplace_toolchain.json"
            )
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.toolchain_path = selected.resolve()
        self.toolchain = json.loads(
            self.toolchain_path.read_text(encoding="utf-8")
        )
        self.cache_path = Path(
            cache_path
            or self.root
            / ".agent_control"
            / "capability_os"
            / "toolchain"
            / "latest-releases.json"
        ).resolve()

    @property
    def policy(self) -> dict[str, Any]:
        value = self.toolchain.get("policy")
        return dict(value) if isinstance(value, dict) else {}

    def local_integrity(self) -> dict[str, Any]:
        rows: dict[str, Any] = {}
        for name, raw in sorted((self.toolchain.get("tools") or {}).items()):
            configured = dict(raw) if isinstance(raw, dict) else {}
            path_text = str(configured.get("path") or "").strip()
            expected = str(
                configured.get("executableSha256") or ""
            ).strip().casefold()
            if path_text in {"", "auto"}:
                rows[name] = {
                    "version": str(configured.get("version") or ""),
                    "path": path_text,
                    "state": "platform-managed",
                    "healthy": path_text == "auto",
                    "hashVerified": expected == "dynamic-platform-update",
                }
                continue
            path = Path(path_text).resolve()
            actual = (
                _sha256_file(path)
                if path.is_file()
                else ""
            )
            verified = bool(
                actual
                and _SHA256.fullmatch(expected)
                and hmac.compare_digest(actual, expected)
            )
            rows[name] = {
                "version": str(configured.get("version") or ""),
                "path": str(path),
                "state": "verified" if verified else "invalid",
                "healthy": verified,
                "hashVerified": verified,
                "expectedSha256": expected,
                "actualSha256": actual,
            }
        result = {
            "schema": "neyvia.marketplace-toolchain-integrity/v1",
            "generatedAt": _utc_now(),
            "tools": rows,
            "healthy": all(row["healthy"] for row in rows.values()),
            "invalidTools": sorted(
                name for name, row in rows.items() if not row["healthy"]
            ),
        }
        from .proofs_c_runtime import check_toolchain_integrity
        check_toolchain_integrity(result)
        return result

    def check_latest(
        self,
        *,
        force: bool = False,
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        if not force:
            cached = self._fresh_cache()
            if cached is not None:
                result = {**cached, "cache": "hit"}
                from .proofs_c_runtime import check_toolchain_discovery
                check_toolchain_discovery(self, result)
                return result

        rows: dict[str, Any] = {}
        for name, raw in sorted((self.toolchain.get("tools") or {}).items()):
            configured = dict(raw) if isinstance(raw, dict) else {}
            update = configured.get("update")
            if not isinstance(update, dict):
                rows[name] = {
                    "installedVersion": str(configured.get("version") or ""),
                    "state": "platform-managed",
                    "updateAvailable": False,
                }
                continue
            try:
                rows[name] = self._check_tool(
                    name,
                    configured,
                    update,
                    timeout_seconds=timeout_seconds,
                )
            except (OSError, ValueError, urllib.error.URLError) as exc:
                rows[name] = {
                    "installedVersion": str(configured.get("version") or ""),
                    "state": "check-failed",
                    "updateAvailable": False,
                    "error": str(exc),
                }

        return self._publish_discovery(rows)

    def _publish_discovery(self, rows: dict[str, Any]) -> dict[str, Any]:
        result = {
            "schema": TOOLCHAIN_UPDATE_SCHEMA,
            "checkedAt": _utc_now(),
            "stableOnly": bool(
                self.policy.get("stableReleasesOnly", True)
            ),
            "activationPolicy": str(
                self.policy.get("candidateActivation")
                or "signed-neyvia-release"
            ),
            "tools": rows,
            "summary": {
                "checked": sum(
                    1 for row in rows.values() if row["state"] != "platform-managed"
                ),
                "current": sum(
                    1 for row in rows.values() if row["state"] == "current"
                ),
                "updatesAvailable": sum(
                    1 for row in rows.values() if row["updateAvailable"]
                ),
                "errors": sum(
                    1 for row in rows.values() if row["state"] == "check-failed"
                ),
            },
            "cache": "miss",
        }
        from .proofs_c_runtime import check_toolchain_discovery
        check_toolchain_discovery(self, result)
        _atomic_json(self.cache_path, result)
        if json.loads(self.cache_path.read_text(encoding="utf-8")) != result:
            raise ValueError("Contract runtime.toolchain.cache: published cache differs from observed discovery")
        return result

    def _check_tool(
        self,
        name: str,
        configured: dict[str, Any],
        update: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        repository = str(update.get("repository") or "").strip()
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError(f"{name}: invalid GitHub repository")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/releases/latest",
            headers=self._github_headers(),
            method="GET",
        )
        with urllib.request.urlopen(
            request,
            timeout=max(1, min(int(timeout_seconds), 60)),
        ) as response:
            if int(getattr(response, "status", 200)) != 200:
                raise OSError(f"{name}: GitHub returned {response.status}")
            release = json.loads(response.read(4 * 1024 * 1024))
        return self._release_candidate(name, configured, update, release)

    def _release_candidate(self, name: str, configured: dict[str, Any], update: dict[str, Any], release: object) -> dict[str, Any]:
        """Validate observed release metadata; this pure step grants no install authority."""
        repository = str(update.get("repository") or "").strip()
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError(f"{name}: invalid GitHub repository")
        if not isinstance(release, dict):
            raise ValueError(f"{name}: invalid GitHub release response")
        if release.get("draft") or (
            self.policy.get("stableReleasesOnly", True)
            and release.get("prerelease")
        ):
            raise ValueError(f"{name}: latest release is not stable")

        prefix = str(update.get("tagPrefix") or "")
        tag = str(release.get("tag_name") or "").strip()
        if prefix and not tag.startswith(prefix):
            raise ValueError(f"{name}: unexpected release tag {tag}")
        latest = tag[len(prefix) :] if prefix else tag
        installed = str(configured.get("version") or "").strip()
        installed_tuple = _version_tuple(installed)
        latest_tuple = _version_tuple(latest)

        template = str(update.get("assetTemplate") or "").strip()
        if not template:
            raise ValueError(f"{name}: update asset template is missing")
        asset_name = template.format(version=latest, tag=tag)
        assets = release.get("assets")
        asset = next(
            (
                item
                for item in assets
                if isinstance(item, dict)
                and item.get("name") == asset_name
            ),
            None,
        ) if isinstance(assets, list) else None
        if asset is None:
            raise ValueError(f"{name}: release asset is missing: {asset_name}")
        size = int(asset.get("size") or 0)
        maximum = int(update.get("maxDownloadBytes") or 250_000_000)
        if size <= 0 or size > maximum:
            raise ValueError(
                f"{name}: release asset size {size} violates limit {maximum}"
            )
        digest_text = str(asset.get("digest") or "")
        algorithm, separator, digest = digest_text.partition(":")
        if (
            separator != ":"
            or algorithm.casefold() != "sha256"
            or not _SHA256.fullmatch(digest)
        ):
            raise ValueError(
                f"{name}: GitHub release asset has no valid SHA-256 digest"
            )
        download_url = str(asset.get("browser_download_url") or "")
        expected_prefix = (
            f"https://github.com/{repository}/releases/download/"
        )
        if not download_url.startswith(expected_prefix):
            raise ValueError(f"{name}: release asset URL is not authoritative")

        update_available = latest_tuple > installed_tuple
        state = (
            "update-available"
            if update_available
            else "current"
            if latest_tuple == installed_tuple
            else "installed-ahead"
        )
        return {
            "installedVersion": installed,
            "latestVersion": latest,
            "latestTag": tag,
            "state": state,
            "updateAvailable": update_available,
            "releaseUrl": str(release.get("html_url") or ""),
            "publishedAt": str(release.get("published_at") or ""),
            "candidate": {
                "assetName": asset_name,
                "assetBytes": size,
                "assetSha256": digest.casefold(),
                "downloadUrl": download_url,
            },
        }

    def _fresh_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.is_file():
            return None
        try:
            age = time.time() - self.cache_path.stat().st_mtime
            ttl = max(
                60,
                int(self.policy.get("updateCheckTtlSeconds") or 21_600),
            )
            # Atomic replacement on Windows can leave an NTFS modification
            # timestamp fractionally ahead of time.time(). Treat only material
            # future skew as invalid so an immediate follow-up check remains a
            # cache hit without accepting a deliberately future-dated cache.
            if age < -5.0 or age > ttl:
                return None
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return (
            payload
            if isinstance(payload, dict)
            and payload.get("schema") == TOOLCHAIN_UPDATE_SCHEMA
            else None
        )

    @staticmethod
    def _github_headers() -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Neyvia-Marketplace-Toolchain",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = str(
            os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
            or ""
        ).strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
