# web_auth_sessions

Durable storage for web account sessions.

- **Public API:** `WebAuthSessions`, `session_id`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `neyvia-core.account-session-binding`, `proofs-e-wz.auth-issuance`, `proofs-e-wz.auth-rejection`, `proofs-e-wz.auth-renewal`.
- **Dependencies:** [backend.proofs_d_neyvia](../backend.proofs_d_neyvia/README.md), [backend.proofs_e_wz](../backend.proofs_e_wz/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/web_auth_sessions.py](../../src/grant_agent/web_auth_sessions.py).
