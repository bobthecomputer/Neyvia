"""Deterministic final-workspace proof auditing for Neyvia Native."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .subprocess_utils import hidden_windows_subprocess_kwargs


PROOF_SCHEMA = "neyvia.native-proof-audit/v1"
_SKIP_DIRS = {
    ".git",
    ".agent_control",
    ".agent_runs",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _hash_bytes(raw.encode("utf-8"))


def _safe_tail(value: str, limit: int = 8000) -> str:
    return str(value or "")[-limit:]


@dataclass(frozen=True)
class WorkspaceSnapshot:
    root: str
    fingerprint: str
    files: int
    bytes: int
    entries: dict[str, dict[str, Any]]
    truncated: bool

    def public_dict(self, include_entries: bool = False) -> dict[str, Any]:
        payload = {
            "root": self.root,
            "fingerprint": self.fingerprint,
            "files": self.files,
            "bytes": self.bytes,
            "truncated": self.truncated,
        }
        if include_entries:
            payload["entries"] = self.entries
        return payload


class NativeProofAuditor:
    def __init__(
        self,
        root: Path,
        *,
        maximum_files: int = 6000,
        maximum_file_bytes: int = 8 * 1024 * 1024,
        timeout_seconds: int = 240,
    ) -> None:
        self.root = root.resolve()
        self.maximum_files = max(100, int(maximum_files))
        self.maximum_file_bytes = max(1024, int(maximum_file_bytes))
        self.timeout_seconds = max(10, int(timeout_seconds))

    def snapshot(self) -> WorkspaceSnapshot:
        entries: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        truncated = False
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part in _SKIP_DIRS for part in relative.parts):
                continue
            if path.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if len(entries) >= self.maximum_files:
                truncated = True
                break
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.maximum_file_bytes:
                entries[relative.as_posix()] = {
                    "size": size,
                    "sha256": "oversized-not-hashed",
                }
                total_bytes += size
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            entries[relative.as_posix()] = {"size": size, "sha256": _hash_bytes(data)}
            total_bytes += size
        return WorkspaceSnapshot(
            root=str(self.root),
            fingerprint=_canonical_hash(entries),
            files=len(entries),
            bytes=total_bytes,
            entries=entries,
            truncated=truncated,
        )

    @staticmethod
    def diff(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> dict[str, Any]:
        before_keys = set(before.entries)
        after_keys = set(after.entries)
        added = sorted(after_keys - before_keys)
        removed = sorted(before_keys - after_keys)
        modified = sorted(
            key
            for key in before_keys & after_keys
            if before.entries[key] != after.entries[key]
        )
        return {
            "changed": bool(added or removed or modified),
            "added": added,
            "removed": removed,
            "modified": modified,
            "changeCount": len(added) + len(removed) + len(modified),
        }

    def _verification_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        proof_command = self.root / "scripts" / "verify_proofs.py"
        if proof_command.is_file():
            candidates.append({"id": "python:manual-contracts", "quality": "manual-contracts",
                               "argv": [sys.executable, str(proof_command), "--root", str(self.root)]})
        package_path = self.root / "package.json"
        if package_path.is_file():
            try:
                package = json.loads(package_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                package = {}
            scripts = package.get("scripts") if isinstance(package, dict) else {}
            if isinstance(scripts, dict):
                for name, quality in (
                    ("test", "test"),
                    ("verify", "verification"),
                    ("frontend:build", "build"),
                    ("build", "build"),
                    ("lint", "lint"),
                    ("typecheck", "typecheck"),
                ):
                    if name in scripts:
                        candidates.append(
                            {
                                "id": f"npm:{name}",
                                "quality": quality,
                                "argv": ["npm", "run", name],
                            }
                        )
        if (self.root / "pyproject.toml").is_file() and (self.root / "tests").is_dir():
            candidates.append(
                {
                    "id": "python:pytest",
                    "quality": "test",
                    "argv": [sys.executable, "-m", "pytest", "-q"],
                }
            )
        if (self.root / "Cargo.toml").is_file():
            candidates.append(
                {"id": "cargo:test", "quality": "test", "argv": ["cargo", "test", "--quiet"]}
            )
        if (self.root / "go.mod").is_file():
            candidates.append(
                {"id": "go:test", "quality": "test", "argv": ["go", "test", "./..."]}
            )
        return candidates

    def select_verification(self, proof_gates: Iterable[str]) -> dict[str, Any] | None:
        candidates = self._verification_candidates()
        if not candidates:
            return None
        priorities = {"manual-contracts": -1, "test": 0, "verification": 1, "typecheck": 2, "build": 3, "lint": 4}
        candidates.sort(key=lambda row: (priorities.get(str(row["quality"]), 9), str(row["id"])))
        return candidates[0]

    def _run_check(self, candidate: dict[str, Any]) -> dict[str, Any]:
        started = _utc_now()
        before = time.monotonic()
        try:
            completed = subprocess.run(
                list(candidate["argv"]),
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env=dict(os.environ),
                **hidden_windows_subprocess_kwargs(),
            )
            timed_out = False
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            return_code = None
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        except OSError as exc:
            timed_out = False
            return_code = None
            stdout = ""
            stderr = str(exc)
        finished = _utc_now()
        duration_ms = max(1, int((time.monotonic() - before) * 1000))
        result = {
            "candidateId": candidate["id"],
            "quality": candidate["quality"],
            "argv": list(candidate["argv"]),
            "shell": False,
            "startedAt": started,
            "finishedAt": finished,
            "durationMs": duration_ms,
            "returnCode": return_code,
            "timedOut": timed_out,
            "stdoutTail": _safe_tail(stdout),
            "stderrTail": _safe_tail(stderr),
            "passed": return_code == 0 and not timed_out,
        }
        result["receiptHash"] = _canonical_hash(result)
        return result

    @staticmethod
    def audit_receipts(paths: Iterable[str]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for raw in paths:
            path = Path(str(raw or ""))
            row: dict[str, Any] = {"path": str(path), "readable": False, "accepted": False}
            if not path.is_file():
                row["reason"] = "missing"
                rows.append(row)
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                row["reason"] = f"invalid_json:{type(exc).__name__}"
                rows.append(row)
                continue
            status = str(payload.get("status") or payload.get("result") or "").lower()
            ok = payload.get("ok")
            row.update(
                {
                    "readable": True,
                    "status": status,
                    "schema": str(payload.get("schema") or ""),
                    "accepted": status not in {"failed", "error", "blocked", "cancelled"}
                    and ok is not False,
                    "sha256": _hash_bytes(path.read_bytes()),
                }
            )
            if not row["accepted"]:
                row["reason"] = "receipt_reports_failure"
            rows.append(row)
        return {
            "receipts": rows,
            "coverage": len(rows),
            "accepted": all(row["accepted"] for row in rows) if rows else True,
        }

    def audit(
        self,
        *,
        before: WorkspaceSnapshot,
        behavior_plan: dict[str, Any],
        allow_mutations: bool,
        receipt_paths: Iterable[str] = (),
    ) -> dict[str, Any]:
        after = self.snapshot()
        delta = self.diff(before, after)
        capsule = behavior_plan.get("capsule") or {}
        proof_gates = list(capsule.get("proofGates") or ())
        mutation_expected = bool(capsule.get("mutationExpected"))
        receipt_audit = self.audit_receipts(receipt_paths)
        verification_required = bool(
            allow_mutations
            and mutation_expected
            and any(gate in proof_gates for gate in ("deterministic_check", "user_path_receipt"))
        )
        candidate = self.select_verification(proof_gates) if verification_required else None
        check = self._run_check(candidate) if candidate else None
        failures: list[str] = []
        if receipt_audit["accepted"] is False:
            failures.append("A declared child/tool receipt is missing or reports failure.")
        if allow_mutations and mutation_expected and not delta["changed"]:
            failures.append("The behavior contract expected a workspace delta, but none was observed.")
        if verification_required and candidate is None:
            failures.append("No bounded deterministic verification command was discoverable.")
        if check is not None and not check["passed"]:
            failures.append("The selected deterministic verification command failed or timed out.")
        final_fingerprint_fresh = after.fingerprint == self.snapshot().fingerprint
        if not final_fingerprint_fresh:
            failures.append("The workspace changed while the final proof audit was being sealed.")
        if failures:
            status = "blocked"
            run_status = "blocked"
        elif allow_mutations and delta["changed"]:
            status = "verified" if check is not None else "receipt_verified_change"
            run_status = "completed"
        else:
            status = "completed_read_only"
            run_status = "completed"
        result = {
            "schema": PROOF_SCHEMA,
            "status": status,
            "runStatus": run_status,
            "proofGates": proof_gates,
            "before": before.public_dict(),
            "after": after.public_dict(),
            "workspaceDelta": delta,
            "receiptAudit": receipt_audit,
            "verificationRequired": verification_required,
            "selectedVerification": candidate,
            "verification": check,
            "finalWorkspaceFingerprintFresh": final_fingerprint_fresh,
            "failures": failures,
            "truthBoundary": (
                "Passing checks prove only the selected checks and receipt integrity; "
                "they do not prove universal semantic correctness."
            ),
            "sealedAt": _utc_now(),
        }
        result["auditHash"] = _canonical_hash({key: value for key, value in result.items() if key != "auditHash"})
        from .proofs_d_native import check_audit
        check_audit(result)
        return result
