# manual_versions

Scoped manual revisions: quarantined JSON patches, explicit promotion and lineage.

- **Public API:** `apply_operations`, `promote`, `quarantine`, `revision`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.manual_state](../backend.manual_state/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/manual_versions.py](../../src/grant_agent/manual_versions.py).
