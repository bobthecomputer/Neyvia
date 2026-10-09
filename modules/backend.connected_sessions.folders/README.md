# folders

Where a new chat can run: recent folders, local git projects, GitHub repos.

- **Public API:** `candidates`, `clone`, `create_worktree`, `github_candidates`, `github_repos`, `github_status`, `local_projects`, `projects_root`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sessions.folders.availability`, `sessions.folders.catalogue`, `sessions.folders.confirm`, `sessions.folders.direct`, `sessions.folders.filter`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.folder_jobs](../backend.connected_sessions.folder_jobs/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/folders.py](../../src/grant_agent/connected_sessions/folders.py).
