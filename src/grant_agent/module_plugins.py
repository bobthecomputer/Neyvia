"""Trusted, repository-local optional modules; one manifest owns each action."""
from __future__ import annotations

import importlib.util
import json
import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def confined(path: str, base=REPO) -> Path:
    target = (base / path).resolve()
    target.relative_to(base.resolve())
    if not target.is_file():
        raise ValueError("Module file is missing: " + path)
    return target


def manifests(root=None):
    rows = []
    names = set()
    actions = set()
    selected = {}
    for path in sorted((REPO / "apps").glob("*/neyvia.module.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row["id"] in selected:
            raise ValueError("Duplicate repository module")
        selected[row["id"]] = (path, REPO, True)
    if root:
        from .source_marketplace import SourceMarketplace
        for item in SourceMarketplace(root).catalog()["items"]:
            if item["kind"] == "mod":
                base = Path(item["targetPath"])
                selected[item["id"]] = (base / "neyvia.module.json", base, item["state"] == "active")
    for path, base, enabled in selected.values():
        row = json.loads(path.read_text(encoding="utf-8"))
        if base != REPO:
            prefix = "apps/" + row["id"] + "/"
            row["files"] = [file.removeprefix(prefix) for file in row["files"]]
            for action in row["actions"]:
                action["file"] = action["file"].removeprefix(prefix)
        if row.get("schema") != "neyvia.module.v1" or not re.fullmatch(r"[a-z][a-z0-9-]*", row.get("id", "")):
            raise ValueError("Invalid module identity: " + str(path))
        if row["id"] in names:
            raise ValueError("Duplicate module: " + row["id"])
        names.add(row["id"])
        for key in ("name", "purpose", "files", "manual", "actions", "settings", "events", "dependencies", "ownerSurface"):
            if key not in row:
                raise ValueError("Module lacks " + key + ": " + row["id"])
        row["files"] = sorted(set(row["files"] + [path.relative_to(base).as_posix()]))
        for owned in row["files"]:
            confined(owned, base)
        for action in row["actions"]:
            # This namespace cannot replace core tools. Code is trusted installed
            # source, not user input, a download or an arbitrary Python import.
            name = action["name"]
            if not re.fullmatch(r"neyvia\.mod\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", name) or name in actions:
                raise ValueError("Invalid or duplicate mod action: " + name)
            actions.add(name)
            source = action["file"]
            if source not in row["files"] or not source.endswith(".py"):
                raise ValueError("Mod action must use owned Python source")
            if action.get("mutability") not in {"read", "artifact_write", "external_action"}:
                raise ValueError("Mod action must declare its actual mutability")
            if not re.fullmatch(r"[a-zA-Z_]\w*", action["function"]):
                raise ValueError("Invalid action function")
            schema = action["inputSchema"]
            if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
                raise ValueError("Mod action needs a typed object input schema")
        row["optional"] = True
        if base != REPO:
            row["_base"] = str(base)
            row["_enabled"] = enabled
        rows.append(row)
    return rows


def definitions(root=None):
    return [(action["name"].removeprefix("neyvia."), action["description"],
             action["inputSchema"]["properties"], action["inputSchema"].get("required", []))
            for row in manifests(root) for action in row["actions"]]


def mutability(name, root=None):
    return next(action["mutability"] for row in manifests(root) for action in row["actions"]
                if action["name"] == "neyvia." + name)


@lru_cache(maxsize=32)
def _load(source, stamp, base):
    spec = importlib.util.spec_from_file_location("neyvia_mod_" + str(abs(hash(source))), confined(source, Path(base)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dispatch(service, name, args):
    from .source_marketplace import SourceMarketplace
    market = SourceMarketplace(service.bus.root)
    with market._lock():
        return _dispatch_locked(service, name, args)


def _dispatch_locked(service, name, args):
    for row in manifests(service.bus.root):
        for action in row["actions"]:
            if action["name"] != "neyvia." + name:
                continue
            if row.get("_enabled") is False:
                raise ValueError("Module is disabled or its installed source failed integrity: " + row["id"])
            base = Path(row.get("_base", REPO))
            source = confined(action["file"], base)
            module = _load(action["file"], source.stat().st_mtime_ns, str(base))
            return getattr(module, action["function"])(args, root=service.bus.root)
    raise ValueError("Unknown mod action: " + name)
