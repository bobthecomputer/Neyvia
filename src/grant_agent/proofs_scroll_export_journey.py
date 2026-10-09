"""Outcome contract for Scroll pack export and single-use phone delivery."""
from __future__ import annotations

import hashlib
import io
import os
import re
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

CONTRACTS = ("p22.scroll.reviewed-export-singleuse-outcome",)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACTS[0]}: {detail}")


class _Response:
    """Small response sink for the production download handler."""

    protocol_version = "HTTP/1.1"

    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status, message=None):
        self.status = status

    def send_header(self, name, value):
        self.headers[name.lower()] = value

    def end_headers(self):
        pass


def _download(root: Path, url: str) -> _Response:
    from .neyvia_scroll import download

    response = _Response()
    download(root, response, urlsplit(url))
    return response


def _svg_has_qr_geometry(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.search(r"<svg\b", value, re.I)
        and re.search(r"<path\b[^>]*\bd=['\"][^'\"]{8,}['\"]", value, re.I)
    )


def self_check(root=None):
    """Exercise production Scroll import, review, export, send and download semantics."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    supplied = Path(root).expanduser().resolve() if root else Path("D:/NeyviaRuns/P22/scroll-export-journey").resolve()
    allowed = (Path("D:/NeyviaRuns/P22").resolve(),)
    require(any(supplied.is_relative_to(parent) for parent in allowed),
            "scratch root must stay under D:/NeyviaRuns/P22")
    run_root = supplied / uuid.uuid4().hex
    run_root.mkdir(parents=True, exist_ok=False)
    note = run_root / "naïve résumé Δ.md"
    note_text = "# Café and 東京\n\nA reviewed pack keeps naïve résumé and 東京 exact through export.\n"
    note.write_text(note_text, encoding="utf-8", newline="")
    pack_id = "p22-scroll-export-" + uuid.uuid4().hex[:12]

    from .neyvia_scroll import call, load, save, store
    from .scroll_pack import read_scrollpack

    def safe_path(value):
        resolved = Path(value).resolve()
        if resolved != note.resolve():
            raise ValueError("The Scroll proof accepts only its own Unicode note")
        return resolved

    service = SimpleNamespace(bus=SimpleNamespace(root=run_root), safe_path=safe_path)
    imported = call(service, "scroll.import", {
        "paths": [str(note)], "packId": pack_id, "title": "Café Δ", "subject": "notes",
    })
    require(imported.get("ok") is True and imported["pack"]["meta"]["id"] == pack_id,
            "production import must create the requested pack from the Unicode note")

    row = load(run_root, pack_id)
    sources = row["sources"]["records"]
    require(len(sources) == 1, "the imported pack must retain its single source record")
    source_id = sources[0]["id"]
    concept_id = "unicode-exactness"
    card_id = concept_id + ".fact.01"
    row["value"]["generation"]["run"] = "p22-export-contract"
    row["value"]["concepts"] = [{
        "id": concept_id, "name": "Unicode archive fidelity", "chapter": "unicode-records",
        "subject": "notes", "prereqs": [], "kind": "fact",
        "definition": "UTF-8 archive members preserve the original Unicode source text.",
    }]
    row["value"]["cards"] = [{
        "id": card_id, "type": "fact", "subject": "notes", "chapter": "unicode-records",
        "concepts": {"teaches": [concept_id], "requires": [], "tests": []},
        "body": "The archive must retain café, naïve résumé, and 東京 exactly.",
        "difficulty": 0.2, "seconds": 20, "lang": "en",
        "source": {"doc": source_id, "span": [0, len(note_text)]},
        "provenance": {"stage": "contract-fixture", "tier": "script", "runId": "p22-export-contract"},
    }]
    row["review"] = {}
    save(run_root, row)

    reviewed = call(service, "scroll.review", {
        "pack": pack_id, "decisions": [{"cardId": card_id, "action": "approve"}],
    })
    require(reviewed.get("ok") is True and
            reviewed["active"]["review"]["chapters"][0]["cards"][0]["status"] == "approved",
            "the real review operation must persist this card as approved")

    exported = call(service, "scroll.pack", {"pack": pack_id})
    require(exported.get("ok") is True and exported.get("bytes", 0) > 0 and
            re.fullmatch(r"[a-f0-9]{64}", exported.get("sha256", "")) is not None,
            "approved export must return a nonempty archive and SHA-256")
    archive_path = Path(exported["path"]).resolve()
    require(archive_path.is_relative_to(run_root.resolve()) and archive_path.suffix == ".scrollpack",
            "export must remain inside the owned workspace scratch root")
    archive_bytes = archive_path.read_bytes()
    require(len(archive_bytes) == exported["bytes"] and
            hashlib.sha256(archive_bytes).hexdigest() == exported["sha256"],
            "export receipt size and digest must match the saved archive bytes")
    unpacked, unpacked_sources = read_scrollpack(archive_path)
    require(unpacked["meta"]["title"] == "Café Δ" and
            unpacked["cards"] == row["value"]["cards"] and
            unpacked["concepts"] == row["value"]["concepts"] and
            unpacked_sources == row["sources"]["source_texts"] and
            next(iter(unpacked_sources.values())) == note_text,
            "archive readback must preserve reviewed semantics and exact Unicode source text")

    env_name = "NEYVIA_UI_BACKEND_URL"
    prior_url = os.environ.get(env_name)
    os.environ[env_name] = "http://127.0.0.1:49088"
    try:
        delivery = call(service, "scroll.send", {"pack": pack_id})
    finally:
        if prior_url is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = prior_url

    require(delivery.get("ok") is True and delivery.get("downloads") == 1 and
            isinstance(delivery.get("expires"), (int, float)) and delivery["expires"] > time.time(),
            "send must issue one unexpired download capability")
    require(urlsplit(delivery.get("url", "")).path.startswith("/api/ui/scroll/download/"),
            "send must return the production download route")
    require(_svg_has_qr_geometry(delivery.get("qrSvg")),
            "send must return SVG with actual QR path geometry (no decode claim)")

    token = urlsplit(delivery["url"]).path.rsplit("/", 1)[-1]
    with store(run_root) as (db, _):
        link = db.execute("SELECT expires,consumed FROM links WHERE token=?", (token,)).fetchone()
    require(link is not None and link["consumed"] == 0 and link["expires"] > time.time(),
            "send must persist one unconsumed, unexpired capability")
    original_expiry = link["expires"]
    with store(run_root) as (db, _):
        changed = db.execute("UPDATE links SET expires=0 WHERE token=? AND consumed=0", (token,)).rowcount
    require(changed == 1, "expiry case must change only its own scratch capability")
    expired = _download(run_root, delivery["url"])
    require(expired.status == 410 and b"expired" in expired.wfile.getvalue(),
            "an expired capability must refuse delivery with 410")
    with store(run_root) as (db, _):
        changed = db.execute("UPDATE links SET expires=? WHERE token=? AND consumed=0 AND expires=0",
                             (original_expiry, token)).rowcount
    require(changed == 1, "expiry probe must leave the issued capability unconsumed and restore its expiry")

    success = _download(run_root, delivery["url"])
    require(success.status == 200 and success.headers.get("content-type") == "application/zip" and
            success.wfile.getvalue() == archive_bytes,
            "first download must return the exact exported archive payload")
    repeated = _download(run_root, delivery["url"])
    require(repeated.status == 410 and b"already downloaded" in repeated.wfile.getvalue(),
            "the same capability must refuse a second download with 410")

    case = {
        "id": "unicode-export-single-use-delivery",
        "contracts": list(CONTRACTS),
        "ok": True,
        "unicodeSourceExact": True,
        "archiveSemanticRoundtrip": True,
        "archiveSha256": exported["sha256"],
        "qrSvgHasPathGeometry": True,
        "qrDecodeClaimed": False,
        "expiryProbeRestoredIssuedCapability": True,
        "firstDownload": {"status": success.status, "exactPayload": True},
        "repeatedDownloadStatus": repeated.status,
        "expiredDownloadStatus": expired.status,
    }
    return {
        "ok": True,
        "contracts": list(CONTRACTS),
        "cases": [case],
        "failures": [],
        "durationMs": round((time.perf_counter() - started) * 1000, 3),
        "scratchRoot": str(run_root),
        "frontier": "Exercises production Scroll import/review/export/send once and the download handler directly in an isolated D-drive workspace. The issued capability is briefly expired and restored before delivery so expiry, exact 200 payload and replay 410 are checked without a second export or QR generation. It proves QR SVG geometry only; it does not exercise HTTP authentication, a phone scanner, QR decoding, or a UI consumer.",
    }
