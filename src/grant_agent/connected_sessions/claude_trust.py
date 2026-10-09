"""Recognize only Claude Code's startup folder-trust menu; never answer it automatically."""
from __future__ import annotations

import re
from dataclasses import dataclass

TRUST_TOOL = "ClaudeFolderTrust"
_CHOICE = re.compile(r"(?P<selected>[>❯])?\s*(?P<label>No, exit|Yes, I trust this folder)")


@dataclass(frozen=True)
class TrustMenu:
    detail: str
    labels: tuple[str, ...]
    selected: int

    def keys(self, approve: bool) -> str:
        target = self.labels.index("Yes, I trust this folder" if approve else "No, exit")
        movement = "\x1b[B" if target > self.selected else "\x1b[A"
        return movement * abs(target - self.selected) + "\r"


def trust_menu(text: str) -> TrustMenu | None:
    # Output is bounded by the terminal owner. Use the latest complete startup frame.
    start = text.rfind("Quick safety check:")
    if start < 0:
        return None
    frame = text[start:]
    end = frame.find("Esc to cancel")
    if end < 0:
        return None
    if frame[end + len("Esc to cancel"):].strip():
        return None  # A later screen replaced this menu; never act on buffered history.
    frame = frame[:end + len("Esc to cancel")]
    if "Is this a project you created or one you trust?" not in frame or "Enter to confirm" not in frame:
        return None
    choices = list(_CHOICE.finditer(frame))
    labels = tuple(match.group("label") for match in choices)
    selected = [index for index, match in enumerate(choices) if match.group("selected")]
    if len(choices) != 2 or set(labels) != {"No, exit", "Yes, I trust this folder"} or len(selected) != 1:
        return None
    return TrustMenu(frame, labels, selected[0])
