import re

_WINDOWS_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/](?:[^\s<>\"'|]+[\\/])*[^\s<>\"'|]*")
_UNIX_ROOT = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|workspace|workspaces|Projects|mnt|opt|var|tmp|app|repo|root)/[^\s<>\"'|]+", re.I)
_REPO_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])(?:src|app|apps|packages|workspace|workspaces|projects|\.agent_control|\.github|\.codex|public|assets|lib|test|tests|docs)/[A-Za-z0-9_.@+%-]+(?:/[A-Za-z0-9_.@+%-]+)*(?:\.[A-Za-z0-9]{1,8})?(?![A-Za-z0-9])")
_ENCODED_ROUTE = re.compile(r"(?i)(?:%2f|%5c)(?:[A-Za-z0-9._~+%-]|%[0-9a-f]{2}){2,}")

def measure(rgb, nodes, viewport):
    facts = {}
    out_nodes = []
    for node in nodes:
        text = node.get("text", "")
        found = bool(_WINDOWS_PATH.search(text) or _UNIX_ROOT.search(text) or _REPO_PATH.search(text) or _ENCODED_ROUTE.search(text))
        node_facts = {"visiblePathCopy": found}
        facts[node["id"]] = node_facts
        out_nodes.append({"kind": node.get("kind", "text"), "text": text, "bounds": node.get("bounds", {}), "facts": node_facts})
    return {"facts": facts, "nodes": out_nodes}