# neyvia_files_tools

Files app: a file explorer over Home, the workspace and project folders.

- **Public API:** `bin_records`, `call_files`, `entry`, `guard`, `list_folder`, `mkdir`, `move`, `open_with`, `parse_recycle_info`, `place_of`, `places`, `recycle`, `restore`, `serve_raw`, `stat_path`, `tool_specs`, `trash`, `undo`.
- **Manual:** [files.cl](../../manuals/cl/files.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `files.mkdir-durable`, `files.move-conservation`, `files.no-overwrite`, `files.recycle-record`, `files.trash-recoverable`, `files.undo-once`, `outputs.backend-publication-byte-recovery`.
- **Dependencies:** [backend.neyvia_notes_tools](../backend.neyvia_notes_tools/README.md), [backend.neyvia_pdf_tools](../backend.neyvia_pdf_tools/README.md), [backend.neyvia_ui_client](../backend.neyvia_ui_client/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.proofs_notes_files](../backend.proofs_notes_files/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / files.
- **Files:** [src/grant_agent/neyvia_files_tools.py](../../src/grant_agent/neyvia_files_tools.py).
