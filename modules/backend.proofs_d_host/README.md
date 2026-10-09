# proofs_d_host

PROOFS-d host invariants and disposable local action procedures.

- **Public API:** `check_artifact_row`, `check_context_packet`, `check_delta_merge`, `check_event_identity`, `check_nearby_history`, `check_nearby_projection`, `check_nearby_state`, `check_policy_release`, `check_skill_catalog`, `check_stage_receipt`, `check_synthesis`, `require`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.artifact-serving`, `d.host.delta-merge`, `d.host.delta-synthesis`, `d.host.event-identity`, `d.host.nearby-history`, `d.host.nearby-recovery`, `d.host.nearby-redaction`, `d.host.policy-owner`, `d.host.policy-root`, `d.host.policy-startup`, `d.host.remote-transport`, `d.host.selected-context`, `d.host.skill-provenance`, `d.host.stage-parallel`, `d.host.stage-receipt`, `d.host.stage-refusal`, `d.host.stage-tool-authority`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.agent_delta](../backend.agent_delta/README.md), [backend.connected_sessions.claude_terminal](../backend.connected_sessions.claude_terminal/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.nearby_send](../backend.nearby_send/README.md), [backend.neyvia_remote](../backend.neyvia_remote/README.md), [backend.neyvia_runtime_invocation](../backend.neyvia_runtime_invocation/README.md), [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.neyvia_stage_scheduler](../backend.neyvia_stage_scheduler/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.orchestration_language](../backend.orchestration_language/README.md), [backend.progressive_tools](../backend.progressive_tools/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.skills](../backend.skills/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_d_host.py](../../src/grant_agent/proofs_d_host.py).
