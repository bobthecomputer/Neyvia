"""Keep screenshots small before they enter a model's history.

A full-size PNG screenshot costs thousands of image tokens on every later turn, because history is replayed.
Every image that is about to become model input goes through ``shrunk_image``: 1024 px long edge, JPEG.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

LONG_EDGE = 1024
JPEG_QUALITY = 80


def shrunk_image(raw: bytes, *, long_edge: int = LONG_EDGE, quality: int = JPEG_QUALITY) -> tuple[str, bytes]:
    """Return ``(mime, bytes)``: the image scaled so its long edge is at most ``long_edge``, as JPEG.

    A JPEG that is already small enough is returned unchanged, so repeated calls are stable.
    """
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as picture:
        picture.load()
        fits = max(picture.size) <= long_edge
        if fits and picture.format == "JPEG":
            return "image/jpeg", raw
        flat = picture
        if picture.mode in ("RGBA", "LA", "P"):
            rgba = picture.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
        elif picture.mode != "RGB":
            flat = picture.convert("RGB")
        if not fits:
            scale = long_edge / max(flat.size)
            flat = flat.resize((max(1, round(flat.width * scale)), max(1, round(flat.height * scale))), Image.LANCZOS)
        out = io.BytesIO()
        flat.save(out, format="JPEG", quality=quality, optimize=True)
        return "image/jpeg", out.getvalue()


def shrunk_data_url(path: Path) -> str:
    mime, data = shrunk_image(Path(path).read_bytes())
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
