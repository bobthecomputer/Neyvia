from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


FXTWITTER_API_BASE = "https://api.fxtwitter.com"
FOLO_API_BASE = "https://api.folo.is"
DEFAULT_USER_AGENT = "FluxioResearch/1.0 (source intelligence; respectful bounded collector)"
HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class XFollowingSourceError(RuntimeError):
    """Raised when a source cannot provide truthful following or timeline data."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_x_handle(value: str) -> str:
    handle = str(value or "").strip().lstrip("@")
    if not HANDLE_PATTERN.fullmatch(handle):
        raise ValueError("X username must contain 1 to 15 letters, numbers, or underscores.")
    return handle


def _https_base(value: str, *, label: str) -> str:
    candidate = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS origin.")
    return candidate


def _request_json(
    url: str,
    *,
    timeout_seconds: int = 30,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(5, int(timeout_seconds))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:600]
        raise XFollowingSourceError(f"Source returned HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise XFollowingSourceError(f"Source request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise XFollowingSourceError("Source returned a non-object JSON response.")
    return payload


def _profile_row(item: dict[str, Any]) -> dict[str, Any]:
    handle = normalize_x_handle(str(item.get("screen_name") or ""))
    return {
        "id": str(item.get("id") or ""),
        "screenName": handle,
        "name": str(item.get("name") or handle),
        "description": str(item.get("description") or ""),
        "url": str(item.get("url") or f"https://x.com/{handle}"),
        "avatarUrl": item.get("avatar_url"),
        "protected": bool(item.get("protected")),
        "followers": int(item.get("followers") or 0),
        "following": int(item.get("following") or 0),
        "statuses": int(item.get("statuses") or 0),
        "joined": item.get("joined"),
        "verified": bool((item.get("verification") or {}).get("verified")),
    }


def fetch_following_accounts(
    username: str,
    *,
    max_accounts: int = 500,
    page_size: int = 100,
    max_pages: int = 10,
    api_base: str = FXTWITTER_API_BASE,
    timeout_seconds: int = 30,
    request_json: Callable[..., dict[str, Any]] = _request_json,
) -> dict[str, Any]:
    handle = normalize_x_handle(username)
    base = _https_base(api_base, label="FxTwitter API base")
    max_accounts = min(max(1, int(max_accounts)), 2_000)
    page_size = min(max(1, int(page_size)), 100)
    max_pages = min(max(1, int(max_pages)), 50)
    cursor = ""
    seen_cursors: set[str] = set()
    accounts: list[dict[str, Any]] = []
    seen_handles: set[str] = set()
    source_urls: list[str] = []
    pagination_stop_reason = "max_pages"
    observed_pages: list[tuple[dict[str, Any], str]] = []

    for _page in range(max_pages):
        params = {"count": str(page_size)}
        if cursor:
            params["cursor"] = cursor
        url = f"{base}/2/profile/{urllib.parse.quote(handle)}/following?{urllib.parse.urlencode(params)}"
        payload = request_json(url, timeout_seconds=timeout_seconds)
        source_urls.append(url)
        if int(payload.get("code") or 0) != 200:
            raise XFollowingSourceError(
                f"FxTwitter following lookup failed with code {payload.get('code')}: "
                f"{payload.get('message') or 'unknown error'}"
            )
        results = payload.get("results")
        if not isinstance(results, list):
            raise XFollowingSourceError("FxTwitter response omitted the following results array.")
        observed_pages.append((payload, url))
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                row = _profile_row(item)
            except ValueError:
                continue
            key = row["screenName"].casefold()
            if key in seen_handles:
                continue
            seen_handles.add(key)
            accounts.append(row)
            if len(accounts) >= max_accounts:
                break
        next_cursor = str((payload.get("cursor") or {}).get("bottom") or "").strip()
        if len(accounts) >= max_accounts:
            cursor = next_cursor
            pagination_stop_reason = "max_accounts" if next_cursor else "exhausted"
            break
        if not results or not next_cursor:
            cursor = ""
            pagination_stop_reason = "exhausted"
            break
        if next_cursor in seen_cursors:
            cursor = next_cursor
            pagination_stop_reason = "cursor_loop"
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if not accounts:
        raise XFollowingSourceError("FxTwitter returned no accounts for the following list.")
    snapshot = {
        "schema": "fluxio.x_following_snapshot.v1",
        "accountUsername": handle,
        "collectedAt": utc_now_iso(),
        "provider": "FxTwitter",
        "providerUrl": "https://docs.fxembed.com/api/twitter/operations/2profilehandlefollowing/",
        "authentication": "none",
        "cost": "free_no_key",
        "sourceUrls": source_urls,
        "accountCount": len(accounts),
        "truncated": pagination_stop_reason != "exhausted",
        "nextCursorAvailable": bool(cursor),
        "paginationStopReason": pagination_stop_reason,
        "accounts": accounts,
    }
    from .proofs_e_wz import check_following
    check_following(snapshot, max_accounts, observed_pages)
    return snapshot


def _timeline_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "guid": str(item.get("guid") or ""),
        "author": str(item.get("author") or ""),
        "authorUrl": str(item.get("authorUrl") or ""),
        "publishedAt": str(item.get("publishedAt") or ""),
        "description": str(item.get("description") or ""),
        "content": str(item.get("content") or ""),
        "media": item.get("media") if isinstance(item.get("media"), list) else [],
    }


def fetch_folo_timeline(
    username: str,
    *,
    entries_limit: int = 5,
    api_base: str = FOLO_API_BASE,
    timeout_seconds: int = 30,
    request_json: Callable[..., dict[str, Any]] = _request_json,
) -> dict[str, Any]:
    handle = normalize_x_handle(username)
    base = _https_base(api_base, label="Folo API base")
    entries_limit = min(max(1, int(entries_limit)), 20)
    feed_url = f"rsshub://twitter/user/{handle}"
    query = urllib.parse.urlencode({"url": feed_url, "entriesLimit": entries_limit})
    source_url = f"{base}/feeds?{query}"
    payload = request_json(source_url, timeout_seconds=timeout_seconds)
    if payload.get("code") != 0:
        raise XFollowingSourceError(
            f"Folo feed lookup failed with code {payload.get('code')}: "
            f"{payload.get('message') or 'unknown error'}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise XFollowingSourceError("Folo response omitted feed data.")
    feed = data.get("feed") if isinstance(data.get("feed"), dict) else {}
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    return {
        "screenName": handle,
        "status": "ok" if entries else "empty",
        "feedUrl": feed_url,
        "sourceUrl": source_url,
        "siteUrl": str(feed.get("siteUrl") or f"https://x.com/{handle}"),
        "feedTitle": str(feed.get("title") or handle),
        "checkedAt": str(feed.get("checkedAt") or utc_now_iso()),
        "errorMessage": str(feed.get("errorMessage") or ""),
        "entries": [_timeline_entry(item) for item in entries if isinstance(item, dict)],
    }


def collect_following_digest_sources(
    username: str,
    *,
    max_accounts: int = 500,
    posts_per_account: int = 5,
    workers: int = 4,
    timeout_seconds: int = 30,
    fxtwitter_api_base: str = FXTWITTER_API_BASE,
    folo_api_base: str = FOLO_API_BASE,
    request_json: Callable[..., dict[str, Any]] = _request_json,
) -> dict[str, Any]:
    following = fetch_following_accounts(
        username,
        max_accounts=max_accounts,
        api_base=fxtwitter_api_base,
        timeout_seconds=timeout_seconds,
        request_json=request_json,
    )
    public_accounts = [item for item in following["accounts"] if not item["protected"]]
    timelines: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=min(max(1, int(workers)), 8)) as executor:
        future_by_handle = {
            executor.submit(
                fetch_folo_timeline,
                item["screenName"],
                entries_limit=posts_per_account,
                api_base=folo_api_base,
                timeout_seconds=timeout_seconds,
                request_json=request_json,
            ): item["screenName"]
            for item in public_accounts
        }
        for future in as_completed(future_by_handle):
            handle = future_by_handle[future]
            try:
                timelines.append(future.result())
            except Exception as exc:
                failures.append({"screenName": handle, "reason": str(exc)})

    timelines.sort(key=lambda item: item["screenName"].casefold())
    failures.sort(key=lambda item: item["screenName"].casefold())
    bundle = {
        "schema": "fluxio.x_following_source_bundle.v1",
        "collectedAt": utc_now_iso(),
        "accountUsername": following["accountUsername"],
        "providers": [
            {
                "name": "FxTwitter",
                "purpose": "Following-list enumeration",
                "authentication": "none",
                "cost": "free_no_key",
                "documentation": following["providerUrl"],
            },
            {
                "name": "Folo + RSSHub",
                "purpose": "Recent public X timeline entries",
                "authentication": "none_for_public_feed_lookup",
                "cost": "free_no_key",
                "documentation": "https://github.com/RSSNext/Folo",
            },
        ],
        "following": following,
        "timelines": timelines,
        "failures": failures,
        "summary": {
            "followingAccounts": following["accountCount"],
            "protectedAccounts": len(following["accounts"]) - len(public_accounts),
            "timelinesRequested": len(public_accounts),
            "timelinesSucceeded": len(timelines),
            "timelinesFailed": len(failures),
            "postsCollected": sum(len(item["entries"]) for item in timelines),
        },
    }
    from .proofs_e_wz import check_source_bundle
    check_source_bundle(bundle)
    return bundle


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_following_source_bundle(bundle: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    files = {
        "following_snapshot.json": bundle["following"],
        "recent_posts.json": {
            "schema": "fluxio.x_recent_posts.v1",
            "collectedAt": bundle["collectedAt"],
            "accountUsername": bundle["accountUsername"],
            "timelines": bundle["timelines"],
            "failures": bundle["failures"],
            "summary": bundle["summary"],
        },
        "free_api_access_receipt.json": {
            "schema": "fluxio.x_free_api_access_receipt.v1",
            "checkedAt": bundle["collectedAt"],
            "accountUsername": bundle["accountUsername"],
            "providers": bundle["providers"],
            "summary": bundle["summary"],
            "paidApiCreditsUsed": False,
            "credentialsUsed": False,
        },
    }
    for filename, payload in files.items():
        _write_json_atomic(output_dir / filename, payload)
    artifacts = [
        {
            "path": filename,
            "bytes": (output_dir / filename).stat().st_size,
            "sha256": _sha256(output_dir / filename),
        }
        for filename in sorted(files)
    ]
    manifest = {
        "schema": "fluxio.x_source_manifest.v1",
        "generatedAt": utc_now_iso(),
        "accountUsername": bundle["accountUsername"],
        "status": "collected" if bundle["summary"]["timelinesSucceeded"] else "blocked",
        "artifacts": artifacts,
    }
    _write_json_atomic(output_dir / "free_api_source_manifest.json", manifest)
    receipt = {
        "outputDir": str(output_dir),
        "manifestPath": str(output_dir / "free_api_source_manifest.json"),
        "manifestSha256": _sha256(output_dir / "free_api_source_manifest.json"),
        "summary": bundle["summary"],
    }
    from .proofs_e_wz import check_source_artifacts
    check_source_artifacts(output_dir, files, manifest, receipt)
    return receipt
