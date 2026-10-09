"""Real PDF bytes, PDFium raster, text-worker and refusal journey."""
from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit

CONTRACTS = ("p22.pdf.backend-range-raster-worker",)


def require(condition, detail):
    if not condition:
        raise ValueError("Contract p22.pdf.backend-range-raster-worker: " + detail)


class _Handler:
    """Small in-memory HTTP request/response surface for the real dispatcher."""

    protocol_version = "HTTP/1.1"
    request_version = "HTTP/1.1"
    command = "GET"

    def __init__(self, *, headers=None, body=b"", authenticated=True):
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.authenticated = authenticated
        self.status = None
        self.response_headers = {}
        self.close_connection = False

    def send_response(self, status, message=None):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name.lower()] = str(value)

    def end_headers(self):
        pass

    @property
    def body(self):
        return self.wfile.getvalue()


class _Backend:
    def __init__(self, root):
        self.root = root
        self.username = "pdf-proof-owner"

    def authenticated_session(self, handler):
        return {"username": self.username} if handler.authenticated else None


def _request(backend, path, *, method="GET", headers=None, body=b"", authenticated=True):
    from . import neyvia_ui_api

    handler = _Handler(headers=headers, body=body, authenticated=authenticated)
    parsed = urlsplit(path)
    # UI routing normally starts app services here. This proof exercises only
    # the production PDF routes, so suppress unrelated timers and brokers.
    from unittest.mock import patch
    with patch.object(neyvia_ui_api, "bind_backend", lambda _backend: None):
        handled = neyvia_ui_api.serve(backend, handler, parsed, method)
    require(handled is True, "the production UI dispatcher did not claim " + parsed.path)
    return handler


def _clean_escaped_fixture(path):
    """Delete only the run-owned PDF after proving it stays in the P22 scratch."""
    if path is None:
        return None
    owned = Path("D:/NeyviaRuns/P22/drafts/pdf-backend/escaped").resolve()
    candidate = Path(path)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(owned) or candidate.is_symlink():
        raise ValueError("Escaped PDF cleanup target left its owned D: scratch root")
    if resolved.exists():
        resolved.unlink()
    return str(resolved)


