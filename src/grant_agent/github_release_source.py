"""Resolve Neyvia marketplace applications from GitHub releases.

:mod:`grant_agent.module_marketplace` already does the hard parts — manifest
validation, signature and checksum verification, collision checks, quarantine,
atomic activation, rollback. What it had no notion of was *where a release comes
from*. This module supplies that one missing piece and nothing else: it turns a
GitHub repository into the release metadata and platform artifact the existing
install path already knows how to verify.

Two properties matter more than features here:

**An update check must not download a package.** Checking costs a small JSON
document; installing is the user's decision. :func:`check_for_update` therefore
never touches an asset, and a test asserts it.

**A failed check must never look like "up to date".** Rate limits, offline
laptops, and deleted repositories all produce an *unknown* result that says so.
Reporting "no updates" because the network failed is how a security fix silently
never arrives.

Network access is injected, so the whole module is testable against a local
fixture without reaching GitHub.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .module_marketplace import _compare_semver
from .proofs_b_adapters import checked as _proofs_b_checked

GITHUB_API = "https://api.github.com"

#: Manifest channels (from the module manifest schema) mapped onto what GitHub
#: actually records about a release.
CHANNEL_STABLE = "stable"
CHANNEL_BETA = "beta"

#: How large a metadata response may be before we treat it as suspicious. A
#: releases listing is a few hundred KiB at most; anything larger is not
#: metadata and must not be pulled into memory during a routine check.
MAX_METADATA_BYTES = 4 * 1024 * 1024

#: Streaming chunk for asset downloads, which are expected to be large.
_DOWNLOAD_CHUNK = 128 * 1024


class GitHubReleaseError(RuntimeError):
    """Raised when a release cannot be resolved or verified."""


@dataclass(frozen=True)
class GitHubSource:
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def releases_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}/releases"


@_proofs_b_checked("reference")
def parse_github_ref(value: object) -> GitHubSource | None:
    """Accept ``owner/repo`` or a GitHub URL. Returns ``None`` if neither.

    Returning ``None`` rather than raising lets a manifest that is simply not
    GitHub-hosted flow through the ordinary registry path untouched.
    """
    text = str(value or "").strip()
    if not text:
        return None

    matched_host = False
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:", "github.com/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            matched_host = True
            break

    # A URL for some other host is not a GitHub reference. Without this check a
    # value like "https://example.com/thing" parses into owner "https:", which
    # would route a non-GitHub manifest down the GitHub path.
    if not matched_host and ("://" in text or "@" in text):
        return None

    text = text.removesuffix(".git").strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    if not _is_github_name(owner) or not _is_github_name(repo):
        return None
    return GitHubSource(owner=owner, repo=repo)


def _is_github_name(value: str) -> bool:
    """GitHub owner and repository names allow only these characters."""
    return bool(value) and all(char.isalnum() or char in "-_." for char in value)


# --- transport --------------------------------------------------------------


def _default_fetch(url: str, *, token: str | None, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise GitHubReleaseError(
            f"Response from {url} exceeded {max_bytes} bytes; refusing to treat it as metadata."
        )
    return payload


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Neyvia-Marketplace",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


Fetcher = Callable[..., bytes]


def fetch_releases(
    source: GitHubSource,
    *,
    token: str | None = None,
    timeout: float = 15.0,
    fetch: Fetcher | None = None,
) -> list[dict[str, Any]]:
    """Fetch release metadata only. Never downloads an asset."""
    fetcher = fetch or _default_fetch
    try:
        raw = fetcher(
            source.releases_url, token=token, timeout=timeout, max_bytes=MAX_METADATA_BYTES
        )
    except urllib.error.HTTPError as exc:
        detail = "rate limit or authentication" if exc.code in (401, 403, 429) else f"HTTP {exc.code}"
        raise GitHubReleaseError(
            f"Could not read releases for {source.slug} ({detail}). "
            "This is not the same as there being no update."
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise GitHubReleaseError(
            f"Could not reach GitHub for {source.slug}: {exc}. "
            "This is not the same as there being no update."
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GitHubReleaseError(f"GitHub returned unreadable release data for {source.slug}.") from exc

    if not isinstance(payload, list):
        raise GitHubReleaseError(f"GitHub returned an unexpected release listing for {source.slug}.")
    return [item for item in payload if isinstance(item, dict)]


# --- selection --------------------------------------------------------------


def release_channel(release: dict[str, Any]) -> str:
    """Map a GitHub release onto a manifest channel."""
    return CHANNEL_BETA if release.get("prerelease") else CHANNEL_STABLE


@_proofs_b_checked("version")
def normalize_version(value: object) -> str:
    """Strip a leading ``v`` so ``v1.2.3`` and ``1.2.3`` compare equal."""
    text = str(value or "").strip()
    return text[1:] if text[:1].lower() == "v" and text[1:2].isdigit() else text


def compare_versions(installed: object, published: object) -> int | None:
    """Compare two marketplace versions, or return ``None`` when ordering is unknown."""

    current = normalize_version(installed)
    latest = normalize_version(published)
    if current == latest:
        return 0
    try:
        return _compare_semver(current, latest)
    except (TypeError, ValueError):
        return None


@_proofs_b_checked("selection")
def select_release(
    releases: list[dict[str, Any]],
    *,
    channel: str = CHANNEL_STABLE,
    version: str | None = None,
) -> dict[str, Any] | None:
    """Pick the release to offer.

    Drafts are never offered — they are unpublished by definition, and treating
    one as installable would surface work the publisher has not released.
    """
    candidates = [
        release
        for release in releases
        if not release.get("draft")
        and (channel == CHANNEL_BETA or release_channel(release) == channel)
    ]
    if version:
        wanted = normalize_version(version)
        return next(
            (
                release
                for release in candidates
                if normalize_version(release.get("tag_name")) == wanted
            ),
            None,
        )
    # GitHub returns newest first; rely on that rather than parsing dates, and
    # keep the publisher's ordering rather than inventing our own ranking.
    return candidates[0] if candidates else None


@_proofs_b_checked("platform")
def select_platform_asset(
    release: dict[str, Any],
    *,
    platform_tag: str,
) -> dict[str, Any] | None:
    """Find the asset built for this platform.

    Matches on the platform tag appearing in the asset name, which is the
    convention release tooling already follows.
    """
    assets = [asset for asset in (release.get("assets") or []) if isinstance(asset, dict)]
    tag = platform_tag.strip().lower()
    for asset in assets:
        if tag and tag in str(asset.get("name") or "").lower():
            return asset
    return None


@_proofs_b_checked("checksum")
def find_checksum_for(release: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any] | None:
    """Locate the sidecar checksum asset that accompanies ``asset``, if published."""
    name = str(asset.get("name") or "")
    wanted = {f"{name}.sha256", f"{name}.sha256sum", "checksums.txt", "SHA256SUMS"}
    for candidate in release.get("assets") or []:
        if isinstance(candidate, dict) and str(candidate.get("name") or "") in wanted:
            return candidate
    return None


# --- update checking --------------------------------------------------------


@_proofs_b_checked("update")
def check_for_update(
    installed_version: str,
    source: GitHubSource,
    *,
    channel: str = CHANNEL_STABLE,
    platform_tag: str = "",
    token: str | None = None,
    fetch: Fetcher | None = None,
) -> dict[str, Any]:
    """Report whether a newer release exists, without downloading anything.

    The ``state`` is one of ``current``, ``update_available``, or ``unknown``.
    ``unknown`` is a first-class outcome: a check that could not run has not
    established that the user is up to date.
    """
    try:
        releases = fetch_releases(source, token=token, fetch=fetch)
    except GitHubReleaseError as error:
        return {
            "schema": "neyvia.marketplace.update_check/1",
            "state": "unknown",
            "detail": str(error),
            "source": source.slug,
            "installedVersion": installed_version,
        }

    release = select_release(releases, channel=channel)
    if release is None:
        return {
            "schema": "neyvia.marketplace.update_check/1",
            "state": "unknown",
            "detail": f"No published {channel} release was found for {source.slug}.",
            "source": source.slug,
            "installedVersion": installed_version,
        }

    latest = normalize_version(release.get("tag_name"))
    current = normalize_version(installed_version)
    asset = select_platform_asset(release, platform_tag=platform_tag) if platform_tag else None

    relation = compare_versions(current, latest)
    if relation == 0:
        state, detail = "current", f"{source.slug} is at {latest}."
    elif relation is not None and relation > 0:
        state = "current"
        detail = (
            f"The installed {source.slug} version {current} is newer than the "
            f"latest published {latest}; no downgrade is offered."
        )
    elif relation is None:
        state = "unknown"
        detail = (
            f"Neyvia could not safely order installed version {current!r} and "
            f"published version {latest!r}; no update or downgrade is offered."
        )
    elif platform_tag and asset is None:
        # A release that has no artifact for this machine is not an update the
        # user can take, and offering it would produce a failing install.
        state = "unknown"
        detail = (
            f"{source.slug} published {latest}, but it has no artifact for {platform_tag}."
        )
    else:
        state, detail = "update_available", f"{source.slug} {latest} is available."

    return {
        "schema": "neyvia.marketplace.update_check/1",
        "state": state,
        "detail": detail,
        "source": source.slug,
        "installedVersion": installed_version,
        "latestVersion": latest,
        "channel": release_channel(release),
        "releaseName": release.get("name") or release.get("tag_name"),
        "releaseNotes": release.get("body") or "",
        "publishedAt": release.get("published_at"),
        "asset": (
            {
                "name": asset.get("name"),
                "bytes": asset.get("size"),
                "url": asset.get("browser_download_url"),
            }
            if asset
            else None
        ),
        # Stated so the caller can prove the promise rather than trust it.
        "downloadedBytes": 0,
    }


# --- download ---------------------------------------------------------------


def download_asset(
    asset: dict[str, Any],
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
    token: str | None = None,
    timeout: float = 120.0,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Serialize verified promotion and its readback for one staged target."""
    from .harness_jobs import _exclusive_job_lock
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=timeout):
        return _download_asset_locked(asset, target, expected_sha256=expected_sha256,
                                      token=token, timeout=timeout, opener=opener)


