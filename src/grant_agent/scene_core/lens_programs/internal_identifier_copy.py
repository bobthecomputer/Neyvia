import re

_INTERNAL_PATTERNS = (
    re.compile(r"\bnull\b|\bnone\b|\bundefined\b", re.IGNORECASE),
    re.compile(r"<[A-Z]\d{1,3}[-_][A-Za-z0-9_-]{3,}", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]{2,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9_-]{2,}\.(?:exe|dll|py|so|dylib)\b", re.IGNORECASE),
    re.compile(r"\b(?:source|session|run|tool)[-_ ]?(?:id|key|token)\s*[:=]\s*[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{12,}\b", re.IGNORECASE),
)

def measure(rgb, nodes, viewport):
    facts = {}
    for node in nodes:
        text = node.get("text", "")
        flagged = any(pattern.search(text) for pattern in _INTERNAL_PATTERNS)
        facts[node["id"]] = {"internalIdentifier": bool(flagged)}
    return {"facts": facts, "nodes": []}