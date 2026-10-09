"""Selective, provider-neutral context import with durable lineage.

Neyvia never scrapes an entire provider database.  A user chooses an exported
JSON, JSONL, or Markdown file; Neyvia previews exactly what it can understand,
redacts obvious credentials, then imports only selected records.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .durability import append_jsonl_durable, atomic_write_json

CONTEXT_IMPORT_SCHEMA = "neyvia.context_import.v1"
CONTEXT_IMPORT_PREVIEW_SCHEMA = "neyvia.context_import.preview.v1"
CONTEXT_IMPORT_RECEIPT_SCHEMA = "neyvia.context_import.receipt.v1"
SUPPORTED_PROVIDERS = ("codex", "claude-code", "opencode", "hermes", "openclaw")
SUPPORTED_EXTENSIONS = {".json", ".jsonl", ".ndjson", ".md", ".txt"}
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_ITEMS = 10_000
_IMPORTS_RELATIVE = Path(".agent_control") / "neyvia" / "context_imports"
_STAGED_UPLOADS_RELATIVE = Path(".agent_control") / "neyvia" / "context_uploads"
_UPLOAD_ID_PATTERN = re.compile(r"^upload-[0-9a-f]{24}$")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END [^-]+-----"),
    re.compile(r"\b(?:sk|ghp|gho|xoxb|xoxp|xoxa|xoxr)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9_./+-]{20,}"
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_display_name(value: object) -> str:
    """Return a safe display name; it is never used as a destination path."""

    raw = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    raw = re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()
    raw = re.sub(r"[^A-Za-z0-9._ -]", "_", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .")[:120]
    if not raw or raw in {".", ".."}:
        raise ValueError("A supported export filename is required.")
    return raw


def _validate_extension(name: str) -> None:
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Supported context exports are JSON, JSONL, Markdown, or text.")


def stage_upload(
    root: str | Path,
    *,
    filename: str,
    chunks: Iterable[bytes],
) -> dict[str, Any]:
    """Stream an explicitly selected browser file into a generated upload area."""

    display_name = _sanitize_display_name(filename)
    _validate_extension(display_name)
    upload_id = f"upload-{uuid.uuid4().hex[:24]}"
    target = Path(root).resolve() / _STAGED_UPLOADS_RELATIVE / upload_id
    target.mkdir(parents=True, exist_ok=False)
    content_path = target / "content"
    digest = hashlib.sha256()
    total = 0
    try:
        with content_path.open("wb") as handle:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise ValueError("Upload chunks must contain bytes.")
                data = bytes(chunk)
                total += len(data)
                if total > MAX_EXPORT_BYTES:
                    raise ValueError(f"Context export exceeds the {MAX_EXPORT_BYTES // (1024 * 1024)} MiB limit.")
                digest.update(data)
                handle.write(data)
        if total <= 0:
            raise ValueError("The selected context export is empty.")
        receipt = {
            "schema": "neyvia.context_upload.receipt.v1",
            "uploadId": upload_id,
            "displayName": display_name,
            "sizeBytes": total,
            "sha256": digest.hexdigest(),
            "stagedAt": _now(),
        }
        atomic_write_json(target / "receipt.json", receipt)
        from .proofs_a_control import check_upload
        check_upload(target, receipt)
        return receipt
    except Exception:
        for path in (content_path, target / "receipt.json"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            target.rmdir()
        except OSError:
            pass
        raise


def _resolve_staged_upload(root: str | Path, upload_id: str, *, expected_sha256: str | None = None) -> tuple[Path, dict[str, Any]]:
    normalized = str(upload_id or "").strip().lower()
    if not _UPLOAD_ID_PATTERN.fullmatch(normalized):
        raise ValueError("A valid staged upload id is required.")
    target = Path(root).resolve() / _STAGED_UPLOADS_RELATIVE / normalized
    receipt_path = target / "receipt.json"
    content_path = target / "content"
    if not receipt_path.is_file() or not content_path.is_file():
        raise ValueError(f"Staged upload {normalized} is incomplete.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Staged upload {normalized} has an invalid durable receipt.") from exc
    if not isinstance(receipt, dict) or receipt.get("uploadId") != normalized:
        raise ValueError(f"Staged upload {normalized} has an invalid durable identity.")
    recorded_sha = str(receipt.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_sha):
        raise ValueError(f"Staged upload {normalized} has no valid SHA-256 receipt.")
    recorded_size = int(receipt.get("sizeBytes") or -1)
    if recorded_size < 0 or recorded_size > MAX_EXPORT_BYTES:
        raise ValueError(f"Staged upload {normalized} has an invalid size receipt.")
    if content_path.stat().st_size != recorded_size:
        raise ValueError("The staged upload size changed after it was recorded.")
    actual_sha = _sha256(content_path)
    if actual_sha != recorded_sha:
        raise ValueError("The staged upload changed after it was recorded.")
    if expected_sha256 and actual_sha != str(expected_sha256).strip().lower():
        raise ValueError("The staged upload changed after preview. Review it again before using it.")
    _validate_extension(str(receipt.get("displayName") or ""))
    return content_path, {
        "uploadId": normalized,
        "displayName": str(receipt["displayName"]),
        "sizeBytes": recorded_size,
        "sha256": actual_sha,
        "stagedAt": str(receipt.get("stagedAt") or ""),
    }


def _provider(value: object) -> str:
    provider = str(value or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported context source: {provider or 'missing'}")
    return provider


def source_catalog() -> dict[str, Any]:
    return {
        "schema": CONTEXT_IMPORT_SCHEMA,
        "sources": [
            {
                "provider": provider,
                "label": {
                    "codex": "Codex",
                    "claude-code": "Claude Code",
                    "opencode": "OpenCode",
                    "hermes": "Hermes",
                    "openclaw": "OpenClaw",
                }[provider],
                "mode": "selected_export",
                "automaticDiscovery": False,
                "status": "export_required",
                "detail": (
                    "Choose a supported export explicitly. Neyvia will preview it before importing "
                    "and will not scan unrelated provider history."
                ),
                "extensions": sorted(SUPPORTED_EXTENSIONS),
            }
            for provider in SUPPORTED_PROVIDERS
        ],
        "codexAssets": {
            "mode": "safe_asset_import",
            "detail": "Codex instructions, skills, and plugin metadata use the existing redacted asset importer.",
        },
    }


def _content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _redact(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern in _SECRET_PATTERNS:
        redacted, matches = pattern.subn("[REDACTED_CREDENTIAL]", redacted)
        count += matches
    return redacted, count


def _objects_from_export(
    path: Path,
    *,
    display_name: str | None = None,
    provider: str | None = None,
) -> Iterable[dict[str, Any]]:
    suffix = Path(display_name or path.name).suffix.lower()
    if suffix in {".md", ".txt"}:
        yield {"role": "context", "content": path.read_text(encoding="utf-8")}
        return
    if suffix in {".jsonl", ".ndjson"}:
        rows: list[tuple[int, dict[str, Any]]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append((line_number, value))
        is_codex_rollout = provider == "codex" and any(
            row.get("type") == "response_item" for _, row in rows
        )
        if is_codex_rollout:
            for line_number, row in rows:
                if row.get("type") != "response_item":
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                if role not in {"user", "assistant"}:
                    continue
                yield {
                    "id": payload.get("id"),
                    "role": role,
                    "content": payload.get("content"),
                    "timestamp": row.get("timestamp"),
                    "_line": line_number,
                }
        else:
            for line_number, row in rows:
                yield {**row, "_line": line_number}
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = next(
            (
                value.get(key)
                for key in ("messages", "turns", "items", "conversation")
                if isinstance(value.get(key), list)
            ),
            [value],
        )
    else:
        rows = []
    for row in rows:
        if isinstance(row, dict):
            yield row


def _resolve_export_source(
    export_path: str | Path | None,
    *,
    root: str | Path | None = None,
    staged_upload_id: str | None = None,
    expected_sha256: str | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    if staged_upload_id:
        if root is None:
            raise ValueError("A workspace root is required for a staged upload.")
        path, source = _resolve_staged_upload(
            root,
            staged_upload_id,
            expected_sha256=expected_sha256,
        )
        return path, source, True
    if not export_path:
        raise ValueError("Choose an existing exported context file or a staged upload.")
    path = Path(export_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Choose an existing exported context file.")
    _validate_extension(path.name)
    size = path.stat().st_size
    if size > MAX_EXPORT_BYTES:
        raise ValueError(f"Context export exceeds the {MAX_EXPORT_BYTES // (1024 * 1024)} MiB limit.")
    actual_sha = _sha256(path)
    if expected_sha256 and actual_sha != str(expected_sha256).strip().lower():
        raise ValueError("The export changed after preview. Review it again before using it.")
    return path, {
        "path": str(path),
        "sha256": actual_sha,
        "sizeBytes": size,
        "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }, False


def preview_export(
    provider: str,
    export_path: str | Path | None = None,
    *,
    root: str | Path | None = None,
    staged_upload_id: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    source = _provider(provider)
    path, source_info, is_staged = _resolve_export_source(
        export_path,
        root=root,
        staged_upload_id=staged_upload_id,
        expected_sha256=expected_sha256,
    )
    size = int(source_info["sizeBytes"])

    items: list[dict[str, Any]] = []
    attachment_count = 0
    redaction_count = 0
    truncated = False
    for index, row in enumerate(
        _objects_from_export(
            path,
            display_name=source_info.get("displayName") if is_staged else None,
            provider=source,
        )
    ):
        if len(items) >= MAX_ITEMS:
            truncated = True
            break
        raw = _content(
            row.get("content")
            or row.get("text")
            or row.get("message")
            or row.get("body")
        )
        if not raw.strip():
            continue
        safe, redactions = _redact(raw)
        redaction_count += redactions
        attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
        attachment_count += len(attachments)
        item_id = str(row.get("id") or row.get("turn_id") or f"item-{index + 1:05d}")
        items.append(
            {
                "itemId": item_id,
                "role": str(row.get("role") or row.get("type") or "context"),
                "createdAt": str(
                    row.get("created_at")
                    or row.get("createdAt")
                    or row.get("timestamp")
                    or ""
                ),
                "sizeBytes": len(safe.encode("utf-8")),
                "preview": safe[:280],
                "content": safe,
                "credentialRedactions": redactions,
                "attachmentNames": [
                    str(item.get("name") or item.get("path") or "attachment")
                    if isinstance(item, dict)
                    else str(item)
                    for item in attachments
                ],
            }
        )

    result = {
        "schema": CONTEXT_IMPORT_PREVIEW_SCHEMA,
        "provider": source,
        "source": source_info,
        "items": items,
        "counts": {
            "available": len(items),
            "attachmentsExcludedByDefault": attachment_count,
            "credentialRedactions": redaction_count,
            "truncated": truncated,
        },
        "warnings": [
            message
            for condition, message in (
                (
                    bool(redaction_count),
                    f"{redaction_count} credential-like value(s) will remain redacted.",
                ),
                (
                    bool(attachment_count),
                    "Attachments are listed for review but are not imported automatically.",
                ),
            )
            if condition
        ],
        "requiresExplicitSelection": True,
    }
    from .proofs_a_control import check_import_preview
    check_import_preview(path, result)
    return result


def import_selection(
    root: str | Path,
    *,
    provider: str,
    export_path: str | Path | None = None,
    staged_upload_id: str | None = None,
    selected_item_ids: Iterable[str],
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    preview = preview_export(
        provider,
        export_path,
        root=root,
        staged_upload_id=staged_upload_id,
        expected_sha256=expected_sha256,
    )
    if expected_sha256 and preview["source"]["sha256"] != expected_sha256:
        raise ValueError("The export changed after preview. Review it again before importing.")
    selected = {str(item) for item in selected_item_ids if str(item).strip()}
    if not selected:
        raise ValueError("Select at least one context item to import.")
    available = {item["itemId"]: item for item in preview["items"]}
    unknown = sorted(selected - available.keys())
    if unknown:
        raise ValueError(f"Unknown context item selection: {', '.join(unknown[:5])}")

    import_id = f"context-{uuid.uuid4().hex[:12]}"
    target = Path(root).resolve() / _IMPORTS_RELATIVE / import_id
    content_path = target / "content.jsonl"
    target.mkdir(parents=True, exist_ok=True)
    selected_rows = [available[item_id] for item_id in selected if item_id in available]
    for item in selected_rows:
        append_jsonl_durable(
            content_path,
            {
                "schema": "neyvia.context_import.item.v1",
                "importId": import_id,
                "provider": preview["provider"],
                "sourceItemId": item["itemId"],
                "sourceSha256": preview["source"]["sha256"],
                "role": item["role"],
                "createdAt": item["createdAt"],
                "content": item["content"],
                "credentialRedactions": item["credentialRedactions"],
            },
        )
    receipt = {
        "schema": CONTEXT_IMPORT_RECEIPT_SCHEMA,
        "importId": import_id,
        "importedAt": _now(),
        "provider": preview["provider"],
        "source": preview["source"],
        "sourceSha256": preview["source"]["sha256"],
        **(
            {"uploadId": preview["source"]["uploadId"]}
            if preview["source"].get("uploadId")
            else {}
        ),
        "scope": {"selectedItemIds": sorted(selected)},
        "importedItems": len(selected_rows),
        "excludedItems": len(preview["items"]) - len(selected_rows),
        "excludedAttachments": preview["counts"]["attachmentsExcludedByDefault"],
        "credentialRedactions": sum(item["credentialRedactions"] for item in selected_rows),
        "contentPath": str(content_path),
        "warnings": preview["warnings"],
        "lineage": {
            "sourceProvider": preview["provider"],
            "sourceSha256": preview["source"]["sha256"],
            "selectionExplicit": True,
            **(
                {"uploadId": preview["source"]["uploadId"]}
                if preview["source"].get("uploadId")
                else {}
            ),
        },
    }
    atomic_write_json(target / "receipt.json", receipt)
    from .proofs_a_control import check_import
    check_import(preview, selected, receipt, read_import_selection(root, import_id))
    return receipt


def list_imports(root: str | Path) -> dict[str, Any]:
    base = Path(root).resolve() / _IMPORTS_RELATIVE
    receipts: list[dict[str, Any]] = []
    if base.exists():
        for path in sorted(base.glob("*/receipt.json"), reverse=True):
            try:
                receipts.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return {
        "schema": CONTEXT_IMPORT_SCHEMA,
        "imports": receipts,
        "count": len(receipts),
    }


def read_import_selection(root: str | Path, import_id: str) -> dict[str, Any]:
    """Read one durable import without widening its selected source scope."""

    normalized_id = str(import_id or "").strip()
    if not normalized_id or Path(normalized_id).name != normalized_id:
        raise ValueError("A valid context import id is required.")
    target = Path(root).resolve() / _IMPORTS_RELATIVE / normalized_id
    receipt_path = target / "receipt.json"
    content_path = target / "content.jsonl"
    if not receipt_path.is_file() or not content_path.is_file():
        raise ValueError(f"Context import {normalized_id} is incomplete.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Context import {normalized_id} has an invalid durable receipt.") from exc
    if not isinstance(receipt, dict):
        raise ValueError(f"Context import {normalized_id} has an invalid durable receipt.")
    if receipt.get("schema") != CONTEXT_IMPORT_RECEIPT_SCHEMA:
        raise ValueError(f"Context import {normalized_id} has an unsupported receipt schema.")
    if str(receipt.get("importId") or "") != normalized_id:
        raise ValueError(f"Context import {normalized_id} receipt identity does not match its path.")
    source = receipt.get("source")
    source_sha256 = str(
        (source.get("sha256") if isinstance(source, dict) else None)
        or receipt.get("sourceSha256")
        or ""
    ).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256):
        raise ValueError(f"Context import {normalized_id} has no valid source SHA-256 receipt.")
    receipt_source_sha256 = str(receipt.get("sourceSha256") or "").strip()
    if receipt_source_sha256 and receipt_source_sha256 != source_sha256:
        raise ValueError(f"Context import {normalized_id} has conflicting source SHA-256 receipts.")
    lineage = receipt.get("lineage")
    if isinstance(lineage, dict) and str(lineage.get("sourceSha256") or "") not in {
        "",
        source_sha256,
    }:
        raise ValueError(f"Context import {normalized_id} lineage does not match its source receipt.")
    scope = receipt.get("scope")
    expected = {
        str(item).strip()
        for item in ((scope or {}).get("selectedItemIds") or [])
        if str(item).strip()
    } if isinstance(scope, dict) else set()
    if not expected:
        raise ValueError(f"Context import {normalized_id} has no selected rows in its receipt.")
    rows: list[dict[str, Any]] = []
    try:
        lines = content_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Context import {normalized_id} content is unreadable.") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Context import {normalized_id} contains invalid selected rows.") from exc
        if not isinstance(item, dict):
            raise ValueError(f"Context import {normalized_id} contains an invalid selected row.")
        if str(item.get("importId") or "") != normalized_id:
            raise ValueError(f"Context import {normalized_id} contains a row from another import.")
        row_source_sha256 = str(item.get("sourceSha256") or source_sha256)
        if row_source_sha256 != source_sha256:
            raise ValueError(f"Context import {normalized_id} selected rows do not match the source receipt.")
        source_item_id = str(item.get("sourceItemId") or "").strip()
        if not source_item_id or not str(item.get("content") or "").strip():
            raise ValueError(f"Context import {normalized_id} contains an incomplete selected row.")
        rows.append({**item, "sourceSha256": source_sha256})
    actual = {str(item.get("sourceItemId") or "") for item in rows}
    if len(actual) != len(rows) or actual != expected:
        raise ValueError(f"Context import {normalized_id} does not match its durable receipt.")
    imported_items = receipt.get("importedItems")
    if imported_items is not None:
        try:
            imported_items_count = int(imported_items)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Context import {normalized_id} has an invalid item count.") from exc
        if imported_items_count != len(rows):
            raise ValueError(f"Context import {normalized_id} item count does not match its durable receipt.")
    result = {
        "receipt": receipt,
        "items": rows,
        "importId": normalized_id,
        "sourceSha256": source_sha256,
    }
    from .proofs_a_control import check_import_read
    check_import_read(receipt, result)
    return result
