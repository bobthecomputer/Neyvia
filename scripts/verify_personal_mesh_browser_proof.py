#!/usr/bin/env python3
"""Validate a redacted, deterministic Personal Mesh browser-proof receipt.

The recorder is deliberately separate from this verifier.  It may run in an
already-authenticated browser session, but this tool never reads credentials,
cookies, or storage and never performs a login.  A receipt is only accepted
when its UI observations still describe the checked source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "neyvia.personal-mesh-browser-proof.v1"
_RGB = re.compile(r"^rgba?\(([^)]+)\)$", re.I)
_HEX = re.compile(r"^#([0-9a-f]{3,8})$", re.I)
_SENSITIVE_KEY = re.compile(r"(?:password|token|cookie|authorization)", re.I)


class ProofError(ValueError):
    """A receipt is not sufficient evidence for the Personal Mesh gate."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rgb(value: str) -> tuple[float, float, float]:
    value = value.strip()
    match = _HEX.fullmatch(value)
    if match:
        raw = match.group(1)
        if len(raw) in {3, 4}:
            raw = "".join(char * 2 for char in raw)
        if len(raw) == 8 and raw[-2:].lower() != "ff":
            raise ProofError("transparent backgrounds are not deterministic proof")
        return tuple(int(raw[offset : offset + 2], 16) / 255 for offset in (0, 2, 4))  # type: ignore[return-value]
    match = _RGB.fullmatch(value)
    if not match:
        raise ProofError(f"unsupported computed colour {value!r}")
    parts = [part.strip() for part in match.group(1).split(",")]
    if len(parts) not in {3, 4}:
        raise ProofError(f"invalid computed colour {value!r}")
    if len(parts) == 4 and float(parts[3]) != 1:
        raise ProofError("transparent backgrounds are not deterministic proof")
    channels = []
    for part in parts[:3]:
        if part.endswith("%"):
            channels.append(float(part[:-1]) / 100)
        else:
            channels.append(float(part) / 255)
    if any(channel < 0 or channel > 1 for channel in channels):
        raise ProofError(f"invalid computed colour {value!r}")
    return tuple(channels)  # type: ignore[return-value]


