# model_usage

Usage receipts: context size and cumulative thread spend are different facts.

- **Public API:** `CodexUsage`, `accumulate_sdk_usage`, `add_summary_usage`, `claude_receipt`, `counters`, `include_compaction`, `record_run_usage`, `runtime_usage`, `sdk_receipt`, `stream_sdk_usage`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `context.config.runtime-budget`, `p22.compaction-bookkeeping`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/model_usage.py](../../src/grant_agent/model_usage.py).
