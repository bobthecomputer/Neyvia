from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
import base64
import importlib.util
from dataclasses import asdict
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from .models import DeliveryReceipt, MissionEvent, utc_now_iso
from .proofs_b_desktop import checked
from .durability import atomic_write_text

RECEIPTS_FILENAME = "delivery_receipts.jsonl"
MAX_RECEIPTS_TO_KEEP = 500
WEB_PUSH_SUBSCRIPTIONS_FILENAME = "web_push_subscriptions.jsonl"
WEB_PUSH_VAPID_FILENAME = "web_push_vapid.json"
NTFY_SETTINGS_FILENAME = "ntfy_settings.json"


def delivery_receipts_path(root: str | Path) -> Path:
    path = Path(root) / ".agent_control" / RECEIPTS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _receipts_path(root: str | Path) -> Path:
    return delivery_receipts_path(root)


def _resolve_receipts_path(path_or_root: str | Path) -> Path:
    candidate = Path(path_or_root)
    if candidate.suffix == ".jsonl" or candidate.name == RECEIPTS_FILENAME:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    return delivery_receipts_path(candidate)


def web_push_subscriptions_path(root: str | Path) -> Path:
    path = Path(root) / ".agent_control" / WEB_PUSH_SUBSCRIPTIONS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def web_push_vapid_path(root: str | Path) -> Path:
    path = Path(root) / ".agent_control" / WEB_PUSH_VAPID_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ntfy_settings_path(root: str | Path) -> Path:
    path = Path(root) / ".agent_control" / NTFY_SETTINGS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ntfy_status(root: str | Path | None = None) -> dict[str, Any]:
    settings = _load_ntfy_settings(root)
    server_url = _ntfy_server_url(settings)
    topic = _ntfy_topic(settings)
    token = _ntfy_token(settings)
    configured = bool(topic)
    return {
        "schema": "fluxio.ntfy_status.v1",
        "configured": configured,
        "senderConfigured": configured,
        "serverUrl": server_url,
        "topic": topic,
        "tokenConfigured": bool(token),
        "channel": "ntfy",
        "setupPath": str(ntfy_settings_path(root)) if root else "",
        "nextAction": (
            "ntfy can send phone/tablet mission notifications."
            if configured
            else "Set FLUXIO_NTFY_TOPIC or .agent_control/ntfy_settings.json before ntfy phone push can send."
        ),
    }


def web_push_status(root: str | Path | None = None) -> dict[str, Any]:
    vapid_config = _load_web_push_vapid_config(root) if root else {}
    public_key = _web_push_public_key(root, vapid_config=vapid_config)
    private_key = _web_push_private_key(root, vapid_config=vapid_config)
    dependency_available = _web_push_dependency_available()
    subscription_count = len(load_web_push_subscriptions(root)) if root else 0
    keys_configured = bool(public_key and private_key)
    sender_configured = bool(keys_configured and dependency_available)
    return {
        "schema": "fluxio.web_push_status.v1",
        "configured": bool(public_key),
        "senderConfigured": sender_configured,
        "dependencyAvailable": dependency_available,
        "privateKeyConfigured": bool(private_key),
        "localKeyConfigured": bool(vapid_config.get("publicKey") and vapid_config.get("privateKeyPem")),
        "configuredSource": _web_push_key_source(root, vapid_config=vapid_config),
        "setupPath": str(web_push_vapid_path(root)) if root else "",
        "publicKey": public_key,
        "subscriptionCount": subscription_count,
        "channel": "web_push",
        "nextAction": (
            "Closed-tab Web Push can send mission notifications."
            if sender_configured and subscription_count > 0
            else "Register this browser from the notification stack before closed-tab push can send."
            if sender_configured
            else "Install pywebpush and set FLUXIO_WEB_PUSH_PUBLIC_KEY plus FLUXIO_WEB_PUSH_PRIVATE_KEY before closed-tab push can send."
            if keys_configured and not dependency_available
            else "Set FLUXIO_WEB_PUSH_PRIVATE_KEY before closed-tab push can send."
            if public_key
            else "Provision VAPID keys from the notification stack or set FLUXIO_WEB_PUSH_PUBLIC_KEY and FLUXIO_WEB_PUSH_PRIVATE_KEY."
        ),
    }


