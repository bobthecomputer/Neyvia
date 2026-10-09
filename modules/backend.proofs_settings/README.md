# proofs_settings

Canonical Settings contracts checked inside its existing SQLite transaction.

- **Public API:** `check_committed`, `check_rejection`, `check_revision`, `check_view`, `require`, `self_check`, `snapshot`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `settings.canonical-mirrors`, `settings.invalid-preserves`, `settings.legacy-theme`, `settings.night-policy-event`, `settings.revision-cas`, `settings.view-durable`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_settings.py](../../src/grant_agent/proofs_settings.py).
