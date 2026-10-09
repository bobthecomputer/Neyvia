# durability

Provides backend / durability in Neyvia.

- **Public API:** `append_jsonl_durable`, `atomic_write_bytes`, `atomic_write_json`, `atomic_write_text`, `file_transaction`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.harness_jobs](../backend.harness_jobs/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/durability.py](../../src/grant_agent/durability.py).
