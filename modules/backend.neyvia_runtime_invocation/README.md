# neyvia_runtime_invocation

Durable N-E-Y-V-I-A external runtime invocation registry.

- **Public API:** `build_invocation_record`, `build_selected_context_packet`, `can_transition`, `close_invocation`, `default_root`, `describe_effective_composition`, `is_open`, `is_resumable`, `load_registry`, `open_invocation`, `partition_delegation`, `reap_orphans`, `registry_path`, `retained_responsibilities`, `runtime_readiness`, `runtime_readiness_snapshot`, `update_invocation`, `validate_route_selection`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.import-packet`, `d.host.selected-context`.
- **Dependencies:** [backend.context_import](../backend.context_import/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_d_host](../backend.proofs_d_host/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_runtime_invocation.py](../../src/grant_agent/neyvia_runtime_invocation.py).
