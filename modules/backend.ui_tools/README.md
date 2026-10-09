# ui_tools

Compact model-facing UI query tools (ui.find / ui.diff / ui.do / …).

- **Public API:** `UiToolSurface`, `default_ui_surface`, `describe_api_surface`, `register_with_native_registry`, `register_with_progressive_surface`, `ui_tool_specs`, `wire_ui_tools`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sv.ui.action-gates`, `sv.ui.compact-result`, `sv.ui.discovery`.
- **Dependencies:** [backend.native_tools](../backend.native_tools/README.md), [backend.perception_frames](../backend.perception_frames/README.md), [backend.progressive_tools](../backend.progressive_tools/README.md), [backend.proofs_e_sv](../backend.proofs_e_sv/README.md), [backend.ui_graph](../backend.ui_graph/README.md), [backend.ui_observer](../backend.ui_observer/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/ui_tools.py](../../src/grant_agent/ui_tools.py).
