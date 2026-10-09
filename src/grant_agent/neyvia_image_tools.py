"""Image Studio state and real pixel edits; generation reuses the existing provider."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .ui_command_bus import now

S = {"type": "string"}
REGION = {"type": "object", "properties": {key: {"type": "integer", "minimum": 0 if key in {"x", "y"} else 1} for key in ("x", "y", "width", "height")}, "required": ["x", "y", "width", "height"]}
DEFINITIONS = [
    ("image.state", "Read observed Image Studio state, requested asset and generation receipts.", {}, []),
    ("image.open", "Inspect and request opening an actual workspace image; does not modify it.", {"source": S}, ["source"]),
    ("image.crop", "Crop the requested image into a new PNG artifact, preserving the source.", {"region": REGION}, ["region"]),
    ("image.resize", "Resize the requested image into a new PNG with explicit dimensions.", {"width": {"type": "integer", "minimum": 1}, "height": {"type": "integer", "minimum": 1}}, ["width", "height"]),
    ("image.composite", "Paste an edited region into a new PNG and verify all outside pixels remain unchanged.", {"edit": S, "region": REGION}, ["edit", "region"]),
    ("image.export", "Export the requested image to a new workspace file; owner approves the destination. Never overwrite.", {"path": S}, ["path"]),
    ("image.generate", "Generate through the existing Codex-subscription image provider; exact requestId retries never resend uncertain work. Requires owner approval.",
     {"requestId": S, "request": {"type": "object"}}, ["requestId", "request"]),
]


def generation_worker(service, identity, fingerprint, payload):
    try:
        result = service.backend._write_image_playground_artifact(payload)
        success = result.get("providerStatus") == "available" and bool(result.get("outputArtifactPath"))
        receipt = {"fingerprint": fingerprint, "status": "completed" if success else "blocked", "result": result, "finishedAt": now()}
        service.bus.update("image:generation", {identity: receipt})
        if success:
            with service.image_lock:
                publish(service, result["outputArtifactPath"], extra={"operation": "generate"})
        else:
            service.bus.emit("notify", {"message": "Image generation blocked", "level": "warning", "requestId": identity})
    except Exception as exc:
        service.bus.update("image:generation", {identity: {"fingerprint": fingerprint, "status": "uncertain", "error": str(exc)[:500], "finishedAt": now()}})
        service.bus.emit("notify", {"message": "Image generation uncertain; inspect its saved receipt before a new intent", "level": "warning", "requestId": identity})
    finally:
        with service.image_lock:
            service.image_generation = None


def inside(service, source):
    path = service.safe_path(source)
    roots = [service.bus.root, Path(__file__).resolve().parents[2], *[Path(row["path"]) for row in service.bus.get("projects", {}).values()]]
    if not any(root.resolve() in path.parents for root in roots):
        raise ValueError("Image must be inside this workspace or an approved project")
    if path.exists() and path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Image exceeds 32 MB")
    return path


def inspect(service, source):
    from PIL import Image
    path = inside(service, source)
    with Image.open(path) as image:
        if image.width * image.height > 50_000_000:
            raise ValueError("Image exceeds 50 megapixels")
    from .visual_specifications import inspect_image
    return inspect_image(path)


def publish(service, path, action="image.open", extra=None):
    asset = {**inspect(service, path), **(extra or {}), "requestedAt": now()}
    identity = uuid.uuid4().hex
    service.bus.update("image:assets", {identity: asset})
    asset.update(id=identity, url="/api/ui/image-file?id=" + identity)
    service.bus.put("image:requested", asset)
    publication = {}
    if extra:
        from .neyvia_outputs import publish as publish_output
        publication = {"publication": publish_output(service, {"path": str(path), "kind": "image", "metadata": {"producer": "image-studio", **extra}})}
    return {"ok": True, "asset": asset, "event": service.bus.emit(action, asset), "uiVerified": False, **publication}


def call(service, name, args):
    if name == "image.state":
        receipts = service.bus.get("image:generation", {})
        for row in receipts.values():
            if row.get("status") == "running" and service.image_generation is None:
                row["status"] = "uncertain"
                row["reason"] = "Service no longer owns this generation; inspect the saved provider artifact"
        state = dict(service.bus.get("app:image-studio") or {})
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(state.get('observedAt', '').replace('Z', '+00:00'))).total_seconds()
            state['fresh'] = 0 <= age <= 5
        except (ValueError, TypeError):
            state['fresh'] = False
        return {"ok": True, "state": state, "requested": service.bus.get("image:requested"),
                "generation": receipts}
    if name == "image.open":
        return publish(service, args["source"])
    if name == "image.generate":
        identity, payload = args.get("requestId"), args.get("request")
        if not isinstance(identity, str) or not identity.strip() or not isinstance(payload, dict):
            raise ValueError("Use a stable requestId and provider request object")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        receipts = service.bus.get("image:generation", {})
        old = receipts.get(identity)
        if old:
            if old["fingerprint"] != fingerprint:
                raise ValueError("requestId already represents a different image request")
            if old["status"] == "running" and service.image_generation is None:
                old = {**old, "status": "uncertain"}
            return {"ok": old["status"] in {"running", "completed"}, "replayed": True, **old}
        if service.image_generation is not None:
            return {"ok": False, "status": "busy", "error": "An image generation is already running; observe image.state"}
        from .neyvia_image_approval import preflight
        refusal = preflight(service, name, args)
        if refusal:
            return refusal
        if service.backend is None:
            raise ValueError("Generation needs the running Neyvia backend")
        ready = service.backend._image_playground_readiness()
        if payload.get("allowPaidApiFallback") or payload.get("allow_paid_api_fallback"):
            raise ValueError("This action is scoped to the configured subscription route; paid fallback is disabled")
        if not ready.get("codexSubscriptionReady"):
            return {"ok": False, "status": "blocked", "readiness": ready}
        receipts[identity] = {"fingerprint": fingerprint, "status": "running", "startedAt": now()}
        service.bus.put("image:generation", receipts)
        provider_request = {**payload, "requestId": "studio_" + hashlib.sha256(identity.encode()).hexdigest()[:24]}
        worker = threading.Thread(target=generation_worker, args=(service, identity, fingerprint, provider_request), name="neyvia-image-generation", daemon=True)
        service.image_generation = identity
        try:
            worker.start()
        except RuntimeError:
            service.image_generation = None
            service.bus.update("image:generation", {identity: {"fingerprint": fingerprint, "status": "not_started"}})
            raise
        return {"ok": True, **receipts[identity], "requestId": identity,
                "event": service.bus.emit("notify", {"message": "Image generation started", "level": "info", "requestId": identity})}
    asset = service.bus.get("image:requested")
    if not asset:
        raise ValueError("Open an image first")
    source = inside(service, asset["path"])
    if inspect(service, source)["sha256"] != asset["sha256"]:
        raise ValueError("Source changed; open it again before editing")
    from PIL import Image
    if name in {"image.crop", "image.composite"}:
        region = args["region"]
        if not isinstance(region, dict) or any(type(region.get(key)) is not int or region[key] < (0 if key in {"x", "y"} else 1) for key in ("x", "y", "width", "height")):
            raise ValueError("Use a rectangle with integer coordinates and positive dimensions")
        box = (region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"])
        if box[2] > asset["dimensions"]["width"] or box[3] > asset["dimensions"]["height"]:
            raise ValueError("Crop exceeds image dimensions")
        output = service.safe_path(service.bus.root / ".agent_control/image-studio" / (uuid.uuid4().hex + ".png"))
        output.parent.mkdir(parents=True, exist_ok=True)
        if name == "image.composite":
            edit = inspect(service, args["edit"])
            from .visual_specifications import composite_region
            result = composite_region(source, edit["path"], output, region)
            return publish(service, output, extra={"parentSha256": asset["sha256"], **result})
        with Image.open(source) as image:
            image.crop(box).save(output, "PNG")
    elif name == "image.resize":
        width, height = args["width"], args["height"]
        if type(width) is not int or type(height) is not int or min(width, height) < 1 or width * height > 50_000_000:
            raise ValueError("Use positive dimensions under 50 megapixels")
        output = service.safe_path(service.bus.root / ".agent_control/image-studio" / (uuid.uuid4().hex + ".png"))
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.resize((width, height), Image.Resampling.LANCZOS).save(output, "PNG")
    elif name == "image.export":
        output = inside(service, args["path"])
        if output.exists():
            raise ValueError("Export never overwrites an existing file")
        from .neyvia_image_approval import preflight
        refusal = preflight(service, name, args)
        if refusal:
            return refusal
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(source.read_bytes())
        from .neyvia_outputs import publish as publish_output
        publication = publish_output(service, {"path": str(output), "kind": "image", "metadata": {"producer": "image-studio", "operation": "export"}})
        return {"ok": True, "path": str(output), "sha256": inspect(service, output)["sha256"], "event": service.bus.emit("notify", {"message": "Image exported", "level": "success"}), "publication": publication}
    else:
        raise ValueError("Unknown image action")
    return publish(service, output, extra={"parentSha256": asset["sha256"], "operation": name})


def report_state(service, state, client):
    if not isinstance(state, dict):
        raise ValueError("Image state must be an object")
    result = {key: state.get(key) for key in ("status", "assetId", "zoom", "selection", "regions", "error")}
    result.update(observedAt=now(), clientId=client)
    service.bus.put("app:image-studio", result)
    return result


def serve_file(service, handler, parsed):
    from urllib.parse import parse_qs
    from .web_backend import _apply_security_headers
    identity = (parse_qs(parsed.query).get("id") or [""])[0]
    asset = service.bus.get("image:assets", {}).get(identity)
    if not asset:
        raise ValueError("Unknown image asset")
    path = inside(service, asset["path"])
    current = inspect(service, path)
    if current["sha256"] != asset["sha256"]:
        raise ValueError("Image changed since opening")
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}.get(current["format"])
    if not mime:
        raise ValueError("Unsupported browser image format")
    raw = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "private, no-store")
    _apply_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(raw)
