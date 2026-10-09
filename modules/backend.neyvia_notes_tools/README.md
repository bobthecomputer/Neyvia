# neyvia_notes_tools

Notes app: a folder of Markdown notes (default ~/Neyvia Notes) shared by Paul and models.

- **Public API:** `call_notes`, `excerpt_of`, `file_name`, `list_notes`, `notes_folder`, `pin_note`, `read_note`, `search_notes`, `set_folder`, `snippet`, `tags_of`, `title_of`, `tool_specs`, `write_note`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [notes.cl](../../manuals/cl/notes.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `cl.adaptive-work-journey`, `cl.completion-after-effect`, `notes.body-durable`, `notes.path-jail`, `notes.pin-durable`, `notes.prose-metadata`, `notes.stale-preserves`.
- **Dependencies:** [backend.neyvia_ui_client](../backend.neyvia_ui_client/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.proofs_notes_files](../backend.proofs_notes_files/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / notes.
- **Files:** [src/grant_agent/neyvia_notes_tools.py](../../src/grant_agent/neyvia_notes_tools.py).