@_proofs_b_checked("staging")
def _download_asset_locked(
    asset: dict[str, Any],
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
    token: str | None = None,
    timeout: float = 120.0,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download one release asset and verify it.

    Verification is not optional when a checksum is supplied: a mismatch deletes
    the partial file and raises, so a corrupted or substituted artifact can never
    reach the marketplace's staging step.
    """
    url = str(asset.get("browser_download_url") or asset.get("url") or "")
    if not url:
        raise GitHubReleaseError("The release asset has no download URL.")

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.partial"
    )

    digest = hashlib.sha256()
    written = 0
    open_url = opener or (
        lambda: urllib.request.urlopen(  # noqa: S310
            urllib.request.Request(url, headers=_headers(token)), timeout=timeout
        )
    )

    try:
        with open_url() as response, temporary.open("wb") as handle:
            # HTTP framing is transport evidence, distinct from optional
            # publisher metadata. A premature EOF must never replace a valid
            # staged package, even when no publisher checksum was supplied.
            headers = getattr(response, "headers", None)
            declared_transport_bytes = headers.get("Content-Length") if headers else None
            transport_bytes = (
                int(declared_transport_bytes)
                if declared_transport_bytes and str(declared_transport_bytes).isdigit()
                else None
            )
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
            if transport_bytes is not None and written != transport_bytes:
                raise GitHubReleaseError(
                    f"Downloading {url} was interrupted: HTTP declared "
                    f"{transport_bytes} bytes but {written} were received."
                )
            handle.flush()
            os.fsync(handle.fileno())
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        temporary.unlink(missing_ok=True)
        raise GitHubReleaseError(f"Downloading {url} failed: {exc}") from exc
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    actual = digest.hexdigest()
    if expected_sha256 and actual.lower() != str(expected_sha256).strip().lower():
        temporary.unlink(missing_ok=True)
        raise GitHubReleaseError(
            f"Checksum mismatch for {asset.get('name')}: expected {expected_sha256}, got {actual}. "
            "The download was discarded."
        )

    declared = asset.get("size")
    size_warning = (
        f"The publisher declared {declared} bytes but {written} were received."
        if isinstance(declared, int) and declared != written
        else ""
    )
    try:
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise GitHubReleaseError(
            f"Could not atomically stage {asset.get('name')}: {exc}"
        ) from exc

    return {
        "schema": "neyvia.marketplace.download/1",
        "path": str(target),
        "bytes": written,
        "sha256": actual,
        "verified": bool(expected_sha256),
        # An unverified download is usable but must be labelled, so the caller
        # can decide whether to proceed rather than assume it was checked.
        "detail": (
            "Verified against the publisher's checksum."
            if expected_sha256
            else "No checksum was published for this asset; it could not be verified."
        ),
        "warning": size_warning,
    }
