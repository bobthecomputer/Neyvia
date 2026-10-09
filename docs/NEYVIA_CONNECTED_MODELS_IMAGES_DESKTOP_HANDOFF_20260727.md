# Neyvia connected models, images, and desktop handoff

## Outcome

The desktop now finds the usable Codex binary installed by the Codex app instead of stopping at the protected WindowsApps launcher. Read-only model workspaces use a short per-user path, avoiding Windows path-length failures.

The packaged Images workspace now:

- is allowed through the bounded desktop bridge;
- includes its `imagegen` skill contract;
- acquires a verified compatible Node.js runtime under Neyvia's per-user data directory when the system Node is too old;
- accepts OpenClaw's current plain-text OAuth and route receipt;
- copies generated PNGs only from OpenClaw's controlled media directory into Neyvia's safe artifact area;
- records actual PNG dimensions separately from requested dimensions;
- sizes the displayed layer from the real file;
- requires visual review instead of claiming that route and hash proof establish prompt adherence.

## Real model and image checks

- `gpt-5.6-sol` returned `NEYVIA_DESKTOP_SOL_OK` through Hermes with the requested OpenAI/Codex route.
- `gpt-5.6-terra` returned `NEYVIA_DESKTOP_TERRA_OK` through the installed Codex CLI.
- `gpt-image-2` produced a real PNG through OAuth and `codex-responses`, with artifact, manifest, hashes, and an executed `imagegen` receipt.
- Visual review found that the image was polished but did not exactly follow the requested monogram concept. The provider returned `1024x1536` for a `1024x1024` request; the corrected backend now reports that mismatch truthfully.

## Verification

- 169 backend/desktop/runtime Python tests passed.
- 107 frontend behavior tests passed.
- 16 Rust desktop-shell tests passed.
- Production frontend build passed.
- MSI, NSIS, and staged-backend size/content budgets passed.
- The exact final executable launched from an empty working directory, displayed `Neyvia - Intelligence Aligned`, remained responsive, loaded the bundled backend and image skill, and kept the same SHA-256 after first launch.

## Artifact status

The corrected executable and installers are in `artifacts/desktop/`. Their hashes are recorded in `artifacts/proof/model-image-tests-20260727/MODEL_IMAGE_DESKTOP_TEST_RECEIPT.json`.

The corrected installers do not have updater signatures because the secured private signing key was not exposed to this session. The earlier signed `f44d664` artifacts remain together with their matching signatures under `artifacts/desktop/prior-signed-f44d664/`. Do not mix the prior signatures with the corrected files.

This is a work-in-progress handoff only. No public `current` pointer, release, update feed, GitHub branch, or published installer was changed.
