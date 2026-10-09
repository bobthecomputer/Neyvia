# nx_gate_shard

pytest plugin for `nx_promote.py gate`: run only this worker's share of the tests.

- **Public API:** `pytest_collection_modifyitems`, `test_key`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/nx_gate_shard.py](../../scripts/nx_gate_shard.py).
