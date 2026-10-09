# cluster

Provides backend / cluster in Neyvia.

- **Public API:** `ClusterRegistry`, `WorkerCapabilities`, `build_local_worker_capabilities`, `classify_provider_result`, `current_host_id`, `current_host_type`, `nas_execution_policy`, `normalize_concurrency_limit`, `resolve_cluster_root`, `small_sleep`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.scheduler.capabilities`, `a-cli.scheduler.choose`, `a-cli.scheduler.claim`, `a-cli.scheduler.expire`, `a-cli.scheduler.job`, `a-cli.scheduler.lease`, `a-cli.scheduler.load`, `a-cli.scheduler.root`, `a-cli.scheduler.stale`, `d.runtime.circuit.admission`, `d.runtime.circuit.classification`, `d.runtime.circuit.reporting`, `d.runtime.circuit.reset`, `d.runtime.circuit.transition`.
- **Dependencies:** [backend.models](../backend.models/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.proofs_a_cli_scheduler](../backend.proofs_a_cli_scheduler/README.md), [backend.proofs_d_runtime_auth](../backend.proofs_d_runtime_auth/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cluster.py](../../src/grant_agent/cluster.py).
