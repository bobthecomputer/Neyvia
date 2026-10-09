# connected_device_bridge

Provides backend / connected_device_bridge in Neyvia.

- **Public API:** `AppSurfaceCapability`, `BridgeActionDecision`, `BridgeActionRequest`, `CommandCapability`, `ConnectedHostManifest`, `FileRootScope`, `GitHubAuthCapability`, `HostHealth`, `PermissionGrant`, `ToolCapability`, `bridge_to_payload`, `build_bridge_operation_receipt`, `build_connected_host_manifests`, `build_dual_path_bridge_snapshot`, `build_live_review_structured_feedback_receipt`, `evaluate_bridge_action`, `load_bridge_audit_events`, `load_bridge_permission_grants`, `load_bridge_receipts`, `manual_github_bridge_actions`, `record_bridge_audit_event`, `save_bridge_permission_grants`, `upsert_bridge_permission_grant`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.bridge-authority`, `control.bridge-feedback`, `control.bridge-grants`, `control.bridge-receipt`, `control.bridge-snapshot`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.models](../backend.models/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_device_bridge.py](../../src/grant_agent/connected_device_bridge.py).
