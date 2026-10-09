# Hello module

Build a personal greeting through a small agent-callable optional mod.

- **Public API:** `greet`, `neyvia.mod.hello.greet`.
- **Manual:** [hello-module.cl](../../manuals/cl/hello-module.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run hello-module.verify-greeting()`, `run modules.verify-map()`.
- **Outcome contracts:** `p22.mod-lifecycle`.
- **Dependencies:** None statically declared.
- **Owner:** Marketplace / Mods.
- **Files:** [apps/hello-module/greeting.py](../../apps/hello-module/greeting.py), [apps/hello-module/host-contract.json](../../apps/hello-module/host-contract.json), [apps/hello-module/manual.cl](../../apps/hello-module/manual.cl), [apps/hello-module/neyvia.module.json](../../apps/hello-module/neyvia.module.json).
