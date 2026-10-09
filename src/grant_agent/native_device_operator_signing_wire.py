"""Opaque signing-wire package for paired-device operator approvals.

The signed-authority store intentionally keeps the operator private key outside
NEYVIA. This module closes the next interoperability gap: external signers sign
the exact server-prepared UTF-8 bytes rather than reserializing a Python dict in
Swift/Kotlin/JavaScript and hoping the byte representation matches.

The request is not itself execution authority. Only a valid Ed25519 signature
over ``signingBytesBase64`` that still matches the current durable approval can
be submitted to ``OperatorAuthorizedDeviceCommandStore.decide_approval``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from datetime import datetime
from typing import Any

from .native_device_operator_authority import (
    OPERATOR_DECISION_PAYLOAD_SCHEMA,
    OPERATOR_DECISION_SCHEMA,
    OperatorAuthorizedDeviceCommandStore,
    _json_bytes,
)


SIGNING_REQUEST_SCHEMA = "neyvia.device-command-operator-signing-request/v1"
SIGNING_RULE = "sign-decoded-signingBytesBase64-exactly"
_MAX_SIGNING_BYTES = 32 * 1024
_REQUEST_FIELDS = {
    "schema",
    "algorithm",
    "keyId",
    "approvalId",
    "signingRule",
    "signingBytesBase64",
    "signingBytesSha256",
    "review",
    "privateKeyRequiredByNeyvia",
}


def _strict_json_value(value: Any, path: str = "$") -> None:
    """Reject values outside interoperable JSON/I-JSON primitive space.

    JSON-RPC peers implemented in different languages should never be expected
    to reproduce Python-only NaN/Infinity encodings. Large integers beyond the
    exact IEEE-754 safe-integer range are also rejected from this signing wire;
    callers that need larger exact values should send them as strings.
    """

    if value is None or isinstance(value, bool) or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > 9_007_199_254_740_991:
            raise ValueError(
                f"{path}: integers outside the IEEE-754 safe range must be encoded as strings"
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: NaN and Infinity are not permitted in signing JSON")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _strict_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: JSON object keys must be strings")
            _strict_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path}: value is not representable as interoperable JSON")


def _strict_b64decode(value: object, *, label: str) -> bytes:
    text = str(value or "").strip()
    if not text or len(text) > (_MAX_SIGNING_BYTES * 2):
        raise ValueError(f"{label} is missing or unreasonably large")
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} is not valid base64") from exc
    if not raw or len(raw) > _MAX_SIGNING_BYTES:
        raise ValueError(f"{label} exceeds the signing-wire size limit")
    return raw


def _review_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "purpose": payload.get("purpose"),
        "approvalId": payload.get("approvalId"),
        "deviceId": payload.get("deviceId"),
        "action": payload.get("action"),
        "arguments": payload.get("arguments"),
        "actorId": payload.get("actorId"),
        "sessionId": payload.get("sessionId"),
        "runId": payload.get("runId"),
        "requestedAt": payload.get("requestedAt"),
        "approvalExpiresAt": payload.get("approvalExpiresAt"),
        "decision": payload.get("decision"),
        "decidedBy": payload.get("decidedBy"),
        "decisionNote": payload.get("decisionNote"),
        "issuedAt": payload.get("issuedAt"),
        "operatorAuthorityKeyId": payload.get("operatorAuthorityKeyId"),
    }


def inspect_signing_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a signing package without needing access to workspace state."""

    if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
        raise ValueError("operator signing request fields are invalid")
    if request.get("schema") != SIGNING_REQUEST_SCHEMA:
        raise ValueError("operator signing request schema is invalid")
    if request.get("algorithm") != "ed25519":
        raise ValueError("operator signing request algorithm is invalid")
    if request.get("signingRule") != SIGNING_RULE:
        raise ValueError("operator signing request signing rule is invalid")
    if request.get("privateKeyRequiredByNeyvia") is not False:
        raise ValueError("NEYVIA must never require the operator private key")

    signing_bytes = _strict_b64decode(
        request.get("signingBytesBase64"), label="signingBytesBase64"
    )
    actual_hash = hashlib.sha256(signing_bytes).hexdigest()
    if request.get("signingBytesSha256") != actual_hash:
        raise ValueError("operator signing request byte hash does not match")

    try:
        decoded_text = signing_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("operator signing bytes must be UTF-8") from exc
    try:
        payload = json.loads(
            decoded_text,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("operator signing bytes are not strict JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("operator signing payload must be a JSON object")
    _strict_json_value(payload)
    if payload.get("schema") != OPERATOR_DECISION_PAYLOAD_SCHEMA:
        raise ValueError("operator signing payload schema is invalid")

    # The bytes originate from the Python verifier. Require that decoding and
    # re-encoding under that same implementation is byte-stable. External
    # signers never perform this reserialization; they sign signing_bytes.
    if _json_bytes(payload) != signing_bytes:
        raise ValueError("operator signing bytes are not the server canonical form")

    approval_id = str(payload.get("approvalId") or "")
    if request.get("approvalId") != approval_id:
        raise ValueError("operator signing request approvalId does not match")
    if request.get("keyId") != payload.get("operatorAuthorityKeyId"):
        raise ValueError("operator signing request keyId does not match payload")
    review = _review_from_payload(payload)
    if _json_bytes(request.get("review")) != _json_bytes(review):
        raise ValueError("operator signing request review does not match signed bytes")

    return {
        "schema": SIGNING_REQUEST_SCHEMA,
        "algorithm": "ed25519",
        "keyId": request["keyId"],
        "approvalId": approval_id,
        "signingRule": SIGNING_RULE,
        "signingBytes": signing_bytes,
        "signingBytesSha256": actual_hash,
        "payload": payload,
        "review": review,
        "privateKeyRequiredByNeyvia": False,
    }


def prepare_signing_request(
    store: OperatorAuthorizedDeviceCommandStore,
    approval_id: str,
    *,
    decided_by: str,
    note: str = "",
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Create one immutable wire package for an external/hardware signer."""

    status = store.operator_authority_status()
    if not status.get("ready") or not status.get("keyId"):
        raise PermissionError("Cryptographic device-operator verifier is not configured.")

    payload = store.build_operator_decision_payload(
        approval_id,
        decision="approved",
        decided_by=decided_by,
        note=note,
        issued_at=issued_at,
    )
    _strict_json_value(payload)
    signing_bytes = _json_bytes(payload)
    if len(signing_bytes) > _MAX_SIGNING_BYTES:
        raise ValueError("operator signing payload exceeds the signing-wire size limit")

    request = {
        "schema": SIGNING_REQUEST_SCHEMA,
        "algorithm": "ed25519",
        "keyId": status["keyId"],
        "approvalId": payload["approvalId"],
        "signingRule": SIGNING_RULE,
        "signingBytesBase64": base64.b64encode(signing_bytes).decode("ascii"),
        "signingBytesSha256": hashlib.sha256(signing_bytes).hexdigest(),
        "review": _review_from_payload(payload),
        "privateKeyRequiredByNeyvia": False,
    }
    inspect_signing_request(request)
    return request


def validate_signing_request_against_store(
    store: OperatorAuthorizedDeviceCommandStore,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Rebind an opaque signing request to the current durable approval state."""

    inspected = inspect_signing_request(request)
    payload = inspected["payload"]
    expected = store.build_operator_decision_payload(
        inspected["approvalId"],
        decision="approved",
        decided_by=str(payload.get("decidedBy") or ""),
        note=str(payload.get("decisionNote") or ""),
        issued_at=datetime.fromisoformat(
            str(payload.get("issuedAt") or "").replace("Z", "+00:00")
        ),
    )
    _strict_json_value(expected)
    expected_bytes = _json_bytes(expected)
    if expected_bytes != inspected["signingBytes"]:
        raise PermissionError(
            "Operator signing request no longer matches the current durable approval."
        )
    return inspected


def submit_operator_signature(
    store: OperatorAuthorizedDeviceCommandStore,
    request: dict[str, Any],
    *,
    signature_base64: str,
) -> dict[str, Any]:
    """Submit a signature over exact server bytes to the canonical authority.

    Submission is idempotent while the exact signed approval remains in the
    durable ``approved`` state. This matters when an operator surface loses the
    acknowledgement after the server has already committed the approval: a
    retry re-verifies the same signature instead of creating new authority or
    returning a misleading failure.
    """

    inspected = inspect_signing_request(request)
    payload = inspected["payload"]
    signature = _strict_b64decode(signature_base64, label="signature")
    if len(signature) != 64:
        raise ValueError("Ed25519 operator signature must be exactly 64 bytes")
    normalized_signature = base64.b64encode(signature).decode("ascii")

    current = store.get_approval(inspected["approvalId"])
    if current.get("status") != "approved":
        inspected = validate_signing_request_against_store(store, request)
        payload = inspected["payload"]

    envelope = {
        "schema": OPERATOR_DECISION_SCHEMA,
        "algorithm": "ed25519",
        "keyId": inspected["keyId"],
        "payload": payload,
        "signature": normalized_signature,
    }
    return store.decide_approval(
        inspected["approvalId"],
        decision="approved",
        decided_by=str(payload.get("decidedBy") or ""),
        human_confirmed=True,
        note=str(payload.get("decisionNote") or ""),
        signed_decision=envelope,
    )


def deny_operator_approval(
    store: OperatorAuthorizedDeviceCommandStore,
    approval_id: str,
    *,
    decided_by: str,
    note: str = "",
) -> dict[str, Any]:
    """Fail-safe denial: removes authority and never needs a signing key."""

    return store.decide_approval(
        approval_id,
        decision="denied",
        decided_by=decided_by,
        human_confirmed=True,
        note=note,
        signed_decision=None,
    )
