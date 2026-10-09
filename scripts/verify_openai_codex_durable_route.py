#!/usr/bin/env python3
"""Prove one real OpenAI/Codex turn through Neyvia's durable backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PASSWORD_FILE = ROOT / ".agent_control" / "neyvia_admin_password.txt"
DEFAULT_OUT_DIR = ROOT / ".agent_control" / "proofs" / "openai-codex-durable-route"
DEFAULT_PROMPT = (
    "Reply with exactly NEYVIA_CODEX_ROUTE_OK followed by one short sentence "
    "confirming this turn reached the durable Neyvia conversation."
)


class ProofError(RuntimeError):
    """Raised when the live proof cannot establish the expected contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
            return {"status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:500]}
        raise ProofError(f"{path} returned HTTP {exc.code}: {body.get('error') or 'request failed'}") from exc
    except urllib.error.URLError as exc:
        raise ProofError(f"{path} could not reach the Neyvia backend: {exc.reason}") from exc


def _backend(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    command: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    response = _post(
        opener,
        base_url,
        "/api/backend",
        {"command": command, "payload": payload},
        timeout=timeout,
    )
    body = response.get("body")
    if not isinstance(body, dict):
        raise ProofError(f"{command} returned an invalid response body")
    if body.get("ok") is False or body.get("error"):
        raise ProofError(f"{command} failed: {body.get('error') or 'unknown backend error'}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ProofError(f"{command} returned no structured data")
    return data


def _load_local_account(path: Path, default_username: str) -> tuple[str, str]:
    if not path.is_file():
        raise ProofError(f"Admin password file was not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    fields: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() in {"username", "password"}:
            fields[key.strip().lower()] = value.strip()
    username = fields.get("username") or default_username
    password = fields.get("password") or (
        lines[0].strip() if len(lines) == 1 else ""
    )
    if not password:
        raise ProofError(f"Admin password file has no readable Password field: {path}")
    return username, password


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "reply": str(result.get("reply") or "").strip(),
        "runtime": result.get("runtime"),
        "sessionId": result.get("sessionId"),
        "route": result.get("route"),
        "status": result.get("status") or ("completed" if result.get("reply") else "failed"),
        "error": result.get("error"),
        "elapsedMs": result.get("elapsedMs"),
        "toolTimeline": result.get("toolTimeline") or [],
        "filesChanged": result.get("filesChanged") or [],
        "conversationPersistence": result.get("conversationPersistence"),
        "readOnly": result.get("readOnly"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and persist one real gpt-5.6-sol turn through Neyvia."
    )
    parser.add_argument("--url", default="http://127.0.0.1:47880")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password-file", default=str(DEFAULT_PASSWORD_FILE))
    parser.add_argument(
        "--runtime",
        choices=("codex", "openclaw", "hermes"),
        default="codex",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    created_at = _utc_now()
    run_key = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    conversation_id = f"proof-openai-codex-{run_key}"
    user_turn_id = f"{conversation_id}-user"
    assistant_turn_id = f"{conversation_id}-assistant"
    session_id = f"neyvia-openai-codex-{run_key}"

    receipt: dict[str, Any] = {
        "schema": "neyvia.openai_codex_durable_route_proof.v1",
        "createdAt": created_at,
        "baseUrl": args.url,
        "requested": {
            "runtime": args.runtime,
            "provider": "openai-codex",
            "model": args.model,
            "effort": args.effort,
            "readOnly": True,
        },
        "checks": {},
        "passed": False,
    }
    exit_code = 1
    opener: urllib.request.OpenerDirector | None = None

    try:
        username, password = _load_local_account(
            Path(args.password_file).expanduser().resolve(),
            args.username,
        )
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        login = _post(
            opener,
            args.url,
            "/api/auth/login",
            {"username": username, "password": password},
            timeout=min(args.timeout, 30.0),
        )
        login_body = login.get("body")
        login_ok = bool(isinstance(login_body, dict) and login_body.get("ok"))
        if not login_ok:
            raise ProofError("Local Neyvia authentication was rejected")
        receipt["checks"]["localAuthentication"] = True

        payload = {
            "runtime": args.runtime,
            "runtimeId": args.runtime,
            "message": args.prompt,
            "prompt": args.prompt,
            "sessionId": session_id,
            "workspaceId": ROOT.name,
            "workspacePath": str(ROOT),
            "requestStartedAt": created_at,
            "conversationId": conversation_id,
            "userTurnId": user_turn_id,
            "assistantTurnId": assistant_turn_id,
            "route": {
                "provider": "openai-codex",
                "model": args.model,
                "effort": args.effort,
                "role": "verifier",
            },
        }
        first = _backend(
            opener,
            args.url,
            "send_agent_chat_command",
            payload,
            timeout=args.timeout,
        )
        compact_first = _compact_result(first)
        reply = str(compact_first.get("reply") or "")
        persistence = compact_first.get("conversationPersistence")
        route = compact_first.get("route") if isinstance(compact_first.get("route"), dict) else {}
        first_ok = bool(
            "NEYVIA_CODEX_ROUTE_OK" in reply
            and compact_first.get("runtime") == args.runtime
            and route.get("provider") == "openai-codex"
            and route.get("model") == args.model
            and isinstance(persistence, dict)
            and persistence.get("status") == "persisted"
            and persistence.get("storage") == "sqlite"
            and not compact_first.get("error")
        )
        receipt["firstTurn"] = compact_first
        receipt["checks"]["realModelReply"] = "NEYVIA_CODEX_ROUTE_OK" in reply
        receipt["checks"]["requestedRoutePreserved"] = bool(
            route.get("provider") == "openai-codex" and route.get("model") == args.model
        )
        receipt["checks"]["sqlitePersistence"] = bool(
            isinstance(persistence, dict)
            and persistence.get("status") == "persisted"
            and persistence.get("storage") == "sqlite"
        )
        if not first_ok:
            raise ProofError(
                str(compact_first.get("error") or "The live turn did not satisfy the requested route and persistence contract")
            )

        conversation = _backend(
            opener,
            args.url,
            "get_neyvia_conversation_command",
            {"conversationId": conversation_id, "includeTurns": True},
            timeout=min(args.timeout, 30.0),
        )
        turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
        persisted_roles = [str(turn.get("role") or "") for turn in turns if isinstance(turn, dict)]
        receipt["conversation"] = {
            "conversationId": conversation.get("conversationId"),
            "revision": conversation.get("revision"),
            "turnCount": len(turns),
            "roles": persisted_roles,
        }
        receipt["checks"]["conversationReadable"] = bool(
            conversation.get("conversationId") == conversation_id
            and "user" in persisted_roles
            and "assistant" in persisted_roles
        )

        replay = _backend(
            opener,
            args.url,
            "send_agent_chat_command",
            payload,
            timeout=min(args.timeout, 30.0),
        )
        replay_persistence = replay.get("conversationPersistence")
        replay_ok = bool(
            replay.get("reply") == first.get("reply")
            and isinstance(replay_persistence, dict)
            and replay_persistence.get("status") == "replayed"
            and replay_persistence.get("turnId") == assistant_turn_id
        )
        receipt["replay"] = {
            "replyDigest": hashlib.sha256(str(replay.get("reply") or "").encode("utf-8")).hexdigest(),
            "conversationPersistence": replay_persistence,
        }
        receipt["checks"]["idempotentReplay"] = replay_ok
        if not all(receipt["checks"].values()) or not replay_ok:
            raise ProofError("The persisted turn could not be replayed idempotently")
        exit_code = 0
    except ProofError as exc:
        receipt["error"] = str(exc)
    finally:
        if opener is not None and receipt.get("firstTurn"):
            try:
                settled = _backend(
                    opener,
                    args.url,
                    "settle_neyvia_conversation_command",
                    {
                        "conversationId": conversation_id,
                        "settlementReason": (
                            "Durable OpenAI/Codex route proof completed."
                            if exit_code == 0
                            else "Durable OpenAI/Codex route proof recorded a terminal failure."
                        ),
                        "settledBy": "openai-codex-route-verifier",
                    },
                    timeout=min(args.timeout, 30.0),
                )
                receipt["settlement"] = {
                    "conversationId": settled.get("conversationId"),
                    "attentionState": settled.get("attentionState"),
                    "lifecycleState": settled.get("lifecycleState"),
                }
                receipt["checks"]["conversationSettled"] = bool(
                    settled.get("conversationId") == conversation_id
                    and settled.get("attentionState") == "settled"
                    and settled.get("lifecycleState") == "settled"
                )
            except ProofError as exc:
                receipt["settlementError"] = str(exc)
                receipt["checks"]["conversationSettled"] = False
                if exit_code == 0:
                    receipt["error"] = str(exc)
                    exit_code = 1
        receipt["passed"] = bool(
            exit_code == 0
            and receipt["checks"]
            and all(receipt["checks"].values())
        )
        receipt["finishedAt"] = _utc_now()
        out_dir = Path(args.out_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = out_dir / f"{run_key}.json"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        (out_dir / "latest.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        summary = {
            "passed": receipt["passed"],
            "runtime": args.runtime,
            "model": args.model,
            "checks": receipt["checks"],
            "receiptPath": str(receipt_path),
            "error": receipt.get("error"),
        }
        print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
