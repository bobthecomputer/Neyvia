"""Native execution of portable, enabled Codex MCP servers.

Configuration stays in its original store; commands and credentials never enter
the model-visible inventory. Host-private app transports are explicitly reported.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from .codex_import import CodexAssetImporter
from .mcp_broker import McpOutboundBroker


def _server_id(owner: str, name: str) -> str:
    digest = hashlib.sha256(f"{owner}:{name}".encode()).hexdigest()[:10]
    return "codex-" + re.sub(r"[^a-z0-9-]", "-", name.lower())[:36] + "-" + digest


def _expand(value, plugin_root: Path):
    if isinstance(value, str):
        for marker in ("${CLAUDE_PLUGIN_ROOT}", "${CODEX_PLUGIN_ROOT}", "${PLUGIN_ROOT}"):
            value = value.replace(marker, str(plugin_root))
        return value
    if isinstance(value, list):
        return [_expand(item, plugin_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, plugin_root) for key, item in value.items()}
    return value


def discover_codex_servers(root: Path, codex_home=None):
    importer = CodexAssetImporter(root, codex_home or os.environ.get("CODEX_HOME"))
    config = importer._config()
    servers, rows = {}, []

    def add(owner, name, raw, plugin_root):
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            return
        server_id = _server_id(owner, name)
        expanded = _expand(raw, plugin_root)
        stdio = bool(expanded.get("command")) and not expanded.get("url")
        http = bool(expanded.get("url")) and not expanded.get("command") and not any(
            expanded.get(key) for key in ("oauth", "auth", "bearer_token_env_var", "env_http_headers", "app", "app_host")
        ) and str(expanded.get("transport") or expanded.get("type") or "http").lower() in {
            "http", "streamable-http", "streamable_http"
        }
        portable = stdio or http
        unresolved = "${" in json.dumps(expanded)
        reason = ("Unresolved plugin environment/configuration placeholder" if unresolved else
                  "Requires OAuth, an app-host or a legacy transport adapter" if not portable else "")
        if portable and not unresolved:
            servers[server_id] = {**expanded, "transport": "stdio" if stdio else "streamable-http", "framing": "newline",
                                  "cwd": expanded.get("cwd") or str(plugin_root),
                                  "startupTimeoutS": expanded.get("startup_timeout_sec", 15),
                                  "requestTimeoutS": expanded.get("tool_timeout_sec", 30),
                                  "requiresApprovalDefault": True}
        rows.append({"server": server_id, "name": name, "pluginId": owner,
                     "nativeExecutable": portable and not unresolved,
                     "status": "configured_not_probed" if portable and not unresolved else "adapter_required",
                     "reason": reason})

    for name, raw in (config.get("mcp_servers") or {}).items():
        add("codex-config", str(name), raw, importer.codex_home)
    for plugin in importer._plugin_rows(config):
        if not plugin["enabled"]:
            continue
        manifest_path = Path(plugin["manifestPath"])
        plugin_root = manifest_path.parent.parent if manifest_path.parent.name == ".codex-plugin" else manifest_path.parent
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            definitions = manifest.get("mcpServers")
            if definitions is None and (plugin_root / ".mcp.json").is_file():
                definitions = ".mcp.json"
            if isinstance(definitions, str):
                candidate = (plugin_root / definitions).resolve()
                if not candidate.is_relative_to(plugin_root.resolve()):
                    raise ValueError("Plugin server manifest escapes plugin root")
                definitions = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(definitions, dict):
                definitions = definitions.get("mcpServers", definitions)
                for name, raw in definitions.items():
                    add(plugin["pluginId"], str(name), raw, plugin_root)
            elif plugin.get("hasApps") or plugin.get("hasMcpServers"):
                rows.append({"pluginId": plugin["pluginId"], "name": plugin["name"],
                             "nativeExecutable": False, "status": "adapter_required",
                             "reason": "Plugin requires the Codex app's connected service"})
        except (OSError, ValueError, TypeError):
            rows.append({"pluginId": plugin["pluginId"], "name": plugin["name"],
                         "nativeExecutable": False, "status": "invalid_manifest",
                         "reason": "Plugin MCP manifest could not be resolved"})
    return servers, rows


class CodexPluginAccess:
    def __init__(self, root: Path, codex_home=None):
        servers, self.rows = discover_codex_servers(root, codex_home)
        self.configs = servers
        self.broker = McpOutboundBroker(root, config={"servers": servers}, include_default_demo=False)

    def inventory(self):
        return {"servers": self.rows, "nativeServerCount": len(self.broker.list_servers()),
                "toolDiscovery": "Select a server and search to connect and enumerate its real tools"}

    def search(self, server: str, query: str = "", limit: int = 20):
        return {"tools": [row for row in self.broker.search(query, limit=max(1, min(limit, 50)), server=server)
                          if self._allowed(server, row.get("name", ""))]}

    def _allowed(self, server, tool):
        cfg = self.configs.get(server, {})
        return ("enabled_tools" not in cfg or tool in cfg["enabled_tools"]) and tool not in cfg.get("disabled_tools", [])

    def describe(self, server: str, tool: str):
        if not self._allowed(server, tool):
            raise PermissionError("Tool disabled in Codex configuration")
        return self.broker.describe(server, tool)

    def call(self, server: str, tool: str, arguments: dict, *, approved: bool = False):
        if not self._allowed(server, tool):
            return {"ok": False, "status": "blocked", "reason": "Tool disabled in Codex configuration"}
        return self.broker.call(server, tool, arguments, approved=approved)

    def close(self):
        for state in self.broker._servers.values():
            transport = state._transport_impl
            if transport and hasattr(transport, "close"):
                transport.close()
