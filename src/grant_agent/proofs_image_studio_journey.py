"""Exercise real local Image Studio pixel edits and their durable observers."""
from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


CONTRACTS = ("p22.image-studio.pixel-edit-journey",)


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACTS[0]}: {detail}")


def self_check(root=None, selected=None) -> dict:
    """Run crop, resize, composite, export and path-refusal against owned pixels."""
    from .contract_gate import wants

    started = time.perf_counter()
    if selected is not None and not set(selected).intersection(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    case_root = repo / ".agent_control" / "p22" / "image-studio-journey" / uuid.uuid4().hex
    case_root.mkdir(parents=True, exist_ok=False)
    evidence_root = Path(os.environ.get("P22_EVIDENCE_ROOT", "D:/NeyviaRuns/P22"))
    outside_root = evidence_root / "image-studio-journey" / uuid.uuid4().hex
    outside_root.mkdir(parents=True, exist_ok=False)
    outside_path = outside_root / "outside-synthetic.png"
    source_path = case_root / "source-synthetic.png"
    edit_path = case_root / "edit-synthetic.png"

    try:
        from PIL import Image
        from .ui_command_bus import UICommandBus
        from .neyvia_workspace_tools import WorkspaceTools
        from .neyvia_image_tools import call, report_state

        # Explicitly pin all bus writes to this disposable SSD workspace, even
        # if the invoking shell has a UI state override configured.
        previous_state = os.environ.get("NEYVIA_UI_STATE_ROOT")
        os.environ["NEYVIA_UI_STATE_ROOT"] = str(case_root)
        try:
            bus = UICommandBus(case_root)
            _require(bus.root.resolve() == case_root.resolve(), "the fixture bus must stay inside its owned root")
            class FixtureService(SimpleNamespace):
                require_approval = WorkspaceTools.require_approval
                approve = WorkspaceTools.approve

            service = FixtureService(bus=bus, safe_path=WorkspaceTools.safe_path,
                                     image_lock=threading.RLock(), image_generation=None,
                                     backend=None)

            # 4x3 source has a different color per column; the edit has an
            # unmistakable magenta patch in the upper-left 2x2 region.
            base_colors = [(20, 30, 40), (50, 60, 70), (80, 90, 100), (110, 120, 130)]
            with Image.new("RGB", (4, 3)) as source:
                for y in range(3):
                    for x, color in enumerate(base_colors):
                        source.putpixel((x, y), color)
                source.save(source_path, "PNG")
            with Image.new("RGB", (4, 3), (5, 15, 25)) as edit:
                for y in range(2):
                    for x in range(2):
                        edit.putpixel((x, y), (230, 20, 180))
                edit.save(edit_path, "PNG")
            with Image.new("RGB", (1, 1), (200, 5, 5)) as outside:
                outside.save(outside_path, "PNG")

            opened = call(service, "image.open", {"source": str(source_path)})
            source_sha = opened["asset"]["sha256"]
            _require(opened.get("ok") is True and opened["asset"]["dimensions"] == {"width": 4, "height": 3},
                     "opening must return the actual source dimensions")

            crop = call(service, "image.crop", {"region": {"x": 1, "y": 1, "width": 2, "height": 2}})
            crop_path = Path(crop["asset"]["path"])
            with Image.open(crop_path) as cropped:
                _require((cropped.size, cropped.format, cropped.getpixel((0, 0))) ==
                         ((2, 2), "PNG", base_colors[1]), "crop must write the selected source pixels as a 2x2 PNG")
            _require(crop["asset"]["parentSha256"] == source_sha and crop_path.name.lower().endswith(".png"),
                     "crop must preserve the source lineage and return a PNG filename")

            call(service, "image.open", {"source": str(source_path)})
            resized = call(service, "image.resize", {"width": 2, "height": 5})
            resized_path = Path(resized["asset"]["path"])
            with Image.open(resized_path) as image:
                _require((image.size, image.format) == ((2, 5), "PNG"),
                         "resize must produce the requested 2x5 PNG")
            _require(resized["asset"]["parentSha256"] == source_sha and resized_path.name.lower().endswith(".png"),
                     "resize must retain parent provenance and return a PNG filename")

            call(service, "image.open", {"source": str(source_path)})
            region = {"x": 0, "y": 0, "width": 2, "height": 2}
            composite = call(service, "image.composite", {"edit": str(edit_path), "region": region})
            composite_path = Path(composite["asset"]["path"])
            with Image.open(source_path) as source, Image.open(edit_path) as edit, Image.open(composite_path) as result:
                _require(result.size == source.size and result.format == "PNG",
                         "composite must preserve source dimensions in a PNG")
                _require(result.getpixel((0, 0))[:3] == edit.getpixel((0, 0)) == (230, 20, 180),
                         "composite must apply the requested edited pixel")
                _require(result.getpixel((3, 2))[:3] == source.getpixel((3, 2)) == base_colors[3],
                         "composite must preserve pixels outside the edited region")
            _require(composite["asset"].get("outsideProtectedPixelsUnchanged") is True
                     and composite["asset"]["parentSha256"] == source_sha,
                     "the native composite observer must confirm untouched pixels and source lineage")

            # A cold invalid edit must not even create the internal artifact
            # folder; observe the actual public handler and both durable UI
            # state keys before and after its refusal.
            cold_root = case_root / "cold-invalid-crop"
            cold_root.mkdir(parents=True, exist_ok=False)
            os.environ["NEYVIA_UI_STATE_ROOT"] = str(cold_root)
            cold_bus = UICommandBus(cold_root)
            os.environ["NEYVIA_UI_STATE_ROOT"] = str(case_root)
            cold_service = FixtureService(bus=cold_bus, safe_path=WorkspaceTools.safe_path,
                                         image_lock=threading.RLock(), image_generation=None,
                                         backend=None)
            cold_source = cold_root / "cold-source.png"
            with Image.new("RGB", (4, 3), (41, 52, 63)) as cold_image:
                cold_image.save(cold_source, "PNG")
            call(cold_service, "image.open", {"source": str(cold_source)})
            report_state(cold_service, {"status": "editing", "assetId": "fixture-cold-image"}, "p22-fixture")
            cold_output_dir = cold_bus.root / ".agent_control" / "image-studio"

            def cold_snapshot():
                return {
                    "artifactDirectoryExists": cold_output_dir.exists(),
                    "artifactNames": sorted(path.name for path in cold_output_dir.iterdir())
                    if cold_output_dir.exists() else [],
                    "requested": cold_bus.get("image:requested"),
                    "uiState": cold_bus.get("app:image-studio"),
                }

            before_invalid = cold_snapshot()
            try:
                call(cold_service, "image.crop", {"region": {"x": 3, "y": 2, "width": 2, "height": 2}})
            except ValueError as error:
                _require("exceeds image dimensions" in str(error), "invalid rectangles need a clear boundary refusal")
            else:
                raise ValueError(f"Contract {CONTRACTS[0]}: an out-of-bounds crop was accepted")
            after_invalid = cold_snapshot()
            _require(after_invalid == before_invalid,
                     "a rejected rectangle must preserve the artifact directory, requested image and observed UI state")

            # An image outside every approved root must also leave the active
            # asset and visible native state untouched.
            before_refusal = {"requested": bus.get("image:requested"), "uiState": bus.get("app:image-studio")}
            try:
                call(service, "image.open", {"source": str(outside_path)})
            except ValueError as error:
                _require("inside this workspace" in str(error), "outside-root image refusal must identify the boundary")
            else:
                raise ValueError(f"Contract {CONTRACTS[0]}: an outside-root image was opened")
            after_refusal = {"requested": bus.get("image:requested"), "uiState": bus.get("app:image-studio")}
            _require(after_refusal == before_refusal,
                     "an outside-root refusal must preserve the current requested image and observed UI state")

            export_path = case_root / "exports" / "source-export.png"
            call(service, "image.open", {"source": str(source_path)})
            approval = call(service, "image.export", {"path": str(export_path)})
            _require(approval.get("status") == "approval_required" and approval.get("approvalId"),
                     "export must request approval before writing")
            approved = service.approve(approval["approvalId"])
            _require(approved.get("approved") is True,
                     "the disposable fixture must approve only its exact export request")
            exported = call(service, "image.export", {"path": str(export_path)})
            _require(exported.get("ok") is True and Path(exported["path"]).name == "source-export.png",
                     "export must return the requested new filename")
            _require(export_path.is_file() and hashlib.sha256(export_path.read_bytes()).hexdigest() == source_sha,
                     "export must write the exact source bytes to the new destination")
            _require(isinstance(exported.get("publication"), dict) and exported["publication"].get("ok") is True,
                     "export must publish its real output through the shared observer")
            case = {"id": "image-studio.pixel-edit-journey", "contracts": list(CONTRACTS), "ok": True,
                    "cropDimensions": crop["asset"]["dimensions"], "resizeDimensions": resized["asset"]["dimensions"],
                    "compositeOutsidePixelsUnchanged": composite["asset"]["outsideProtectedPixelsUnchanged"],
                    "exportFilename": export_path.name, "outsidePathRefused": True,
                    "invalidRectangleRefused": True,
                    "invalidRectanglePreservedArtifactDirectory": before_invalid == after_invalid,
                    "invalidRectanglePreservedRequestedImage": after_invalid["requested"] == before_invalid["requested"],
                    "invalidRectanglePreservedUiState": after_invalid["uiState"] == before_invalid["uiState"]}
            return {"ok": True, "contracts": list(CONTRACTS), "cases": [case], "failures": [],
                    "durationMs": round((time.perf_counter() - started) * 1000, 3),
                    "stateRoot": str(case_root), "evidenceRoot": str(outside_root),
                    "frontier": "Proves the production native Image Studio handler transforms synthetic pixels, preserves the unedited composite region, requests and receives a disposable fixture grant before export, publishes exact bytes, and refuses the two tested invalid paths; no real operator identity, remote provider, editor rendering, user assets, or browser journey is claimed."}
        finally:
            if previous_state is None:
                os.environ.pop("NEYVIA_UI_STATE_ROOT", None)
            else:
                os.environ["NEYVIA_UI_STATE_ROOT"] = previous_state
    except Exception as error:
        return {"ok": False, "contracts": list(CONTRACTS), "cases": [{"id": "image-studio.pixel-edit-journey",
                "contracts": list(CONTRACTS), "ok": False, "error": str(error)}], "failures": [str(error)],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(case_root), "evidenceRoot": str(outside_root)}
