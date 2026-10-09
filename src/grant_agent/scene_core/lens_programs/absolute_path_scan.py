import re

_DRIVE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/])(?:[^\\/\s<>\"']+[\\/])*[^\\/\s<>\"']+")
_REPO_PATH = re.compile(r"(?<![A-Za-z0-9.])(?:[A-Za-z0-9_.@-]+/){1,}[A-Za-z0-9_.@-]+\.[A-Za-z0-9]{1,12}(?![A-Za-z0-9])")
_ENCODED_ROUTE = re.compile(r"(?i)(?:%2f|%5c)(?:[a-z0-9._~%+-]+(?:%2f|%5c)){1,}[a-z0-9._~%+-]*")

def measure(rgb, nodes, viewport):
    facts = {}
    for node in nodes:
        text = node.get("text", "")
        found = bool(_DRIVE_PATH.search(text) or _REPO_PATH.search(text) or _ENCODED_ROUTE.search(text))
        facts[node["id"]] = {"absolutePathText": found}
    return {"facts": facts, "nodes": []}
