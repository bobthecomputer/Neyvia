import re

_ERROR_CONTEXT = re.compile(r"\b(?:error|failed|failure|missing|cannot|could not|install|runtime|driver|source|session|trace|request|task|checkout|token|identifier|internal)\b", re.I)
_NULL_LITERAL = re.compile(r"(?<![\w.])(?:null|undefined|none|nan)(?![\w.])", re.I)
_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_PLACEHOLDER = re.compile(r"<[^<>]{1,80}>")
_ID_LABEL = re.compile(r"\b(?:source|session|run|task|trace|request)[-_ ]?(?:id|key|token)\s*[:=]\s*[A-Za-z0-9._-]+\b", re.I)
_HEX_ID = re.compile(r"\b[0-9a-fA-F]{12,}\b")
_DOTTED_INTERNAL = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,}\b")
_WEB_DOMAIN = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+(?:com|org|net|edu|gov|io|dev|app|co|uk|fr|de|jp|info|ai)\b", re.I)
_PATH = re.compile(r"(?:[A-Za-z]:\s*\\|/)[^\s<>]+")
_DRIVER_TOKEN = re.compile(r"\b[A-Za-z0-9_-]*(?:runtime|directory|source|session|checkout|driver|token|identifier|id)[A-Za-z0-9_-]*\b", re.I)
_COMMAND_CONTEXT = re.compile(r"\b(?:run|command|execute|install|script|download|missing|error|failed|failure|cannot|could not|driver|runtime)\b", re.I)
_GENERIC_NULL_CONTEXT = re.compile(r"\b(?:error|failed|failure|missing|cannot|could not|unexpected|invalid|value|returned|response|result)\b", re.I)


def measure(rgb, nodes, viewport):
    facts = {}
    for node in nodes:
        text = node.get("text", "")
        if not text:
            continue
        placeholder = _PLACEHOLDER.search(text)
        placeholder_internal = bool(placeholder and _DRIVER_TOKEN.search(placeholder.group()))
        explicit_id = bool(_ID_LABEL.search(text))
        context = bool(_COMMAND_CONTEXT.search(text))
        path = bool(_PATH.search(text))
        # Paths alone commonly appear in terminal transcripts; require explicit command/error framing.
        path_internal = path and context and bool(re.search(r"\\|/", text))
        # A generic status such as "None open" is ordinary UI copy; require technical context for null-like values.
        null_internal = bool(_NULL_LITERAL.search(text)) and bool(_GENERIC_NULL_CONTEXT.search(text))
        token_internal = context and bool(_DRIVER_TOKEN.search(text))
        hex_internal = bool(_HEX_ID.search(text)) and bool(_ERROR_CONTEXT.search(text))
        dotted = bool(_DOTTED_INTERNAL.search(text)) and not _WEB_DOMAIN.search(text)
        dotted_internal = dotted and bool(_COMMAND_CONTEXT.search(text))
        if placeholder_internal or explicit_id or path_internal or null_internal or token_internal or hex_internal or dotted_internal:
            facts[node["id"]] = {"identifierCopy": True}
    return {"facts": facts, "nodes": []}