def _luminance(rgb: tuple[float, float, float]) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = _luminance(_rgb(foreground)), _luminance(_rgb(background))
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _reject_undefined(value: Any, path: str) -> None:
    if value is None:
        raise ProofError(f"{path} contains null user-visible data")
    if isinstance(value, str) and value.strip().lower() in {"undefined", "null"}:
        raise ProofError(f"{path} contains undefined user-visible data")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_undefined(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_undefined(child, f"{path}[{index}]")


def _reject_sensitive_keys(value: Any, path: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                raise ProofError(f"{path}.{key} is not allowed in a browser proof receipt")
            _reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, f"{path}[{index}]")


def _require_map(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProofError(f"{field} must be an object")
    return value


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofError(f"{field} must be a non-negative integer")
    return value


def _require_capture(value: Any, field: str) -> dict[str, Any]:
    capture = _require_map(value, field)
    if capture.get("visited") is not True or not isinstance(capture.get("capture"), str) or not capture["capture"].strip():
        raise ProofError(f"{field} needs a visited state and a bounded capture reference")
    visible = capture.get("visibleValues")
    if not isinstance(visible, list) or not visible:
        raise ProofError(f"{field}.visibleValues must be a non-empty list")
    _reject_undefined(visible, f"{field}.visibleValues")
    return capture


def validate_receipt(receipt: dict[str, Any], *, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    """Validate receipt and return a compact, safe gate result or raise ProofError."""
    _reject_sensitive_keys(receipt)
    if receipt.get("schema") != SCHEMA:
        raise ProofError(f"schema must be {SCHEMA}")
    captured_at = receipt.get("capturedAt")
    if not isinstance(captured_at, str):
        raise ProofError("capturedAt must be an ISO-8601 timestamp")
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProofError("capturedAt must be an ISO-8601 timestamp") from exc
    max_age = receipt.get("maxAgeSeconds", 900)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not 1 <= max_age <= 3600:
        raise ProofError("maxAgeSeconds must be a positive integer no greater than 3600")
    current = now or datetime.now(UTC)
    if captured.tzinfo is None or captured > current or (current - captured).total_seconds() > max_age:
        raise ProofError("browser evidence is stale or has an invalid capture time")

    source_files = receipt.get("sourceFiles")
    if not isinstance(source_files, list) or not source_files:
        raise ProofError("sourceFiles must contain current source hashes")
    checked_hashes: list[dict[str, str]] = []
    for row in source_files:
        row = _require_map(row, "sourceFiles entry")
        relative = row.get("path")
        expected = row.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise ProofError("every sourceFiles entry needs a relative path and SHA-256")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ProofError(f"source path must be a safe relative path: {relative}")
        candidate = (root / relative_path).resolve()
        if root.resolve() not in candidate.parents or not candidate.is_file():
            raise ProofError(f"source file is unavailable: {relative}")
        actual = _sha256(candidate)
        if actual.lower() != expected.lower():
            raise ProofError(f"stale embedded proof: {relative} hash changed")
        checked_hashes.append({"path": relative, "sha256": actual})

    states = _require_map(receipt.get("states"), "states")
    for state_name in ("route", "modal", "entry"):
        state = _require_map(states.get(state_name), f"states.{state_name}")
        if not isinstance(state.get("before"), str) or not isinstance(state.get("after"), str):
            raise ProofError(f"states.{state_name} needs before and after captures")
    if states["route"]["after"] != "/control":
        raise ProofError("Personal Mesh proof must return to /control")
    if states["modal"].get("after") not in {"closed", "false"}:
        raise ProofError("Personal Mesh modal must have a captured closed state")
    if states["entry"].get("before") != "Lab" or states["entry"].get("after") != "Personal Mesh":
        raise ProofError("Lab/Personal Mesh entry was not captured separately")
    mesh_tabs = _require_map(states.get("meshTabs"), "states.meshTabs")
    for tab_name in ("trust", "nearby", "sync"):
        _require_capture(mesh_tabs.get(tab_name), f"states.meshTabs.{tab_name}")

    ui = _require_map(receipt.get("ui"), "ui")
    api = _require_map(receipt.get("api"), "api")
    ui_count = _require_int(ui.get("historyCount"), "ui.historyCount")
    api_count = _require_int(api.get("historyCount"), "api.historyCount")
    if ui_count != api_count:
        raise ProofError(f"history count mismatch: ui={ui_count}, api={api_count}")
    visible = ui.get("visibleValues")
    if not isinstance(visible, list) or not visible:
        raise ProofError("ui.visibleValues must record bounded visible UI values")
    _reject_undefined(visible, "ui.visibleValues")

    styles = receipt.get("computedStyles")
    if not isinstance(styles, list) or not styles:
        raise ProofError("computedStyles must record foreground/background pairs")
    contrasts = []
    for index, style in enumerate(styles):
        style = _require_map(style, f"computedStyles[{index}]")
        name, fg, bg = style.get("name"), style.get("foreground"), style.get("background")
        if not all(isinstance(item, str) and item.strip() for item in (name, fg, bg)):
            raise ProofError(f"computedStyles[{index}] must name foreground and background")
        ratio = contrast_ratio(fg, bg)
        if ratio < 4.5:
            raise ProofError(f"computedStyles[{index}] contrast {ratio:.2f} is below 4.5")
        contrasts.append({"name": name, "ratio": round(ratio, 2)})
    return {"ok": True, "schema": SCHEMA, "historyCount": ui_count, "contrast": contrasts, "sourceFiles": checked_hashes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="write a compact validation result")
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        result = validate_receipt(_require_map(receipt, "receipt"))
    except (OSError, json.JSONDecodeError, ProofError) as exc:
        result = {"ok": False, "schema": SCHEMA, "error": str(exc)}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
