# neyvia_devices

Owner-approved, scoped PC file access over the tailnet.

- **Public API:** `Devices`, `PeerError`, `bind_peer_backend`, `call_devices`, `devices_for`, `network_allowed`, `serve_peer`, `serve_raw`, `tool_specs`, `neyvia.files.list`, `neyvia.files.stat`.
- **Manual:** [cross-pc.cl](../../manuals/cl/cross-pc.cl), [files.cl](../../manuals/cl/files.cl), [handoff-recovery.cl](../../manuals/cl/handoff-recovery.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.connected_device_inventory](../backend.connected_device_inventory/README.md), [backend.native_pairing](../backend.native_pairing/README.md), [backend.neyvia_files_tools](../backend.neyvia_files_tools/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / cross-pc.
- **Files:** [src/grant_agent/neyvia_devices.py](../../src/grant_agent/neyvia_devices.py).
