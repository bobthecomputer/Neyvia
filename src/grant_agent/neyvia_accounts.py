"""Neyvia accounts: who can sign in to this PC's Neyvia, and where they are signed in.

The first account in ``.agent_control/neyvia_web_admin.json`` is the PC owner. Everyone can
change their own name and password and end their own sessions; only the owner adds people,
resets their passwords, removes them or signs them out. When the account comes from the
environment (``SYNTELOS_ACCOUNT_PASSWORD``) the list is read-only here.

Two commands go through ``POST /api/backend`` (and the desktop bridge, which signs in as the
owner): ``accounts_list_command`` and ``accounts_update_command`` with an ``op``. Passwords
are stored only as PBKDF2 records; nothing here writes one in clear text.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any

ACCOUNT_COMMANDS = frozenset({"accounts_list_command", "accounts_update_command"})

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
DISPLAY_NAME_MAX = 60
PASSWORD_MIN = 8
PASSWORD_MAX = 256
# The desktop bridge signs in for one call and signs out again; its sessions are not devices.
_BRIDGE_AGENT = "python-urllib"

_write_lock = threading.Lock()


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def public(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "error": self.message, "message": self.message}


# -- devices -----------------------------------------------------------------------------


def _describe_device(user_agent: str) -> str:
    """A short name for a browser, like "Chrome on Windows" or "Safari on iPhone"."""
    agent = str(user_agent or "")
    if not agent:
        return "Unknown device"
    lower = agent.lower()
    if lower.startswith(_BRIDGE_AGENT):
        return "Neyvia desktop app"
    if "iphone" in lower:
        system = "iPhone"
    elif "ipad" in lower:
        system = "iPad"
    elif "android" in lower:
        system = "Android"
    elif "windows" in lower:
        system = "Windows"
    elif "mac os" in lower or "macintosh" in lower:
        system = "Mac"
    elif "linux" in lower or "x11" in lower:
        system = "Linux"
    else:
        system = ""
    if "edg/" in lower or "edga/" in lower or "edgios/" in lower:
        browser = "Edge"
    elif "firefox/" in lower or "fxios/" in lower:
        browser = "Firefox"
    elif "opr/" in lower:
        browser = "Opera"
    elif "chrome/" in lower or "crios/" in lower:
        browser = "Chrome"
    elif "safari/" in lower:
        browser = "Safari"
    else:
        browser = "Browser"
    return f"{browser} on {system}" if system else browser


def describe_device(user_agent: str) -> str:
    result = _describe_device(user_agent)
    from .proofs_d_neyvia import account_device
    account_device(user_agent, result)
    return result


def request_device(handler: Any) -> tuple[str, str]:
    """The user agent and client address of a request, through a local proxy such as Tailscale serve."""
    headers = getattr(handler, "headers", None)
    agent = str(headers.get("User-Agent") or "") if headers is not None else ""
    address = str((getattr(handler, "client_address", None) or ("",))[0] or "")
    if headers is not None and address in {"127.0.0.1", "::1"}:
        forwarded = str(headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        if forwarded:
            address = forwarded
    return agent, address


# -- the account file ----------------------------------------------------------------------


def _key(username: object) -> str:
    return str(username or "").strip().casefold()


def environment_managed() -> bool:
    import os

    return bool(os.environ.get("SYNTELOS_ACCOUNT_PASSWORD") or os.environ.get("GRAND_AGENT_ADMIN_PASSWORD"))


def _clean_display_name(value: object, fallback: str) -> str:
    name = " ".join(str(value or "").split())
    if len(name) > DISPLAY_NAME_MAX:
        raise AccountError("invalid_name", f"A name can be at most {DISPLAY_NAME_MAX} characters.")
    return name or fallback


def _check_password(password: object) -> str:
    value = str(password or "")
    if len(value) < PASSWORD_MIN:
        raise AccountError("weak_password", f"Use at least {PASSWORD_MIN} characters.")
    if len(value) > PASSWORD_MAX:
        raise AccountError("invalid_password", f"A password can be at most {PASSWORD_MAX} characters.")
    if any(char in value for char in "\r\n\x00"):
        raise AccountError("invalid_password", "A password can't contain line breaks.")
    return value


def _save(backend: Any, users: list[dict[str, Any]]) -> None:
    from .web_backend import ADMIN_CONFIG_RELATIVE_PATH, _normalise_admin_payload, _write_private_json

    payload = dict(backend.admin_config)
    payload["users"] = users
    payload = _normalise_admin_payload(payload)
    _write_private_json(backend.root / ADMIN_CONFIG_RELATIVE_PATH, payload)
    backend.admin_config = payload


def _find(users: list[dict[str, Any]], username: object) -> dict[str, Any] | None:
    wanted = _key(username)
    return next((user for user in users if _key(user.get("username")) == wanted), None)


def session_identity(backend: Any, username: str) -> str | None:
    """What a session of ``username`` is bound to: the account's name, role and credential."""
    import hashlib
    import os

    user = _find(backend.admin_users, username)
    if user is None:
        return None
    if environment_managed():
        # Environment accounts get a fresh salt at every start; bind to the secret itself.
        secret = os.environ.get("SYNTELOS_ACCOUNT_PASSWORD") or os.environ.get("GRAND_AGENT_ADMIN_PASSWORD") or ""
        credential: object = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    else:
        credential = user.get("password")
    return json.dumps(
        {"username": _key(user.get("username")), "role": str(user.get("role") or ""), "credential": credential},
        sort_keys=True,
        default=str,
    )


