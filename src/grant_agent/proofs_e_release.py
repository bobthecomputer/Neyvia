"""Executable PROOFS-e release, inventory and import-provenance postconditions."""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path


class ReleaseProofContractError(RuntimeError):
    def __init__(self, contract: str):
        self.contract = contract
        super().__init__(f"Proof contract {contract} failed")


def require(condition, contract):
    if not condition:
        raise ReleaseProofContractError(contract)


def check_hermes_inventory(result):
    require(set(result) == {"available", "plugins", "error"} and isinstance(result["available"], bool)
            and isinstance(result["error"], str) and isinstance(result["plugins"], list)
            and (result["available"] or not result["plugins"])
            and all(set(row) == {"name", "description", "version", "status", "source"}
                    and all(isinstance(value, str) for value in row.values()) for row in result["plugins"]),
            "runtime.hermes-metadata")
    return result


def check_runtime_inventory(result, broker_config, audit, broker_rows):
    require(result.get("schema") == "neyvia.runtime_capability_inventory.v1"
            and result.get("pluginPolicy", {}).get("mode") == "native_instructions_and_portable_mcp"
            and "Native can read enabled Codex skills" in result.get("pluginPolicy", {}).get("summary", ""),
            "runtime.capability-metadata")
    ordinary = {"name", "transport", "configured", "callable", "authState", "hasEnvironment", "requiresApprovalDefault", "toolCountCached", "notes"}
    linked = {"name", "serverId", "transport", "configured", "callable", "nativeExecutable", "authState", "source", "notes"}
    require(all(set(row) == (linked if row.get("source") == "codex" else ordinary)
                and isinstance(row["configured"], bool) and isinstance(row["callable"], bool)
                and (row.get("source") != "codex" or row["callable"] is False)
                for row in result["mcpServers"]), "runtime.capability-metadata")
    projected = [{"name": str(row.get("name") or ""), "transport": str(row.get("transport") or "unknown"),
                  "configured": bool(row.get("configured")), "callable": bool(row.get("callable")),
                  "authState": str(row.get("authState") or "unknown"), "hasEnvironment": bool(row.get("hasEnvironment")),
                  "requiresApprovalDefault": bool(row.get("requiresApprovalDefault")), "toolCountCached": row.get("toolCountCached"),
                  "notes": [str(note) for note in row.get("notes", []) if isinstance(note, str)]}
                 for row in broker_rows]
    require([row for row in result["mcpServers"] if row.get("source") != "codex"]
            == sorted(projected, key=lambda row: row["name"]), "runtime.capability-metadata")
    public_strings = []
    def collect(value):
        if isinstance(value, str): public_strings.append(value)
        elif isinstance(value, dict):
            for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(result)
    private_values = []
    for raw in (broker_config or {}).get("servers", {}).values():
        if isinstance(raw, dict):
            private_values.extend(str(raw.get(key) or "") for key in ("command", "url"))
            private_values.extend(str(value) for value in (raw.get("env") or {}).values())
    require(not any(value and any(value == public or (len(value) > 12 and value in public) for public in public_strings)
                    for value in private_values), "runtime.capability-metadata")
    public_plugins = {"pluginId", "name", "version", "marketplace", "enabledInCodex", "skillCount", "hasMcpServers", "activation", "nativeInNeyvia", "nativeDetail"}
    source = {row["pluginId"]: row for row in (audit or {}).get("plugins", []) if isinstance(row, dict)}
    complete_plugins = "codex" not in result["degradedSources"]
    require((len(result["plugins"]) == len(source) if complete_plugins else len(result["plugins"]) <= len(source))
            and all(set(row) in (public_plugins, public_plugins - {"nativeDetail"})
            and row["pluginId"] in source and row["enabledInCodex"] == bool(source[row["pluginId"]].get("enabled"))
            and row["activation"] in (("instructions_available",) if row["nativeInNeyvia"] else ("disabled_or_host_required", "linked_metadata_only"))
            and row["nativeInNeyvia"] == any(skill.get("pluginId") == row["pluginId"] and skill.get("enabled") for skill in result["pluginSkills"])
            for row in result["plugins"]), "runtime.capability-metadata")
    check_hermes_inventory(result["hermes"])
    return result


def check_ui_command_evidence(tokens, gateways, result):
    expected, registry_stack, pending = set(), [], False
    registry_name = re.compile(r"(?:[A-Z][A-Z0-9_]*_)?COMMANDS")
    quoted = re.compile(r"[\"'`]([a-z][a-z0-9_]*_command)[\"'`]")
    for number, token in enumerate(tokens):
        preceding = tokens[max(0, number - 4):number]
        if token == "=" and preceding and registry_name.fullmatch(preceding[-1]): pending = True
        if token in {"{", "[", "("}:
            registry_stack.append(pending or bool(registry_stack and registry_stack[-1])); pending = False
        elif token in {"}", "]", ")"}:
            if registry_stack: registry_stack.pop()
        elif token == ";": pending = False
        match = quoted.fullmatch(token)
        if not match: continue
        gateway = len(preceding) >= 2 and preceding[-1] == "(" and preceding[-2] in gateways
        command_slot = len(preceding) >= 2 and preceding[-1] in {":", "="} and re.fullmatch(r"(?:\w*_)?command|\w*Command", preceding[-2])
        if gateway or command_slot or (registry_stack and registry_stack[-1]): expected.add(match.group(1))
    require(result == expected, "impact.ui-call-evidence")
    return result


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return {node.value}
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        rows = [_literal(value) for value in node.elts]
        return set().union(*rows) if all(value is not None for value in rows) else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"set", "frozenset"} and len(node.args) == 1:
        return _literal(node.args[0])
    return None


def check_imported_registries(tree, trees, repo, result):
    expected = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module: continue
        source = Path(repo) / "src/grant_agent" / (node.module.removeprefix("grant_agent.").replace(".", "/") + ".py")
        if source not in trees: continue
        exported = {}
        for statement in trees[source].body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name): continue
            values = _literal(statement.value)
            if values and any(value.endswith("_command") for value in values):
                exported.setdefault(statement.targets[0].id, set()).update(values)
        for alias in node.names:
            if alias.name in exported: expected[alias.asname or alias.name] = exported[alias.name]
    require(result == expected, "impact.import-provenance")
    return result


def check_impact_index(result):
    branches = result["branches"]
    require(set(result["handled"]) == set().union(*(branch["commands"] for branch in branches))
            and all(any(command in branch["commands"] and location == f"src/grant_agent/web_backend.py:{branch['start']}"
                        for branch in branches) for command, location in result["handled"].items())
            and set(result["nextUi"]) <= set(result["ui"])
            and all(isinstance(paths, set) and paths and all(path.startswith("web/src/") for path in paths)
                    for paths in result["ui"].values()), "impact.index-provenance")
    return result


def check_dispatch_membership(tree, variable, named, result):
    def resolved(node):
        values = _literal(node)
        if values is not None: return values
        if isinstance(node, ast.Name): return set(named.get(node.id, set()))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr): return resolved(node.left) | resolved(node.right)
        return set()
    expected = []
    for branch in ast.walk(tree):
        if not isinstance(branch, ast.If): continue
        for test in ast.walk(branch.test):
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == variable and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.In)):
                commands = {value for value in resolved(test.comparators[0]) if value.endswith("_command")}
                if commands: expected.append((test.lineno, branch.body[-1].end_lineno, commands, branch))
    require(result == expected, "impact.dispatch-membership")
    return result
