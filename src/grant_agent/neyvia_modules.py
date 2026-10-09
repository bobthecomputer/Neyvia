"""Read-only repository module ownership and contract discovery."""
from __future__ import annotations

import json
from functools import lru_cache

from .module_map import REGISTRY, private_source
from .module_plugins import confined

TEXT = {"type": "string"}
DEFINITIONS = [
    ("modules.list", "Read and search Neyvia's generated module map, with saved enabled state.",
     {"query": TEXT, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
    ("modules.get", "Read a module's source ownership, manuals, actions, dependencies and contracts.", {"id": TEXT}, ["id"]),
    ("modules.source", "Read an exact owned module source file; never opens an unrelated workspace path.", {"id": TEXT, "path": TEXT}, ["id", "path"]),
    ("modules.validate", "Check every scoped file is owned, the map is current and manual actions exist.", {}, []),
]
COMMANDS = frozenset("modules_" + verb + "_command" for verb in ("list", "get", "source", "validate"))


@lru_cache(maxsize=2)
def _registry(stamp):
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def registry():
    return _registry(REGISTRY.stat().st_mtime_ns)


def module(identity):
    for row in registry()["modules"]:
        if row["id"] == identity:
            return row
    raise ValueError("Unknown module: " + str(identity))


def observed(service, row):
    from .source_marketplace import SourceMarketplace
    installed = SourceMarketplace(service.bus.root)._load()["items"].get(row["id"])
    return {**row, "enabled": installed.get("enabled", False) if installed else True,
            "manualSource": "manuals/cl/" + row["manual"] + ".cl"}


def call(service, name, args):
    if name == "modules.list":
        query = str(args.get("query", "")).casefold().strip()
        offset = max(0, int(args.get("offset", 0)))
        limit = min(100, max(1, int(args.get("limit", 50))))
        rows = [row for row in registry()["modules"] if not query or query in
                " ".join([row["id"], row["name"], row["purpose"], row["manual"], *row["files"], *row["actions"]]).casefold()]
        projected = [observed(service, row) for row in rows[offset:offset + limit]]
        return {"ok": True, "total": len(rows), "offset": offset,
                "modules": [{key: row[key] for key in
                    ("id", "name", "purpose", "manual", "optional", "enabled", "ownerSurface")}
                    for row in projected]}
    if name == "modules.get":
        return {"ok": True, "module": observed(service, module(args["id"]))}
    if name == "modules.source":
        if private_source(args["path"]):
            raise PermissionError("Private runtime configuration is not module source")
        row = module(args["id"])
        allowed = set(row["files"]) | {"manuals/cl/" + manual + ".cl" for manual in row["manuals"]}
        if args["path"] not in allowed:
            raise ValueError("Source must belong to the selected module or its manual")
        path = confined(args["path"])
        if private_source(path):
            raise PermissionError("Private runtime configuration is not module source")
        with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            text = stream.read(200001)
        return {"ok": True, "path": args["path"], "text": text[:200000], "truncated": len(text) > 200000}
    if name == "modules.validate":
        from .module_map import check
        return check()
    raise ValueError("Unknown module operation")


def handle_command(backend, command, args):
    from .neyvia_workspace_tools import workspace_for
    if command not in COMMANDS:
        raise ValueError("Unknown modules command")
    return call(workspace_for(backend.root, backend), "modules." + command[8:-8], args)
