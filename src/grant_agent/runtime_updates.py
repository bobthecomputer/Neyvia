from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

_CACHE_TTL_SECONDS = 1800.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_HERMES_RELEASE_PATTERN = re.compile(r"^RELEASE_v(\d+)\.(\d+)\.(\d+)\.md$")


def _cached(name: str, builder) -> dict[str, Any]:
    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return dict(cached[1])
    payload = dict(builder())
    _CACHE[name] = (now, payload)
    return dict(payload)


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "fluxio-control-room/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_openclaw_version(value: object) -> str:
    text = str(value or "").strip()
    match = re.search(r"(\d{4}\.\d{1,2}\.\d{1,2})", text)
    return match.group(1) if match else text


def normalize_hermes_version(value: object) -> str:
    text = str(value or "").strip()
    match = re.search(r"v(\d+\.\d+\.\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    match = re.search(r"(\d+\.\d+\.\d+)", text)
    if match:
        return f"v{match.group(1)}"
    return text


def compare_version_tokens(current: str, latest: str) -> int:
    current_tokens = _parse_version_tokens(current)
    latest_tokens = _parse_version_tokens(latest)
    result = (current_tokens > latest_tokens) - (current_tokens < latest_tokens)
    from .proofs_d_runtime import check
    check("d.runtime.version.order", {"current": current, "latest": latest}, result)
    return result


def _parse_version_tokens(value: object) -> tuple[int, ...]:
    text = str(value or "").strip().lower()
    if not text:
        return ()
    if text.startswith("v"):
        text = text[1:]
    parts: list[int] = []
    for chunk in re.split(r"[^0-9]+", text):
        if chunk:
            parts.append(int(chunk))
    return tuple(parts)


def latest_openclaw_release() -> dict[str, Any]:
    def _builder() -> dict[str, Any]:
        try:
            payload = _get_json("https://registry.npmjs.org/openclaw/latest")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {"version": "", "sourceUrl": "https://www.npmjs.com/package/openclaw"}
        version = normalize_openclaw_version(payload.get("version", ""))
        return {
            "version": version,
            "sourceUrl": "https://www.npmjs.com/package/openclaw",
        }

    return _cached("openclaw", _builder)


def latest_hermes_release() -> dict[str, Any]:
    def _builder() -> dict[str, Any]:
        source_url = "https://github.com/NousResearch/hermes-agent"
        try:
            payload = _get_json("https://api.github.com/repos/NousResearch/hermes-agent/contents/")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {"version": "", "sourceUrl": source_url}

        release_names = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                match = _HERMES_RELEASE_PATTERN.match(name)
                if not match:
                    continue
                release_names.append(
                    (
                        tuple(int(part) for part in match.groups()),
                        name,
                    )
                )
        if not release_names:
            return {"version": "", "sourceUrl": source_url}
        release_names.sort()
        latest_name = release_names[-1][1]
        latest_version = latest_name.replace("RELEASE_", "").replace(".md", "")
        return {
            "version": latest_version,
            "sourceUrl": f"https://github.com/NousResearch/hermes-agent/blob/main/{latest_name}",
        }

    return _cached("hermes", _builder)


def latest_npm_release(package: str) -> dict[str, Any]:
    """The newest published version of any npm package (``@scope/name`` or ``name``)."""
    if not re.fullmatch(r"(?:@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*", package or ""):
        return {"version": "", "sourceUrl": ""}

    def _builder() -> dict[str, Any]:
        source_url = f"https://www.npmjs.com/package/{package}"
        try:
            payload = _get_json(f"https://registry.npmjs.org/{package}/latest")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return {"version": "", "sourceUrl": source_url}
        version = str(payload.get("version") or "").strip() if isinstance(payload, dict) else ""
        return {"version": version, "sourceUrl": source_url}

    return _cached(f"npm:{package}", _builder)


def latest_opencode_release() -> dict[str, Any]:
    def _builder() -> dict[str, Any]:
        try:
            payload = _get_json("https://registry.npmjs.org/opencode-ai/latest")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {"version": "", "sourceUrl": "https://www.npmjs.com/package/opencode-ai"}
        version = str(payload.get("version") or "").strip()
        return {
            "version": version,
            "sourceUrl": "https://www.npmjs.com/package/opencode-ai",
        }

    return _cached("opencode", _builder)
