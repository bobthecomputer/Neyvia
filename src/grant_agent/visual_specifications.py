"""Persistent, provenance-bound visual specifications and deterministic edits."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durability import atomic_write_json

ROLES = frozenset({"proposal", "reference", "observation", "repair", "production_asset"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def inspect_image(path: str | Path) -> dict[str, Any]:
    """Inspect the actual local image; no provider/model claim is inferred."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    try:
        from PIL import Image
        with Image.open(target) as image:
            image.load()
            mode = image.mode
            alpha = "A" in image.getbands()
            dimensions = {"width": image.width, "height": image.height}
            fmt = image.format or ""
    except Exception as exc:
        raise ValueError(f"image inspection failed: {exc}") from exc
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"path": str(target), "sha256": digest, "format": fmt, "mode": mode,
            "alpha": alpha, "dimensions": dimensions, "inspectedAt": _now()}


@dataclass
class VisualSpecification:
    specification_id: str
    role: str
    parent_id: str = ""
    version: int = 1
    text_references: list[str] = field(default_factory=list)
    protected_regions: list[dict[str, int]] = field(default_factory=list)
    region_intent: dict[str, str] = field(default_factory=dict)
    assets: list[dict[str, Any]] = field(default_factory=list)
    route_receipt: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unsupported visual role: {self.role}")
        if self.version < 1:
            raise ValueError("version must be positive")
        for region in self.protected_regions:
            _validate_region(region)

    def add_asset(self, path: str | Path, *, label: str = "") -> dict[str, Any]:
        inspected = inspect_image(path)
        asset = {**inspected, "label": _text(label), "role": self.role}
        self.assets.append(asset)
        return asset

    def set_route_receipt(self, receipt: Mapping[str, Any]) -> None:
        """Attach route provenance without asserting the requested route ran."""
        if not isinstance(receipt, Mapping) or not isinstance(receipt.get("requested"), Mapping):
            raise ValueError("route receipt requires a requested route object")
        actual = receipt.get("actual")
        if actual is not None and not isinstance(actual, Mapping):
            raise ValueError("route receipt actual value must be an object when present")
        self.route_receipt = dict(receipt)

    def as_dict(self) -> dict[str, Any]:
        return {"schema": "neyvia.visual_specification.v1", "specificationId": self.specification_id,
                "role": self.role, "parentId": self.parent_id, "version": self.version,
                "textReferences": list(self.text_references), "protectedRegions": list(self.protected_regions),
                "regionIntent": dict(self.region_intent), "assets": list(self.assets),
                "routeReceipt": dict(self.route_receipt), "createdAt": self.created_at}


def _validate_region(region: Mapping[str, Any]) -> None:
    keys = ("x", "y", "width", "height")
    if any(int(region.get(key, -1)) < 0 for key in keys) or int(region["width"]) == 0 or int(region["height"]) == 0:
        raise ValueError("region must have non-negative x/y and positive width/height")


def composite_region(source: str | Path, edit: str | Path, output: str | Path, region: Mapping[str, Any]) -> dict[str, Any]:
    """Paste only ``region`` from edit over source, proving outside pixels unchanged."""
    _validate_region(region)
    from PIL import Image, ImageChops
    source_path, edit_path, output_path = Path(source).resolve(), Path(edit).resolve(), Path(output).resolve()
    with Image.open(source_path).convert("RGBA") as base, Image.open(edit_path).convert("RGBA") as patch:
        box = (int(region["x"]), int(region["y"]), int(region["x"]) + int(region["width"]), int(region["y"]) + int(region["height"]))
        if box[2] > base.width or box[3] > base.height or box[2] > patch.width or box[3] > patch.height:
            raise ValueError("region exceeds source or edit dimensions")
        result = base.copy()
        result.paste(patch.crop(box), box)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path, format="PNG")
        with Image.open(output_path) as checked:
            checked = checked.convert("RGBA")
            difference = ImageChops.difference(base, checked)
            difference.paste((0, 0, 0, 0), box)
            # Check every channel. RGBA's default alpha-only bbox would miss
            # RGB corruption where alpha did not change.
            outside_changed = difference.getbbox(alpha_only=False) is not None
    return {"path": str(output_path), "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "protectedRegion": dict(region), "outsideProtectedPixelsUnchanged": not outside_changed,
            "dimensions": {"width": base.width, "height": base.height}}


class VisualSpecificationRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).resolve() if path else None
        self.specifications: dict[str, VisualSpecification] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for row in payload.get("specifications", []):
            spec = VisualSpecification(_text(row.get("specificationId")), _text(row.get("role")), _text(row.get("parentId")), int(row.get("version", 1)), list(row.get("textReferences") or []), list(row.get("protectedRegions") or []), dict(row.get("regionIntent") or {}), list(row.get("assets") or []), dict(row.get("routeReceipt") or {}), _text(row.get("createdAt")) or _now())
            self.specifications[spec.specification_id] = spec

    def register(self, specification: VisualSpecification) -> VisualSpecification:
        if specification.specification_id in self.specifications:
            raise ValueError("specification identity already exists; create a child version")
        if specification.parent_id and specification.parent_id not in self.specifications:
            raise ValueError("parent specification is not registered")
        if specification.parent_id and specification.version != self.specifications[specification.parent_id].version + 1:
            raise ValueError("child version must follow the parent version")
        self.specifications[specification.specification_id] = specification
        if self.path:
            atomic_write_json(self.path, {"schema": "neyvia.visual_specification_registry.v1", "specifications": [item.as_dict() for item in self.specifications.values()]})
        return specification

    def get(self, specification_id: str) -> VisualSpecification | None:
        return self.specifications.get(_text(specification_id))


def record_generated_visual(root: str | Path, request: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Attach actual provider output to an immutable visual lineage.

    Prompt adherence stays pending until a separate visual review. A generated
    image is never promoted to observed application state here.
    """
    from .harness_jobs import _exclusive_job_lock
    import uuid
    workspace = Path(root).resolve()
    path = workspace / ".agent_control" / "visual_specifications" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    requested = request.get("visualSpecification") or {}
    if not isinstance(requested, Mapping): raise ValueError("visualSpecification must be an object")
    asset = Path(str(manifest["artifactPath"])).resolve()
    asset.relative_to(workspace)
    with _exclusive_job_lock(path):
        registry = VisualSpecificationRegistry(path)
        parent_id = str(requested.get("parentId") or "")
        parent = registry.get(parent_id) if parent_id else None
        if parent_id and parent is None: raise ValueError("Unknown parent visual specification")
        spec = VisualSpecification("visual_" + uuid.uuid4().hex, str(requested.get("role") or "proposal"),
            parent_id=parent_id, version=parent.version + 1 if parent else 1,
            text_references=list(requested.get("textReferences") or []),
            protected_regions=list(requested.get("protectedRegions") or []),
            region_intent=dict(requested.get("regionIntent") or {}))
        spec.add_asset(asset)
        route = (manifest.get("provenance") or {}).get("routeEvidence") or {}
        spec.set_route_receipt({"requested":{"provider":request.get("providerId"),"model":request.get("model")},
            "actual":{"provider":route.get("provider"),"model":route.get("model")},
            "artifactSha256":manifest.get("artifactSha256"),"source":"provider_artifact_receipt"})
        registry.register(spec)
        return {"specification":spec.as_dict(),"registryPath":str(path),"semanticReview":"required"}
