from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BROKER_STATE_RELATIVE_PATH = Path(".agent_control/provider_auth_broker.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def proxy_runtime_root() -> Path | None:
    for variable in ("SYNTELOS_PROXY_RUNTIME_ROOT", "FLUXIO_PROXY_RUNTIME_ROOT"):
        value = str(os.environ.get(variable) or "").strip()
        if value:
            return Path(value).expanduser()
    default = Path("/volume1/Saclay/runtime")
    return default if default.exists() else None


def codex_auth_directory(runtime_root: Path | None = None) -> Path | None:
    root = runtime_root or proxy_runtime_root()
    return root / "home" / ".cli-proxy-api" if root else None


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    )
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def broker_codex_oauth(
    tokens: dict[str, Any],
    identity: dict[str, str],
    *,
    workspace_root: Path,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    auth_dir = codex_auth_directory(runtime_root)
    if auth_dir is None:
        raise RuntimeError(
            "The OpenAI auth broker is not configured. Set "
            "SYNTELOS_PROXY_RUNTIME_ROOT or FLUXIO_PROXY_RUNTIME_ROOT."
        )
    account_id = str(identity.get("accountId") or "").strip()
    email = str(identity.get("email") or "").strip()
    profile_hint = account_id or email or "default"
    safe_hint = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in profile_hint
    ).strip("-")[:80] or "default"
    auth_path = auth_dir / f"codex-{safe_hint}.json"
    auth_payload = {
        "id_token": str(tokens.get("id_token") or ""),
        "access_token": str(tokens.get("access") or ""),
        "refresh_token": str(tokens.get("refresh") or ""),
        "account_id": account_id,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "email": email,
        "type": "codex",
        "expired": "",
    }
    if not auth_payload["access_token"] or not auth_payload["refresh_token"]:
        raise ValueError("Codex OAuth broker requires access and refresh tokens.")
    _atomic_private_json(auth_path, auth_payload)

    state_path = workspace_root.resolve() / BROKER_STATE_RELATIVE_PATH
    _atomic_private_json(
        state_path,
        {
            "schema": "neyvia.provider_auth_broker.v1",
            "updatedAt": _utc_now(),
            "providers": {
                "openai": {
                    "owner": "cliproxyapi",
                    "authMode": "codex-oauth",
                    "connected": True,
                    "accountId": account_id or None,
                    "email": email or None,
                    "consumers": [
                        "codex",
                        "grok-build-compatible-route",
                        "hermes",
                        "kimi-code",
                        "openclaw",
                        "opencode",
                    ],
                }
            },
        },
    )
    return {
        "provider": "openai",
        "owner": "cliproxyapi",
        "authMode": "codex-oauth",
        "authStorePath": str(auth_path),
        "statePath": str(state_path),
    }


def codex_broker_status(runtime_root: Path | None = None) -> dict[str, Any]:
    auth_dir = codex_auth_directory(runtime_root)
    if auth_dir is None:
        return {"configured": False, "authenticated": False, "owner": None}
    auth_files = sorted(auth_dir.glob("*.json")) if auth_dir.exists() else []
    authenticated = False
    for path in auth_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and str(payload.get("type") or "").lower() == "codex"
            and bool(payload.get("refresh_token"))
        ):
            authenticated = True
            break
    return {
        "configured": True,
        "authenticated": authenticated,
        "owner": "cliproxyapi",
        "authDirectory": str(auth_dir),
        "authFileCount": len(auth_files),
    }
