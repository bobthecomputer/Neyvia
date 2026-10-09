# workspaceToolAccess

Provides WORKSPACE_PERMISSION_MODES, WORKSPACE_PERMISSION_STORAGE_KEY, normalizeWorkspacePermissionMode, workspacePermissionAllowsTools for Neyvia's UI state and behavior.

- **Public API:** `WORKSPACE_PERMISSION_MODES`, `WORKSPACE_PERMISSION_STORAGE_KEY`, `buildWorkspacePermissionScope`, `normalizeWorkspacePermissionMode`, `readWorkspacePermissionModes`, `supportsNativeWorkspacePermissionModes`, `transferDraftWorkspacePermissionMode`, `workspacePermissionAllowsTools`, `workspacePermissionGrantForScope`, `workspacePermissionModeForScope`, `writeWorkspacePermissionMode`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [workspace.cl](../../manuals/cl/workspace.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `permission.get`, `permission.grant`, `permission.normalize`, `permission.read`, `permission.runtime`, `permission.scope`, `permission.tools`, `permission.transfer`, `permission.write`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / workspaceToolAccess.
- **Files:** [web/src/neyvia/workspaceToolAccess.js](../../web/src/neyvia/workspaceToolAccess.js).
