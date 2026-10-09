"""Provider and model discovery for routes delegated to OpenCode.

This catalog is separate from Neyvia Native's narrower transport catalog. It
uses Models.dev's public metadata and the installed OpenCode CLI's local model
list, while keeping credential values and provider options out of the result.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .runtimes.base import runtime_subprocess_env, runtime_which

MODELS_DEV_URL = "https://models.dev/api.json"
PROVIDER_CATALOG_SCHEMA = "neyvia.provider_model_catalog.v1"
MAX_MODELS_DEV_BYTES = 16 * 1024 * 1024
CATALOG_CACHE_RELATIVE_PATH = Path(".agent_control") / "provider_model_catalog.modelsdev.json"
OPENCODE_ROUTES_CACHE_RELATIVE_PATH = Path(".agent_control") / "provider_model_catalog.opencode.json"
OPENCODE_AUTH_STORE_RELATIVE_PATH = Path(".local") / "share" / "opencode" / "auth.json"
_MODELS_DEV_TTL_SECONDS = 7 * 24 * 60 * 60
_OPENCODE_ROUTES_TTL_SECONDS = 5 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _models_dev_payload(root: Path, *, refresh: bool) -> tuple[dict[str, Any], str, int | None]:
    cache_path = root / CATALOG_CACHE_RELATIVE_PATH
    cached: dict[str, Any] | None = None
    fetched_at: datetime | None = None
    try:
        cached_envelope = json.loads(cache_path.read_text(encoding="utf-8"))
        candidate = cached_envelope.get("catalog")
        if isinstance(candidate, dict):
            cached = candidate
            fetched_at = _parse_timestamp(cached_envelope.get("fetchedAt"))
    except (OSError, ValueError, TypeError):
        pass

    cache_age = (
        max(0, int((_utc_now() - fetched_at).total_seconds()))
        if fetched_at
        else None
    )
    # Refreshes are explicit after an initial bootstrap; a stale but usable
    # catalog remains available offline until the user asks to update it.
    should_fetch = refresh or cached is None
    if should_fetch:
        request = urllib.request.Request(
            MODELS_DEV_URL,
            headers={"Accept": "application/json", "User-Agent": "Neyvia provider catalog"},
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read(MAX_MODELS_DEV_BYTES + 1)
            if len(body) > MAX_MODELS_DEV_BYTES:
                raise ValueError("Models.dev catalog exceeded the configured size limit")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Models.dev catalog had an unexpected format")
            fetched_at = _utc_now()
            cache_age = 0
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temp = cache_path.with_suffix(cache_path.suffix + ".tmp")
                temp.write_text(
                    json.dumps({"fetchedAt": fetched_at.isoformat(), "catalog": payload}, separators=(",", ":")),
                    encoding="utf-8",
                )
                os.replace(temp, cache_path)
            except OSError:
                # An unwritable workspace must not prevent an online lookup.
                pass
            return payload, "models.dev", cache_age
        except (OSError, ValueError, UnicodeError, TimeoutError):
            if cached is not None:
                return cached, "models.dev-cache", cache_age
            return {}, "unavailable", None
    return cached or {}, "models.dev-cache", cache_age


def _opencode_command(root: Path) -> str | None:
    # Runtime discovery honors OpenCode's managed and user PATHs without a shell.
    return runtime_which("opencode", root)


def _parse_verbose_models(text: str) -> list[dict[str, Any]]:
    """Extract only safe model metadata from `opencode models --verbose`.

    OpenCode emits a canonical route ID followed by its model object. We parse
    each object but project an allowlist so custom headers/options never escape.
    """
    rows: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            cursor = start + 1
            continue
        cursor = end
        if not isinstance(value, dict):
            continue
        model_id = str(value.get("id") or "").strip()
        provider_id = str(value.get("providerID") or value.get("providerId") or "").strip()
        if not model_id or not provider_id:
            continue
        caps = value.get("capabilities") if isinstance(value.get("capabilities"), dict) else {}
        input_modalities = caps.get("input") if isinstance(caps.get("input"), dict) else {}
        limit = value.get("limit") if isinstance(value.get("limit"), dict) else {}
        variants = value.get("variants") if isinstance(value.get("variants"), dict) else {}
        rows.append(
            {
                "providerId": provider_id,
                "id": model_id,
                "name": str(value.get("name") or model_id),
                "reasoning": bool(caps.get("reasoning")),
                "toolCall": bool(caps.get("toolcall")),
                "attachment": bool(caps.get("attachment")),
                "inputModalities": [name for name, enabled in input_modalities.items() if enabled is True],
                "contextLimit": _positive_int(limit.get("context")),
                "outputLimit": _positive_int(limit.get("output")),
                "variantIds": sorted(str(key) for key in variants),
            }
        )
    return rows


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _installed_opencode_models(root: Path, *, refresh: bool) -> tuple[list[dict[str, Any]], str]:
    cache_path = root / OPENCODE_ROUTES_CACHE_RELATIVE_PATH
    cached: list[dict[str, Any]] = []
    try:
        envelope = json.loads(cache_path.read_text(encoding="utf-8"))
        rows = envelope.get("models")
        fetched_at = _parse_timestamp(envelope.get("fetchedAt"))
        if isinstance(rows, list) and fetched_at and (_utc_now() - fetched_at).total_seconds() <= _OPENCODE_ROUTES_TTL_SECONDS:
            cached = [row for row in rows if isinstance(row, dict)]
    except (OSError, ValueError, TypeError):
        pass
    if cached and not refresh:
        return cached, "opencode-cli-cache"
    command = _opencode_command(root)
    if not command:
        return cached, "not-installed" if not cached else "opencode-cli-cache"
    from .opencode_bridge import _popen_args

    try:
        launch_command = command
        if os.name == "nt":
            shim = Path(command)
            package_roots = [shim.parent / "node_modules", shim.parent.parent]
            # NeyviaCLI uses a stable shim that calls a versioned npm package
            # under its own packages directory. Resolve only its quoted .cmd
            # target, then prefer the package's native executable.
            if shim.suffix.lower() in {".cmd", ".bat"}:
                try:
                    shim_text = shim.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    shim_text = ""
                match = re.search(r'(?im)^\s*call\s+"([^"\r\n]+\.(?:cmd|bat))"', shim_text)
                if match:
                    target = Path(match.group(1))
                    if target.is_absolute() and target.is_file():
                        package_roots.append(target.parent.parent)
            native_exe = next(
                (
                    package_root / "opencode-ai" / "bin" / "opencode.exe"
                    for package_root in package_roots
                    if (package_root / "opencode-ai" / "bin" / "opencode.exe").is_file()
                ),
                None,
            )
            if native_exe:
                launch_command = str(native_exe)
            elif shim.suffix.lower() == ".ps1" and shim.with_suffix(".cmd").is_file():
                launch_command = str(shim.with_suffix(".cmd"))
        completed = subprocess.run(
            _popen_args([launch_command, "models", "--verbose"]),
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=18,
            check=False,
            env=runtime_subprocess_env(root),
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return cached, "query-failed" if not cached else "opencode-cli-cache"
    if completed.returncode:
        # Do not echo CLI diagnostics: they can include provider-specific paths.
        return cached, "query-failed" if not cached else "opencode-cli-cache"
    text = completed.stdout or ""
    rows = _parse_verbose_models(text)
    # Be conservative: the compact format gives real routes even if a future
    # OpenCode release changes its verbose serialization.
    if not rows:
        for line in text.splitlines():
            route_id = line.strip()
            if "/" not in route_id or route_id.startswith("{"):
                continue
            provider_id, model_id = route_id.split("/", 1)
            if provider_id and model_id:
                rows.append({"providerId": provider_id, "id": model_id, "name": model_id})
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temp.write_text(
            json.dumps({"fetchedAt": _utc_now().isoformat(), "models": rows}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp, cache_path)
    except OSError:
        pass
    return rows, "opencode-cli"


def _provider_auth_presence(root: Path, providers: dict[str, Any]) -> dict[str, bool]:
    """Check presence only. Credential contents are never returned or logged."""
    configured: set[str] = set()
    auth_paths = [Path.home() / ".local" / "share" / "opencode" / "auth.json"]
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if appdata:
        auth_paths.append(Path(appdata) / "opencode" / "auth.json")
    for path in auth_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(value, dict):
            configured.update(str(key).lower() for key in value)

    result: dict[str, bool] = {}
    for provider_id, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        env_names = provider.get("env") if isinstance(provider.get("env"), list) else []
        has_environment_auth = any(
            str(name).strip() and bool(os.environ.get(str(name).strip()))
            for name in env_names
        )
        result[str(provider_id).lower()] = (
            str(provider_id).lower() in configured or has_environment_auth
        )
    return result


def _model_from_models_dev(
    provider_id: str, model_id: str, raw: dict[str, Any], *, route_listed: bool, credentials_present: bool
) -> dict[str, Any]:
    limits = raw.get("limit") if isinstance(raw.get("limit"), dict) else {}
    modalities = raw.get("modalities") if isinstance(raw.get("modalities"), dict) else {}
    input_modalities = modalities.get("input") if isinstance(modalities.get("input"), list) else []
    return {
        "id": model_id,
        "name": str(raw.get("name") or model_id),
        "description": str(raw.get("description") or ""),
        "family": str(raw.get("family") or ""),
        "reasoning": bool(raw.get("reasoning")),
        "toolCall": bool(raw.get("tool_call")),
        "attachment": bool(raw.get("attachment")),
        "inputModalities": [str(item) for item in input_modalities],
        "contextLimit": _positive_int(limits.get("context")),
        "outputLimit": _positive_int(limits.get("output")),
        "releaseDate": str(raw.get("release_date") or ""),
        "routeId": f"{provider_id}/{model_id}",
        "runtimeId": "opencode",
        "configured": route_listed,
        "routeListed": route_listed,
        "credentialsPresent": credentials_present,
    }


def normalize_provider_catalog(
    models_dev: dict[str, Any],
    installed_models: list[dict[str, Any]],
    *,
    provider_auth: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build a display-safe provider catalog from public metadata and local IDs."""
    provider_auth = provider_auth or {}
    configured_routes: dict[str, set[str]] = {}
    for item in installed_models:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("providerId") or "").strip().lower()
        model_id = str(item.get("id") or "").strip()
        if provider_id and model_id:
            configured_routes.setdefault(provider_id, set()).add(model_id)

    providers: list[dict[str, Any]] = []
    model_count = 0
    for provider_id, raw_provider in models_dev.items():
        if not isinstance(raw_provider, dict):
            continue
        provider_id = str(raw_provider.get("id") or provider_id).strip()
        if not provider_id:
            continue
        local_id = provider_id.lower()
        route_ids = configured_routes.get(local_id, set())
        is_authenticated = bool(provider_auth.get(local_id))
        raw_models = raw_provider.get("models") if isinstance(raw_provider.get("models"), dict) else {}
        models: list[dict[str, Any]] = []
        for model_key, raw_model in raw_models.items():
            if not isinstance(raw_model, dict):
                continue
            model_id = str(raw_model.get("id") or model_key).strip()
            if not model_id:
                continue
            models.append(
                _model_from_models_dev(
                    local_id,
                    model_id,
                    raw_model,
                    route_listed=model_id in route_ids,
                    credentials_present=is_authenticated,
                )
            )
        models.sort(key=lambda row: (row["name"].casefold(), row["id"].casefold()))
        configured_count = sum(1 for row in models if row["routeListed"])
        model_count += len(models)
        env_names = raw_provider.get("env") if isinstance(raw_provider.get("env"), list) else []
        providers.append(
            {
                "id": local_id,
                "name": str(raw_provider.get("name") or provider_id),
                "description": str(raw_provider.get("description") or ""),
                "docUrl": str(raw_provider.get("doc") or ""),
                "sdk": str(raw_provider.get("npm") or ""),
                "setupEnvNames": [str(name) for name in env_names if str(name).strip()],
                "configured": bool(configured_count or is_authenticated),
                "credentialsPresent": is_authenticated,
                "routesListed": bool(configured_count),
                "configuredModelCount": configured_count,
                "catalogModelCount": len(models),
                "setupStatus": "route-listed" if configured_count else ("credentials-present" if is_authenticated else "setup-needed"),
                "runtimeId": "opencode",
                "models": models,
            }
        )
    providers.sort(key=lambda row: (not row["configured"], row["name"].casefold()))
    return {
        "schema": PROVIDER_CATALOG_SCHEMA,
        "providerCount": len(providers),
        "modelCount": model_count,
        "providers": providers,
        "models": [model for provider in providers for model in provider["models"]],
        "configuredRouteCount": sum(len(routes) for routes in configured_routes.values()),
        "configuredRouteIds": sorted(
            f"{provider_id}/{model_id}"
            for provider_id, ids in configured_routes.items()
            for model_id in ids
        ),
    }


