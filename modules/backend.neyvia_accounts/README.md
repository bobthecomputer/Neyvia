# neyvia_accounts

Neyvia accounts: who can sign in to this PC's Neyvia, and where they are signed in.

- **Public API:** `AccountError`, `describe_device`, `environment_managed`, `handle_account_command`, `list_accounts`, `request_device`, `respond_account_command`, `session_identity`, `update_account`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `neyvia-core.account-devices`.
- **Dependencies:** [backend.proofs_d_neyvia](../backend.proofs_d_neyvia/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_accounts.py](../../src/grant_agent/neyvia_accounts.py).
