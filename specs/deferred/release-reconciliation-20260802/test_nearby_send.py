from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from grant_agent.capability_service import CapabilityService
from grant_agent.nearby_send import NEARBY_HASH_ACK_PATH, NearbySendService


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "capability_packs.json"


class _LocalSendReceiver(BaseHTTPRequestHandler):
    files: dict[str, dict[str, object]] = {}
    uploads: dict[str, bytes] = {}
    support_hash_ack: bool = True
    session_id: str = "ephemeral-session"
    hold_upload: threading.Event | None = None
    release_upload: threading.Event | None = None

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if (
            type(self).support_hash_ack
            and parsed.path.rstrip("/") == NEARBY_HASH_ACK_PATH.rstrip("/")
        ):
            query = parse_qs(parsed.query)
            session_id = (query.get("sessionId") or [""])[0]
            if session_id != type(self).session_id:
                self._send_json(404, {"error": "unknown_session"})
                return
            files_out = {}
            for file_id, metadata in type(self).files.items():
                received = type(self).uploads.get(file_id, b"")
                digest = hashlib.sha256(received).hexdigest() if received else ""
                expected = str(metadata.get("sha256") or "")
                files_out[file_id] = {
                    "fileId": file_id,
                    "fileName": metadata.get("fileName") or file_id,
                    "received": file_id in type(self).uploads,
                    "size": len(received),
                    "sha256": digest,
                    "expectedSha256": expected,
                    "matchesExpected": bool(digest and digest == expected),
                }
            self._send_json(
                200,
                {
                    "schema": "neyvia.nearby-hash-ack/v1",
                    "sessionId": session_id,
                    "cancelled": False,
                    "files": files_out,
                    "summary": {
                        "fileCount": len(files_out),
                        "received": sum(
                            1 for row in files_out.values() if row["received"]
                        ),
                        "matched": sum(
                            1
                            for row in files_out.values()
                            if row["matchesExpected"]
                        ),
                    },
                },
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.endswith("/prepare-upload"):
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length))
            type(self).files = payload["files"]
            response = {
                "sessionId": type(self).session_id,
                "files": {
                    file_id: "ephemeral-token-" + file_id
                    for file_id in payload["files"]
                },
            }
            self._send_json(200, response)
            return
        if parsed.path.endswith("/upload"):
            query = parse_qs(parsed.query)
            file_id = query["fileId"][0]
            assert query["sessionId"] == [type(self).session_id]
            assert query["token"] == ["ephemeral-token-" + file_id]
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            hold = type(self).hold_upload
            release = type(self).release_upload
            if hold is not None and release is not None:
                hold.set()
                release.wait(timeout=5)
            type(self).uploads[file_id] = body
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path.endswith("/cancel"):
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


class _PlainLocalSendReceiver(_LocalSendReceiver):
    support_hash_ack = False


def _serve(handler: type[_LocalSendReceiver]):
    handler.files = {}
    handler.uploads = {}
    handler.hold_upload = None
    handler.release_upload = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def receiver() -> tuple[str, type[_LocalSendReceiver]]:
    _LocalSendReceiver.support_hash_ack = True
    yield from _serve(_LocalSendReceiver)


@pytest.fixture
def plain_receiver() -> tuple[str, type[_PlainLocalSendReceiver]]:
    yield from _serve(_PlainLocalSendReceiver)


