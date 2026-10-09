"""Nearby transfer action contracts and bounded real loopback protocol lab.

The receiver stores bytes, computes content hashes and persists acknowledgements;
malformed responses are deliberate wire-level adverse inputs, not mock results.
No physical-device, multicast, Internet peer or multi-recipient proof is claimed.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONTRACTS = (
    "d.nearby.hash-bound-plan", "d.nearby.legacy-migration", "d.nearby.resume-integrity",
    "d.nearby.chunk-ack-integrity", "d.nearby.durable-ack-prefix",
    "d.nearby.cancel-truth", "d.nearby.terminal-receipt",
)
COVERAGE = {
    "test_chunk_plan_enforces_part_limit_before_network": ["d.nearby.hash-bound-plan"],
    "test_pre_upgrade_plan_is_verified_then_enriched_with_chunks": ["d.nearby.legacy-migration", "d.nearby.hash-bound-plan", "d.nearby.chunk-ack-integrity"],
    "test_mid_chunk_cross_process_cancel_stops_streaming": ["d.nearby.cancel-truth", "d.nearby.terminal-receipt", "d.nearby.durable-ack-prefix"],
    "test_invalid_resume_or_integrity_ack_is_never_claimed": ["d.nearby.resume-integrity", "d.nearby.chunk-ack-integrity", "d.nearby.terminal-receipt"],
    "test_killed_sender_persists_receipt_and_retry_resumes": ["d.nearby.durable-ack-prefix", "d.nearby.resume-integrity", "d.nearby.terminal-receipt"],
    "test_in_flight_cancel_is_shared_across_sdk_instances_and_truthful": ["d.nearby.cancel-truth", "d.nearby.terminal-receipt"],
    "test_remote_upload_failure_returns_failed_receipt_and_cancel_ack": ["d.nearby.cancel-truth", "d.nearby.terminal-receipt"],
    "test_cancel_rejection_never_claims_remote_acknowledgement": ["d.nearby.cancel-truth", "d.nearby.terminal-receipt"],
}


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def _identity(row):
    return {key: row[key] for key in ("part", "offset", "size", "sha256")}


def _check_chunks(size, chunks):
    offset = 0
    for part, row in enumerate(chunks):
        require(row["part"] == part and row["offset"] == offset and row["size"] > 0 and len(row["sha256"]) == 64,
                "d.nearby.hash-bound-plan", "chunk ordering, bounds or digest")
        offset += row["size"]
    require(offset == size, "d.nearby.hash-bound-plan", "chunks do not cover the exact file")


def check_plan(service, plan):
    from .nearby_send import _canonical_hash
    unsigned = {key: value for key, value in plan.items() if key != "planHash"}
    require(plan["planHash"] == _canonical_hash(unsigned), "d.nearby.hash-bound-plan", "canonical preview hash")
    files, summary = plan["files"], plan["summary"]
    require(summary["fileCount"] == len(files) and summary["totalBytes"] == sum(row["size"] for row in files), "d.nearby.hash-bound-plan", "file/byte totals")
    require(summary["partCount"] == sum(len(row["chunks"]) for row in files) <= service._chunk_limits()[1], "d.nearby.hash-bound-plan", "part limit before network")
    for row in files:
        path = Path(row["path"])
        require(path.is_relative_to(service.root) and path.is_file() and path.stat().st_size == row["size"], "d.nearby.hash-bound-plan", "source is outside selected workspace or changed")
        _check_chunks(row["size"], row["chunks"])
    require(plan["requiresApproval"] is True and plan["tokensRetained"] is False, "d.nearby.hash-bound-plan", "external side-effect authority")


def check_verified_file(row, actual_chunks, *, migrated):
    require(row["chunks"] == actual_chunks and row["chunkManifestMigrated"] is migrated, "d.nearby.legacy-migration", "verified legacy manifest enrichment")
    _check_chunks(row["size"], row["chunks"])


def check_chunk_receipt(chunk, receipt, source):
    require(_identity(chunk) == _identity(receipt) and receipt["integrityVerified"] is True and receipt["source"] == source,
            "d.nearby.chunk-ack-integrity", "acknowledgement does not bind exact part/offset/size/hash")


def check_resume_authorization(item, result):
    offset, chunks, receipts = result["offset"], item["chunks"], result["acknowledgements"]
    require(offset in {0, item["size"], *(row["offset"] + row["size"] for row in chunks)}, "d.nearby.resume-integrity", "resume offset is not a chunk boundary")
    expected = [row for row in chunks if row["offset"] < offset]
    require(len(receipts) == len(expected) and sum(row["size"] for row in receipts) == offset, "d.nearby.resume-integrity", "resume ACKs do not cover exact prefix")
    for chunk, receipt in zip(expected, receipts, strict=True):
        check_chunk_receipt(chunk, receipt, "resume")


def check_ack_progress(service, transfer_id, item, acknowledgements, offset):
    state = json.loads(service.active_state_path.read_text(encoding="utf-8"))
    require(state["transferId"] == transfer_id, "d.nearby.durable-ack-prefix", "transfer identity changed before ACK persistence")
    row = next(row for row in state["files"] if row["fileId"] == item["id"])
    require(row["acknowledgedChunks"] == acknowledgements and row["acknowledgedOffset"] == offset,
            "d.nearby.durable-ack-prefix", "wire ACK not durably persisted")
    require(sum(receipt["size"] for receipt in acknowledgements) == offset, "d.nearby.durable-ack-prefix", "ACK bytes are not contiguous")
    for chunk, receipt in zip(item["chunks"], acknowledgements):
        check_chunk_receipt(chunk, receipt, receipt["source"])


def check_cancel_transport(result):
    require(result["attempted"] and result["acknowledged"] is (result["httpStatus"] in {200, 204}), "d.nearby.cancel-truth", "remote cancel ACK must follow real HTTP status")
    require(result["errorCode"] == ("" if result["acknowledged"] else "recipient_cancel_rejected"), "d.nearby.cancel-truth", "cancel error mapping")


def check_cancel_request(result, remote):
    require(result["accepted"] is True and result["cancelled"] is False and result["finalState"] == "pending" and result["status"] == "cancel_requested", "d.nearby.cancel-truth", "request prematurely claims final cancellation")
    require(result["remoteCancelAttempted"] == remote["attempted"] and result["remoteCancelAcknowledged"] == remote["acknowledged"] and result["remoteCancelHttpStatus"] == remote["httpStatus"], "d.nearby.cancel-truth", "remote cancellation response differs")


def check_transfer_result(service, items, result):
    path = (service.root / result["receiptPath"]).resolve()
    require(path.is_relative_to(service.receipt_root.resolve()) and path.is_file(), "d.nearby.terminal-receipt", "final result has no owned durable receipt")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    require(result["receiptId"] == receipt["receiptId"] and result["status"] == receipt["status"] and result["error"] == receipt["error"], "d.nearby.terminal-receipt", "public result differs from durable terminal state")
    require(receipt["ok"] is (receipt["status"] == "completed") and receipt["cancelled"] is (receipt["status"] == "cancelled"), "d.nearby.terminal-receipt", "terminal truth flags")
    require(not receipt["physicalDeviceVerified"] and not receipt["multiRecipientVerified"] and receipt["tokensRetained"] is False, "d.nearby.terminal-receipt", "unproved transfer capability claimed")
    rows = receipt["files"]
    require(len(rows) == len(items), "d.nearby.terminal-receipt", "planned file accounting")
    by_id = {item["id"]: item for item in items}
    for row in rows:
        item = by_id[row["fileId"]]
        acks = row["chunkReceipts"]
        require(row["size"] == item["size"] and row["sha256"] == item["sha256"] and row["chunkCount"] == len(item["chunks"]), "d.nearby.terminal-receipt", "receipt not bound to verified source")
        for chunk, ack in zip(item["chunks"], acks):
            require(ack["source"] in {"resume", "upload"}, "d.nearby.chunk-ack-integrity", "ACK source")
            check_chunk_receipt(chunk, ack, ack["source"])
        require(len(acks) <= len(item["chunks"]) and row["acknowledgedParts"] == len(acks) and row["resumedParts"] == sum(ack["source"] == "resume" for ack in acks) and row["uploadedParts"] == sum(ack["source"] == "upload" for ack in acks), "d.nearby.terminal-receipt", "parts accounting")
        if row["remoteHashVerified"]:
            require(bool(acks) and len(acks) == len(item["chunks"]) and row["acknowledgedOffset"] == item["size"] and row["transportAccepted"], "d.nearby.chunk-ack-integrity", "whole-file hash claim lacks complete verified ACKs")
    summary = receipt["summary"]
    for key, expected in {
        "fileCount": len(rows), "totalBytes": sum(row["size"] for row in rows),
        "transportAccepted": sum(row["transportAccepted"] for row in rows),
        "remoteHashVerified": sum(row["remoteHashVerified"] for row in rows),
        "partCount": sum(row["chunkCount"] for row in rows),
        "acknowledgedParts": sum(row["acknowledgedParts"] for row in rows),
        "resumedParts": sum(row["resumedParts"] for row in rows),
        "uploadedParts": sum(row["uploadedParts"] for row in rows),
    }.items():
        require(summary[key] == expected, "d.nearby.terminal-receipt", "summary differs from file evidence")
    if receipt["status"] == "failed":
        require(bool(receipt["error"] and receipt["error"]["code"]), "d.nearby.terminal-receipt", "failure has no stable cause")
    cancel = receipt["cancellation"]
    if cancel["remoteAcknowledged"]:
        require(cancel["remoteAttempted"] and cancel["remoteHttpStatus"] in {200, 204}, "d.nearby.cancel-truth", "receipt falsely claims cancel ACK")


def self_check(root):
    """Real sender, SDK cancellation in a child, crash/retry, and wire refusals."""
    from .nearby_send import NearbySendService, NEARBY_CHUNK_TRANSFER_SCHEMA, _canonical_hash
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from . import sdk
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases, receipts, wire = [], [], []
    endpoint = proof_text("http://127.0.0.1:48495")
    repo = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo / "src"), "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0"}

    class Peer:
        def __init__(self):
            self.mode = "chunks"
            self.fault = ""
            self.cancel_status = 204
            self.upload_status = 200
            self.pause_stream = False
            self.block_part = None
            self.abort_block = False
            self.started = threading.Event()
            self.cancelled = threading.Event()
            self.blocked = threading.Event()
            self.release = threading.Event()
            self.closed_upload = threading.Event()
            self.manifests, self.acknowledged, self.received = {}, {}, {}
            self.attempted, self.accepted = [], []
            self.cancel_calls = 0
            self.directory = root / "peer" / str(time.time_ns())
            self.directory.mkdir(parents=True)

    peer = Peer()

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload=None):
            body = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionError, OSError):
                pass

        def do_POST(self):
            current = peer
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path.endswith("/prepare-upload"):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                authorizations = {}
                for file_id, metadata in body["files"].items():
                    contract = metadata["chunkTransfer"]
                    require(contract["schema"] == NEARBY_CHUNK_TRANSFER_SCHEMA, "d.nearby.resume-integrity", "wire protocol schema")
                    current.manifests[file_id] = contract
                    chunks = contract["chunks"]
                    ack = current.acknowledged.setdefault(file_id, [])
                    if current.mode == "legacy":
                        authorizations[file_id] = "fixture-private-token-" + file_id
                        continue
                    offset = sum(row["size"] for row in ack)
                    public_acks = [{**row, "integrityVerified": True} for row in ack]
                    if current.fault == "resume-offset":
                        offset += 1
                    elif current.fault == "resume-hash":
                        offset = chunks[0]["size"]
                        public_acks = [{**chunks[0], "sha256": "0" * 64, "integrityVerified": True}]
                    authorizations[file_id] = {"token": "fixture-private-token-" + file_id, "chunkTransfer": {"schema": NEARBY_CHUNK_TRANSFER_SCHEMA, "offset": offset, "acknowledgedChunks": public_acks}}
                wire.append({"action": "prepare", "mode": current.mode, "files": len(authorizations), "fault": current.fault})
                self.reply(200, {"sessionId": "fixture-private-session", "files": authorizations})
                return
            if parsed.path.endswith("/cancel"):
                current.cancel_calls += 1
                current.cancelled.set()
                wire.append({"action": "cancel", "httpStatus": current.cancel_status})
                self.reply(current.cancel_status)
                return
            if not parsed.path.endswith("/upload"):
                self.reply(404)
                return
            file_id = query["fileId"][0]
            contract = current.manifests[file_id]
            chunked = "part" in query
            part = int(query["part"][0]) if chunked else 0
            offset = int(query["offset"][0]) if chunked else 0
            current.attempted.append(offset)
            length = int(self.headers["Content-Length"])
            expected = contract["chunks"][part] if chunked else {"offset": 0, "size": contract["size"], "sha256": contract["sha256"]}
            require(length == expected["size"] and offset == expected["offset"], "d.nearby.chunk-ack-integrity", "wire content bounds")
            if chunked:
                require(query["chunkId"] == [expected["sha256"]], "d.nearby.chunk-ack-integrity", "wire content identity")
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
            digest, remaining, count = hashlib.sha256(), length, 0
            output = current.directory / f"{file_id}-{part}.bin"
            try:
                with output.open("wb") as destination:
                    while remaining:
                        piece = self.rfile.read(min(64 * 1024, remaining))
                        if not piece:
                            break
                        if count == 0:
                            current.started.set()
                            if current.pause_stream:
                                current.cancelled.wait(timeout=12)
                        count += len(piece)
                        remaining -= len(piece)
                        digest.update(piece)
                        destination.write(piece)
                        if current.pause_stream:
                            time.sleep(0.001)
                current.received[part] = count
                wire.append({"action": "upload", "part": part, "offset": offset, "receivedBytes": count, "declaredBytes": length, "hashVerified": not remaining and digest.hexdigest() == expected["sha256"]})
                if remaining:
                    return
                require(digest.hexdigest() == expected["sha256"], "d.nearby.chunk-ack-integrity", "received actual bytes have wrong digest")
                if current.block_part == part:
                    current.blocked.set()
                    current.release.wait(timeout=12)
                    if current.abort_block:
                        self.reply(503)
                        return
                if current.upload_status not in {200, 204}:
                    self.reply(current.upload_status)
                    return
                if chunked:
                    current.acknowledged[file_id].append(dict(expected))
                    current.accepted.append(offset)
                    (current.directory / "acknowledgements.json").write_text(json.dumps(current.acknowledged), encoding="utf-8")
                    self.reply(200, {"acknowledged": True, "nextOffset": offset + length, "sha256": "0" * 64 if current.fault == "upload-hash" else digest.hexdigest(), "integrityVerified": True})
                else:
                    current.accepted.append(offset)
                    self.reply(204)
            except (ConnectionError, OSError):
                current.received[part] = count
            finally:
                current.closed_upload.set()

    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48495)), Receiver)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()

    def reset():
        nonlocal peer
        peer = Peer()
        return peer

    def workspace(name, *, chunk_bytes=4, max_parts=8):
        area = root / name
        config_dir = area / "config"
        config_dir.mkdir(parents=True)
        config = json.loads((repo / "config/neyvia_nearby_send.json").read_text(encoding="utf-8"))
        config["protocol"]["port"] = proof_port(48495)
        config["limits"].update(chunkBytes=chunk_bytes, maxParts=max_parts, requestTimeoutSeconds=15)
        (config_dir / "neyvia_nearby_send.json").write_text(json.dumps(config), encoding="utf-8")
        return area, NearbySendService(area)

    def record(name, action):
        begin = time.perf_counter()
        row = {"case": name, "contracts": COVERAGE[name]}
        try:
            action()
            row["ok"] = True
        except Exception as exc:
            row.update(ok=False, error=str(exc))
        row["durationMs"] = round((time.perf_counter() - begin) * 1000, 3)
        cases.append(row)

    def clean_receipt(area, result):
        serialized = json.dumps(result)
        require(str(area) not in serialized and endpoint not in serialized and "fixture-private-token" not in serialized and "fixture-private-session" not in serialized, "d.nearby.terminal-receipt", "private state leaked")
        require((area / result["receiptPath"]).is_file(), "d.nearby.terminal-receipt", "receipt not persisted")
        receipts.append({"caseRoot": area.name, "status": result["status"], "receiptPath": str(area / result["receiptPath"]), "summary": result["summary"], "cancellation": result["cancellation"]})

    def subprocess_cancel(area):
        code = "import json,sys;from grant_agent.sdk import cancel_nearby_active_transfer;print(json.dumps(cancel_nearby_active_transfer(workspace_root=sys.argv[1])))"
        completed = subprocess.run([sys.executable, "-c", code, str(area)], env=env, capture_output=True, text=True, timeout=15, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "d.nearby.cancel-truth", "child SDK cancel failed")
        return json.loads(completed.stdout)

    def part_limit():
        reset()
        area, service = workspace("part-limit", max_parts=2)
        path = area / "input.bin"
        path.write_bytes(b"123456789")
        before = len(wire)
        try:
            service.build_plan([path], recipient_endpoint=endpoint)
        except ValueError as exc:
            require("chunk part limit" in str(exc), "d.nearby.hash-bound-plan", "wrong preflight failure")
        else:
            raise ValueError("Part-limit overflow accepted")
        require(len(wire) == before, "d.nearby.hash-bound-plan", "preflight touched network")

    def migrate():
        current = reset()
        area, service = workspace("legacy-migration")
        path = area / "input.bin"
        path.write_bytes(b"legacy-plan")
        plan = service.build_plan([path], recipient_endpoint=endpoint)
        plan["files"][0].pop("chunks")
        for key in ("chunkBytes", "partCount", "maxParts"):
            plan["summary"].pop(key)
        plan["planHash"] = _canonical_hash({key: value for key, value in plan.items() if key != "planHash"})
        result = service.send(plan, approved=True)
        row = result["files"][0]
        manifest = current.manifests[row["fileId"]]
        require(result["ok"] and row["chunkManifestMigrated"] and result["summary"]["migratedChunkManifests"] == 1 and manifest["manifestMigrated"] and len(manifest["chunks"]) == 3, "d.nearby.legacy-migration", "legacy manifest not verified/enriched on actual wire")
        clean_receipt(area, result)

    def streaming_cancel(*, chunked, rejected=False, via_child=True):
        current = reset()
        current.pause_stream = True
        current.mode = "chunks" if chunked else "legacy"
        current.cancel_status = 500 if rejected else 204
        size = 32 * 1024 * 1024 if chunked else 24 * 1024 * 1024
        chunk_bytes = 16 * 1024 * 1024 if chunked else 8 * 1024 * 1024
        area, service = workspace("cancel-chunks" if chunked else "cancel-rejected" if rejected else "cancel-legacy", chunk_bytes=chunk_bytes, max_parts=3)
        source = area / "input.bin"
        with source.open("wb") as destination:
            for _ in range(size // (1024 * 1024)):
                destination.write(b"x" * (1024 * 1024))
        plan = sdk.plan_nearby_send([source], recipient_endpoint=endpoint, workspace_root=area)
        outcome, errors = {}, []

        def send():
            try:
                outcome.update(sdk.send_nearby_files(plan, approved=True, workspace_root=area))
            except Exception as exc:
                errors.append(str(exc))

        sender = threading.Thread(target=send)
        sender.start()
        try:
            require(current.started.wait(timeout=10), "d.nearby.cancel-truth", "actual upload never began")
            cancel = subprocess_cancel(area) if via_child else sdk.cancel_nearby_active_transfer(workspace_root=area)
            sender.join(timeout=20)
            require(not sender.is_alive() and not errors, "d.nearby.cancel-truth", "sender did not stop: " + str(errors))
            require(current.closed_upload.wait(timeout=10), "d.nearby.cancel-truth", "receiver stream was not reaped")
            require(cancel["accepted"] and not cancel["cancelled"] and cancel["finalState"] == "pending" and cancel["remoteCancelAttempted"] and cancel["remoteCancelAcknowledged"] is (not rejected), "d.nearby.cancel-truth", "request reply not truthful")
            require(outcome["status"] == "cancelled" and outcome["cancelled"] and not outcome["ok"] and outcome["cancellation"]["remoteAcknowledged"] is (not rejected), "d.nearby.cancel-truth", "terminal cancel state")
            require(current.cancel_calls >= 1 and current.cancelled.is_set() and 0 < sum(current.received.values()) < (chunk_bytes if chunked else size), "d.nearby.cancel-truth", "upload was not interrupted midstream")
            if chunked:
                require(current.attempted == [0] and outcome["summary"]["uploadedParts"] == 0 and outcome["summary"]["remoteHashVerified"] == 0, "d.nearby.chunk-ack-integrity", "partial chunk was falsely acknowledged")
            if rejected:
                require(cancel["remoteCancelHttpStatus"] == 500 and outcome["cancellation"]["errorCode"] == "recipient_cancel_rejected", "d.nearby.cancel-truth", "cancel rejection hidden")
            clean_receipt(area, outcome)
        finally:
            current.cancelled.set()
            if sender.is_alive():
                service.request_cancel_active_transfer()
                sender.join(timeout=20)
            require(not sender.is_alive(), "d.nearby.cancel-truth", "owned sender thread still running")

    def invalid_wire():
        for fault, code in (("resume-offset", "invalid_resume_offset"), ("resume-hash", "invalid_resume_receipts"), ("upload-hash", "invalid_chunk_acknowledgement")):
            current = reset()
            current.fault = fault
            area, service = workspace("fault-" + fault)
            source = area / "input.bin"
            source.write_bytes(b"abcdefgh")
            result = service.send(service.build_plan([source], recipient_endpoint=endpoint), approved=True)
            require(not result["ok"] and result["status"] == "failed" and result["error"]["code"] == code and result["summary"]["remoteHashVerified"] == 0 and not result["files"][0]["remoteHashVerified"], "d.nearby.resume-integrity", "invalid wire integrity was claimed: " + fault)
            clean_receipt(area, result)

    def crash_retry():
        current = reset()
        current.block_part = 1
        area, service = workspace("crash-retry")
        source = area / "input.bin"
        source.write_bytes(b"abcdefghijkl")
        plan = service.build_plan([source], recipient_endpoint=endpoint)
        plan_path = area / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        code = "import json,sys;from grant_agent.nearby_send import NearbySendService;NearbySendService(sys.argv[1]).send(json.load(open(sys.argv[2],encoding='utf-8')),approved=True)"
        sender = subprocess.Popen([sys.executable, "-c", code, str(area), str(plan_path)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
        try:
            require(current.blocked.wait(timeout=10), "d.nearby.durable-ack-prefix", "child sender did not reach second chunk")
            sender.terminate()
            sender.communicate(timeout=10)
            current.abort_block = True
            current.release.set()
            recovered = service.get_active_transfer()
            progress = recovered["progress"]["files"][0]
            require(not recovered["active"] and recovered["recovery"] == "stale_transfer_recovered" and recovered["progress"]["status"] == "interrupted" and progress["acknowledgedOffset"] == 4 and progress["acknowledgedParts"] == 1 and progress["chunkReceipts"][0]["integrityVerified"], "d.nearby.durable-ack-prefix", "crash lost persisted first ACK")
            # Wait for the aborted second upload to close before changing peer policy.
            deadline = time.monotonic() + 5
            while len([row for row in wire if row.get("action") == "upload"]) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            current.block_part = None
            result = NearbySendService(area).send(plan, approved=True)
            summary, row = result["summary"], result["files"][0]
            require(result["ok"] and (summary["partCount"], summary["acknowledgedParts"], summary["resumedParts"], summary["uploadedParts"], summary["remoteHashVerified"]) == (3, 3, 1, 2, 1), "d.nearby.resume-integrity", "retry part accounting")
            require(row["resumeOffset"] == 4 and row["acknowledgedOffset"] == 12 and row["remoteHashVerified"] and [ack["source"] for ack in row["chunkReceipts"]] == ["resume", "upload", "upload"] and current.accepted == [0, 4, 8], "d.nearby.resume-integrity", "retry resent accepted bytes or fabricated ACKs")
            require(not result["physicalDeviceVerified"] and not result["multiRecipientVerified"], "d.nearby.terminal-receipt", "local lab claimed device proof")
            clean_receipt(area, result)
        finally:
            current.release.set()
            if sender.poll() is None:
                sender.kill()
                sender.communicate(timeout=5)
            require(sender.poll() is not None, "d.nearby.durable-ack-prefix", "owned child not reaped")

    def upload_failure():
        current = reset()
        current.mode, current.upload_status = "legacy", 500
        area, service = workspace("upload-failure")
        source = area / "input.bin"
        source.write_bytes(b"remote failure")
        result = service.send(service.build_plan([source], recipient_endpoint=endpoint), approved=True)
        require(not result["ok"] and result["status"] == "failed" and result["error"] == {"code": "recipient_upload_rejected", "remoteHttpStatus": 500} and result["cancellation"]["remoteAttempted"] and result["cancellation"]["remoteAcknowledged"] and current.cancel_calls == 1, "d.nearby.terminal-receipt", "upload failure/cancel ACK not truthful")
        clean_receipt(area, result)

    try:
        for name, action in (
            ("test_chunk_plan_enforces_part_limit_before_network", part_limit),
            ("test_pre_upgrade_plan_is_verified_then_enriched_with_chunks", migrate),
            ("test_mid_chunk_cross_process_cancel_stops_streaming", lambda: streaming_cancel(chunked=True)),
            ("test_invalid_resume_or_integrity_ack_is_never_claimed", invalid_wire),
            ("test_killed_sender_persists_receipt_and_retry_resumes", crash_retry),
            ("test_in_flight_cancel_is_shared_across_sdk_instances_and_truthful", lambda: streaming_cancel(chunked=False)),
            ("test_remote_upload_failure_returns_failed_receipt_and_cancel_ack", upload_failure),
            ("test_cancel_rejection_never_claims_remote_acknowledgement", lambda: streaming_cancel(chunked=False, rejected=True, via_child=False)),
        ):
            record(name, action)
    finally:
        peer.release.set()
        peer.cancelled.set()
        server.shutdown()
        server.server_close()
        listener.join(timeout=3)
    return {"ok": all(row["ok"] for row in cases), "cases": cases, "contracts": list(CONTRACTS), "failures": [row for row in cases if not row["ok"]],
            "durationMs": round((time.perf_counter() - started) * 1000, 3), "scratchRoot": str(root), "peerPort": proof_port(48495),
            "procedures": ["bounded-preview-before-network", "legacy-preview-migration", "mid-chunk-child-sdk-cancel", "reject-invalid-resume-and-ack", "killed-sender-ack-recovery-and-retry", "legacy-sdk-cancel", "upload-failure-cancel", "rejected-remote-cancel"],
            "observers": ["NearbySendService.get_active_transfer"], "actionReceipts": receipts, "wire": wire,
            "physicalDeviceVerified": False, "multiRecipientVerified": False, "ownedPeerClosed": not listener.is_alive()}
