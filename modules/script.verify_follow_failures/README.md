# verify_follow_failures

Classify historical failure evidence and record bounded repair receipts.

- **Public API:** `OriginalTransaction`, `case_id`, `category`, `classify`, `continuity_cases`, `continuity_failure`, `device_fixtures`, `isolate`, `main`, `real_http`, `session_lifecycle`, `web_auth_cases`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.continuity_policy](../backend.continuity_policy/README.md), [backend.web_auth_sessions](../backend.web_auth_sessions/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/verify_follow_failures.py](../../scripts/verify_follow_failures.py).
