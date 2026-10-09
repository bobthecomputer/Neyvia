"""The PDF bot side sends A2's typed actions and observes the same app state."""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path

from .pdf_document import read_pdf
from .ui_command_bus import bus_for, now
from .neyvia_workspace_tools import workspace_for


DEFINITIONS = [
    ("state", "Read the PDF user's actual page, selection and search state plus pending commands.", {}, []),
    ("open", "Open a local PDF on the user side; the path must be in a Neyvia workspace.", {"source": {"type": "string"}, "page": {"type": "integer", "minimum": 1}}, ["source"]),
    ("goto", "Go to an existing PDF page.", {"page": {"type": "integer", "minimum": 1}}, ["page"]),
    ("search", "Search real PDF text and show the same query on the user side.", {"query": {"type": "string"}, "maxHits": {"type": "integer", "minimum": 1, "maximum": 10000}}, []),
    ("highlight", "Highlight text or PDF-point rectangles on a page; the source file is preserved.", {"page": {"type": "integer", "minimum": 1}, "text": {"type": "string"}, "rects": {"type": "array"}, "note": {"type": "string"}}, ["page"]),
    ("extract_text", "Extract actual text from a PDF page, with explicit truncation.", {"page": {"type": "integer", "minimum": 1}, "maxChars": {"type": "integer", "minimum": 512, "maximum": 100000}}, []),
    ("zoom", "Set PDF zoom to 0.25–5 or fit-width.", {"scale": {"oneOf": [
        {"type": "number", "minimum": 0.25, "maximum": 5},
        {"type": "string", "enum": ["fit-width"]}]}}, ["scale"]),
]


def tool_specs(spec_type):
    return [spec_type(name="neyvia.pdf." + name, description=description, category="neyvia-pdf",
                      input_schema={"type": "object", "properties": props, "required": required},
                      mutability_class="read" if name in {"state", "extract_text"} else "none",
                      capabilities=("neyvia.pdf." + name,), parallel_safe=False)
            for name, description, props, required in DEFINITIONS]


def safe_pdf(root, source) -> Path:
    path = workspace_for(root).safe_path(source)
    bus = bus_for(root)
    roots = [bus.root, Path(__file__).resolve().parents[2],
             *[Path(project["path"]) for project in bus.get("projects", {}).values()]]
    if not any(path == allowed.resolve() or allowed.resolve() in path.parents for allowed in roots):
        raise ValueError("PDF must be inside a Neyvia workspace or an approved project folder")
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("Choose an existing .pdf file")
    with path.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise ValueError("The file is not a PDF")
    return path


def call_pdf(root, name: str, args: dict):
    service = workspace_for(root)
    if service.backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        from .neyvia_ui_client import call_tool
        return call_tool("pdf." + name, args)
    bus = bus_for(root)
    if name == "state":
        requested = bus.get("pdf:requested", {})
        state = bus.get("app:pdf")
        current = state or {}
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(current['observedAt'])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = float('inf')
        rendered = (current.get('renderedPages') or {}).get(str(current.get('page'))) or {}
        return {"ok": True, "state": state, "requested": requested, "fresh": 0 <= age <= 3,
                "outcome": rendered.get('outcome') if rendered.get('visible') else None,
                "event": bus.emit("notify", {"message": "PDF state inspected", "level": "info"})}
    if name == "open":
        path = safe_pdf(root, args["source"])
        metadata = read_pdf(path)
        page = args.get("page", 1)
        if not 1 <= page <= metadata["pages"]:
            raise ValueError("Page is outside this PDF")
        requested = {"source": str(path), "page": page, "pages": metadata["pages"], "requestedAt": now()}
        bus.put("pdf:requested", requested)
        event = bus.emit("pdf.open", {"source": str(path), "page": page})
        return {"ok": True, **metadata, "event": event, "uiVerified": False}
    observed = bus.get("app:pdf") or {}
    requested = bus.get("pdf:requested") or {}
    state = observed if observed.get("observedAt", "") > requested.get("requestedAt", "") else requested
    if not state or not state.get("source"):
        raise ValueError("Open a PDF first")
    path = safe_pdf(root, state["source"])
    page = args.get("page") or state.get("page") or 1
    # Extraction validates its own page and search enumerates actual pages.
    # Avoid parsing the same file twice for these two read-only operations.
    count = read_pdf(path)["pages"] if name not in {"extract_text", "search"} else state.get("pages")
    if name == "extract_text":
        result = read_pdf(path, "extract", page=page, maxChars=args.get("maxChars", 20000))
        return {"ok": True, **result, "event": bus.emit("notify", {"message": f"Extracted PDF page {page}", "level": "info"})}
    if name == "search":
        query = args.get("query", "")
        result = read_pdf(path, "search", query=query, maxHits=args.get("maxHits", 500))
        event = bus.emit("pdf.search", {"query": query})
        return {"ok": True, **result, "event": event, "uiVerified": False}
    if type(page) is not int or not 1 <= page <= count:
        raise ValueError("Page is outside this PDF")
    if name == "highlight":
        rects = args.get("rects")
        if rects is not None and (not rects or not all(isinstance(rect, list) and len(rect) == 4 and
                 all(isinstance(v, (float, int)) and math.isfinite(v) for v in rect) for rect in rects)):
            raise ValueError("rects must be nonempty lists of four finite PDF coordinates")
        text = args.get("text")
        if not rects and not text:
            raise ValueError("Supply highlight text or rectangles")
        if text and not rects and text.casefold() not in read_pdf(path, "extract", page=page, maxChars=100000)["text"].casefold():
            raise ValueError("Highlight text was not found on that page")
        payload = {**args, "page": page}
    elif name == "goto":
        payload = {"page": page}
    elif name == "zoom":
        scale = args["scale"]
        if scale != "fit-width" and (type(scale) not in {float, int} or not 0.25 <= scale <= 5):
            raise ValueError("scale must be 0.25–5 or fit-width")
        payload = {"scale": scale}
    else:
        raise ValueError("Unknown PDF action")
    event = bus.emit("pdf." + name, payload)
    return {"ok": True, "event": event, "uiVerified": False}


def report_pdf_state(root, state, client):
    if not isinstance(state, dict):
        raise ValueError("PDF state must be an object")
    allowed = {key: state.get(key) for key in ("status", "source", "name", "pages", "page", "scale", "fitWidth", "search", "selection", "highlights", "renderedPages", "error")}
    allowed.update(observedAt=now(), clientId=client)
    bus_for(root).put("app:pdf", allowed)
    return allowed
