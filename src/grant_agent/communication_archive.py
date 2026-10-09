from __future__ import annotations

import hashlib
import mailbox
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Iterable


MAX_ARCHIVE_MESSAGES = 500
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_BODY_PREVIEW = 600


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _message_preview(message: Message) -> str:
    parts: Iterable[Message]
    if message.is_multipart():
        parts = message.walk()
    else:
        parts = (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() != "text/plain":
            continue
        try:
            value = part.get_content()
        except (AttributeError, LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            value = payload.decode("utf-8", "replace")
        compact = " ".join(str(value or "").split())
        if compact:
            return compact[:MAX_BODY_PREVIEW]
    return ""


from .proofs_a_cli import checked


@checked('a-cli.archive.summary')
def _message_summary(message: Message, *, source_ref: str) -> dict[str, Any]:
    attachments = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment" and not part.get_filename():
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            {
                "filename": str(part.get_filename() or "attachment"),
                "mediaType": str(part.get_content_type() or "application/octet-stream"),
                "bytes": len(payload),
            }
        )
    identity = "\n".join(
        [
            str(message.get("Message-ID") or ""),
            str(message.get("Date") or ""),
            str(message.get("From") or ""),
            str(message.get("Subject") or ""),
            source_ref,
        ]
    )
    return {
        "messageId": hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest(),
        "internetMessageId": str(message.get("Message-ID") or "") or None,
        "subject": str(message.get("Subject") or "(no subject)"),
        "from": str(message.get("From") or ""),
        "to": str(message.get("To") or ""),
        "date": str(message.get("Date") or ""),
        "bodyPreview": _message_preview(message),
        "attachments": attachments,
        "sourceRef": source_ref,
    }


def _parse_eml(path: Path, *, source_ref: str) -> dict[str, Any]:
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"EML source exceeds {MAX_SOURCE_BYTES} bytes")
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    return _message_summary(message, source_ref=source_ref)


@checked('a-cli.archive.inspect')
def inspect_communication_archive(
    source_path: str | Path,
    *,
    limit: int = MAX_ARCHIVE_MESSAGES,
) -> dict[str, Any]:
    requested = Path(source_path).expanduser()
    if not requested.exists():
        raise FileNotFoundError(str(requested))
    source = requested.resolve(strict=True)
    bounded_limit = max(1, min(int(limit or MAX_ARCHIVE_MESSAGES), MAX_ARCHIVE_MESSAGES))

    if source.is_file() and source.suffix.casefold() == ".msg":
        return {
            "schema": "neyvia.communication-archive-inspection.v1",
            "sourcePath": str(source),
            "format": "msg",
            "status": "adapter-required",
            "messages": [],
            "messageCount": 0,
            "attachmentCount": 0,
            "truncated": False,
            "sourceDigest": _file_digest(source),
            "limitations": [
                "MSG parsing requires a declared Outlook/export adapter; no content was inferred."
            ],
        }

    messages: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    truncated = False
    archive_format = "eml"

    if source.is_file():
        if source.suffix.casefold() != ".eml":
            raise ValueError("Supported archive sources are EML files, EML folders, and Maildir")
        digest.update(source.name.encode("utf-8"))
        digest.update(bytes.fromhex(_file_digest(source)))
        messages.append(_parse_eml(source, source_ref=source.name))
    elif all((source / name).is_dir() for name in ("cur", "new", "tmp")):
        archive_format = "maildir"
        maildir = mailbox.Maildir(str(source), factory=None, create=False)
        keys = sorted(maildir.iterkeys())
        truncated = len(keys) > bounded_limit
        for key in keys[:bounded_limit]:
            message = maildir.get_message(key)
            if message is None:
                continue
            source_ref = f"maildir:{key}"
            digest.update(source_ref.encode("utf-8"))
            digest.update(message.as_bytes(policy=policy.default))
            messages.append(_message_summary(message, source_ref=source_ref))
    elif source.is_dir():
        files = sorted(path for path in source.rglob("*.eml") if path.is_file())
        truncated = len(files) > bounded_limit
        for path in files[:bounded_limit]:
            relative = path.relative_to(source).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(bytes.fromhex(_file_digest(path)))
            messages.append(_parse_eml(path, source_ref=relative))
    else:
        raise ValueError("Archive source must be a regular file or directory")

    return {
        "schema": "neyvia.communication-archive-inspection.v1",
        "sourcePath": str(source),
        "format": archive_format,
        "status": "ready",
        "messages": messages,
        "messageCount": len(messages),
        "attachmentCount": sum(len(item["attachments"]) for item in messages),
        "truncated": truncated,
        "sourceDigest": digest.hexdigest(),
        "limitations": (
            [f"Preview limited to the first {bounded_limit} messages"]
            if truncated
            else []
        ),
    }
