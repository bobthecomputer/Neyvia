# evolve_final

Evidence script: the final EVOLVE gate + CL-compile patches against the current release candidate.

- **Public API:** `apply_sites`, `build_manual_cache`, `clone`, `compile_tree`, `contract_tree`, `contracts`, `finals`, `gate_selection`, `generate_module_map`, `log`, `main`, `measurement_tree`, `memo`, `patches`, `ports_free`, `read_json`, `recheck`, `regenerate`, `report`, `reset`, `run`, `same_outcome`, `stale`, `targets`, `timing`, `verify`, `wait_for_ports`, `worker`, `write_json`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.evolve_gate](../backend.evolve_gate/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/evolve_final.py](../../scripts/evolve_final.py).
