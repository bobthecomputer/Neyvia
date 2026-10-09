"""Server-side permission modes for Neyvia Native chat access."""

from __future__ import annotations

from typing import Any


PERMISSION_MODES = frozenset({"read-only", "workspace", "full-access"})

# These are the exact local grants already exposed by the workspace permission.
WORKSPACE_MUTATION_TOOLS = (
    "neyvia.memory.remember",
    "neyvia.memory.correct",
    "neyvia.memory.forget",
    "workspace.write",
    "workspace.patch",
    "preview.screenshot",
    "preview.taste",
    "laya.native.neyvia_navigation",
    "neyvia.image.crop",
    "neyvia.image.resize",
    "neyvia.image.composite",
    "neyvia.image.export",
    # Public-source research: reads public pages like web.fetch and writes its
    # receipts and cached sources in the selected workspace only.
    "neyvia.research.journey",
)

# Full access adds local command execution and the supported in-product browser
# journey. The Laya grant above remains its one explicitly named native journey;
# this set does not confer managed connector or arbitrary external mutations.
FULL_ACCESS_MUTATION_TOOLS = tuple(sorted({
    *WORKSPACE_MUTATION_TOOLS,
    "terminal.exec",
    "workspace.browser",
    "neyvia.image.generate",
}))


def normalize_permission_mode(payload: dict[str, Any]) -> str:
    """Read the explicit mode, falling back to the legacy workspace boolean."""

    if "permissionMode" in payload:
        mode = payload.get("permissionMode")
        if not isinstance(mode, str) or mode not in PERMISSION_MODES:
            raise ValueError("permissionMode must be read-only, workspace, or full-access.")
        return mode
    return "workspace" if payload.get("workspaceToolsAllowed") is True else "read-only"


def mutation_tools_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "read-only":
        return ()
    if mode == "workspace":
        return WORKSPACE_MUTATION_TOOLS
    if mode == "full-access":
        return FULL_ACCESS_MUTATION_TOOLS
    raise ValueError("Unknown Native permission mode.")


def access_context(
    mode: str,
    *,
    environment: dict[str, Any] | None = None,
    laya: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
    granted_tools: list[str] | tuple[str, ...] | set[str] | None = None,
    mutations_allowed: bool = True,
    situation_interface: bool = True,
) -> dict[str, Any]:
    """Return compact, truthful effective-access and runtime capability facts."""

    environment = environment if isinstance(environment, dict) else {}
    if isinstance(environment.get("result"), dict):
        environment = environment["result"]
    allowed = set(granted_tools) if granted_tools is not None else set(mutation_tools_for_mode(mode))
    if not mutations_allowed:
        allowed.clear()
    executables = environment.get("executables") if isinstance(environment.get("executables"), dict) else {}
    shell_names = executables.get("shells") if isinstance(executables.get("shells"), dict) else {}
    powershell = bool(shell_names.get("powershell"))
    python = bool(executables.get("python") or environment.get("python"))
    laya = laya if isinstance(laya, dict) else {}
    if isinstance(laya.get("result"), dict):
        laya = laya["result"]
    preview = preview if isinstance(preview, dict) else {}
    laya_status = laya.get("status") or ("available" if laya.get("available") is True else "unavailable" if laya.get("available") is False else "unknown")
    available_shells = sorted(name for name, path in shell_names.items() if path)
    python_info = environment.get("python")
    python_executable = executables.get("python")
    if python_executable or environment.get("python"):
        available_shells.append("python")
    command_permission = "terminal.exec" in allowed
    workspace_root = str(environment.get("workspaceRoot") or "")
    laya_ready = laya.get("available") is True or str(laya_status).lower() in {"available", "ready", "ok"}
    return {
        "permissionMode": mode,
        "effectiveAccess": {
            "workspaceEdits": "workspace.write" in allowed,
            "localCommandExecution": command_permission,
            "defaultCommandCwd": workspace_root if command_permission else "",
            "cwdIsSandboxed": False if command_permission else None,
            "boundedFileTools": any(tool.startswith("workspace.") for tool in allowed),
        },
        "capabilities": {
            # Preserve the legacy permission-gated command booleans while
            # reporting host runtime availability independently.
            "powershellCommands": powershell and command_permission,
            "pythonCommands": python and command_permission,
            "powershellAvailable": powershell,
            "pythonAvailable": python,
            "commandExecutionPermitted": command_permission,
            "localCommandsMayAccessNetwork": command_permission,
            "previewInspection": preview.get("inspectAvailable"),
            "previewCapture": preview.get("captureAvailable"),
            "previewControlJourney": "preview.taste" in allowed,
            "browserInteraction": "workspace.browser" in allowed,
            "laya": {
                "availableAsNamedTool": True,
                "granted": "laya.native.neyvia_navigation" in allowed,
                "runtimeStatus": laya_status,
                "runtimeReady": laya_ready,
                "scope": "Neyvia navigation workflow only; no generic desktop control",
            },
        },
        "toolRoutes": [
            {"purpose": "Inspect live operating system, workspace cwd, and installed executables",
             "toolId": "runtime.environment", "available": True},
            {"purpose": "Run a local command in the selected workspace",
             "toolId": "terminal.exec", "available": command_permission,
             "runtimeAvailable": bool(available_shells),
             "executionPermitted": command_permission,
             "defaultCwd": workspace_root if command_permission else "",
             "availableShells": available_shells if command_permission else [],
             "executables": {"powershell": shell_names.get("powershell") or "", "python": str(python_executable or (python_info.get("executable") if isinstance(python_info, dict) else python_info or ""))}},
            {"purpose": "Inspect and test a web page with a goal and bounded journey",
             "toolId": "preview.taste", "available": "preview.taste" in allowed,
             "requiredInputs": ["url", "goal", "journey"]},
            {"purpose": "Ordinary browser observation and interaction on approved origins",
             "toolIds": ["neyvia_situation", "neyvia.situation"], "available": bool(situation_interface),
             "approvedOriginsRequired": True, "mutationAvailable": "workspace.browser" in allowed},
            {"purpose": "Named desktop navigation workflow only",
             "toolId": "laya.native.neyvia_navigation",
             "available": "laya.native.neyvia_navigation" in allowed and laya_ready,
             "runtimeReady": laya_ready, "scope": "Neyvia navigation; no generic desktop control"},
        ],
        "grantedLocalTools": sorted(allowed),
        "managedConnectorMutations": False,
    }
