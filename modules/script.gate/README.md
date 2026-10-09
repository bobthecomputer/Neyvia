# gate

Impact-scoped Connected Language release gate (no pytest or full tour).

- **Public API:** No separately exported API; use the owning module..
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.impact`, `p22.laya-advisory`.
- **Dependencies:** [backend.contract_gate](../backend.contract_gate/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/gate.py](../../scripts/gate.py).
