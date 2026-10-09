# project_files

Bounded file browsing and export for registered project workspaces.

- **Public API:** `ArchiveDescriptor`, `DownloadDescriptor`, `ProjectFilesError`, `Workspace`, `create_project_archive`, `list_project_entries`, `open_project_download`, `preview_project_file`, `resolve_registered_workspace`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.files.registered-project-export-outcome`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/project_files.py](../../src/grant_agent/project_files.py).
