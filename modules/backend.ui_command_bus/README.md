# ui_command_bus

Durable backend-to-UI commands shared by the web service and model workers.

- **Public API:** `UICommandBus`, `bus_for`, `now`, `state_root`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.gamedev.screen-state-persistence`, `p22.image-studio.pixel-edit-journey`, `p22.settings.preference-journey`, `p22.workspace.output-journey`.
- **Dependencies:** [backend.cl.renderer_effects](../backend.cl.renderer_effects/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/ui_command_bus.py](../../src/grant_agent/ui_command_bus.py).