def _write_cancelled_receipt(
    service: NearbySendService,
    plan: dict[str, object],
    receipt_id: str,
) -> dict[str, object]:
    file0 = plan["files"][0]
    assert isinstance(file0, dict)
    cancelled = {
        "schema": "neyvia.nearby-transfer-receipt/v1",
        "receiptId": receipt_id,
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "ok": False,
        "status": "cancelled",
        "protocol": "localsend-v2.1",
        "recipient": plan["recipient"],
        "sessionDigest": "",
        "files": [
            {
                "fileId": file0["id"],
                "fileName": file0["fileName"],
                "path": file0["path"],
                "size": file0["size"],
                "sha256": file0["sha256"],
                "destinationSha256": "",
                "transportAccepted": False,
                "remoteHashVerified": False,
                "sourceMatchesDestination": False,
            }
        ],
        "summary": {
            "fileCount": 1,
            "totalBytes": file0["size"],
            "durationMs": 1,
            "transportAccepted": 0,
            "remoteHashVerified": 0,
            "sourceMatchesDestination": 0,
        },
        "tokensRetained": False,
        "completedAt": "2026-07-24T00:00:00Z",
    }
    service.receipt_root.mkdir(parents=True, exist_ok=True)
    (service.receipt_root / f"{receipt_id}.json").write_text(
        json.dumps(cancelled),
        encoding="utf-8",
    )
    return cancelled


def test_nearby_send_plan_is_workspace_scoped_hash_bound_and_approval_gated(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, handler = receiver
    first = tmp_path / "first.txt"
    second = tmp_path / "second.bin"
    first.write_text("nearby text proof", encoding="utf-8")
    second.write_bytes(bytes(range(256)) * 8)
    service = NearbySendService(tmp_path)

    plan = service.build_plan(
        [first, second],
        recipient_endpoint=endpoint,
    )
    blocked = service.send(plan, approved=False)
    result = service.send(plan, approved=True)

    assert plan["summary"]["fileCount"] == 2
    assert blocked["status"] == "approval_required"
    assert result["ok"] is True, result
    assert result["summary"]["transportAccepted"] == 2
    assert result["summary"]["remoteHashVerified"] == 2
    assert result["hashAck"]["available"] is True
    assert result["tokensRetained"] is False
    assert Path(result["receiptPath"]).is_file()
    assert "ephemeral-token" not in json.dumps(result)
    for file_id, metadata in handler.files.items():
        received = handler.uploads[file_id]
        assert hashlib.sha256(received).hexdigest() == metadata["sha256"]
    for row in result["files"]:
        assert row["remoteHashVerified"] is True
        assert row["destinationSha256"] == row["sha256"]
        assert row["sourceMatchesDestination"] is True


def test_nearby_send_without_hash_ack_leaves_remote_unverified(
    tmp_path: Path,
    plain_receiver: tuple[str, type[_PlainLocalSendReceiver]],
) -> None:
    endpoint, handler = plain_receiver
    source = tmp_path / "plain.txt"
    source.write_text("plain localsend", encoding="utf-8")
    service = NearbySendService(tmp_path)
    plan = service.build_plan([source], recipient_endpoint=endpoint)
    result = service.send(plan, approved=True)

    assert result["ok"] is True, result
    assert result["summary"]["transportAccepted"] == 1
    assert result["summary"]["remoteHashVerified"] == 0
    assert result["hashAck"]["available"] is False
    assert result["files"][0]["remoteHashVerified"] is False
    received = next(iter(handler.uploads.values()))
    assert hashlib.sha256(received).hexdigest() == plan["files"][0]["sha256"]


def test_nearby_receiver_sidecar_acks_destination_hash(tmp_path: Path) -> None:
    source = tmp_path / "sidecar-proof.txt"
    source.write_text("sidecar destination hash proof", encoding="utf-8")
    service = NearbySendService(tmp_path)
    try:
        status = service.start_receiver_sidecar(host="127.0.0.1", port=0)
        assert status["running"] is True
        assert status["endpoint"].startswith("http://127.0.0.1:")
        assert service.compatibility_snapshot()["receiverSidecarImplemented"] is True

        plan = service.build_plan(
            [source],
            recipient_endpoint=status["endpoint"],
        )
        result = service.send(plan, approved=True)
        history = service.list_transfer_history(limit=5)

        assert result["ok"] is True, result
        assert result["summary"]["remoteHashVerified"] == 1
        assert result["files"][0]["destinationSha256"] == plan["files"][0]["sha256"]
        assert history["summary"]["remoteHashVerifiedCount"] >= 1
        assert history["summary"]["sourceMatchesDestinationCount"] >= 1
        assert history["transfers"][0]["files"][0]["sourceMatchesDestination"] is True
    finally:
        service.stop_receiver_sidecar()


def test_nearby_send_rejects_source_changes_after_preview(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, _handler = receiver
    source = tmp_path / "changing.txt"
    source.write_text("before", encoding="utf-8")
    service = NearbySendService(tmp_path)
    plan = service.build_plan([source], recipient_endpoint=endpoint)
    source.write_text("after", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after transfer preview"):
        service.send(plan, approved=True)


def test_nearby_tool_operation_is_typed_and_external_send_requires_approval(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, handler = receiver
    source = tmp_path / "typed.txt"
    source.write_text("typed nearby operation", encoding="utf-8")
    service = CapabilityService(tmp_path, catalog_path=CATALOG)

    planned = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.plan-send",
            "arguments": {
                "paths": [str(source)],
                "recipientEndpoint": endpoint,
            },
        }
    )
    blocked = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.send",
            "arguments": {
                "plan": planned["result"],
                "approved": True,
            },
        }
    )
    sent = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.send",
            "approvedPermissions": [
                "network.write",
                "external.side_effect",
            ],
            "arguments": {
                "plan": planned["result"],
                "approved": True,
            },
        }
    )

    assert planned["ok"] is True, planned
    assert planned["outputValidation"]["valid"] is True
    assert blocked["status"] == "approval_required"
    assert sent["ok"] is True, sent
    assert sent["outputValidation"]["valid"] is True
    assert len(handler.uploads) == 1
    assert sent["artifactReceipt"]["artifacts"]


