from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BRIDGE_SCHEMA = "fluxio.nas_bridge.v1"
MESSAGE_SCHEMA = "fluxio.nas_message.v1"
TRANSFER_SCHEMA = "fluxio.nas_transfer.v1"
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024
_BLOB_LOCKS = tuple(threading.RLock() for _ in range(64))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: object, fallback: str = "item") -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return (name or fallback)[:120]


def _sha256(path: Path, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class TransferReceipt:
    transfer_id: str
    source: str
    destination: str
    sha256: str
    size_bytes: int
    bytes_transferred: int
    reused_bytes: int
    resumed_from_bytes: int
    duration_ms: int
    throughput_mbps: float
    status: str
    transport: str = "buffered_smb"
    schema: str = TRANSFER_SCHEMA
    created_at: str = field(default_factory=_utc_now)


class NasBridge:
    """Content-addressed message and attachment exchange for a mounted NAS root.

    The protocol keeps large payloads out of JSON envelopes, resumes interrupted
    writes from a partial file, and transfers a given SHA-256 blob only once.
    """

    def __init__(self, local_root: str | Path, nas_root: str | Path) -> None:
        self.local_root = Path(local_root).expanduser().resolve()
        self.nas_root = Path(nas_root).expanduser().resolve()
        self.bridge_root = self.nas_root / ".agent_control" / "neyvia_bridge"
        self.blob_root = self.bridge_root / "blobs" / "sha256"
        self.message_root = self.bridge_root / "messages"
        self.receipt_root = self.bridge_root / "receipts"

    @property
    def available(self) -> bool:
        return self.nas_root.exists() and self.nas_root.is_dir()

    def status(self) -> dict[str, Any]:
        return {
            "schema": BRIDGE_SCHEMA,
            "available": self.available,
            "localRoot": str(self.local_root),
            "nasRoot": str(self.nas_root),
            "bridgeRoot": str(self.bridge_root),
            "transport": "mounted-filesystem",
            "features": [
                "sha256_deduplication",
                "resumable_partial_writes",
                "atomic_message_envelopes",
                "parallel_attachment_uploads",
                "verified_receive",
            ],
        }

    def _blob_path(self, digest: str) -> Path:
        return self.blob_root / digest[:2] / digest[2:4] / digest

    @staticmethod
    def _blob_metadata_path(blob_path: Path) -> Path:
        return Path(f"{blob_path}.meta.json")

    def _existing_blob_is_valid(self, blob_path: Path, digest: str, size_bytes: int) -> bool:
        if not blob_path.is_file() or blob_path.stat().st_size != size_bytes:
            return False
        metadata_path = self._blob_metadata_path(blob_path)
        if metadata_path.is_file():
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if payload.get("sha256") == digest and int(payload.get("sizeBytes") or -1) == size_bytes:
                return True
        return _sha256(blob_path) == digest

    def _copy_resumable(self, source: Path, destination: Path, digest: str) -> TransferReceipt:
        # Independent bridge instances and attachment workers share the same
        # content-addressed partial. Keep copy, admission and metadata in one
        # lease; a process exit releases the OS guard while retaining the prefix.
        from .harness_jobs import _exclusive_job_lock
        destination.parent.mkdir(parents=True, exist_ok=True)
        shard = zlib.crc32(os.path.normcase(str(destination.resolve())).encode("utf-8")) % len(_BLOB_LOCKS)
        with _BLOB_LOCKS[shard], _exclusive_job_lock(destination, timeout_seconds=120):
            return self._copy_resumable_locked(source, destination, digest)

    def _copy_resumable_locked(self, source: Path, destination: Path, digest: str) -> TransferReceipt:
        started = time.perf_counter()
        transfer_id = f"transfer_{uuid.uuid4().hex[:12]}"
        size_bytes = source.stat().st_size
        destination.parent.mkdir(parents=True, exist_ok=True)

        if self._existing_blob_is_valid(destination, digest, size_bytes):
            return TransferReceipt(
                transfer_id=transfer_id,
                source=str(source),
                destination=str(destination),
                sha256=digest,
                size_bytes=size_bytes,
                bytes_transferred=0,
                reused_bytes=size_bytes,
                resumed_from_bytes=size_bytes,
                duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
                throughput_mbps=0.0,
                status="deduplicated",
            )

        partial = destination.with_suffix(".partial")
        resumed_from = partial.stat().st_size if partial.is_file() else 0
        if resumed_from > size_bytes:
            partial.unlink()
            resumed_from = 0

        mode = "ab" if resumed_from else "wb"
        with source.open("rb") as source_handle, partial.open(mode) as destination_handle:
            source_handle.seek(resumed_from)
            while chunk := source_handle.read(DEFAULT_CHUNK_BYTES):
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())

        if partial.stat().st_size != size_bytes:
            raise RuntimeError(
                f"NAS transfer stopped at {partial.stat().st_size} of {size_bytes} bytes; partial data was kept for resume."
            )
        copied_digest = _sha256(partial)
        if copied_digest != digest:
            raise RuntimeError("NAS transfer checksum mismatch; partial data was kept for inspection.")

        os.replace(partial, destination)
        _atomic_json(
            self._blob_metadata_path(destination),
            {
                "schema": TRANSFER_SCHEMA,
                "sha256": digest,
                "sizeBytes": size_bytes,
                "verifiedAt": _utc_now(),
            },
        )
        elapsed = max(time.perf_counter() - started, 0.000001)
        bytes_transferred = max(size_bytes - resumed_from, 0)
        return TransferReceipt(
            transfer_id=transfer_id,
            source=str(source),
            destination=str(destination),
            sha256=digest,
            size_bytes=size_bytes,
            bytes_transferred=bytes_transferred,
            reused_bytes=0,
            resumed_from_bytes=resumed_from,
            duration_ms=max(1, int(elapsed * 1000)),
            throughput_mbps=round((bytes_transferred * 8 / 1_000_000) / elapsed, 2),
            status="completed",
        )

    def send_file(self, source: str | Path) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Attachment does not exist: {source_path}")
        if not self.available:
            raise RuntimeError(f"NAS root is unavailable: {self.nas_root}")
        digest = _sha256(source_path)
        receipt = self._copy_resumable(source_path, self._blob_path(digest), digest)
        receipt_path = self.receipt_root / f"{receipt.transfer_id}.json"
        receipt_payload = asdict(receipt)
        receipt_payload["receiptPath"] = str(receipt_path)
        _atomic_json(receipt_path, receipt_payload)
        return {
            "name": source_path.name,
            "sha256": digest,
            "sizeBytes": source_path.stat().st_size,
            "blobPath": str(self._blob_path(digest)),
            "transfer": receipt_payload,
        }

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        message: str,
        attachments: Iterable[str | Path] = (),
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(f"NAS root is unavailable: {self.nas_root}")
        sender_id = _safe_name(sender, "local")
        recipient_id = _safe_name(recipient, "nas")
        attachment_paths = [Path(item).expanduser().resolve() for item in attachments]
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(attachment_paths)))) as pool:
            uploaded = list(pool.map(self.send_file, attachment_paths)) if attachment_paths else []

        message_id = f"msg_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        envelope = {
            "schema": MESSAGE_SCHEMA,
            "messageId": message_id,
            "sender": sender_id,
            "recipient": recipient_id,
            "message": str(message or "").strip(),
            "attachments": uploaded,
            "createdAt": _utc_now(),
        }
        inbox_path = self.message_root / "inbox" / recipient_id / f"{message_id}.json"
        outbox_path = self.message_root / "outbox" / sender_id / f"{message_id}.json"
        _atomic_json(inbox_path, envelope)
        _atomic_json(outbox_path, envelope)
        return {
            **envelope,
            "inboxPath": str(inbox_path),
            "outboxPath": str(outbox_path),
            "transferredBytes": sum(int(item["transfer"]["bytes_transferred"]) for item in uploaded),
            "reusedBytes": sum(int(item["transfer"]["reused_bytes"]) for item in uploaded),
        }

    def receive_messages(
        self,
        *,
        recipient: str,
        output_dir: str | Path,
        limit: int = 20,
        acknowledge: bool = False,
    ) -> dict[str, Any]:
        recipient_id = _safe_name(recipient, "local")
        inbox = self.message_root / "inbox" / recipient_id
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        messages: list[dict[str, Any]] = []
        if not inbox.exists():
            return {"schema": MESSAGE_SCHEMA, "recipient": recipient_id, "messages": []}

        for envelope_path in sorted(inbox.glob("*.json"))[: max(1, int(limit))]:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            materialized: list[dict[str, Any]] = []
            for attachment in envelope.get("attachments", []):
                digest = str(attachment.get("sha256") or "")
                blob_path = self._blob_path(digest)
                name = _safe_name(attachment.get("name"), digest[:12] or "attachment")
                destination = output_root / name
                receipt = self._copy_resumable(blob_path, destination, digest)
                materialized.append({"name": name, "path": str(destination), "transfer": asdict(receipt)})
            envelope["receivedAttachments"] = materialized
            envelope["envelopePath"] = str(envelope_path)
            if acknowledge:
                ack_path = self.message_root / "acks" / recipient_id / f"{envelope.get('messageId')}.json"
                _atomic_json(
                    ack_path,
                    {
                        "schema": MESSAGE_SCHEMA,
                        "messageId": envelope.get("messageId"),
                        "recipient": recipient_id,
                        "acknowledgedAt": _utc_now(),
                    },
                )
                envelope["ackPath"] = str(ack_path)
            messages.append(envelope)
        return {"schema": MESSAGE_SCHEMA, "recipient": recipient_id, "messages": messages}


def configured_nas_root(root: str | Path, explicit: str | Path | None = None) -> Path | None:
    root_path = Path(root).expanduser().resolve()
    mounted_project = Path("Y:/projects") / root_path.name if os.name == "nt" else None
    candidates = [
        explicit,
        os.environ.get("NEYVIA_NAS_ROOT"),
        os.environ.get("FLUXIO_NAS_ROOT"),
        mounted_project,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and path.is_dir():
            return path.resolve()
    return None


from .proofs_d_runtime import checked as _checked
NasBridge._copy_resumable = _checked("d.runtime.bridge.bytes", NasBridge._copy_resumable)
NasBridge.send_message = _checked("d.runtime.bridge.envelope", NasBridge.send_message)
NasBridge.receive_messages = _checked("d.runtime.bridge.receive", NasBridge.receive_messages)
