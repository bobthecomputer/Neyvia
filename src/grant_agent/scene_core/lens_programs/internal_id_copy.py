import re


def measure(rgb, nodes, viewport):
    facts = {}
    # Keep patterns narrow: ordinary domain names and dotted versions are user-facing
    # in browser previews, while implementation-shaped tokens are stronger evidence.
    patterns = [
        re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9])"),
        re.compile(r"(?i)(?<![A-Za-z0-9])(?:null|undefined|nan)(?![A-Za-z0-9])"),
        re.compile(r"(?i)(?<![A-Za-z0-9])(?:[a-z][a-z0-9-]*\.)+(?:exe|dll|py|js|ts|json|yaml|yml|toml|sh|bat|ps1)(?![A-Za-z0-9])"),
        re.compile(r"(?i)<[^<>]{2,}(?:runtime|directory|path|token|id)[^<>]*>"),
        re.compile(r"(?i)\b(?:source|session|run|trace|request|task|job)[-_ ]?(?:id|token)\s*[:=]\s*[A-Za-z0-9._:-]{6,}"),
        re.compile(r"\b[A-Fa-f0-9]{8}-(?:[A-Fa-f0-9]{4}-){3}[A-Fa-f0-9]{12}\b"),
        re.compile(r"\b[A-Fa-f0-9]{24,}\b"),
    ]
    for node in nodes:
        text = node.get("text", "")
        matches = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                token = match.group(0)
                if token.lower() not in {item.lower() for item in matches}:
                    matches.append(token[:48])
        facts[node["id"]] = {"internalIdentifier": bool(matches), "identifierTokens": matches[:4]}
    return {"facts": facts, "nodes": []}