def test_nearby_send_rejects_unpinned_https_and_non_loopback_plain_http(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("proof", encoding="utf-8")
    service = NearbySendService(tmp_path)

    with pytest.raises(ValueError, match="fingerprint"):
        service.build_plan(
            [source],
            recipient_endpoint="https://192.0.2.10:53317",
        )
    with pytest.raises(ValueError, match="loopback"):
        service.build_plan(
            [source],
            recipient_endpoint="http://192.168.1.2:53317",
        )


def test_nearby_send_rejects_files_outside_workspace(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, _handler = receiver
    outside = tmp_path.parent / "outside-nearby-proof.txt"
    outside.write_text("outside", encoding="utf-8")
    service = NearbySendService(tmp_path)
    try:
        with pytest.raises(PermissionError, match="active-workspace"):
            service.build_plan([outside], recipient_endpoint=endpoint)
    finally:
        outside.unlink(missing_ok=True)


def test_discovered_device_contract_preserves_certificate_fingerprint() -> None:
    row = NearbySendService._discovered_device(
        {
            "alias": "Phone",
            "version": "2.1",
            "deviceModel": "Android",
            "deviceType": "mobile",
            "fingerprint": "ab" * 32,
            "port": 53317,
            "protocol": "https",
            "download": True,
            "announce": False,
        },
        "192.168.1.50",
    )

    assert row is not None
    assert row["endpoint"] == "https://192.168.1.50:53317"
    assert row["certificateFingerprint"] == "ab" * 32


def test_nearby_transfer_history_lists_receipts_with_source_hashes(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, handler = receiver
    source = tmp_path / "history-proof.txt"
    source.write_text("history proof body", encoding="utf-8")
    service = NearbySendService(tmp_path)
    plan = service.build_plan([source], recipient_endpoint=endpoint)
    result = service.send(plan, approved=True)

    history = service.list_transfer_history(limit=10)
    active = service.get_active_transfer()

    assert result["ok"] is True, result
    assert history["schema"] == "neyvia.nearby-transfer-history/v1"
    assert history["summary"]["transfers"] == 1
    assert history["summary"]["remoteHashVerifiedCount"] == 1
    assert history["summary"]["sourceMatchesDestinationCount"] == 1
    assert history["physicalDeviceProof"]["available"] is False
    transfer = history["transfers"][0]
    assert transfer["receiptId"] == result["receiptId"]
    assert transfer["files"][0]["sha256"] == plan["files"][0]["sha256"]
    assert transfer["files"][0]["remoteHashVerified"] is True
    assert transfer["files"][0]["destinationSha256"] == plan["files"][0]["sha256"]
    received = next(iter(handler.uploads.values()))
    assert hashlib.sha256(received).hexdigest() == transfer["files"][0]["sha256"]
    assert active["active"] is False


def test_nearby_cancel_request_is_idle_when_no_active_transfer(
    tmp_path: Path,
) -> None:
    service = NearbySendService(tmp_path)
    cancelled = service.request_cancel_active_transfer()
    assert cancelled["ok"] is False
    assert cancelled["status"] == "not_active"
    assert "message" in cancelled


def test_nearby_retry_rebuilds_plan_from_cancelled_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retry-proof.txt"
    source.write_text("retry body", encoding="utf-8")
    service = NearbySendService(tmp_path)
    try:
        status = service.start_receiver_sidecar(host="127.0.0.1", port=0)
        plan = service.build_plan([source], recipient_endpoint=status["endpoint"])
        cancelled_receipt = _write_cancelled_receipt(
            service,
            plan,
            "nearby_receipt_retryfixture00000000000000000001",
        )

        blocked = service.retry_transfer(
            cancelled_receipt["receiptId"],
            approved=False,
        )
        retried = service.retry_transfer(
            cancelled_receipt["receiptId"],
            approved=True,
        )

        assert blocked["status"] == "approval_required"
        assert retried["ok"] is True, retried
        assert retried["retriedFromReceiptId"] == cancelled_receipt["receiptId"]
        assert retried["summary"]["remoteHashVerified"] == 1
    finally:
        service.stop_receiver_sidecar()


def test_nearby_cancel_during_upload_writes_cancelled_receipt(
    tmp_path: Path,
    receiver: tuple[str, type[_LocalSendReceiver]],
) -> None:
    endpoint, handler = receiver
    hold = threading.Event()
    release = threading.Event()
    handler.hold_upload = hold
    handler.release_upload = release

    source = tmp_path / "cancel-live.txt"
    source.write_bytes(b"x" * (256 * 1024))
    sender = NearbySendService(tmp_path)
    canceller = NearbySendService(tmp_path)
    plan = sender.build_plan([source], recipient_endpoint=endpoint)

    result_holder: dict[str, object] = {}

    def _send() -> None:
        result_holder["result"] = sender.send(plan, approved=True)

    worker = threading.Thread(target=_send, daemon=True)
    worker.start()
    assert hold.wait(timeout=5), "upload never reached the receiver hold point"
    cancel = canceller.request_cancel_active_transfer()
    release.set()
    worker.join(timeout=10)
    result = result_holder.get("result")

    assert cancel["ok"] is True
    assert cancel["status"] in {"cancel_requested", "cancel_already_requested"}
    assert isinstance(result, dict)
    assert result["status"] == "cancelled"
    assert result["ok"] is False
    assert result["summary"]["remoteHashVerified"] == 0
    assert Path(str(result["receiptPath"])).is_file()


def test_nearby_load_receipt_rejects_path_shaped_ids(tmp_path: Path) -> None:
    service = NearbySendService(tmp_path)
    with pytest.raises(ValueError, match="bare receipt identifier"):
        service._load_receipt(r"C:\tmp\nearby_receipt_abc")


def test_nearby_favorites_are_sender_quick_targets_only(
    tmp_path: Path,
) -> None:
    service = NearbySendService(tmp_path)
    empty = service.list_favorites()
    assert empty["summary"]["devices"] == 0
    assert empty["policy"]["autoAcceptFromFavorites"] is False

    added = service.upsert_favorite(
        {
            "alias": "Loopback Box",
            "endpoint": "http://127.0.0.1:53317",
        }
    )
    listed = service.list_favorites()
    assert added["ok"] is True
    assert listed["summary"]["devices"] == 1
    device_id = added["device"]["deviceId"]

    source = tmp_path / "fav-plan.txt"
    source.write_text("favorite plan", encoding="utf-8")
    plan = service.build_plan(
        [source],
        favorite_device_id=device_id,
    )
    assert plan["recipient"]["endpoint"] == "http://127.0.0.1:53317"
    assert plan["recipient"]["favoriteDeviceId"] == device_id

    removed = service.remove_favorite(device_id)
    assert removed["ok"] is True
    assert service.list_favorites()["summary"]["devices"] == 0


def test_nearby_text_and_link_payloads_hash_ack(
    tmp_path: Path,
) -> None:
    service = NearbySendService(tmp_path)
    try:
        status = service.start_receiver_sidecar(host="127.0.0.1", port=0)
        plan = service.build_plan(
            payloads=[
                {"kind": "text", "content": "hello nearby text"},
                {"kind": "link", "content": "https://example.com/neyvia"},
            ],
            recipient_endpoint=status["endpoint"],
        )
        result = service.send(plan, approved=True)

        assert plan["summary"]["textCount"] == 1
        assert plan["summary"]["linkCount"] == 1
        assert result["ok"] is True, result
        assert result["summary"]["remoteHashVerified"] == 2
        assert result["summary"]["textCount"] == 1
        assert result["summary"]["linkCount"] == 1
        kinds = {row["payloadKind"] for row in result["files"]}
        assert kinds == {"text", "link"}
        for row in result["files"]:
            assert row["remoteHashVerified"] is True
            assert row["destinationSha256"] == row["sha256"]
    finally:
        service.stop_receiver_sidecar()


def test_nearby_link_payload_rejects_non_http_urls(tmp_path: Path) -> None:
    service = NearbySendService(tmp_path)
    with pytest.raises(ValueError, match="http\\(s\\) URL"):
        service.build_plan(
            payloads=[{"kind": "link", "content": "ftp://example.com/file"}],
            recipient_endpoint="http://127.0.0.1:53317",
        )


def test_nearby_cancel_retry_and_sidecar_tool_ops_are_permission_aware(
    tmp_path: Path,
) -> None:
    service = CapabilityService(tmp_path, catalog_path=CATALOG)

    history = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.transfer-history",
            "arguments": {"limit": 5},
        }
    )
    active = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.active-transfer",
            "arguments": {},
        }
    )
    status = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.sidecar-status",
            "arguments": {},
        }
    )
    cancel = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.cancel-active",
            "arguments": {},
        }
    )
    start_blocked = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.start-sidecar",
            "arguments": {"host": "127.0.0.1", "port": 0},
        }
    )
    retry_blocked = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.retry-transfer",
            "arguments": {
                "receiptId": "nearby_receipt_missing",
                "approved": True,
            },
        }
    )
    started = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-nearby-send",
            "operationId": "nearby.start-sidecar",
            "approvedPermissions": ["network.write"],
            "arguments": {"host": "127.0.0.1", "port": 0},
        }
    )
    try:
        stopped = service.execute_tool_operation(
            {
                "toolId": "tool.neyvia-nearby-send",
                "operationId": "nearby.stop-sidecar",
                "approvedPermissions": ["network.write"],
                "arguments": {},
            }
        )
    finally:
        NearbySendService(tmp_path).stop_receiver_sidecar()

    assert history["ok"] is True, history
    assert history["outputValidation"]["valid"] is True
    assert active["ok"] is True, active
    assert active["result"]["active"] is False
    assert status["ok"] is True, status
    assert status["result"]["hashAckPath"] == NEARBY_HASH_ACK_PATH
    assert cancel["status"] == "approval_required"
    assert start_blocked["status"] == "approval_required"
    assert retry_blocked["status"] == "approval_required"
    assert started["ok"] is True, started
    assert started["result"]["running"] is True
    assert started["result"]["hashAckPath"] == NEARBY_HASH_ACK_PATH
    assert stopped["ok"] is True, stopped
    assert stopped["result"]["running"] is False
