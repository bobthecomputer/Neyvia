# runtime

CL execution adapts syntax to existing tools; it never grants authority.

- **Public API:** `describe_registry`, `describe_tool`, `execute_action`, `execute_gateway`, `prepare_action`, `state_layer`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.compiled-command`.
- **Dependencies:** [backend.cl.parser](../backend.cl.parser/README.md), [backend.cl.renderer](../backend.cl.renderer/README.md), [backend.cl.schema](../backend.cl.schema/README.md), [backend.manual_state](../backend.manual_state/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cl/runtime.py](../../src/grant_agent/cl/runtime.py).
