# proofs_b_desktop

Desktop evidence contracts checked by the same functions used in real actions.

- **Public API:** `before`, `check`, `checked`, `gateway_journal_lock`, `journal_lock`, `require`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `delivery.ack`, `delivery.append`, `delivery.browser`, `delivery.message`, `delivery.observe`, `delivery.skipped`, `delivery.tail-update`, `delivery.update`, `desktop.bridge.allowlist`, `desktop.dashboard.artifact`, `desktop.debugger.bundle`, `desktop.debugger.summary`, `desktop.demo.comparison`, `desktop.demo.export`, `desktop.demo.probe`, `desktop.docs.evidence`, `desktop.gateway.event`, `desktop.gateway.heartbeat`, `desktop.gateway.reconcile`, `desktop.gateway.route`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.challenge_presets](../backend.challenge_presets/README.md), [backend.cluster](../backend.cluster/README.md), [backend.dashboard](../backend.dashboard/README.md), [backend.debugger_bundle](../backend.debugger_bundle/README.md), [backend.delivery_receipt](../backend.delivery_receipt/README.md), [backend.dependency_inventory](../backend.dependency_inventory/README.md), [backend.desktop_bridge](../backend.desktop_bridge/README.md), [backend.desktop_gateway](../backend.desktop_gateway/README.md), [backend.doc_ingestion](../backend.doc_ingestion/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.models](../backend.models/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_b_desktop.py](../../src/grant_agent/proofs_b_desktop.py).