def _load_ntfy_settings(root: str | Path | None) -> dict[str, Any]:
    if not root:
        return {}
    try:
        payload = json.loads(ntfy_settings_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ntfy_server_url(settings: dict[str, Any] | None = None) -> str:
    value = (
        os.environ.get("FLUXIO_NTFY_SERVER_URL")
        or os.environ.get("NTFY_SERVER_URL")
        or str((settings or {}).get("serverUrl") or (settings or {}).get("server_url") or "")
        or "https://ntfy.sh"
    ).strip()
    return value.rstrip("/")


def _ntfy_topic(settings: dict[str, Any] | None = None) -> str:
    return (
        os.environ.get("FLUXIO_NTFY_TOPIC")
        or os.environ.get("NTFY_TOPIC")
        or str((settings or {}).get("topic") or "")
        or ""
    ).strip().strip("/")


def _ntfy_token(settings: dict[str, Any] | None = None) -> str:
    return (
        os.environ.get("FLUXIO_NTFY_TOKEN")
        or os.environ.get("NTFY_TOKEN")
        or str((settings or {}).get("token") or "")
        or ""
    ).strip()


def record_web_push_subscription(
    root: str | Path,
    *,
    subscription: dict[str, Any],
    user_agent: str = "",
    status: str = "subscribed",
) -> dict[str, Any]:
    endpoint = str(subscription.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("Web Push subscription endpoint is required.")
    row = {
        "schema": "fluxio.web_push_subscription.v1",
        "subscriptionId": f"push_{uuid.uuid4().hex[:12]}",
        "endpoint": endpoint,
        "subscription": subscription,
        "userAgent": user_agent,
        "status": status,
        "createdAt": utc_now_iso(),
        "channel": "web_push",
    }
    with web_push_subscriptions_path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return {
        **row,
        "subscription": {
            "endpoint": endpoint,
            "keysPresent": bool((subscription.get("keys") or {}).get("p256dh"))
            and bool((subscription.get("keys") or {}).get("auth")),
        },
    }


def load_web_push_subscriptions(root: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    path = Path(root) / ".agent_control" / WEB_PUSH_SUBSCRIPTIONS_FILENAME
    if not path.exists():
        return []
    latest_by_endpoint: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        subscription = row.get("subscription") if isinstance(row.get("subscription"), dict) else {}
        endpoint = str(row.get("endpoint") or subscription.get("endpoint") or "").strip()
        if endpoint:
            # The newest state wins. This lets a browser unsubscribe or rotate
            # its endpoint without leaving an older active row to receive pushes.
            latest_by_endpoint[endpoint] = row
    rows = [row for row in latest_by_endpoint.values() if row.get("status") == "subscribed"]
    return rows[-max(0, int(limit)):] if limit > 0 else rows


def _web_push_dependency_available() -> bool:
    return importlib.util.find_spec("pywebpush") is not None


def _load_web_push_vapid_config(root: str | Path | None) -> dict[str, Any]:
    if not root:
        return {}
    try:
        payload = json.loads(web_push_vapid_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _web_push_key_source(root: str | Path | None = None, *, vapid_config: dict[str, Any] | None = None) -> str:
    if os.environ.get("FLUXIO_WEB_PUSH_PUBLIC_KEY") or os.environ.get("VAPID_PUBLIC_KEY"):
        return "environment"
    if root and (vapid_config if vapid_config is not None else _load_web_push_vapid_config(root)).get("publicKey"):
        return "local_agent_control"
    return "missing"


def _web_push_private_key(root: str | Path | None = None, *, vapid_config: dict[str, Any] | None = None) -> str:
    config = vapid_config if vapid_config is not None else _load_web_push_vapid_config(root)
    return (
        os.environ.get("FLUXIO_WEB_PUSH_PRIVATE_KEY")
        or os.environ.get("VAPID_PRIVATE_KEY")
        or str(config.get("privateKeyPem") or config.get("privateKey") or "")
        or ""
    ).strip()


def _web_push_public_key(root: str | Path | None = None, *, vapid_config: dict[str, Any] | None = None) -> str:
    config = vapid_config if vapid_config is not None else _load_web_push_vapid_config(root)
    return (
        os.environ.get("FLUXIO_WEB_PUSH_PUBLIC_KEY")
        or os.environ.get("VAPID_PUBLIC_KEY")
        or str(config.get("publicKey") or "")
        or ""
    ).strip()


def generate_web_push_vapid_config(root: str | Path, *, subject: str = "") -> dict[str, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Install cryptography before generating Web Push VAPID keys.") from exc

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
    path = web_push_vapid_path(root)
    payload = {
        "schema": "fluxio.web_push_vapid_config.v1",
        "createdAt": utc_now_iso(),
        "channel": "web_push",
        "subject": subject.strip() or os.environ.get("FLUXIO_WEB_PUSH_SUBJECT", "mailto:fluxio@localhost"),
        "publicKey": public_key,
        "privateKeyPem": private_pem,
        "warning": "This file contains a Web Push private key. Keep it under .agent_control and out of Git.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    status = web_push_status(root)
    return {
        "schema": "fluxio.web_push_vapid_provisioning.v1",
        "ok": True,
        "path": str(path),
        "publicKey": public_key,
        "privateKeyConfigured": True,
        "senderConfigured": bool(status.get("senderConfigured")),
        "dependencyAvailable": bool(status.get("dependencyAvailable")),
        "nextAction": status.get("nextAction", ""),
    }


def send_web_push_delivery_receipts(
    *,
    root: str | Path,
    mission_id: str,
    title: str,
    body: str,
    target_url: str = "/control?mode=agent&surface=agent",
    event_kind: str = "notification.web_push_test",
    subscriptions: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    idempotency_key: str = "",
) -> list[DeliveryReceipt]:
    rows = subscriptions if subscriptions is not None else load_web_push_subscriptions(root)
    idempotency_key = str(idempotency_key or "").strip()
    prior_receipts = load_delivery_receipts(root, limit=MAX_RECEIPTS_TO_KEEP) if idempotency_key else []
    already_delivered = {
        (item.idempotency_key, item.destination)
        for item in prior_receipts
        if item.channel == "web_push" and item.status == "delivered"
    }
    if not rows:
        return [
            _append_receipt(
                root,
                DeliveryReceipt(
                    receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                    mission_id=mission_id,
                    channel="web_push",
                    destination="",
                    event_kind=event_kind,
                    event_message=body,
                    sent_at=utc_now_iso(),
                    status="skipped",
                    error_message="no_web_push_subscriptions",
                ),
            )
        ]

    public_key = _web_push_public_key(root)
    private_key = _web_push_private_key(root)
    dependency_available = _web_push_dependency_available()
    if not public_key or not private_key or not dependency_available:
        reason = (
            "web_push_sender_dependency_missing"
            if public_key and private_key and not dependency_available
            else "web_push_vapid_keys_not_configured"
        )
        return [
            _append_receipt(
                root,
                DeliveryReceipt(
                    receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                    mission_id=mission_id,
                    channel="web_push",
                    destination=str(row.get("endpoint") or ""),
                    event_kind=event_kind,
                    event_message=body,
                    sent_at=utc_now_iso(),
                    status="skipped",
                    error_message=reason,
                ),
            )
            for row in rows
        ]

    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "url": target_url,
            "missionId": mission_id,
            "tag": f"fluxio:{event_kind}:{mission_id}",
        }
    )
    receipts: list[DeliveryReceipt] = []
    for row in rows:
        subscription = row.get("subscription") if isinstance(row.get("subscription"), dict) else {}
        endpoint = str(row.get("endpoint") or subscription.get("endpoint") or "")
        if idempotency_key and (idempotency_key, endpoint) in already_delivered:
            continue
        receipt = _append_receipt(
            root,
            DeliveryReceipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                mission_id=mission_id,
                channel="web_push",
                destination=endpoint,
                event_kind=event_kind,
                event_message=body,
                sent_at=utc_now_iso(),
                status="pending",
                idempotency_key=idempotency_key,
            ),
        )
        if dry_run:
            receipt.status = "delivered"
            receipt.delivery_url = f"dry_run://web_push/{receipt.receipt_id}"
            receipts.append(_update_receipt(root, receipt))
            continue
        try:
            from pywebpush import WebPushException, webpush

            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": os.environ.get("FLUXIO_WEB_PUSH_SUBJECT", "mailto:fluxio@localhost")},
                timeout=2,
            )
            receipt.status = "delivered"
            receipt.delivery_url = "web-push://sent"
        except Exception as exc:  # noqa: BLE001
            receipt.status = "error"
            receipt.error_message = str(exc)
        receipts.append(_update_receipt(root, receipt))
    return receipts


def _read_telegram_token_with_source(root: str | Path | None = None) -> tuple[str, str]:
    token = (
        os.environ.get("SYNTELOS_TELEGRAM_BOT_TOKEN")
        or os.environ.get("FLUXIO_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
    )
    if token:
        return token.strip(), "fluxio_env"
    if root:
        try:
            candidate = Path(root) / ".agent_control" / "telegram_bot_token.txt"
            if candidate.exists():
                token = candidate.read_text(encoding="utf-8").strip()
                if token:
                    return token, "fluxio_agent_control"
        except OSError:
            pass
    for candidate in (
        Path.home() / ".agent_control" / "telegram_bot_token.txt",
        Path.home() / ".syntelos" / "telegram_bot_token.txt",
    ):
        try:
            if candidate.exists():
                token = candidate.read_text(encoding="utf-8").strip()
                if token:
                    return token, "user_agent_control"
        except OSError:
            continue
    token = _read_openclaw_telegram_token()
    return (token, "openclaw_telegram_token") if token else ("", "missing")


def _read_telegram_token(root: str | Path | None = None) -> str:
    token, _source = _read_telegram_token_with_source(root)
    return token


def _read_openclaw_telegram_token() -> str:
    env_path = Path.home() / ".openclaw" / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "TELEGRAM_BOT_TOKEN":
            continue
        token = value.strip().strip('"').strip("'")
        if token:
            return token
    return ""


def _read_telegram_destination(root: str | Path) -> str:
    for key in ("FLUXIO_TELEGRAM_DESTINATION", "TELEGRAM_CHAT_ID", "TELEGRAM_DESTINATION"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    settings_path = Path(root) / ".agent_control" / "telegram_settings.json"
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("destination") or "").strip()


@checked("delivery.append")
def _append_receipt(path_or_root: str | Path, receipt: DeliveryReceipt) -> DeliveryReceipt:
    path = _resolve_receipts_path(path_or_root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    lines.append(json.dumps(asdict(receipt), ensure_ascii=True))
    if len(lines) > MAX_RECEIPTS_TO_KEEP:
        lines = lines[-MAX_RECEIPTS_TO_KEEP:]
    atomic_write_text(path, "\n".join(lines) + "\n")
    return receipt


@checked("delivery.tail-update")
def _update_receipt(root: str | Path, receipt: DeliveryReceipt) -> DeliveryReceipt:
    path = delivery_receipts_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    encoded = json.dumps(asdict(receipt), ensure_ascii=True)
    if lines:
        lines[-1] = encoded
    else:
        lines.append(encoded)
    if len(lines) > MAX_RECEIPTS_TO_KEEP:
        lines = lines[-MAX_RECEIPTS_TO_KEEP:]
    atomic_write_text(path, "\n".join(lines) + "\n")
    return receipt


@checked("delivery.update")
def _update_last_receipt(path_or_root: str | Path, receipt: DeliveryReceipt) -> DeliveryReceipt:
    """Update a receipt by id in place; append when missing, while preserving retention."""
    path = _resolve_receipts_path(path_or_root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    encoded = json.dumps(asdict(receipt), ensure_ascii=True)
    target_id = str(receipt.receipt_id or "").strip()
    updated = False
    next_lines: list[str] = []
    for line in lines:
        if not line.strip():
            next_lines.append(line)
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            next_lines.append(line)
            continue
        if isinstance(payload, dict) and target_id and str(payload.get("receipt_id") or "") == target_id:
            next_lines.append(encoded)
            updated = True
        else:
            next_lines.append(line)
    if not updated:
        next_lines.append(encoded)
    if len(next_lines) > MAX_RECEIPTS_TO_KEEP:
        next_lines = next_lines[-MAX_RECEIPTS_TO_KEEP:]
    atomic_write_text(path, "\n".join(next_lines) + "\n")
    return receipt


def load_delivery_receipts(root: str | Path, limit: int = 50) -> list[DeliveryReceipt]:
    path = Path(root) / ".agent_control" / RECEIPTS_FILENAME
    if not path.exists():
        return []
    rows: list[DeliveryReceipt] = []
    for line in _tail_text_lines(path, limit):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            allowed = DeliveryReceipt.__dataclass_fields__.keys()
            rows.append(DeliveryReceipt(**{key: value for key, value in payload.items() if key in allowed}))
        except (TypeError, json.JSONDecodeError):
            continue
    return rows


@checked("delivery.observe")
def load_receipts(
    root: str | Path,
    *,
    limit: int = 50,
    mission_id: str = "",
) -> list[DeliveryReceipt]:
    """Load receipts newest-last, optionally filtered by mission before applying limit."""
    path = delivery_receipts_path(root)
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    target_mission = str(mission_id or "").strip()
    rows: list[DeliveryReceipt] = []
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if target_mission and str(payload.get("mission_id") or "") != target_mission:
            continue
        allowed = DeliveryReceipt.__dataclass_fields__.keys()
        try:
            rows.append(DeliveryReceipt(**{key: value for key, value in payload.items() if key in allowed}))
        except TypeError:
            continue
    if limit > 0:
        rows = rows[-limit:]
    return rows


def _tail_text_lines(path: Path, limit: int, *, chunk_size: int = 8192) -> list[str]:
    if limit <= 0:
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            offset = size
            chunks: list[bytes] = []
            line_count = 0
            while offset > 0 and line_count <= limit:
                read_size = min(chunk_size, offset)
                offset -= read_size
                handle.seek(offset)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                line_count += chunk.count(b"\n")
    except OSError:
        return []
    data = b"".join(reversed(chunks))
    return data.decode("utf-8", errors="replace").splitlines()[-limit:]


@checked("delivery.ack")
def acknowledge_delivery_receipt(root: str | Path, receipt_id: str) -> bool:
    target = str(receipt_id or "").strip()
    if not target:
        return False
    path = delivery_receipts_path(root)
    if not path.exists():
        return False
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    next_lines: list[str] = []
    matched = False
    for raw_line in raw_lines:
        if not raw_line.strip():
            next_lines.append(raw_line)
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            next_lines.append(raw_line)
            continue
        if not isinstance(row, dict):
            next_lines.append(raw_line)
            continue
        if str(row.get("receipt_id") or "") == target:
            current_status = str(row.get("status") or "").strip().lower()
            if current_status == "error":
                # Do not clobber terminal delivery errors with browser ack.
                next_lines.append(raw_line)
                continue
            row["status"] = "acknowledged"
            row["acknowledged_at"] = utc_now_iso()
            next_lines.append(json.dumps(row, ensure_ascii=True))
            matched = True
        else:
            next_lines.append(raw_line)
    if not matched:
        return False
    atomic_write_text(path, "\n".join(next_lines) + "\n")
    return True


def delivery_receipt_from_event(
    event: MissionEvent,
    *,
    channel: str,
    destination: str,
    transport_provider: str = "",
    producer: str = "",
) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
        mission_id=event.mission_id,
        channel=channel,
        destination=destination,
        event_kind=event.kind,
        event_message=event.message,
        sent_at=utc_now_iso(),
        status="pending",
        origin_runtime=str(
            event.metadata.get("originRuntime")
            or event.metadata.get("runtimeId")
            or event.metadata.get("runtime")
            or ""
        ),
        origin_provider=str(
            event.metadata.get("originProvider")
            or event.metadata.get("provider")
            or event.metadata.get("modelProvider")
            or ""
        ),
        origin_model=str(event.metadata.get("originModel") or event.metadata.get("model") or ""),
        transport_provider=transport_provider,
        producer=producer or str(event.metadata.get("producer") or event.kind.split(".", 1)[0] or ""),
        mission_title=str(event.metadata.get("missionTitle") or event.metadata.get("title") or ""),
        source_session_id=str(event.metadata.get("sourceSessionId") or event.metadata.get("sessionId") or ""),
        evidence_path=str(event.metadata.get("evidencePath") or ""),
        screenshot_path=str(event.metadata.get("screenshotPath") or ""),
    )


def record_delivery_receipt(
    root: str | Path,
    *,
    mission_id: str,
    channel: str,
    destination: str,
    event_kind: str,
    event_message: str,
    status: str,
    error_message: str = "",
    delivery_url: str = "",
    origin_runtime: str = "",
    origin_provider: str = "",
    origin_model: str = "",
    transport_provider: str = "",
    producer: str = "",
    mission_title: str = "",
    source_session_id: str = "",
    evidence_path: str = "",
    screenshot_path: str = "",
    idempotency_key: str = "",
) -> DeliveryReceipt:
    return _append_receipt(
        root,
        DeliveryReceipt(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            mission_id=mission_id,
            channel=channel,
            destination=destination,
            event_kind=event_kind,
            event_message=event_message,
            sent_at=utc_now_iso(),
            status=status,
            error_message=error_message,
            delivery_url=delivery_url,
            origin_runtime=origin_runtime,
            origin_provider=origin_provider,
            origin_model=origin_model,
            transport_provider=transport_provider or channel,
            producer=producer,
            mission_title=mission_title,
            source_session_id=source_session_id,
            evidence_path=evidence_path,
            screenshot_path=screenshot_path,
            idempotency_key=idempotency_key,
        ),
    )


def send_chat_completion_web_push(
    root: str | Path,
    *,
    turn_id: str,
    session_id: str = "",
    runtime: str = "",
    status: str = "completed",
) -> dict[str, Any]:
    """Send a privacy-preserving phone alert for a terminal chat run."""
    normalized_status = str(status or "completed").strip().lower()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id or normalized_status in {"cancelled", "canceled", "stopped"}:
        return {"status": "not_applicable", "deliveredCount": 0}
    sender = web_push_status(root)
    if not sender.get("senderConfigured") or not int(sender.get("subscriptionCount") or 0):
        return {
            "status": "not_ready",
            "senderConfigured": bool(sender.get("senderConfigured")),
            "subscriptionCount": int(sender.get("subscriptionCount") or 0),
            "nextAction": sender.get("nextAction") or "Register a phone subscription before sending push notifications.",
        }
    event_kind = "chat.turn.finished"
    idempotency_key = f"chat.turn.finished:{normalized_turn_id}"
    prior = load_delivery_receipts(root, limit=MAX_RECEIPTS_TO_KEEP)
    if any(
        item.channel == "web_push"
        and item.idempotency_key == idempotency_key
        and item.status == "delivered"
        for item in prior
    ):
        return {
            "status": "already_delivered",
            "senderConfigured": True,
            "subscriptionCount": int(sender.get("subscriptionCount") or 0),
            "deliveredCount": 0,
            "errorCount": 0,
            "skippedCount": 0,
        }
    title = "Neyvia run finished" if normalized_status in {"completed", "success", "succeeded"} else "Neyvia run needs attention"
    body = "Your response is ready to view on your phone." if title == "Neyvia run finished" else "A run on your computer ended before completion. Open Neyvia to review it."
    query = {"surface": "agent", "mode": "agent"}
    if session_id:
        query["chatSessionId"] = str(session_id)
    target_url = "/control?" + urlencode(query)
    receipts = send_web_push_delivery_receipts(
        root=root,
        mission_id=normalized_turn_id,
        title=title,
        body=body,
        target_url=target_url,
        event_kind=event_kind,
        idempotency_key=idempotency_key,
    )
    return {
        "status": "delivered" if any(item.status == "delivered" for item in receipts) else "failed_or_skipped",
        "senderConfigured": True,
        "subscriptionCount": int(sender.get("subscriptionCount") or 0),
        "deliveredCount": sum(item.status == "delivered" for item in receipts),
        "errorCount": sum(item.status == "error" for item in receipts),
        "skippedCount": sum(item.status == "skipped" for item in receipts),
    }


@checked("delivery.browser")
def record_browser_delivery_receipt(
    event: MissionEvent,
    *,
    root: str | Path,
) -> DeliveryReceipt:
    receipt = delivery_receipt_from_event(
        event,
        channel="browser",
        destination="control-room",
        transport_provider="browser",
        producer="browser_progress",
    )
    receipt.status = "delivered"
    return _append_receipt(root, receipt)


@checked("delivery.message")
def _format_telegram_message(event: MissionEvent) -> str:
    mission_id = escape(str(event.mission_id or ""))
    message = escape(str(event.message or ""))
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    note = escape(str(metadata.get("note") or ""))
    lines = [
        f"<b>Neyvia approval</b>",
        f"Mission: <code>{mission_id}</code>",
        message,
    ]
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _send_telegram_message_once(token: str, destination: str, text: str) -> tuple[str, str | None]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {
                "chat_id": destination,
                "text": text,
                "parse_mode": "HTML",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if payload.get("ok"):
            return "delivered", None
        return "error", str(payload.get("description") or "unknown_telegram_error")
    except urllib.error.HTTPError as exc:
        return "error", f"telegram_http_{exc.code}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)


def _send_telegram_message(token: str, destination: str, text: str) -> tuple[str, str | None]:
    """Send one Telegram message with retry only for transient transport failures."""
    last_error = ""
    for attempt in range(3):
        status, error = _send_telegram_message_once(token, destination, text)
        if status == "delivered":
            return "delivered", None
        last_error = error or "unknown_telegram_error"
        code = 0
        if last_error.startswith("telegram_http_"):
            try:
                code = int(last_error.split(":", 1)[0].rsplit("_", 1)[-1])
            except ValueError:
                code = 0
        if code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= 2:
            return "error", last_error
        time.sleep(2**attempt)
    return "error", last_error or "unknown_telegram_error"


def _read_token(root: str | Path | None = None) -> str:
    """Compatibility alias used by tests and older callers."""
    return _read_telegram_token(root)


def _format_ntfy_body(event: MissionEvent) -> str:
    lines = [
        event.message.strip() or "Neyvia mission update.",
        "",
        f"Mission: {event.mission_id}",
        f"Event: {event.kind}",
    ]
    for key, value in list(event.metadata.items())[:5]:
        if key.lower() in {"destination", "token", "authorization"}:
            continue
        lines.append(f"{key}: {str(value)[:160]}")
    return "\n".join(line for line in lines if line is not None)


def send_ntfy_delivery_receipt(
    event: MissionEvent,
    *,
    root: str | Path,
    topic: str = "",
    title: str = "",
    priority: str = "default",
    tags: str = "fluxio",
    click_url: str = "",
    dry_run: bool = False,
) -> DeliveryReceipt:
    settings = _load_ntfy_settings(root)
    server_url = _ntfy_server_url(settings)
    resolved_topic = str(topic or _ntfy_topic(settings)).strip().strip("/")
    destination = f"{server_url}/{resolved_topic}" if resolved_topic else server_url
    receipt = _append_receipt(
        root,
        delivery_receipt_from_event(event, channel="ntfy", destination=destination),
    )
    if not resolved_topic:
        receipt.status = "skipped"
        receipt.error_message = "ntfy_topic_not_configured"
        return _update_receipt(root, receipt)
    if not urlparse(server_url).scheme:
        receipt.status = "error"
        receipt.error_message = "ntfy_server_url_invalid"
        return _update_receipt(root, receipt)
    if dry_run:
        receipt.status = "delivered"
        receipt.delivery_url = f"dry_run://ntfy/{resolved_topic}"
        return _update_receipt(root, receipt)

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "X-Title": title.strip() or "Neyvia mission update",
        "X-Priority": priority.strip() or "default",
        "X-Tags": tags.strip() or "fluxio",
    }
    if click_url.strip():
        headers["X-Click"] = click_url.strip()
    token = _ntfy_token(settings)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{server_url}/{quote(resolved_topic, safe='')}",
        data=_format_ntfy_body(event).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            last_error = ""
            break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            receipt.retry_count = attempt + 1
            if attempt < 2:
                time.sleep(2**attempt)
    if last_error:
        receipt.status = "error"
        receipt.error_message = last_error
    else:
        receipt.status = "delivered"
        receipt.delivery_url = f"{server_url}/***/json"
    return _update_receipt(root, receipt)


def _watchdog_event_from_report(report: dict[str, Any]) -> MissionEvent:
    problem_report = report.get("problemReport") if isinstance(report.get("problemReport"), dict) else {}
    first_problem = (
        problem_report.get("firstProblem")
        if isinstance(problem_report.get("firstProblem"), dict)
        else {}
    )
    problem_count = int(problem_report.get("problemCount") or 0)
    status = str(problem_report.get("status") or ("open" if problem_count else "clear"))
    mission_id = str(first_problem.get("missionId") or "mission_watchdog")
    if problem_count:
        title = str(first_problem.get("title") or "Watchdog problem")
        first_step = str(first_problem.get("firstStep") or problem_report.get("nextAction") or "")
        message = f"{problem_count} watchdog problem(s): {title}. First step: {first_step}"
    else:
        message = str(
            problem_report.get("nextAction")
            or report.get("nextAction")
            or "No watchdog problems found. Keep the external loop active."
        )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return MissionEvent(
        mission_id=mission_id,
        kind="watchdog.problem_report",
        message=message[:900],
        metadata={
            "watchdogStatus": status,
            "problemCount": problem_count,
            "bad": summary.get("bad", 0),
            "warn": summary.get("warn", 0),
            "firstStep": str(first_problem.get("firstStep") or problem_report.get("nextAction") or "")[:240],
        },
    )


def send_telegram_delivery_receipt(
    event: MissionEvent,
    *,
    destination: str,
    root: str | Path,
    dry_run: bool = False,
) -> DeliveryReceipt:
    token, token_source = _read_telegram_token_with_source(root)
    if not token:
        # Tests may patch `_read_token` as the compatibility token source.
        token = _read_token(root)
        token_source = "compat_token" if token else token_source
    transport_provider = (
        "telegram_via_openclaw_token"
        if token_source == "openclaw_telegram_token"
        else f"telegram_via_{token_source}"
        if token_source and token_source != "missing"
        else "telegram"
    )
    event.metadata.setdefault("transportProvider", transport_provider)
    receipt = _append_receipt(
        root,
        delivery_receipt_from_event(
            event,
            channel="telegram",
            destination=destination,
            transport_provider=transport_provider,
            producer=str(event.metadata.get("producer") or "mission_runtime"),
        ),
    )
    if dry_run:
        receipt.status = "delivered"
        receipt.delivery_url = f"dry_run://telegram/{destination}"
        return _update_receipt(root, receipt)

    if not token:
        receipt.status = "error"
        receipt.error_message = "telegram_bot_token_not_configured"
        return _update_receipt(root, receipt)

    text = _format_telegram_message(event)
    last_error = ""
    retry_count = 0
    for attempt in range(3):
        status, error = _send_telegram_message_once(token, destination, text)
        if status == "delivered":
            receipt.retry_count = retry_count
            receipt.status = "delivered"
            receipt.delivery_url = "https://api.telegram.org/bot***/sendMessage"
            receipt.error_message = ""
            return _update_receipt(root, receipt)
        last_error = error or "unknown_telegram_error"
        retry_count = attempt + 1
        code = 0
        if last_error.startswith("telegram_http_"):
            try:
                code = int(last_error.split(":", 1)[0].rsplit("_", 1)[-1])
            except ValueError:
                code = 0
        if code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= 2:
            break
        time.sleep(2**attempt)
    receipt.retry_count = retry_count
    receipt.status = "error"
    receipt.error_message = last_error or "unknown_telegram_error"
    return _update_receipt(root, receipt)


def send_watchdog_delivery_receipt(
    *,
    root: str | Path,
    report: dict[str, Any],
    destination: str = "",
    dry_run: bool = False,
    include_clear: bool = False,
) -> DeliveryReceipt:
    problem_report = report.get("problemReport") if isinstance(report.get("problemReport"), dict) else {}
    problem_count = int(problem_report.get("problemCount") or 0)
    if problem_count <= 0 and not include_clear:
        return _append_receipt(
            root,
            DeliveryReceipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                mission_id="mission_watchdog",
                channel="telegram",
                destination=destination or _read_telegram_destination(root),
                event_kind="watchdog.problem_report",
                event_message="Watchdog clear notification skipped.",
                sent_at=utc_now_iso(),
                status="skipped",
                error_message="watchdog_clear_notification_disabled",
            ),
        )
    resolved_destination = str(destination or _read_telegram_destination(root)).strip()
    if not resolved_destination:
        return _append_receipt(
            root,
            DeliveryReceipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                mission_id=str(
                    (problem_report.get("firstProblem") or {}).get("missionId")
                    if isinstance(problem_report.get("firstProblem"), dict)
                    else "mission_watchdog"
                )
                or "mission_watchdog",
                channel="telegram",
                destination="",
                event_kind="watchdog.problem_report",
                event_message="Watchdog notification could not be sent; no Telegram destination is configured.",
                sent_at=utc_now_iso(),
                status="skipped",
                error_message="telegram_destination_not_configured",
            ),
        )
    return send_telegram_delivery_receipt(
        _watchdog_event_from_report(report),
        destination=resolved_destination,
        root=root,
        dry_run=dry_run,
    )


def send_watchdog_ntfy_delivery_receipt(
    *,
    root: str | Path,
    report: dict[str, Any],
    topic: str = "",
    dry_run: bool = False,
    include_clear: bool = False,
) -> DeliveryReceipt:
    problem_report = report.get("problemReport") if isinstance(report.get("problemReport"), dict) else {}
    problem_count = int(problem_report.get("problemCount") or 0)
    if problem_count <= 0 and not include_clear:
        status = ntfy_status(root)
        return _append_receipt(
            root,
            DeliveryReceipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                mission_id="mission_watchdog",
                channel="ntfy",
                destination=str(status.get("serverUrl") or ""),
                event_kind="watchdog.problem_report",
                event_message="Watchdog clear notification skipped.",
                sent_at=utc_now_iso(),
                status="skipped",
                error_message="watchdog_clear_notification_disabled",
            ),
        )
    event = _watchdog_event_from_report(report)
    return send_ntfy_delivery_receipt(
        event,
        root=root,
        topic=topic,
        title="Neyvia watchdog",
        priority="high" if problem_count else "default",
        tags="fluxio,watchdog",
        click_url="/control?mode=builder&surface=builder",
        dry_run=dry_run,
    )


@checked("delivery.skipped")
def send_approval_escalation_receipt(
    *,
    mission_id: str,
    prompt: str,
    risk_level: str,
    escalation_policy: dict,
    root: str | Path,
    dry_run: bool = False,
) -> DeliveryReceipt:
    if not isinstance(escalation_policy, dict):
        escalation_policy = {}
    channel = str(escalation_policy.get("channel") or "").lower()
    destination = str(escalation_policy.get("destination") or "").strip()
    enabled = bool(escalation_policy.get("enabled"))
    if enabled and channel == "telegram" and destination:
        event = MissionEvent(
            mission_id=mission_id,
            kind="approval.required",
            message=prompt,
            metadata={"risk_level": risk_level, "channel": channel},
        )
        return send_telegram_delivery_receipt(
            event,
            destination=destination,
            root=root,
            dry_run=dry_run,
        )

    reason = "escalation_disabled" if not enabled else "no_telegram_destination"
    return _append_receipt(
        root,
        DeliveryReceipt(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            mission_id=mission_id,
            channel=channel or "none",
            destination=destination,
            event_kind="approval.required",
            event_message=prompt,
            sent_at=utc_now_iso(),
            status="skipped",
            error_message=reason,
        ),
    )
