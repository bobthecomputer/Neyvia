import re
import numpy as np

_DRIVE_RE = re.compile(r"(?i)(?<![\w])([A-Z]:[\\/][^\s<>\"']{3,})")
_REPO_RE = re.compile(r"(?i)(?<![\w])((?:[A-Za-z0-9_.-]+[\\/]){2,}[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9]{1,8})?)(?![\w])")
_ENCODED_RE = re.compile(r"(?i)(?:%2f|%5c)(?:[A-Za-z0-9._~-]|%[0-9a-f]{2}){2,}")
_TERMINAL_RE = re.compile(r"(?i)(?:\bterminal\b|\bconsole\b|\bshell\b|\bcommand prompt\b|\bpowershell\b|\bPS\s+[A-Z]:[\\/])")
_UI_ACTION_RE = re.compile(r"(?i)^\s*(?:edit|annotate|open|copy|share|download|upload|view|save|delete|rename|more)(?:\s*[/|>]\s*[\w -]+)?\s*$")


def measure(rgb, nodes, viewport):
    facts = {}
    for node in nodes:
        if node.get("kind") != "text":
            continue
        text = str(node.get("text", "")).strip()
        if not text or _UI_ACTION_RE.fullmatch(text) or _TERMINAL_RE.search(text):
            continue
        drive = _DRIVE_RE.search(text)
        encoded = _ENCODED_RE.search(text)
        repo = _REPO_RE.search(text)
        # Drive paths commonly occur as terminal prompts; only count them when the
        # OCR line contains meaningful interface copy beyond a path fragment.
        if drive:
            candidate = drive.group(1)
            tail = text[drive.end():].strip()
            path_only = not tail or len(tail) < 5 or re.fullmatch(r"[\\/A-Za-z0-9_.-]+", tail) is not None
            if path_only:
                continue
            facts[node["id"]] = {"userFacingPath": True}
        elif encoded or repo:
            candidate = encoded.group(0) if encoded else repo.group(1)
            # Short component fragments and command-like route crumbs are noisy OCR.
            if len(candidate) < 16:
                continue
            facts[node["id"]] = {"userFacingPath": True}
    return {"facts": facts, "nodes": []}