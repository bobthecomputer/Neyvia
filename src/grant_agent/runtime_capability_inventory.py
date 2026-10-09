"""Small, secret-safe inventory for runtime tools, linked plugins, and MCP servers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


SCHEMA = "neyvia.runtime_capability_inventory.v1"


def build_runtime_capability_inventory(
    root: str | Path,
    codex_home: str | Path | None = None,
    *, environment: dict | None = None,
) -> dict[str, Any]:
    """Return operational state only; never return server commands, URLs, or env values."""
    workspace = Path(root).expanduser().resolve()
    from .hermes_integration import plugin_inventory
    hermes = plugin_inventory(environment=environment)
    broker_config, audit, broker_rows = {}, {}, []
    mcp_servers: list[dict[str, Any]] = []
    mcp_source = "workspace_or_environment_config"
    mcp_error = ""
    try:
        from .mcp_broker import McpOutboundBroker

        broker = McpOutboundBroker(workspace, include_default_demo=False)
        broker_config = broker.config
        broker_rows = broker.list_servers()
        mcp_servers = [
            {
                "name": str(row.get("name") or ""),
                "transport": str(row.get("transport") or "unknown"),
                "configured": bool(row.get("configured")),
                "callable": bool(row.get("callable")),
                "authState": str(row.get("authState") or "unknown"),
                "hasEnvironment": bool(row.get("hasEnvironment")),
                "requiresApprovalDefault": bool(row.get("requiresApprovalDefault")),
                "toolCountCached": row.get("toolCountCached"),
                "notes": [str(note) for note in row.get("notes", []) if isinstance(note, str)],
            }
            for row in broker_rows
        ]
    except Exception as exc:  # The product should show an honest degraded state.
        mcp_error = type(exc).__name__

    plugins: list[dict[str, Any]] = []
    plugin_skills: list[dict[str, Any]] = []
    codex_available = False
    codex_error = ""
    try:
        from .codex_import import CodexAssetImporter

        audit = CodexAssetImporter(workspace, codex_home).audit()
        codex_available = bool(audit.get("available"))
        for row in audit.get("plugins", []):
            if not isinstance(row, dict):
                continue
            plugin = {
                "pluginId": str(row.get("pluginId") or ""),
                "name": str(row.get("name") or ""),
                "version": str(row.get("version") or ""),
                "marketplace": str(row.get("marketplace") or ""),
                "enabledInCodex": bool(row.get("enabled")),
                "skillCount": int(row.get("skillCount") or 0),
                "hasMcpServers": bool(row.get("hasMcpServers")),
                "activation": "linked_metadata_only",
                "nativeInNeyvia": False,
            }
            plugins.append(plugin)
            for skill in row.get("skills", []):
                if isinstance(skill, dict):
                    plugin_skills.append(
                        {
                            "skillId": str(skill.get("skillId") or ""),
                            "name": str(skill.get("name") or ""),
                            "description": str(skill.get("description") or "")[:220],
                            "pluginId": plugin["pluginId"],
                            "adapterRequired": True,
                            "usableAsNativeSkill": False,
                        }
                    )
        from .codex_plugin_access import discover_codex_servers
        from .codex_skill_access import CodexSkillAccess
        _, connections = discover_codex_servers(workspace, codex_home)
        assets = CodexSkillAccess(codex_home, workspace_root=workspace).discover()
        plugin_skills = [{**row, "originType": row["origin"], "status": row["readiness"],
                          "guidanceOnly": True, "usableAsNativeSkill": row["enabled"],
                          "promptHint": "Use codex.instructions.read with skillId=" + row["skillId"] + " and follow its instructions for this task."}
                         for row in assets["skills"]]
        for plugin in plugins:
            relevant = [row for row in connections if row.get("pluginId") == plugin["pluginId"]]
            readable = any(row["pluginId"] == plugin["pluginId"] and row["enabled"] for row in plugin_skills)
            plugin["nativeInNeyvia"] = readable
            plugin["activation"] = "instructions_available" if readable else "disabled_or_host_required"
            plugin["nativeDetail"] = ("Instructions available in Skills. " if readable else "") + " ".join(row["reason"] for row in relevant if row.get("reason"))
        for row in connections:
            mcp_servers.append({"name": row["name"], "serverId": row.get("server", ""),
                "transport": "codex_stdio" if row["nativeExecutable"] else "codex_host",
                "configured": True, "callable": False, "nativeExecutable": row["nativeExecutable"],
                "authState": row["status"], "source": "codex", "notes": [row["reason"] or "Native can connect on demand; execution not yet probed."]})
    except Exception as exc:
        codex_error = type(exc).__name__

    # Preserve same-named entries from distinct config sources for a clear provenance label.
    unique_mcp: dict[tuple[str, str], dict[str, Any]] = {}
    for row in mcp_servers:
        source = str(row.get("source") or "neyvia")
        unique_mcp[(source, str(row.get("name") or ""))] = row

    result = {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "mcpServers": sorted(unique_mcp.values(), key=lambda row: (row.get("source", "neyvia"), row["name"])),
        "plugins": plugins,
        "hermes": hermes,
        "pluginSkills": plugin_skills,
        "pluginPolicy": {
            "mode": "native_instructions_and_portable_mcp",
            "summary": "Native can read enabled Codex skills and reusable prompts, and call portable stdio MCP plugins. App-host and remote OAuth connectors require an adapter. Hermes plugins run in Hermes.",
        },
        "codexAvailable": codex_available,
        "degraded": bool(mcp_error or codex_error),
        "degradedSources": [
            source for source, error in (("mcp", mcp_error), ("codex", codex_error)) if error
        ],
    }
    from .proofs_e_release import check_runtime_inventory
    return check_runtime_inventory(result, broker_config, audit, broker_rows)
