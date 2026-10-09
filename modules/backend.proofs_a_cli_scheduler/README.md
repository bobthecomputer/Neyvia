# proofs_a_cli_scheduler

Checks at scheduler transactions and isolated real local worker procedures.

- **Public API:** `check`, `check_expired`, `check_lease`, `check_load`, `check_queued`, `check_rehome`, `check_stale`, `check_unlimited_admission`, `check_worker_environment`, `environment`, `migration_procedure`, `procedure`, `substitute`, `unlimited_loop_procedure`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.installer.action`, `a-cli.installer.integrity`, `a-cli.scheduler.capabilities`, `a-cli.scheduler.choose`, `a-cli.scheduler.claim`, `a-cli.scheduler.environment`, `a-cli.scheduler.execute`, `a-cli.scheduler.expire`, `a-cli.scheduler.job`, `a-cli.scheduler.lease`, `a-cli.scheduler.lifecycle`, `a-cli.scheduler.load`, `a-cli.scheduler.queued`, `a-cli.scheduler.rehome`, `a-cli.scheduler.roles`, `a-cli.scheduler.root`, `a-cli.scheduler.stale`, `a-cli.scheduler.threads`, `a-cli.scheduler.unlimited-loop`, `a-cli.scheduler.worker`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.cluster](../backend.cluster/README.md), [backend.fluxio_harness](../backend.fluxio_harness/README.md), [backend.models](../backend.models/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.runtime_supervisor](../backend.runtime_supervisor/README.md), [backend.worker](../backend.worker/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_a_cli_scheduler.py](../../src/grant_agent/proofs_a_cli_scheduler.py).
