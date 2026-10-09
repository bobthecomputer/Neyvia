# connected_chrome_policy

Approval boundaries for actions taken in the user's connected browser.

- **Public API:** `ApprovalRequired`, `Assessment`, `action_fingerprint`, `assess`, `ensure_approved`, `grant_approval`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.chrome-grant`, `control.chrome-policy`.
- **Dependencies:** [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_chrome_policy.py](../../src/grant_agent/connected_chrome_policy.py).