def build_provider_catalog(root: Path, *, refresh: bool = False) -> dict[str, Any]:
    """Discover available OpenCode provider choices without putting work on chat.

    `refresh=True` is intended for an explicit Settings/catalog refresh action.
    Ordinary calls use the local Models.dev cache and installed CLI metadata.
    """
    root = root.resolve()
    models_dev, source, age_seconds = _models_dev_payload(root, refresh=refresh)
    installed_models, installed_status = _installed_opencode_models(root, refresh=refresh)
    auth_presence = _provider_auth_presence(root, models_dev)
    catalog = normalize_provider_catalog(models_dev, installed_models, provider_auth=auth_presence)
    # The picker reads provider.models. Avoid duplicating thousands of complete
    # records across the desktop IPC/controller boundary.
    catalog.pop("models", None)
    catalog.update(
        {
            "generatedAt": _utc_now().isoformat(),
            "source": source,
            "sourceUrl": MODELS_DEV_URL,
            "sourceAgeSeconds": age_seconds,
            "sourceStale": age_seconds is None or age_seconds > _MODELS_DEV_TTL_SECONDS,
            "openCodeCliStatus": installed_status,
        }
    )
    return catalog


def _auth_store_path() -> Path:
    data_home = str(os.environ.get("XDG_DATA_HOME") or "").strip()
    base = Path(data_home).expanduser() if data_home else Path.home()
    return (base / "opencode" / "auth.json") if data_home else (base / OPENCODE_AUTH_STORE_RELATIVE_PATH)


