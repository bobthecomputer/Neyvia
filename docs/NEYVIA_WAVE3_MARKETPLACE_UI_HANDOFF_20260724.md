# Neyvia Wave 3 Marketplace UI handoff

Date: 2026-07-24
Branch: `wave3/marketplace-ui`
Baseline: Wave 2 proof commit `3f9e228f14abc284415da681f82d0860d094d0aa`

## Acceptance posture

This slice is a clean reconstruction of GROK 4.5's Marketplace browse concept.
External completion remains candidate work until reviewed and accepted. The
shared checkout was used only as an attribution source; it was not edited.

The shared receipt
`.agent_control/capability_os/qa/PHASE2_MARKETPLACE_SLICE1_WORK_PACKAGE_RECEIPT.md`
claimed a local browse/detail UI plus a new aggregate browse API. The new UI and
browser verifier were standalone untracked files:

| Attributable shared asset | SHA-256 | Decision |
| --- | --- | --- |
| `web/src/neyvia/NeyviaMarketplacePanel.jsx` | `aa36f5440b4fbb81877c4d5aa6e9f7d6940b7959759aed8aac02684bf5cfba37` | Concept reviewed; reconstructed against Wave 2 contracts |
| `scripts/verify_phase2_marketplace_browse_browser.py` | `9881b55daaa48feb2f07cbc1b3ab9228755f2f7601d41e0c94b72679e2124c33` | Not ported; it uses standalone Playwright, which is forbidden for this acceptance lane |
| `.agent_control/capability_os/qa/phase2-marketplace-browse-proof-20260724-131120.json` | `70f6e3adcc18049295f8d023a9fbd48be65a300f27a1582dc22500ccd2981fcb` | Historical candidate evidence only |

The mixed shared edits to `sdk.py`, `web_backend.py`,
`module_marketplace.py`, `neyviaShell.css`, and `NeyviaShellSurfaces.jsx` were
not copied. Wave 2 contains newer reviewed security foundations in those
backend files.

## Integrated behavior

- Marketplace is reachable from Lab and the command palette.
- The panel is lazy-loaded, with its own JavaScript and CSS chunks.
- It calls only the reviewed read-only commands:
  - `get_installed_module_catalog_command`
  - `get_module_marketplace_toolchain_command`
- Exact backend schema names are checked before data is accepted.
- Unknown schemas fail closed and render no candidate rows.
- Runtime state, publisher trust, detached signature evidence, staged
  activation, and blockers are separate facts.
- Missing trust, signature, and staged-pointer evidence is shown as
  `Not reported`; tool availability is not misrepresented as per-package
  signature proof.
- Activation is disabled. There is no install, update, rollback, or fake
  progress action in this slice.

## Verification

- `node --test tests/neyvia_marketplace_model.test.mjs`
  - 3 passed
- `python -m pytest tests/test_neyvia_marketplace_ui.py -q`
  - 4 passed
- `npm run frontend:build`
  - passed; 6,297 modules transformed
  - Marketplace JS: 13.25 kB (4.19 kB gzip)
  - Marketplace CSS: 8.02 kB (1.94 kB gzip)
  - Fluxio shell JS: 452.76 kB
  - Reference shell JS: 496.63 kB

The required in-app browser runtime reported no available browser surface.
Rendered interaction proof is therefore unproven. No Playwright fallback was
used.

## Remaining gaps

- Public OCI or local-registry browse is not exposed by the current reviewed
  frontend API.
- The installed catalog does not expose the exact trust binding, detached
  signature receipt, or separate staged pointer per package.
- No activation, install, update, rollback, streamed progress, or human-review
  workflow is provided by this read-only slice.
- The existing dependency audit still reports five advisories; this slice did
  not run an automatic dependency rewrite.

No NAS, live release pointer, GitHub, or shared-checkout state was changed.
