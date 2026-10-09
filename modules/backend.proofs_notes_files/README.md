# proofs_notes_files

Durable Notes/Files action contracts; also used at UI/direct-call boundaries.

- **Public API:** `after`, `before`, `check_recycle_record`, `check_tags`, `check_title`, `require`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `files.mkdir-durable`, `files.move-conservation`, `files.no-overwrite`, `files.recycle-record`, `files.trash-recoverable`, `files.undo-once`, `notes.body-durable`, `notes.path-jail`, `notes.pin-durable`, `notes.prose-metadata`, `notes.stale-preserves`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_files_tools](../backend.neyvia_files_tools/README.md), [backend.neyvia_notes_tools](../backend.neyvia_notes_tools/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_notes_files.py](../../src/grant_agent/proofs_notes_files.py).