def self_check(root=None):
    """Exercise production PDF routes and the actual installed parser/renderers."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    allowed = Path("D:/NeyviaRuns/P22").resolve()
    scratch = Path(root or allowed).resolve()
    require(scratch.is_relative_to(allowed), "PDF proof scratch must stay under D:/NeyviaRuns/P22")
    state_root = scratch / "pdf-backend-journey" / uuid.uuid4().hex
    require(state_root.resolve().is_relative_to(allowed), "PDF proof state escaped D:/NeyviaRuns/P22")
    state_root.mkdir(parents=True, exist_ok=False)
    source = state_root / "backend-proof.pdf"
    phrase = "Neyvia PDF worker phrase 7391"
    escaped_source = None
    result = None
    try:
        from . import pdf_compat
        document = pdf_compat.Canvas(612, 792)
        document.text((72, 120), phrase, size=18, color=(0.05, 0.1, 0.2))
        document.metadata = {"title": "Local PDF backend proof"}
        document.save(source)

        original = source.read_bytes()
        expected_sha = hashlib.sha256(original).hexdigest()
        require(original.startswith(b"%PDF-"), "the synthetic local PDF must have a real PDF header")
        require(pdf_compat.page_count(original) == 1, "the synthetic PDF must be a valid one-page document")
        geometry = pdf_compat.page_size(original)
        require(abs(geometry[0] - 612) < 0.01 and abs(geometry[1] - 792) < 0.01,
                "the actual PDF page geometry must be 612 by 792 points")
        require(phrase in pdf_compat.page_texts(original)[0],
                "the valid PDF page must contain the independently generated known phrase")
        backend = _Backend(state_root)
        encoded_path = urlencode({"path": str(source)})

        full = _request(backend, "/api/apps/pdf/file?" + encoded_path)
        require(full.status == 200 and full.response_headers.get("content-type") == "application/pdf"
                and full.body == original,
                "the full production PDF route must return exact source bytes")

        ranged = _request(backend, "/api/apps/pdf/file?" + encoded_path,
                          headers={"Range": "bytes=0-31"})
        require(ranged.status == 206 and ranged.response_headers.get("content-range") == f"bytes 0-31/{len(original)}"
                and ranged.body == original[:32],
                "the PDF range route must return the exact requested 32 source bytes")

        unsatisfiable = _request(backend, "/api/apps/pdf/file?" + encoded_path,
                                 headers={"Range": f"bytes={len(original) + 5}-"})
        require(unsatisfiable.status == 416
                and unsatisfiable.response_headers.get("content-range") == f"bytes */{len(original)}"
                and unsatisfiable.body == b"",
                "an unsatisfiable range must return 416 with an empty body")
        # This unique external file is outside workspace/repository scope and
        # lives only in the owned P22 scratch root. Never touch the old draft
        # fixture at .../pdf-backend/outside.pdf.
        escape_root = Path("D:/NeyviaRuns/P22/drafts/pdf-backend/escaped").resolve()
        escaped_source = escape_root / (state_root.name + "-" + uuid.uuid4().hex + ".pdf")
        require(escaped_source.resolve().is_relative_to(escape_root) and not escaped_source.exists(),
                "the unique negative fixture must be a fresh file contained by its owned D: scratch root")
        escaped_source.parent.mkdir(parents=True, exist_ok=True)
        escaped_source.write_bytes(b"%PDF-1.7\nnot inside an approved workspace\n")
        escaped = _request(backend, "/api/apps/pdf/file?" + urlencode({"path": str(escaped_source)}))
        escaped_payload = json.loads(escaped.body.decode("utf-8"))
        require(escaped.status == 400 and "inside a Neyvia workspace" in escaped_payload.get("error", ""),
                "an existing PDF outside approved roots must receive the production 400 refusal")

        raster = _request(backend, "/api/apps/pdf/raster?page=1&scale=1", method="POST",
                          headers={"Content-Type": "application/pdf", "Content-Length": str(len(original))},
                          body=original)
        width = int(raster.response_headers.get("x-pdf-width", "0"))
        height = int(raster.response_headers.get("x-pdf-height", "0"))
        pixels = raster.body
        require(raster.status == 200 and raster.response_headers.get("content-type") == "application/octet-stream"
                and width == 612 and height == 792 and len(pixels) == width * height * 4,
                "PDFium raster dimensions must match the independently checked 612x792 PDF page geometry and RGBA byte count")

        def pixel(x, y):
            at = (y * width + x) * 4
            return pixels[at:at + 4]

        corners = [pixel(0, 0), pixel(width - 1, 0), pixel(0, height - 1), pixel(width - 1, height - 1)]
        corner_white = all(r >= 250 and g >= 250 and b >= 250 and a == 255 for r, g, b, a in corners)
        nonwhite_pixels = 0
        interior_ink_pixels = 0
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixel(x, y)
                if a > 240 and (r < 250 or g < 250 or b < 250):
                    nonwhite_pixels += 1
                # The one known text run begins near PDF point (72, 120).
                # PDFium's page pixels use a top-left origin; this wide region
                # surrounds its glyphs while excluding any page border.
                if 48 <= x < 560 and 70 <= y < 180 and a > 240 and r < 110 and g < 110 and b < 110:
                    interior_ink_pixels += 1
        pixel_sha = hashlib.sha256(pixels).hexdigest()
        require(corner_white and nonwhite_pixels > 100 and interior_ink_pixels > 50
                and raster.response_headers.get("x-pdf-sourcesha256") == expected_sha
                and raster.response_headers.get("x-pdf-pixelsha256") == pixel_sha,
                "actual PDFium pixels must have white page corners, nonwhite content and dark ink in the known text region; response hashes must match actual bytes")

        bad_mime = _request(backend, "/api/apps/pdf/raster?page=1&scale=1", method="POST",
                            headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(original))},
                            body=original)
        require(bad_mime.status == 400 and b"application/pdf" in bad_mime.body,
                "the raster route must refuse a request with the wrong MIME type")

        from .pdf_document import read_pdf
        extracted = read_pdf(source, "extract", page=1, maxChars=10000)
        require(extracted.get("engine") == "pypdf" and extracted.get("pages") == 1
                and phrase in extracted.get("text", "") and not extracted.get("truncated"),
                "the production local text worker must extract the independently known phrase")
        searched = read_pdf(source, "search", query="worker phrase 7391", maxHits=10)
        hits = searched.get("hits", [])
        require(searched.get("engine") == "pypdf" and searched.get("pages") == 1
                and len(hits) == 1 and hits[0].get("page") == 1
                and phrase in hits[0].get("text", ""),
                "the production text worker search must locate the real phrase on page one")
        page_refused = False
        try:
            read_pdf(source, "extract", page=2, maxChars=10000)
        except (ValueError, IndexError):
            page_refused = True
        require(page_refused, "out-of-range worker page must refuse")

        denied = _request(backend, "/api/apps/pdf/file?" + encoded_path, authenticated=False)
        require(denied.status == 401 and b'"loginRequired":true' in denied.body,
                "the PDF route must enforce its authenticated owner boundary")
        cleaned_escape = _clean_escaped_fixture(escaped_source)
        escaped_source = None
        case = {"id": "pdf.backend-range-raster-worker", "contracts": list(CONTRACTS), "ok": True,
                "sourceSha256": expected_sha, "bytes": len(original), "rangeBytes": len(ranged.body),
                "textEngine": extracted["engine"], "phraseFound": True, "searchPage": hits[0]["page"],
                "rasterEngine": raster.response_headers.get("x-pdf-engine"), "width": width,
                "height": height, "cornerWhite": corner_white, "nonwhitePixels": nonwhite_pixels,
                "interiorInkPixels": interior_ink_pixels, "pixelSha256": pixel_sha,
                "escapedSourceRefused": True, "wrongMimeRefused": True, "authRequired": True}
        result = {"ok": True, "contracts": list(CONTRACTS), "cases": [case], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root),
                "frontier": "Exercises the production local dispatcher, exact PDF route responses, verified 612x792 PDF geometry, PDFium page/corner/interior pixels, and the pypdf text worker in-process. It proves backend bytes and local page text/raster, not the mounted PDF.js canvas or a public listener.",
                "escapedFixtureCleaned": cleaned_escape}
    except Exception as error:
        result = {"ok": False, "contracts": list(CONTRACTS),
                "cases": [{"id": "pdf.backend-range-raster-worker", "contracts": list(CONTRACTS),
                           "ok": False, "error": str(error)}], "failures": [str(error)],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root)}
    finally:
        try:
            _clean_escaped_fixture(escaped_source)
        except Exception as cleanup_error:
            detail = "Escaped fixture cleanup failed: " + str(cleanup_error)
            result = {"ok": False, "contracts": list(CONTRACTS),
                      "cases": [{"id": "pdf.backend-range-raster-worker", "contracts": list(CONTRACTS),
                                 "ok": False, "error": detail}], "failures": [detail],
                      "durationMs": round((time.perf_counter() - started) * 1000, 3),
                      "stateRoot": str(state_root)}
    return result
