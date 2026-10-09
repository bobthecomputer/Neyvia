import re

_SNAKE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]+\b")
_DOTTED = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]*\.[a-zA-Z][a-zA-Z0-9_.-]*\b")
_HOST = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|dev|app|edu|gov|co|uk|de|fr|ai|html|htm)\b", re.IGNORECASE)
_NULL = re.compile(r"\b(?:null|undefined|none|nil)\b", re.IGNORECASE)
_HEX = re.compile(r"\b[0-9a-fA-F]{20,}\b")
_ANGLE_ID = re.compile(r"<[A-Z][A-Z0-9]*(?:-[A-Za-z0-9]+){1,}(?:>)?")
_UPPER_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:-[a-zA-Z0-9]+){2,}\b")
_CONTEXT_ID = re.compile(r"\b(?:src|source|session|run|task|tool|runtime|directory|checkout)[-_][a-zA-Z0-9_-]{5,}\b", re.IGNORECASE)


def measure(rgb, nodes, viewport):
    facts = {}
    for node in nodes:
        text = node.get("text", "")
        found = bool(_SNAKE.search(text) or _NULL.search(text) or _HEX.search(text) or _ANGLE_ID.search(text) or _UPPER_ID.search(text) or _CONTEXT_ID.search(text))
        if not found:
            for match in _DOTTED.finditer(text):
                token = match.group(0)
                if not _HOST.fullmatch(token):
                    found = True
                    break
        facts[node["id"]] = {"internalIdentifierCopy": found}
    return {"facts": facts, "nodes": []}