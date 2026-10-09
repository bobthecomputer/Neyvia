"""Content-addressed, workspace-bounded checkpoints for Neyvia Native.

Restore is journaled and fail-closed: every approved restore is fully preflighted,
the current workspace state is captured before mutation, and an interrupted or
failed restore is rolled back before another restore is allowed to proceed.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


CHECKPOINT_SCHEMA = "neyvia.native-checkpoint/v1"
RESTORE_SCHEMA = "neyvia.native-checkpoint-restore/v1"
RESTORE_TRANSACTION_SCHEMA = "neyvia.native-checkpoint-restore-transaction/v1"
RESTORE_LOCK_TIMEOUT_SECONDS = 10.0
RESTORE_LOCK_POLL_SECONDS = 0.05

_BLOCKED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
_BLOCKED_PARTS = {".git", ".agent_control", ".ssh", "node_modules", "target", "dist", "build"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(raw.encode("utf-8"))


def _safe_id(value: object, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return (clean or fallback)[:120]


def _fsync_directory(path: Path) -> None:
    """Best-effort metadata flush after replace/unlink on supporting filesystems."""

    if os.name == "nt":
        return
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            0o600,
        )
        raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _try_advisory_restore_lock(descriptor: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
                exc, "winerror", None
            ) in {32, 33, 36}:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise
    return True


def _release_advisory_restore_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


class NativeCheckpointStore:
    def __init__(
        self,
        root: Path,
        *,
        maximum_files: int = 2000,
        maximum_total_bytes: int = 256 * 1024 * 1024,
        maximum_file_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.root = root.resolve()
        self.state_root = self.root / ".agent_control" / "neyvia_agent" / "checkpoints"
        self.blob_root = self.state_root / "blobs"
        self.manifest_root = self.state_root / "manifests"
        self.restore_root = self.state_root / "restores"
        self.transaction_root = self.restore_root / "transactions"
        for path in (
            self.blob_root,
            self.manifest_root,
            self.restore_root,
            self.transaction_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.maximum_files = max(1, int(maximum_files))
        self.maximum_total_bytes = max(1024, int(maximum_total_bytes))
        self.maximum_file_bytes = max(1024, int(maximum_file_bytes))
        self.recovery_error = ""
        try:
            self._recover_incomplete_restores()
        except (OSError, RuntimeError, ValueError) as exc:
            # A broken restore must degrade checkpoint recovery, not take down
            # unrelated Native planning/goals/learning RPC methods.
            self.recovery_error = str(exc)

    def _resolve(self, raw: str | Path) -> Path:
        path = Path(raw)
        candidate = path.resolve() if path.is_absolute() else (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"Checkpoint path escapes the workspace: {raw}")
        relative = candidate.relative_to(self.root)
        if candidate.name.lower() in _BLOCKED_NAMES or any(
            part in _BLOCKED_PARTS for part in relative.parts
        ):
            raise ValueError(f"Checkpoint path is protected or secret-bearing: {relative}")
        if candidate.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            raise ValueError(f"Checkpoint refuses private-key material: {relative}")
        return candidate

    def _files(self, paths: Iterable[str | Path]) -> list[Path]:
        files: dict[str, Path] = {}
        for raw in paths:
            candidate = self._resolve(raw)
            if candidate.is_file() or not candidate.exists():
                files[candidate.relative_to(self.root).as_posix()] = candidate
                continue
            if candidate.is_dir():
                for path in sorted(candidate.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(self.root)
                    if path.name.lower() in _BLOCKED_NAMES or any(
                        part in _BLOCKED_PARTS for part in relative.parts
                    ):
                        continue
                    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
                        continue
                    files[relative.as_posix()] = path
        return [files[key] for key in sorted(files)]

    def _write_blob(self, data: bytes) -> str:
        digest = _sha256(data)
        blob = self.blob_root / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        if blob.exists():
            if not blob.is_file() or _sha256(blob.read_bytes()) != digest:
                raise ValueError(f"Checkpoint blob integrity failed: {digest}")
            return digest

        temporary = blob.with_name(f"{blob.name}.tmp.{uuid.uuid4().hex[:8]}")
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        os.replace(temporary, blob)
        _fsync_directory(blob.parent)
        return digest

    @contextmanager
    def _restore_lock(self) -> Iterator[None]:
        guard_path = self.state_root / ".restore.guard"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        descriptor = os.open(guard_path, flags, 0o600)
        held = False
        deadline = time.monotonic() + RESTORE_LOCK_TIMEOUT_SECONDS
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            while not held:
                try:
                    held = _try_advisory_restore_lock(descriptor)
                except OSError as exc:
                    raise RuntimeError(
                        "The workspace filesystem cannot provide crash-safe checkpoint "
                        f"restore locking: {type(exc).__name__}: {exc}"
                    ) from exc
                if held:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for the checkpoint restore lock. Another "
                        "Neyvia process is still restoring this workspace."
                    )
                time.sleep(RESTORE_LOCK_POLL_SECONDS)
            yield
        finally:
            if held:
                try:
                    _release_advisory_restore_lock(descriptor)
                except OSError:
                    pass
            os.close(descriptor)

    def create(
        self,
        paths: Iterable[str | Path],
        *,
        run_id: str = "",
        reason: str = "Before bounded Native mutation",
    ) -> dict[str, Any]:
        selected = self._files(paths)
        if len(selected) > self.maximum_files:
            raise ValueError(f"Checkpoint exceeds the {self.maximum_files}-file limit.")
        total = 0
        entries: list[dict[str, Any]] = []
        for path in selected:
            relative = path.relative_to(self.root).as_posix()
            if not path.exists():
                entries.append({"path": relative, "existed": False, "size": 0, "sha256": ""})
                continue
            size = path.stat().st_size
            if size > self.maximum_file_bytes:
                raise ValueError(f"Checkpoint file exceeds per-file limit: {relative}")
            total += size
            if total > self.maximum_total_bytes:
                raise ValueError("Checkpoint exceeds the total byte limit.")
            data = path.read_bytes()
            digest = self._write_blob(data)
            entries.append(
                {
                    "path": relative,
                    "existed": True,
                    "size": size,
                    "sha256": digest,
                    "mode": path.stat().st_mode & 0o777,
                }
            )
        checkpoint_id = _safe_id(
            f"checkpoint-{run_id or uuid.uuid4().hex[:12]}-{uuid.uuid4().hex[:8]}",
            "checkpoint",
        )
        manifest = {
            "schema": CHECKPOINT_SCHEMA,
            "checkpointId": checkpoint_id,
            "runId": str(run_id or ""),
            "workspaceRoot": str(self.root),
            "reason": str(reason or "")[:2000],
            "entries": entries,
            "fileCount": len(entries),
            "totalBytes": total,
            "createdAt": _utc_now(),
        }
        manifest["manifestHash"] = _canonical_hash(manifest)
        path = self.manifest_root / f"{checkpoint_id}.json"
        _atomic_write_json(path, manifest)
        from .proofs_d_native import require
        require(json.loads(path.read_text(encoding="utf-8")) == manifest
                and all(not entry["existed"] or self._entry_matches_workspace(entry) for entry in entries),
                "native.checkpoints.capture", "checkpoint manifest or captured file content changed before return")
        return {**manifest, "manifestPath": str(path)}

    def load(self, checkpoint_id: str) -> dict[str, Any]:
        normalized = _safe_id(checkpoint_id, "invalid")
        path = self.manifest_root / f"{normalized}.json"
        if not path.is_file():
            raise KeyError(f"Unknown Native checkpoint: {normalized}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        supplied = str(payload.pop("manifestHash", ""))
        expected = _canonical_hash(payload)
        payload["manifestHash"] = supplied
        if supplied != expected:
            raise ValueError(f"Checkpoint manifest integrity failed: {normalized}")
        payload["manifestPath"] = str(path)
        return payload

    def _validated_restore_entries(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        raw_entries = manifest.get("entries") or []
        if not isinstance(raw_entries, list):
            raise ValueError("Checkpoint manifest entries are invalid.")
        if len(raw_entries) > self.maximum_files:
            raise ValueError(f"Checkpoint exceeds the {self.maximum_files}-file restore limit.")

        total = 0
        validated: list[dict[str, Any]] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError("Checkpoint manifest contains a non-object entry.")
            relative = str(raw_entry.get("path") or "").strip()
            if not relative:
                raise ValueError("Checkpoint manifest contains an empty path.")
            target = self._resolve(relative)
            canonical_relative = target.relative_to(self.root).as_posix()
            if canonical_relative != Path(relative).as_posix():
                raise ValueError(
                    f"Checkpoint path no longer resolves to its recorded workspace path: {relative}"
                )
            existed = bool(raw_entry.get("existed"))
            entry = {
                "path": canonical_relative,
                "existed": existed,
                "size": int(raw_entry.get("size") or 0),
                "sha256": str(raw_entry.get("sha256") or ""),
            }
            if raw_entry.get("mode") is not None:
                entry["mode"] = int(raw_entry["mode"])
            if existed:
                digest = entry["sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError(f"Checkpoint digest is invalid: {relative}")
                blob = self.blob_root / digest[:2] / digest
                if not blob.is_file():
                    raise ValueError(f"Checkpoint content blob is missing: {relative}")
                data = blob.read_bytes()
                if _sha256(data) != digest:
                    raise ValueError(f"Checkpoint content blob is corrupt: {relative}")
                if len(data) != entry["size"]:
                    raise ValueError(f"Checkpoint content size does not match manifest: {relative}")
                total += len(data)
                if len(data) > self.maximum_file_bytes:
                    raise ValueError(f"Checkpoint file exceeds per-file restore limit: {relative}")
                if total > self.maximum_total_bytes:
                    raise ValueError("Checkpoint exceeds the total restore byte limit.")
            validated.append(entry)
        return validated

    def _snapshot_workspace(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        before: list[dict[str, Any]] = []
        total = 0
        for entry in entries:
            relative = str(entry["path"])
            target = self._resolve(relative)
            if target.exists() and target.is_dir():
                raise ValueError(
                    f"Checkpoint restore target is now a directory and cannot be replaced safely: {relative}"
                )
            if not target.exists():
                before.append({"path": relative, "existed": False, "size": 0, "sha256": ""})
                continue
            size = target.stat().st_size
            if size > self.maximum_file_bytes:
                raise ValueError(
                    f"Current file is too large to protect before restore: {relative}"
                )
            total += size
            if total > self.maximum_total_bytes:
                raise ValueError(
                    "Current workspace state exceeds the rollback byte limit; "
                    "restore was not started."
                )
            data = target.read_bytes()
            digest = self._write_blob(data)
            before.append(
                {
                    "path": relative,
                    "existed": True,
                    "size": size,
                    "sha256": digest,
                    "mode": target.stat().st_mode & 0o777,
                }
            )
        return before

    def _transaction_path(self, transaction_id: str) -> Path:
        return self.transaction_root / f"{_safe_id(transaction_id, 'invalid')}.json"

    def _write_transaction(self, transaction: dict[str, Any]) -> dict[str, Any]:
        payload = dict(transaction)
        payload["updatedAt"] = _utc_now()
        payload.pop("journalHash", None)
        payload["journalHash"] = _canonical_hash(payload)
        _atomic_write_json(self._transaction_path(str(payload["transactionId"])), payload)
        return payload

    def _load_transaction(self, path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != RESTORE_TRANSACTION_SCHEMA:
            raise ValueError(f"Unsupported restore transaction journal: {path.name}")
        supplied = str(payload.pop("journalHash", ""))
        expected = _canonical_hash(payload)
        payload["journalHash"] = supplied
        if not supplied or supplied != expected:
            raise ValueError(f"Restore transaction journal integrity failed: {path.name}")
        recorded_root = str(payload.get("workspaceRoot") or "").strip()
        if not recorded_root or Path(recorded_root).resolve() != self.root:
            raise ValueError(
                f"Restore transaction belongs to a different workspace: {path.name}"
            )
        return payload

    def _entry_matches_workspace(self, entry: dict[str, Any]) -> bool:
        """Return whether the workspace still matches one recorded file state."""

        relative = str(entry.get("path") or "")
        target = self._resolve(relative)
        existed = bool(entry.get("existed"))
        if not existed:
            return not target.exists()
        if not target.is_file():
            return False
        try:
            stat = target.stat()
            expected_size = int(entry.get("size") or 0)
            if stat.st_size != expected_size:
                return False
            digest = str(entry.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                return False
            if _sha256(target.read_bytes()) != digest:
                return False
            if os.name != "nt" and entry.get("mode") is not None:
                if stat.st_mode & 0o777 != int(entry["mode"]):
                    return False
        except (OSError, ValueError):
            return False
        return True

    def _rollback_conflicts(self, transaction: dict[str, Any]) -> list[str]:
        """Detect unrelated edits before recovery overwrites any workspace path.

        During an interrupted apply/rollback each affected path must still be in
        either its captured before-image or requested checkpoint state. Anything
        else is treated as a concurrent external edit and is preserved for manual
        recovery instead of being silently overwritten.
        """

        before_entries = {
            str(entry.get("path") or ""): entry
            for entry in transaction.get("beforeEntries") or []
            if isinstance(entry, dict) and entry.get("path")
        }
        target_entries = {
            str(entry.get("path") or ""): entry
            for entry in transaction.get("targetEntries") or []
            if isinstance(entry, dict) and entry.get("path")
        }
        paths = sorted(set(before_entries) | set(target_entries))
        conflicts: list[str] = []
        for relative in paths:
            before = before_entries.get(relative)
            target = target_entries.get(relative)
            if before is not None and self._entry_matches_workspace(before):
                continue
            if target is not None and self._entry_matches_workspace(target):
                continue
            conflicts.append(relative)
        return conflicts

    def _replace_with_blob(self, target: Path, digest: str, mode: object = None) -> None:
        blob = self.blob_root / digest[:2] / digest
        if not blob.is_file():
            raise ValueError(f"Recovery blob is missing for {target.relative_to(self.root)}")
        data = blob.read_bytes()
        if _sha256(data) != digest:
            raise ValueError(f"Recovery blob is corrupt for {target.relative_to(self.root)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.restore.{uuid.uuid4().hex[:8]}")
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        os.replace(temporary, target)
        if mode is not None:
            try:
                os.chmod(target, int(mode))
            except OSError:
                pass
        _fsync_directory(target.parent)

    def _apply_entries(self, entries: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
        restored: list[str] = []
        removed: list[str] = []
        for entry in entries:
            relative = str(entry["path"])
            target = self._resolve(relative)
            if entry.get("existed"):
                # Recovery need not rewrite a before-image that is already exact.
                # This also lets a later locked file remain untouched while an
                # earlier successful replacement is rolled back after failure.
                if not self._entry_matches_workspace(entry):
                    self._replace_with_blob(target, str(entry["sha256"]), entry.get("mode"))
                restored.append(relative)
            elif target.exists():
                if target.is_dir():
                    raise ValueError(
                        f"Refusing to remove a directory from a file checkpoint: {relative}"
                    )
                target.unlink()
                _fsync_directory(target.parent)
                removed.append(relative)
        from .proofs_d_native import require
        require(all(self._entry_matches_workspace(entry) for entry in entries),
                "native.checkpoints.restore", "restored workspace differs from the fully validated entries")
        return restored, removed

    def _write_restore_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        payload = dict(receipt)
        payload["receiptHash"] = _canonical_hash(payload)
        checkpoint_id = _safe_id(payload.get("checkpointId"), "checkpoint")
        path = self.restore_root / (
            f"restore-{checkpoint_id}-{uuid.uuid4().hex[:8]}.json"
        )
        _atomic_write_json(path, payload)
        return {**payload, "receiptPath": str(path)}

    def _rollback_transaction_locked(
        self,
        transaction: dict[str, Any],
        *,
        trigger: str,
    ) -> tuple[dict[str, Any], list[str]]:
        status = str(transaction.get("status") or "").strip().lower()
        if status == "prepared":
            # `applying` is durably recorded before the first workspace write. A
            # crash while still `prepared` therefore has nothing to undo; changing
            # files here could destroy legitimate edits made after the crash.
            transaction = self._write_transaction(
                {
                    **transaction,
                    "status": "aborted_before_apply",
                    "workspaceSafe": True,
                    "recoveryTrigger": trigger,
                    "abortedAt": _utc_now(),
                    "recoveryFailures": [],
                }
            )
            return transaction, []

        conflicts = self._rollback_conflicts(transaction)
        if conflicts:
            failures = [
                "Workspace changed outside the checkpoint restore transaction; "
                f"automatic rollback refused to overwrite: {', '.join(conflicts)}"
            ]
            transaction = self._write_transaction(
                {
                    **transaction,
                    "status": "recovery_failed",
                    "workspaceSafe": False,
                    "recoveryTrigger": trigger,
                    "conflictPaths": conflicts,
                    "recoveryFailures": failures,
                }
            )
            return transaction, failures

        transaction = self._write_transaction(
            {
                **transaction,
                "status": "rolling_back",
                "recoveryTrigger": trigger,
            }
        )
        failures: list[str] = []
        try:
            restored, removed = self._apply_entries(
                list(transaction.get("beforeEntries") or [])
            )
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
            transaction = self._write_transaction(
                {
                    **transaction,
                    "status": "recovery_failed",
                    "workspaceSafe": False,
                    "recoveryFailures": failures,
                }
            )
            return transaction, failures

        transaction = self._write_transaction(
            {
                **transaction,
                "status": "rolled_back",
                "workspaceSafe": True,
                "rollbackRestoredPaths": restored,
                "rollbackRemovedPaths": removed,
                "rolledBackAt": _utc_now(),
                "recoveryFailures": [],
            }
        )
        return transaction, failures

    def _recover_incomplete_restores_locked(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        for path in sorted(self.transaction_root.glob("*.json")):
            try:
                transaction = self._load_transaction(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(
                    "Checkpoint restore journal is unreadable or corrupt; Neyvia "
                    f"cannot safely continue restore operations: {path.name}: {exc}"
                ) from exc

            status = str(transaction.get("status") or "").strip().lower()
            if status == "recovery_failed":
                raise RuntimeError(
                    "A previous checkpoint restore could not be rolled back safely. "
                    f"Manual recovery is required for transaction {transaction.get('transactionId')}."
                )
            if status not in {"prepared", "applying", "rolling_back"}:
                continue

            recovered_tx, failures = self._rollback_transaction_locked(
                transaction,
                trigger="startup-recovery",
            )
            if failures:
                raise RuntimeError(
                    "A previous checkpoint restore was interrupted and automatic "
                    f"recovery failed for transaction {transaction.get('transactionId')}: "
                    + "; ".join(failures)
                )
            aborted_before_apply = recovered_tx.get("status") == "aborted_before_apply"
            receipt = self._write_restore_receipt(
                {
                    "schema": RESTORE_SCHEMA,
                    "checkpointId": str(transaction.get("checkpointId") or ""),
                    "transactionId": str(transaction.get("transactionId") or ""),
                    "status": (
                        "recovered_no_mutation"
                        if aborted_before_apply
                        else "recovered_rollback"
                    ),
                    "restored": False,
                    "recovered": True,
                    "workspaceSafe": True,
                    "recoveryAction": (
                        "aborted_incomplete_restore_before_apply"
                        if aborted_before_apply
                        else "rolled_back_incomplete_restore"
                    ),
                    "restoredPaths": [],
                    "removedPaths": [],
                    "rollbackRestoredPaths": recovered_tx.get(
                        "rollbackRestoredPaths", []
                    ),
                    "rollbackRemovedPaths": recovered_tx.get(
                        "rollbackRemovedPaths", []
                    ),
                    "failures": [],
                    "finishedAt": _utc_now(),
                }
            )
            recovered.append(receipt)
        return recovered

    def _recover_incomplete_restores(self) -> list[dict[str, Any]]:
        with self._restore_lock():
            return self._recover_incomplete_restores_locked()

    def recovery_status(self) -> dict[str, Any]:
        attention_required = bool(self.recovery_error)
        return {
            "status": (
                "manual_recovery_required" if attention_required else "ready"
            ),
            "safeToRestore": not attention_required,
            "detail": self.recovery_error,
        }

    def restore(self, checkpoint_id: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            return {
                "schema": RESTORE_SCHEMA,
                "checkpointId": checkpoint_id,
                "status": "approval_required",
                "restored": False,
                "workspaceSafe": not bool(self.recovery_error),
                "recoveryStatus": self.recovery_status(),
            }

        with self._restore_lock():
            try:
                self._recover_incomplete_restores_locked()
                self.recovery_error = ""
            except (OSError, RuntimeError, ValueError) as exc:
                self.recovery_error = str(exc)
                return self._write_restore_receipt(
                    {
                        "schema": RESTORE_SCHEMA,
                        "checkpointId": checkpoint_id,
                        "status": "recovery_failed",
                        "restored": False,
                        "recovered": False,
                        "workspaceSafe": False,
                        "recoveryAction": "manual_recovery_required",
                        "recoveryStatus": self.recovery_status(),
                        "restoredPaths": [],
                        "removedPaths": [],
                        "failures": [self.recovery_error],
                        "finishedAt": _utc_now(),
                    }
                )
            try:
                manifest = self.load(checkpoint_id)
                target_entries = self._validated_restore_entries(manifest)
                before_entries = self._snapshot_workspace(target_entries)
            except Exception as exc:
                return self._write_restore_receipt(
                    {
                        "schema": RESTORE_SCHEMA,
                        "checkpointId": checkpoint_id,
                        "status": "failed_preflight",
                        "restored": False,
                        "recovered": False,
                        "workspaceSafe": True,
                        "recoveryAction": "none_required_no_mutation_started",
                        "restoredPaths": [],
                        "removedPaths": [],
                        "failures": [f"{type(exc).__name__}: {exc}"],
                        "finishedAt": _utc_now(),
                    }
                )

            transaction_id = f"restore-tx-{uuid.uuid4().hex}"
            transaction = self._write_transaction(
                {
                    "schema": RESTORE_TRANSACTION_SCHEMA,
                    "transactionId": transaction_id,
                    "checkpointId": str(manifest["checkpointId"]),
                    "status": "prepared",
                    "workspaceRoot": str(self.root),
                    "targetEntries": target_entries,
                    "beforeEntries": before_entries,
                    "workspaceSafe": True,
                    "createdAt": _utc_now(),
                }
            )
            transaction = self._write_transaction(
                {**transaction, "status": "applying", "workspaceSafe": False}
            )

            try:
                restored, removed = self._apply_entries(target_entries)
            except Exception as exc:
                original_failure = f"{type(exc).__name__}: {exc}"
                rolled_back, rollback_failures = self._rollback_transaction_locked(
                    transaction,
                    trigger="apply-failure",
                )
                workspace_safe = not rollback_failures
                return self._write_restore_receipt(
                    {
                        "schema": RESTORE_SCHEMA,
                        "checkpointId": str(manifest["checkpointId"]),
                        "transactionId": transaction_id,
                        "status": (
                            "failed_rolled_back"
                            if workspace_safe
                            else "recovery_failed"
                        ),
                        "restored": False,
                        "recovered": workspace_safe,
                        "workspaceSafe": workspace_safe,
                        "recoveryAction": (
                            "rolled_back_failed_restore"
                            if workspace_safe
                            else "manual_recovery_required"
                        ),
                        "restoredPaths": [],
                        "removedPaths": [],
                        "rollbackRestoredPaths": rolled_back.get(
                            "rollbackRestoredPaths", []
                        ),
                        "rollbackRemovedPaths": rolled_back.get(
                            "rollbackRemovedPaths", []
                        ),
                        "conflictPaths": rolled_back.get("conflictPaths", []),
                        "failures": [original_failure, *rollback_failures],
                        "finishedAt": _utc_now(),
                    }
                )

            transaction = self._write_transaction(
                {
                    **transaction,
                    "status": "committed",
                    "workspaceSafe": True,
                    "committedAt": _utc_now(),
                    "restoredPaths": restored,
                    "removedPaths": removed,
                }
            )
            return self._write_restore_receipt(
                {
                    "schema": RESTORE_SCHEMA,
                    "checkpointId": checkpoint_id,
                    "transactionId": transaction_id,
                    "status": "completed",
                    "restored": True,
                    "recovered": False,
                    "workspaceSafe": True,
                    "recoveryAction": "restore_committed",
                    "restoredPaths": restored,
                    "removedPaths": removed,
                    "failures": [],
                    "finishedAt": _utc_now(),
                }
            )

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(
            self.manifest_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[: max(1, min(200, int(limit)))]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows.append(
                {
                    "checkpointId": payload.get("checkpointId"),
                    "runId": payload.get("runId"),
                    "reason": payload.get("reason"),
                    "fileCount": payload.get("fileCount"),
                    "totalBytes": payload.get("totalBytes"),
                    "createdAt": payload.get("createdAt"),
                    "manifestPath": str(path),
                }
            )
        return rows
