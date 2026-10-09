# workspace

Git and GitHub state for a connected session's folder.

- **Public API:** `WorkspaceError`, `file_diff`, `git_action`, `invalidate`, `workspace_state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sessions.workspace.action`, `sessions.workspace.cache`, `sessions.workspace.checks`, `sessions.workspace.cli`, `sessions.workspace.confirm`, `sessions.workspace.diff`, `sessions.workspace.github`, `sessions.workspace.remote`, `sessions.workspace.state`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.github_client](../backend.github_client/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/workspace.py](../../src/grant_agent/connected_sessions/workspace.py).
