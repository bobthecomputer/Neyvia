"""Authenticated media referenced by an existing public chat message.

No arbitrary path endpoint, remote URL fetches, or source-store modifications.
"""
from __future__ import annotations
import base64
import hashlib
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

MAX_MEDIA_BYTES = 24 * 1024 * 1024
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
         ".txt": "text/plain", ".md": "text/plain", ".html": "text/html",
         ".csv": "text/csv", ".zip": "application/zip",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def media_refs(content, text: str) -> list[str]:
    refs = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if value.get("type") in {"image", "input_image", "image_url"}:
                source = value.get("source") or {}
                url = value.get("image_url") or value.get("url")
                if isinstance(url, dict):
                    url = url.get("url")
                if isinstance(url, str):
                    refs.append(url)
                if isinstance(source, dict) and source.get("type") == "base64" and source.get("media_type") in set(TYPES.values()):
                    refs.append(f"data:{source['media_type']};base64,{source.get('data', '')}")
    visit(content)
    refs.extend(match[0] or match[1] for match in re.findall(r'!?\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\)', text))
    refs.extend(re.findall(r'<image\b[^>]*\bpath="([^"]+)"', text))
    return list(dict.fromkeys(ref for ref in refs if ref and not ref.startswith(("http:", "https:"))))[:30]


def descriptors(identity: str, refs: list[str]) -> list[dict]:
    result = []
    for ref in refs:
        data_image = re.match(r"^data:image/(png|jpeg|webp|gif);base64,", ref)
        suffix = Path(ref).suffix.lower()
        if not data_image and suffix not in TYPES:
            continue
        token = hashlib.sha256(ref.encode()).hexdigest()
        label_path = unquote(urlparse(ref).path) if ref.startswith('file://') else ref
        result.append({"id": token, "label": "Attached image" if data_image else Path(label_path.replace('\\', '/')).name,
                       "kind": "image" if data_image or TYPES.get(suffix, "").startswith("image/") else "file",
                       "url": f"/api/connected-chat-media?chat={quote(identity, safe='')}&media={token}"})
    return result


def read_media(identity: str, media_id: str, root=None) -> tuple[bytes, str, str]:
    from .external_chat_inventory import resolve_external_chat, _codex_messages, _claude_messages
    if not re.fullmatch(r"[0-9a-f]{64}", media_id):
        raise ValueError("Invalid chat media identity")
    row = resolve_external_chat(identity, root)
    reader = {"codex": _codex_messages, "claude-code": _claude_messages}.get(row["app"])
    if not reader:
        raise FileNotFoundError("Media is not available for this source")
    for message in reader(Path(row["_sourcePath"])):
        for ref in message.get("_mediaRefs", []):
            if hashlib.sha256(ref.encode()).hexdigest() != media_id:
                continue
            if ref.startswith("data:"):
                match = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)", ref)
                if not match or len(match[2]) > MAX_MEDIA_BYTES * 4 // 3 + 16:
                    raise ValueError("Unsupported or oversized inline image")
                return base64.b64decode(re.sub(r"\s+", "", match[2]), validate=True), match[1], "image"
            raw = unquote(urlparse(ref).path) if ref.startswith("file://") else ref
            if re.match(r"^/[A-Za-z]:/", raw):
                raw = raw[1:]
            path = Path(raw)
            if not path.is_absolute():
                project = Path(row.get("project") or "")
                if not project.is_absolute():
                    raise FileNotFoundError("Relative media has no known project")
                path = project / path
            content_type = TYPES.get(path.suffix.lower())
            if not content_type or not path.is_file() or path.stat().st_size > MAX_MEDIA_BYTES:
                raise FileNotFoundError("Referenced media is missing or too large")
            return path.read_bytes(), content_type, path.name
    raise FileNotFoundError("Media is not referenced by this chat")
