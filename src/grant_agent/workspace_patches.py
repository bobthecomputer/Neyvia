"""Hash-bound character edits. Coordinates refer to the exact UTF-8 read snapshot."""
from __future__ import annotations

import hashlib
from pathlib import Path


def patched_text(content: str, edits: list[dict]) -> str:
    if not edits or len(edits) > 100:
        raise ValueError("Supply 1–100 range edits")
    ordered = sorted(edits, key=lambda row: (row["start"], row["end"]))
    previous_end = -1
    previous_start = -1
    for row in ordered:
        start, end = row["start"], row["end"]
        if not 0 <= start <= end <= len(content):
            raise ValueError("Patch range is outside the observed file")
        if start < previous_end or start == previous_start:
            raise ValueError("Patch ranges overlap or have ambiguous insertion order")
        if "expectedText" in row and content[start:end] != row["expectedText"]:
            raise ValueError("Patch range no longer matches expectedText")
        previous_start, previous_end = start, end
    for row in reversed(ordered):
        content = content[:row["start"]] + row["text"] + content[row["end"]:]
    return content


def patch(registry, args):
    candidate = Path(args["path"]).expanduser()
    candidate = candidate if candidate.is_absolute() else registry.root / candidate
    resolved = candidate.resolve()
    resolved.relative_to(registry.root)
    raw = resolved.read_bytes()
    if len(raw) > 1024 * 1024 or b"\0" in raw:
        raise ValueError("Patches accept UTF-8 text files up to 1 MiB")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args["expectedSha256"].lower():
        raise ValueError("Patch conflict: expectedSha256 does not match; read the file again")
    content = patched_text(raw.decode("utf-8", errors="strict"), args["edits"])
    result = registry._workspace_write({"path": args["path"], "content": content,
                                       "expectedSha256": digest})
    return {**result, "beforeSha256": digest, "editCount": len(args["edits"]),
            "coordinateUnit": "unicode_character"}


def tool_spec(spec_type):
    return spec_type(
        name="workspace.patch", category="files", mutability_class="file_write",
        risk_level="medium", requires_approval=True, parallel_safe=False,
        capabilities=("workspace.write", "file.hash"), aliases=("patch file", "range edit"),
        description="Apply non-overlapping character ranges from one workspace.read snapshot, guarded by its SHA-256. Replacements preserve untouched bytes; stale hashes fail without writing.",
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": {"path": {"type": "string", "minLength": 1},
                                     "expectedSha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
                                     "edits": {"type": "array", "minItems": 1, "maxItems": 100,
                                               "items": {"type": "object", "additionalProperties": False,
                                                         "properties": {"start": {"type": "integer", "minimum": 0},
                                                                        "end": {"type": "integer", "minimum": 0},
                                                                        "text": {"type": "string"},
                                                                        "expectedText": {"type": "string"}},
                                                         "required": ["start", "end", "text"]}}},
                      "required": ["path", "expectedSha256", "edits"]})
