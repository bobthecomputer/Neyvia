"""Request approval before an image effect enters the durable mutation ledger."""
import hashlib
import json


def preflight(service, name, args):
    if name == "image.export":
        from .neyvia_image_tools import inside
        path = inside(service, args["path"])
        if path.exists():
            raise ValueError("Export never overwrites an existing file")
        return service.require_approval("image-export:" + str(path.parent), "Approve new image exports under " + str(path.parent), {"path": str(path)})
    if name != "image.generate":
        raise ValueError("Unknown image approval preflight")
    identity, payload = args.get("requestId"), args.get("request")
    if not isinstance(identity, str) or not identity.strip() or not isinstance(payload, dict):
        raise ValueError("Use a stable requestId and provider request object")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return service.require_approval("image-generate:" + hashlib.sha256(identity.encode()).hexdigest() + ":" + fingerprint,
        "Approve image generation via the configured Codex subscription route", {"requestId": identity, "request": payload, "intentSha256": fingerprint})


def for_gateway(root, tool_id, args):
    import os
    from .neyvia_workspace_tools import workspace_for
    service = workspace_for(root)
    if service.backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        from .neyvia_ui_client import call_tool
        result = call_tool(tool_id.removeprefix("neyvia."), args, preflight=True)
        return result if result.get("ok") is False else None
    return preflight(service, tool_id.removeprefix("neyvia."), args)
