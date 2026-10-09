"""Files attached to a message: saved on this PC and named in the message for the agent to open.

Images travel as image blocks where the app takes them; every other file (a PDF, a log, a zip,
a spreadsheet) is written under ``~/.neyvia/attachments`` and the message gains one line per
file with its path, which Claude Code, Codex and Neyvia all read with their own file tools.
A file is named after a hash of its content, so a retried message names the same path and
stays the same request.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path
from typing import Any

ATTACHMENT_DIR = Path.home() / ".neyvia" / "attachments"
MAX_FILES = 10
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024


class AttachmentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_name(name: str) -> str:
    base = Path(str(name or "file").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .") or "file"
    return base[:120]


def save_files(raw: Any, directory: Path | None = None) -> list[Path]:
    """Validate and save ``[{name, data(base64)}]``; returns the saved paths."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise AttachmentError("invalid_file", "Attached files must be a list.")
    if len(raw) > MAX_FILES:
        raise AttachmentError("too_many_files", f"Attach at most {MAX_FILES} files.")
    folder = directory or ATTACHMENT_DIR
    decoded: list[tuple[str, bytes]] = []
    total = 0
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), str):
            raise AttachmentError("invalid_file", "Each attached file needs base64 data.")
        try:
            data = base64.b64decode(entry["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentError("invalid_file", "An attached file couldn't be read.") from exc
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentError("file_too_large", f"Each file can be at most {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError("file_too_large", f"Attached files can be at most {MAX_TOTAL_BYTES // (1024 * 1024)} MB together.")
        decoded.append((_safe_name(str(entry.get("name") or "file")), data))
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in decoded:
        path = folder / f"{hashlib.sha256(data).hexdigest()[:16]}-{name}"
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    from ..proofs_a_control import check_attachments
    check_attachments(folder, decoded, paths)
    return paths


def with_files(message: str, paths: list[Path]) -> str:
    """The message with one ``Attached file: <path>`` line per saved file."""
    if not paths:
        return message
    lines = "\n".join(f"Attached file: {path}" for path in paths)
    text = (message or "").rstrip()
    lead = text if text else f"Look at the attached file{'s' if len(paths) > 1 else ''}."
    result = f"{lead}\n\n{lines}"
    from ..proofs_a_control import check_attachment_message
    check_attachment_message(message, paths, result)
    return result