# -- commands ------------------------------------------------------------------------------


def _public_user(user: dict[str, Any], *, owner: str, me: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    username = str(user.get("username") or "")
    mine = [row for row in sessions if _key(row.get("username")) == _key(username)]
    return {
        "username": username,
        "displayName": str(user.get("displayName") or username),
        "role": "owner" if _key(username) == owner else "member",
        "createdAt": str(user.get("createdAt") or ""),
        "isYou": _key(username) == me,
        "devices": len(mine),
        "lastSeenAt": mine[0]["lastSeenAt"] if mine else None,
    }


def _devices(sessions: list[dict[str, Any]], current: str) -> list[dict[str, Any]]:
    return [
        {**row, "device": describe_device(str(row.get("userAgent") or "")), "current": row.get("id") == current}
        for row in sessions
        if not str(row.get("userAgent") or "").lower().startswith(_BRIDGE_AGENT)
    ]


def list_accounts(backend: Any, session: dict[str, Any]) -> dict[str, Any]:
    users = backend.admin_users
    owner = _key(backend.username)
    me = _key(session.get("username"))
    current = str(session.get("sessionId") or "")
    sessions = _devices(backend.web_auth_sessions.sessions(), current)
    you = _find(users, me)
    if you is None:
        raise AccountError("unknown_account", "This account no longer exists. Sign in again.", 401)
    result: dict[str, Any] = {
        "you": {
            **_public_user(you, owner=owner, me=me, sessions=sessions),
            "sessions": [row for row in sessions if _key(row.get("username")) == me],
        },
        "isOwner": me == owner,
        "managed": "environment" if environment_managed() else "local",
        "passwordMin": PASSWORD_MIN,
    }
    if me == owner:
        result["people"] = [_public_user(user, owner=owner, me=me, sessions=sessions) for user in users]
    return result


def update_account(backend: Any, session: dict[str, Any], payload: dict[str, Any],
                   device: tuple[str, str] = ("", "")) -> dict[str, Any]:
    """Run one change. Returns the new account list, plus ``_token`` when this device needs a new session."""
    from .web_backend import _hash_record, _utc_now, _verify_password

    op = str(payload.get("op") or "")
    owner = _key(backend.username)
    me = _key(session.get("username"))
    is_owner = me == owner
    current = str(session.get("sessionId") or "")
    sessions = backend.web_auth_sessions
    target_name = str(payload.get("username") or "").strip() or me
    target_key = _key(target_name)

    def require_owner() -> None:
        if not is_owner:
            raise AccountError("owner_required", "Only the PC owner can manage other people's accounts.", 403)

    if op in {"signOut", "signOutOthers", "signOutAll"}:
        if op == "signOut":
            session_id = str(payload.get("sessionId") or "")
            if not session_id:
                raise AccountError("invalid_request", "Say which device to sign out.")
            if session_id == current:
                raise AccountError("current_session", "Use Sign out to leave this device.")
            if is_owner:
                ended = sessions.revoke_where(session=session_id)
            else:
                ended = sessions.revoke_where(session=session_id, username=me)
        elif op == "signOutOthers":
            ended = sessions.revoke_where(username=me, keep=current or None)
        else:
            require_owner()
            if target_key == me:
                ended = sessions.revoke_where(username=me, keep=current or None)
            else:
                ended = sessions.revoke_where(username=target_name)
        return {**list_accounts(backend, session), "ended": ended}

    if environment_managed():
        raise AccountError("environment_managed",
                           "This PC's account is set by its environment. Change it there, then restart Neyvia.", 409)

    token: str | None = None
    with _write_lock:
        users = [dict(user) for user in backend.admin_users]
        if op == "create":
            require_owner()
            username = str(payload.get("username") or "").strip()
            if not USERNAME_PATTERN.match(username):
                raise AccountError("invalid_username",
                                   "Use 1 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.")
            if _find(users, username) is not None:
                raise AccountError("username_taken", f"There is already an account called {username}.", 409)
            users.append({
                "username": username,
                "displayName": _clean_display_name(payload.get("displayName"), username),
                "role": "account",
                "password": _hash_record(_check_password(payload.get("password"))),
                "source": "account_screen",
                "createdAt": _utc_now(),
            })
            _save(backend, users)
        elif op == "profile":
            user = _find(users, target_name)
            if user is None:
                raise AccountError("unknown_account", f"There is no account called {target_name}.", 404)
            if target_key != me:
                require_owner()
            user["displayName"] = _clean_display_name(payload.get("displayName"), str(user.get("username") or ""))
            _save(backend, users)
        elif op == "password":
            user = _find(users, me)
            if user is None:
                raise AccountError("unknown_account", "This account no longer exists. Sign in again.", 401)
            record = user.get("password")
            if not isinstance(record, dict) or not _verify_password(str(payload.get("currentPassword") or ""), record):
                raise AccountError("wrong_password", "Your current password isn't right.", 403)
            user["password"] = _hash_record(_check_password(payload.get("newPassword")))
            _save(backend, users)
            # The new password ends every session of this account; this device keeps going.
            sessions.revoke_where(username=me)
            if current:
                token = backend._create_session_for_user(user, str(user.get("username") or ""), device=device)
        elif op == "reset":
            require_owner()
            if target_key == me:
                raise AccountError("use_password", "Change your own password with your current one.")
            user = _find(users, target_name)
            if user is None:
                raise AccountError("unknown_account", f"There is no account called {target_name}.", 404)
            user["password"] = _hash_record(_check_password(payload.get("newPassword")))
            _save(backend, users)
            sessions.revoke_where(username=target_name)
        elif op == "remove":
            require_owner()
            if target_key == owner:
                raise AccountError("owner_account", "The PC owner's account can't be removed.")
            if _find(users, target_name) is None:
                raise AccountError("unknown_account", f"There is no account called {target_name}.", 404)
            _save(backend, [user for user in users if _key(user.get("username")) != target_key])
            sessions.revoke_where(username=target_name)
        else:
            raise AccountError("unknown_op", f"Unknown account change: {op or '(none)'}")

    if token:
        refreshed = backend.web_auth_sessions.lookup(token) or session
        result = list_accounts(backend, refreshed)
        result["_token"] = token
        return result
    return list_accounts(backend, session)


def handle_account_command(backend: Any, session: dict[str, Any], command: str, payload: Any,
                           device: tuple[str, str] = ("", "")) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    if command == "accounts_list_command":
        return list_accounts(backend, session)
    if command == "accounts_update_command":
        return update_account(backend, session, body, device)
    raise AccountError("unknown_command", f"Unknown accounts command: {command}", 404)


def respond_account_command(handler: Any, backend: Any, command: str, payload: Any) -> None:
    """Answer ``POST /api/backend`` for an accounts command; a new session cookie rides along when needed."""
    from .web_backend import _apply_security_headers, _json_response, _send_cors_headers, _write_response_body

    session = backend.authenticated_session(handler) or {}
    try:
        result = handle_account_command(backend, session, command, payload, request_device(handler))
    except AccountError as exc:
        _json_response(handler, exc.status, exc.public())
        return
    except Exception:  # noqa: BLE001 - never leak a traceback to a client
        _json_response(handler, 500, {"ok": False, "code": "accounts_failed", "error": "The account change failed."})
        return
    token = result.pop("_token", None)
    if not token:
        _json_response(handler, 200, {"ok": True, "data": result})
        return
    body = json.dumps({"ok": True, "data": result}, separators=(",", ":")).encode("utf-8")
    handler.send_response(200)
    backend._set_session_cookie(handler, token)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _apply_security_headers(handler)
    _send_cors_headers(handler)
    handler.end_headers()
    _write_response_body(handler, body)
