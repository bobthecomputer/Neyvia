"""Read-only validation for immutable agent-submission receipts.

The gate intentionally verifies claims against a worktree and the declared Git
baseline.  It never rewrites the receipt or either tree: acceptance means the
receipt is internally consistent and its evidence still describes the source.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .subprocess_utils import hidden_windows_subprocess_kwargs


SCHEMA = "neyvia.agent-submission-receipt.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_KEY_RE = re.compile(r"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)", re.IGNORECASE)
SECRET_VALUE_RES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:^|\s)(?:bearer|basic)\s+\S+", re.IGNORECASE),
    re.compile(r"(?:^|\b)(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|AIza[\w-]{20,})"),
    re.compile(r"(?:api[_-]?key|password|secret|token)\s*[=:]\s*\S+", re.IGNORECASE),
)


@dataclass(frozen=True)
class GateResult:
    ok: bool
    errors: tuple[str, ...]
    checked_files: int
    checked_proofs: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "neyvia.agent-submission-gate-result.v1",
            "ok": self.ok,
            "errors": list(self.errors),
            "checkedFiles": self.checked_files,
            "checkedProofs": self.checked_proofs,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value.lower()))


def _safe_path(root: Path, value: object, label: str, errors: list[str]) -> tuple[str, Path] | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        errors.append(f"{label} must be a non-empty relative path")
        return None
    candidate = (root / value).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        errors.append(f"{label} escapes the workspace: {value}")
        return None
    return relative.as_posix(), candidate


def _safe_file(root: Path, value: object, label: str, errors: list[str]) -> tuple[str, Path] | None:
    resolved = _safe_path(root, value, label, errors)
    if not resolved:
        return None
    relative, candidate = resolved
    if not candidate.is_file():
        errors.append(f"{label} is missing: {relative}")
        return None
    return relative, candidate


def _matches(path: str, patterns: Iterable[object]) -> bool:
    return any(isinstance(pattern, str) and fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _git_baseline_sha256(root: Path, commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _proof_source_hashes(value: object) -> dict[str, str]:
    """Extract sourceHashes found at any depth of a JSON proof."""
    found: dict[str, str] = {}
    if isinstance(value, dict):
        hashes = value.get("sourceHashes")
        if isinstance(hashes, dict):
            for path, digest in hashes.items():
                if isinstance(path, str) and isinstance(digest, str):
                    found[path] = digest.lower()
        for nested in value.values():
            found.update(_proof_source_hashes(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_proof_source_hashes(nested))
    return found


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _contains_secret_like(value: object) -> bool:
    """Screen receipt material before validation can include it in diagnostics."""
    if isinstance(value, dict):
        return any(
            SECRET_KEY_RE.search(str(key)) is not None or _contains_secret_like(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_like(item) for item in value)
    return isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_VALUE_RES)


def _git_worktree_changes(root: Path, baseline: str) -> dict[str, str]:
    """Return the complete tracked plus untracked delta from ``baseline``."""
    changed: dict[str, str] = {}
    status = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-status", "--no-renames", "-z", baseline, "--"],
        capture_output=True,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if status.returncode:
        return changed
    chunks = [item for item in status.stdout.decode("utf-8", "surrogateescape").split("\0") if item]
    for index in range(0, len(chunks) - 1, 2):
        code, path = chunks[index], chunks[index + 1]
        if code in {"A", "M", "D"}:
            changed[path] = {"A": "added", "M": "modified", "D": "deleted"}[code]
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if not untracked.returncode:
        for path in untracked.stdout.decode("utf-8", "surrogateescape").split("\0"):
            if path:
                changed[path] = "added"
    return changed


def validate_receipt(
    receipt: dict[str, Any],
    *,
    root: str | Path,
    phase_policy: dict[str, Any] | None = None,
) -> GateResult:
    """Validate an incoming receipt without modifying its source workspace."""
    workspace = Path(root).resolve()
    errors: list[str] = []
    checked_files = 0
    checked_proofs = 0
    if _contains_secret_like(receipt):
        result = GateResult(False, ("receipt contains secret-like key or value",), checked_files, checked_proofs)
        from .proofs_a_control import check_submission
        check_submission(receipt, result)
        return result
    if receipt.get("schema") != SCHEMA:
        errors.append(f"schema must equal {SCHEMA}")
    for field in ("agent", "phase", "lane"):
        if not receipt.get(field):
            errors.append(f"{field} is required")
    baseline = receipt.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("commit"), str) or not baseline["commit"]:
        errors.append("baseline.commit is required")
        baseline_commit = ""
    else:
        baseline_commit = baseline["commit"]
        if subprocess.run(["git", "-C", str(workspace), "rev-parse", "--verify", f"{baseline_commit}^{{commit}}"], capture_output=True, check=False, **hidden_windows_subprocess_kwargs()).returncode:
            errors.append("baseline.commit is not available in this worktree")

    changed = receipt.get("changedFiles")
    allowed = receipt.get("allowedFiles")
    forbidden = receipt.get("forbiddenFiles")
    if not isinstance(changed, list) or not changed:
        errors.append("changedFiles must be a non-empty list")
        changed = []
    if not isinstance(allowed, list) or not allowed:
        errors.append("allowedFiles must be a non-empty list")
        allowed = []
    if not isinstance(forbidden, list):
        errors.append("forbiddenFiles must be a list")
        forbidden = []
    policy = (phase_policy or {}).get(str(receipt.get("phase")), {}) if phase_policy else {}
    policy_allowed = policy.get("allowedFiles", []) if isinstance(policy, dict) else []
    policy_forbidden = policy.get("forbiddenFiles", []) if isinstance(policy, dict) else []
    if phase_policy and not isinstance(policy, dict):
        errors.append(f"phase {receipt.get('phase')} has no policy")

    after_hashes: dict[str, str] = {}
    seen_paths: set[str] = set()
    for index, entry in enumerate(changed):
        prefix = f"changedFiles[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        change_type = entry.get("changeType", "modified")
        resolved = _safe_path(workspace, entry.get("path"), f"{prefix}.path", errors)
        if not resolved:
            continue
        path, file_path = resolved
        if path in seen_paths:
            errors.append(f"duplicate changed-file path: {path}")
            continue
        seen_paths.add(path)
        if not _matches(path, allowed):
            errors.append(f"out-of-scope changed file: {path}")
        if _matches(path, forbidden):
            errors.append(f"forbidden changed file: {path}")
        if phase_policy and (not _matches(path, policy_allowed) or _matches(path, policy_forbidden)):
            errors.append(f"out-of-phase changed file: {path}")
        before = entry.get("beforeSha256")
        after = entry.get("afterSha256")
        if change_type not in {"added", "modified", "deleted"}:
            errors.append(f"{prefix}.changeType must be added, modified, or deleted")
        baseline_hash = _git_baseline_sha256(workspace, baseline_commit, path) if baseline_commit else None
        if change_type == "added":
            if before is not None or baseline_hash is not None:
                errors.append(f"{prefix} added file must not have a baseline hash")
            if not _is_sha256(after):
                errors.append(f"{prefix}.afterSha256 must be SHA-256")
            elif not file_path.is_file():
                errors.append(f"{prefix}.path is missing: {path}")
            else:
                actual = _sha256(file_path)
                checked_files += 1
                if actual != after.lower():
                    errors.append(f"changed-file hash drift: {path}")
                after_hashes[path] = actual
        elif change_type == "deleted":
            if not _is_sha256(before):
                errors.append(f"{prefix}.beforeSha256 must be SHA-256")
            elif baseline_hash != before.lower():
                errors.append(f"before-source hash is unstable for {path}")
            if after is not None:
                errors.append(f"{prefix} deleted file must have null afterSha256")
            if file_path.exists():
                errors.append(f"{prefix} deleted file still exists: {path}")
            else:
                checked_files += 1
        else:
            if not _is_sha256(before):
                errors.append(f"{prefix}.beforeSha256 must be SHA-256")
            elif baseline_hash != before.lower():
                errors.append(f"before-source hash is unstable for {path}")
            if not _is_sha256(after):
                errors.append(f"{prefix}.afterSha256 must be SHA-256")
            elif not file_path.is_file():
                errors.append(f"{prefix}.path is missing: {path}")
            else:
                actual = _sha256(file_path)
                checked_files += 1
                if actual != after.lower():
                    errors.append(f"changed-file hash drift: {path}")
                after_hashes[path] = actual
            if isinstance(before, str) and isinstance(after, str) and before.lower() == after.lower():
                errors.append(f"changed file is unchanged according to receipt: {path}")

    if baseline_commit:
        actual_changes = _git_worktree_changes(workspace, baseline_commit)
        scoped_changes = {
            path: change_type
            for path, change_type in actual_changes.items()
            if _matches(path, allowed)
        }
        declared_changes = {
            str(entry.get("path")): str(entry.get("changeType", "modified"))
            for entry in changed
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        if scoped_changes != declared_changes:
            errors.append("receipt changedFiles does not match the in-scope Git diff")

    commands = receipt.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("commands must be a non-empty list")
        commands = []
    for index, command in enumerate(commands):
        if not isinstance(command, dict) or not isinstance(command.get("command"), str) or not command["command"]:
            errors.append(f"commands[{index}].command is required")
            continue
        if not isinstance(command.get("exitCode"), int) or isinstance(command.get("exitCode"), bool):
            errors.append(f"commands[{index}].exitCode must be an integer")
        result = command.get("result")
        if not isinstance(result, dict) or not all(_valid_count(result.get(key)) for key in ("passed", "failed", "skipped")):
            errors.append(f"commands[{index}].result must contain non-negative passed/failed/skipped counts")
        elif command.get("exitCode") == 0 and result["failed"]:
            errors.append(f"commands[{index}] contradicts a zero exit code with failed tests")

    proofs = receipt.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        errors.append("proofs must be a non-empty list")
        proofs = []
    proof_kinds: set[str] = set()
    for index, proof in enumerate(proofs):
        prefix = f"proofs[{index}]"
        if not isinstance(proof, dict):
            errors.append(f"{prefix} must be an object")
            continue
        resolved = _safe_file(workspace, proof.get("path"), f"{prefix}.path", errors)
        digest = proof.get("sha256")
        if not _is_sha256(digest):
            errors.append(f"{prefix}.sha256 must be SHA-256")
        if not resolved:
            continue
        path, proof_path = resolved
        checked_proofs += 1
        if _sha256(proof_path) != str(digest).lower():
            errors.append(f"proof hash drift: {path}")
        kind = proof.get("kind", "local")
        if kind not in {"local", "live", "physical-device"}:
            errors.append(f"{prefix}.kind is unsupported")
        else:
            proof_kinds.add(kind)
        declared_hashes = proof.get("sourceHashes", {})
        if not isinstance(declared_hashes, dict):
            errors.append(f"{prefix}.sourceHashes must be an object")
            declared_hashes = {}
        nested_hashes: dict[str, str] = {}
        try:
            nested_hashes = _proof_source_hashes(json.loads(proof_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        for source_path, source_hash in {**declared_hashes, **nested_hashes}.items():
            if source_path not in after_hashes:
                errors.append(f"stale or unrelated proof source: {source_path}")
            elif not _is_sha256(source_hash) or after_hashes[source_path] != str(source_hash).lower():
                errors.append(f"stale nested proof source hash: {source_path}")

    claims = receipt.get("claims", {})
    if not isinstance(claims, dict):
        errors.append("claims must be an object")
        claims = {}
    for name, kind in (("live", "live"), ("physicalDevice", "physical-device")):
        claim = claims.get(name, {"claimed": False})
        if not isinstance(claim, dict) or not isinstance(claim.get("claimed", False), bool):
            errors.append(f"claims.{name}.claimed must be boolean")
        elif claim.get("claimed") and kind not in proof_kinds:
            errors.append(f"unproven {name} claim requires a {kind} proof")

    summary = receipt.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary is required")
    else:
        expected = {"changedFiles": len(changed), "proofFiles": len(proofs), "commandCount": len(commands)}
        for key, count in expected.items():
            if summary.get(key) != count:
                errors.append(f"summary.{key} contradicts receipt contents")
    result = GateResult(not errors, tuple(errors), checked_files, checked_proofs)
    from .proofs_a_control import check_submission
    check_submission(receipt, result)
    return result
