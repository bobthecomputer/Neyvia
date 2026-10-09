from __future__ import annotations


def looks_like_network_root(path: str) -> bool:
    value = str(path or "").strip().lower()
    return (
        value.startswith("\\\\")
        or value.startswith("//")
        or value.startswith("smb://")
        or value.startswith("nfs://")
        or "synology" in value
        or "/volume" in value
        or "\\volume" in value
        or "/nas/" in value
        or "\\nas\\" in value
    )


def derive_execution_target(
    execution_root: str,
    workspace_root: str,
    strategy: str = "",
) -> dict[str, str]:
    execution = str(execution_root or "").strip()
    workspace = str(workspace_root or "").strip() or execution
    strategy_label = _titleize_token(strategy or "direct")

    if not execution and not workspace:
        return {
            "execution_target": "unresolved",
            "storage_mode": "unknown",
            "host_locality": "unknown",
            "execution_target_detail": "Neyvia has not resolved where the active run is executing yet.",
        }

    focus_root = execution or workspace
    if looks_like_network_root(focus_root) or looks_like_network_root(workspace):
        return {
            "execution_target": "nas",
            "storage_mode": "network_storage",
            "host_locality": "network_attached",
            "execution_target_detail": f"{strategy_label} execution is pointed at NAS or network storage: {focus_root}.",
        }

    if execution and workspace and _normalize_root(execution) != _normalize_root(workspace):
        return {
            "execution_target": "worktree",
            "storage_mode": "local_disk",
            "host_locality": "local_machine",
            "execution_target_detail": f"{strategy_label} execution is isolated in a local worktree: {execution}.",
        }

    return {
        "execution_target": "workspace",
        "storage_mode": "local_disk",
        "host_locality": "local_machine",
        "execution_target_detail": f"{strategy_label} execution is running directly in the local workspace: {focus_root}.",
    }


def _normalize_root(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").rstrip("/").lower()


def _titleize_token(value: str) -> str:
    return " ".join(part.capitalize() for part in str(value or "").replace("_", " ").split())
