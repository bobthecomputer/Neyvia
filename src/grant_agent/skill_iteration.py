from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SKILL_WRITE_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_codex_skill_file(payload: dict[str, Any]) -> tuple[Path, Path]:
    path_value = str(
        payload.get("path")
        or payload.get("sourcePath")
        or payload.get("source_path")
        or ""
    ).strip()
    if not path_value:
        raise RuntimeError("Skill source path is required.")
    codex_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    skills_root = (codex_root / "skills").resolve()
    target = Path(path_value).expanduser().resolve()
    if target.name != "SKILL.md":
        raise RuntimeError("Only SKILL.md skill files can be revised.")
    try:
        target.relative_to(skills_root)
    except ValueError as exc:
        raise RuntimeError("Skill file must live under the local Codex skills directory.") from exc
    if not target.exists():
        raise RuntimeError(f"Skill file does not exist: {target}")
    return skills_root, target


def validate_codex_skill_markdown(content: str) -> dict[str, Any]:
    normalized = str(content or "").replace("\r\n", "\n").strip() + "\n"
    errors: list[str] = []
    if len(normalized.encode("utf-8")) > 512_000:
        errors.append("SKILL.md exceeds the 500 KB live-iteration limit.")
    if not normalized.startswith("---\n"):
        errors.append("SKILL.md must start with YAML frontmatter.")
        frontmatter = ""
        body = normalized
    else:
        parts = normalized.split("---", 2)
        frontmatter = parts[1] if len(parts) >= 3 else ""
        body = parts[2] if len(parts) >= 3 else ""
        if len(parts) < 3:
            errors.append("SKILL.md frontmatter is not closed with ---.")
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line.strip())
        if match:
            fields[match.group(1).lower()] = match.group(2).strip().strip("\"'")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name:
        errors.append("Skill frontmatter requires name.")
    elif not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        errors.append("Skill name must use lowercase letters, digits, and hyphens (64 characters maximum).")
    if not description:
        errors.append("Skill frontmatter requires a description that explains when it should trigger.")
    if not body.strip():
        errors.append("Skill instructions are empty.")
    if len(body.splitlines()) > 500:
        errors.append("SKILL.md instructions exceed 500 lines; move detailed material into references.")
    return {
        "ok": not errors,
        "errors": errors,
        "name": name,
        "description": description,
        "lineCount": len(normalized.splitlines()),
        "sizeBytes": len(normalized.encode("utf-8")),
        "content": normalized,
    }


def read_codex_skill_file(payload: dict[str, Any]) -> dict[str, Any]:
    _, target = resolve_codex_skill_file(payload)
    content = target.read_text(encoding="utf-8")
    validation = validate_codex_skill_markdown(content)
    return {
        "schema": "fluxio.codex_skill_file.v1",
        "ok": True,
        "skillId": str(payload.get("skillId") or payload.get("skill_id") or target.parent.name),
        "path": str(target),
        "fileName": target.name,
        "sha256": _sha256_file(target),
        "content": content,
        "validation": {key: value for key, value in validation.items() if key != "content"},
    }


def iterate_codex_skill_file(payload: dict[str, Any], control_root: Path) -> dict[str, Any]:
    _, target = resolve_codex_skill_file(payload)
    content = str(payload.get("content") or payload.get("instructions") or payload.get("body") or "")
    validation = validate_codex_skill_markdown(content)
    if not validation["ok"]:
        raise RuntimeError("Skill validation failed: " + " ".join(validation["errors"]))
    normalized_content = str(validation["content"])
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    skill_id = str(payload.get("skillId") or payload.get("skill_id") or target.parent.name).strip() or target.parent.name
    expected_sha = str(payload.get("expectedSha256") or payload.get("expected_sha256") or "").strip().lower()
    request_text = str(payload.get("request") or payload.get("iterationRequest") or "").strip()
    safe_skill_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", skill_id).strip(".-")[:96] or "skill"

    from .harness_jobs import _exclusive_job_lock
    with _SKILL_WRITE_LOCK, _exclusive_job_lock(target):
        original = target.read_text(encoding="utf-8")
        before_sha = _sha256_file(target)
        if expected_sha and not hmac.compare_digest(expected_sha, before_sha.lower()):
            raise RuntimeError("Skill changed since it was loaded. Reload the current version before applying this revision.")
        if original.replace("\r\n", "\n").rstrip() == normalized_content.rstrip():
            return {
                "schema": "fluxio.codex_skill_revision_receipt.v1",
                "ok": True,
                "unchanged": True,
                "skillId": skill_id,
                "sessionId": session_id,
                "path": str(target),
                "fileName": target.name,
                "beforeSha256": before_sha,
                "afterSha256": before_sha,
                "content": original,
                "validation": {key: value for key, value in validation.items() if key != "content"},
            }

        saved_at = datetime.now(timezone.utc).isoformat()
        version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        revision_root = control_root.resolve() / ".agent_control" / "skill_revisions" / safe_skill_id
        revision_root.mkdir(parents=True, exist_ok=True)
        backup = revision_root / f"{version}-before.md"
        backup.write_text(original, encoding="utf-8")
        temp_target = target.with_name(f".{target.name}.{version}.tmp")
        temp_target.write_text(normalized_content, encoding="utf-8")
        os.replace(temp_target, target)
        after_sha = _sha256_file(target)
        receipt_path = revision_root / f"{version}.json"
        receipt = {
            "schema": "fluxio.codex_skill_revision_receipt.v1",
            "ok": True,
            "unchanged": False,
            "version": version,
            "skillId": skill_id,
            "sessionId": session_id,
            "path": str(target),
            "fileName": target.name,
            "backupPath": str(backup),
            "receiptPath": str(receipt_path),
            "beforeSha256": before_sha,
            "afterSha256": after_sha,
            "request": request_text,
            "savedAt": saved_at,
            "validation": {key: value for key, value in validation.items() if key != "content"},
        }
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        from .proofs_d_native import require
        require(target.read_text(encoding="utf-8") == normalized_content and backup.read_text(encoding="utf-8") == original
                and json.loads(receipt_path.read_text(encoding="utf-8")) == receipt,
                "native.tools.skill-revision", "skill revision, preserved original and version receipt disagree")
        ledger_path = control_root.resolve() / ".agent_control" / "skill_revision_receipts.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(receipt, separators=(",", ":")) + "\n")

    return {**receipt, "content": normalized_content}


def save_codex_skill_file(payload: dict[str, Any], control_root: Path) -> dict[str, Any]:
    result = iterate_codex_skill_file(payload, control_root)
    return {
        **result,
        "schema": "fluxio.codex_skill_save_receipt.v1",
        "savedAt": datetime.now(timezone.utc).isoformat(),
    }
