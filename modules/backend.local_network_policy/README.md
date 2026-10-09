# local_network_policy

Application egress boundary. Loopback services remain usable; children fail closed.

- **Public API:** `LocalOnlyError`, `active_children`, `check_address`, `child_inventory`, `child_start`, `enabled`, `install`, `loopback`, `refuse`, `register_idle_child`, `release`, `status`, `stop_child`, `stop_idle_children`, `transition`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.policy-owner`, `d.host.policy-root`, `d.host.policy-startup`.
- **Dependencies:** [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.proofs_d_host](../backend.proofs_d_host/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/local_network_policy.py](../../src/grant_agent/local_network_policy.py).
