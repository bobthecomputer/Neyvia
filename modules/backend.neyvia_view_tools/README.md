# neyvia_view_tools

neyvia.view.*: the agent arranges the interface through the same bus the user's layout lives on.

- **Public API:** `call`, `neyvia.view.ambient`, `neyvia.view.arrange`, `neyvia.view.float`, `neyvia.view.place`, `neyvia.view.scene`, `neyvia.view.state`, `neyvia.view.theme`, `neyvia.view.transparency`, `neyvia.view.transparency.state`.
- **Manual:** [design.cl](../../manuals/cl/design.cl), [image-studio.cl](../../manuals/cl/image-studio.cl), [local-rendering.cl](../../manuals/cl/local-rendering.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [onboarding.cl](../../manuals/cl/onboarding.cl), [transparency.cl](../../manuals/cl/transparency.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d-ui.view-arrange`, `d-ui.view-controls`, `settings.legacy-theme`, `settings.view-durable`.
- **Dependencies:** [backend.cl.fixcl4_render_effects](../backend.cl.fixcl4_render_effects/README.md), [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.proofs_d_ui_planning](../backend.proofs_d_ui_planning/README.md), [backend.proofs_settings](../backend.proofs_settings/README.md).
- **Owner:** Neyvia / design.
- **Files:** [src/grant_agent/neyvia_view_tools.py](../../src/grant_agent/neyvia_view_tools.py).