def _acquire_auth_store_lock(path: Path, *, timeout_seconds: float = 10.0):
    """Return a locked file handle, using the OS's advisory file lock."""
    handle = path.with_suffix(path.suffix + ".lock").open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except (OSError, BlockingIOError):
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("OpenCode auth store is busy; try again shortly.")
            time.sleep(0.05)


def _release_auth_store_lock(handle: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def save_opencode_provider_api_key(
    provider_id: str,
    api_key: str,
    *,
    workspace_root: Path,
    replace_existing: bool = False,
    auth_path: Path | None = None,
) -> dict[str, Any]:
    """Store an API key in OpenCode's auth store without exposing it in output.

    Callers must pass `replace_existing=True` only after the user has confirmed
    replacing this provider's saved OpenCode credential.
    """
    provider = str(provider_id or "").strip().lower()
    secret = str(api_key or "").strip()
    if not provider or len(provider) > 100 or any(not (char.isalnum() or char in "._-") for char in provider):
        raise ValueError("Choose a provider from the provider catalog.")
    if not secret or len(secret) > 16_384 or "\n" in secret or "\r" in secret:
        raise ValueError("Enter a valid API key.")
    workspace = Path(workspace_root).resolve()
    known_catalog, _, _ = _models_dev_payload(workspace, refresh=False)
    if not any(
        str(row.get("id") or key).strip().lower() == provider
        for key, row in known_catalog.items()
        if isinstance(row, dict)
    ):
        raise ValueError("Choose a provider from the loaded provider catalog.")
    path = Path(auth_path).expanduser() if auth_path else _auth_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _acquire_auth_store_lock(path)
    try:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            existing = {}
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("OpenCode's auth store could not be read; Neyvia preserved it.") from exc
        if not isinstance(existing, dict):
            raise RuntimeError("OpenCode's auth store has an unsupported format; Neyvia preserved it.")
        previous = existing.get(provider)
        if isinstance(previous, dict) and not replace_existing:
            return {
                "ok": False,
                "error": "credential_replace_confirmation_required",
                "providerId": provider,
                "credentialType": str(previous.get("type") or "unknown"),
                "message": "This provider already has a saved OpenCode credential. Confirm replacement to continue.",
            }
        candidate = dict(existing)
        candidate[provider] = {"type": "api", "key": secret}
        fd, temporary_name = tempfile.mkstemp(prefix="opencode-auth-", suffix=".tmp", dir=str(path.parent))
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(candidate, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            os.replace(temporary_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        _release_auth_store_lock(lock)
    return {"ok": True, "providerId": provider, "credentialType": "api", "credentialsPresent": True}
