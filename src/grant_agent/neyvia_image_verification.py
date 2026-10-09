"""Observe actual Image Studio postconditions without claiming rendered UI proof."""
from __future__ import annotations

import os
from pathlib import Path

from .neyvia_image_tools import inspect
from .neyvia_workspace_tools import workspace_for


class ImageEditAdapter:
    def __init__(self, root, tool_id, arguments):
        self.service = workspace_for(Path(os.environ.get("NEYVIA_UI_STATE_ROOT") or root))
        self.tool_id, self.arguments = tool_id, arguments

    def before(self):
        requested = self.service.bus.get("image:requested") or {}
        source = inspect(self.service, requested["path"])
        return {"source": source, "edit": inspect(self.service, self.arguments["edit"]) if self.tool_id.endswith("composite") else None}

    def after(self, context):
        result = (context.get("effect") or {}).get("result") or {}
        asset = result.get("asset") or {}
        return {"asset": inspect(self.service, asset["path"]) if asset.get("path") else None,
                "source": inspect(self.service, context["before"]["source"]["path"]),
                "edit": inspect(self.service, context["before"]["edit"]["path"]) if context["before"].get("edit") else None}

    def verify(self, context):
        from PIL import Image
        before, after = context["before"], context["after"]
        asset = after.get("asset")
        declared = ((context.get("effect") or {}).get("result") or {}).get("asset") or {}
        if not asset or asset["sha256"] != declared.get("sha256") or before["source"]["sha256"] != after["source"]["sha256"]:
            return {"verified": False, "reason": "Output identity or preserved source differs"}
        if before.get("edit") and before["edit"]["sha256"] != after["edit"]["sha256"]:
            return {"verified": False, "reason": "Edited input changed during composition"}
        with Image.open(before["source"]["path"]) as source, Image.open(asset["path"]) as actual:
            if self.tool_id.endswith("resize"):
                expected = source.resize((self.arguments["width"], self.arguments["height"]), Image.Resampling.LANCZOS)
            else:
                region = self.arguments["region"]
                box = (region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"])
                if self.tool_id.endswith("crop"):
                    expected = source.crop(box)
                else:
                    expected = source.convert("RGBA")
                    with Image.open(before["edit"]["path"]) as edit:
                        expected.paste(edit.convert("RGBA").crop(box), (region["x"], region["y"]))
            try:
                matches = expected.size == actual.size and expected.convert("RGBA").tobytes() == actual.convert("RGBA").tobytes()
            finally:
                expected.close()
        return {"verified": matches, "pixelPostcondition": matches, "sourcePreserved": True,
                "path": asset["path"], "sha256": asset["sha256"], "dimensions": asset["dimensions"], "uiVerified": False}
