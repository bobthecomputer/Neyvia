"""Authenticated, workspace-scoped PDF file transport (including PDF.js range reads)."""
from __future__ import annotations

import re
import hashlib
import math
from urllib.parse import parse_qs

from .neyvia_pdf_tools import safe_pdf


MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_RASTER_PIXELS = 8 * 1024 * 1024


def rasterize(data, page, scale):
    """Render actual PDF fonts, images, clipping and transforms with PDFium (pypdfium2).

    Kept lazy: opening Neyvia or a CL catalog never imports this renderer.
    The caller supplies already authorized bytes; this function reads no paths.
    """
    if not data or len(data) > MAX_PDF_BYTES or b'%PDF-' not in data[:1024]:
        raise ValueError('Choose a PDF of at most 32 MiB')
    if type(page) is not int or page < 1 or not math.isfinite(scale) or not 0.25 <= scale <= 10:
        raise ValueError('Use an existing page and a finite scale from 0.25 to 10')
    import pypdfium2
    try:
        document = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as error:
        if 'password' in str(error).lower():
            raise ValueError('Unlock this PDF before rendering it') from None
        raise ValueError('This file is not a readable PDF') from None
    try:
        if page > len(document):
            raise ValueError('Page is outside this PDF')
        selected = document[page - 1]
        width, height = selected.get_size()
        if math.ceil(width * scale) * math.ceil(height * scale) > MAX_RASTER_PIXELS:
            raise ValueError('Reduce zoom: one rendered page is bounded to 8 megapixels')
        # PDFium composites on a white PDF paper background (matches PDF.js) and
        # Canvas ImageData expects straight alpha, so the page is opaque RGBA.
        image = selected.render(scale=scale).to_pil().convert('RGBA')
    finally:
        document.close()
    rgba = image.tobytes()
    return rgba, {'width': image.width, 'height': image.height,
                  'sourceSha256': hashlib.sha256(data).hexdigest(),
                  'pixelSha256': hashlib.sha256(rgba).hexdigest(), 'engine': 'pdfium'}


def serve_raster(handler, parsed):
    """Owner-authenticated raw-PDF POST; never fetches a path or URL."""
    from .web_backend import _apply_security_headers, _send_cors_headers
    query = parse_qs(parsed.query)
    length = int(handler.headers.get('Content-Length') or 0)
    if not 0 < length <= MAX_PDF_BYTES:
        raise ValueError('PDF raster requests are bounded to 32 MiB')
    if handler.headers.get('Content-Type', '').split(';')[0] != 'application/pdf':
        raise ValueError('Raster requests require application/pdf')
    data = handler.rfile.read(length)
    if len(data) != length:
        raise ValueError('PDF body was truncated')
    rgba, report = rasterize(data, int(query.get('page', ['1'])[0]), float(query.get('scale', ['1'])[0]))
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/octet-stream')
    handler.send_header('Content-Length', str(len(rgba)))
    handler.send_header('Cache-Control', 'private, no-store')
    for key, value in report.items():
        handler.send_header('X-PDF-' + key, str(value))
    handler.send_header('Access-Control-Expose-Headers', 'X-PDF-width, X-PDF-height, X-PDF-sourceSha256, X-PDF-pixelSha256, X-PDF-engine')
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(rgba)


def serve_file(root, handler, parsed):
    from .web_backend import _apply_security_headers, _send_cors_headers
    path = safe_pdf(root, (parse_qs(parsed.query).get("path") or [""])[0])
    size = path.stat().st_size
    first, last, status = 0, size - 1, 200
    byte_range = handler.headers.get("Range")
    if byte_range:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
        if not match or not any(match.groups()):
            raise ValueError("Use a single valid byte range")
        start, end = match.groups()
        if start:
            first = int(start)
            last = min(int(end), size - 1) if end else size - 1
        else:
            first = max(0, size - int(end))
        if first > last or first >= size:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        status = 206
    handler.send_response(status)
    handler.send_header("Content-Type", "application/pdf")
    handler.send_header("Content-Length", str(last - first + 1))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, no-store")
    if status == 206:
        handler.send_header("Content-Range", f"bytes {first}-{last}/{size}")
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    with path.open("rb") as source:
        source.seek(first)
        remaining = last - first + 1
        while remaining:
            data = source.read(min(128 * 1024, remaining))
            if not data:
                break
            handler.wfile.write(data)
            remaining -= len(data)
