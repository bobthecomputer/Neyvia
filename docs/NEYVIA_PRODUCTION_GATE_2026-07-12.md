# Neyvia production gate, 2026-07-12

## Verdict

The supervised local production-candidate gate passes. Public publication remains a separate step because the Windows installer is not signed and the working tree still contains unrelated, unreviewed changes.

## Real runtime evidence

- The Twitter/X mission was real and completed on the Hermes-selected mission path.
- Its proof bundle contains 58 followed accounts, 282 posts, a rendered report, an executor receipt, and an independent verifier receipt with 15 passing checks.
- The proving-cycle gate records two completed Hermes missions.
- Hermes approval-wait and delegated-active continuity evidence are present.
- OpenClaw proving-mission parity remains optional for this Hermes-first release.

## Gate corrections

- Paused, blocked, or failed historical experiments remain visible but no longer block every later release.
- Queued, launching, running, and approval-waiting missions still require current watchdog evidence.
- A queued cluster job still blocks when no worker is online.
- An idle cluster may have no online worker without invalidating previously verified mission proof.
- Mission stop now records terminal planner, continuity, approval, and error state consistently.

## Verification performed

- `uv 0.11.28` installed from the maintained `astral-sh.uv` Winget package.
- Focused gate and runtime tests: 54 passed.
- Exact release CI test selection: 220 passed in 316.71 seconds.
- Frontend production build: passed.
- Tauri release build: passed.
- NSIS and MSI installers: produced.
- Desktop executable: launched successfully.
- Standalone desktop restart with the manually started web backend stopped: passed.
- Seven-step onboarding tutorial: opened, navigated, and completed.
- Mission composer: rendered after onboarding.
- Reasoning selector: exposed Low, Medium, High, X High, and Ultra.
- Local production proof command: passed with zero failed checks.
- Long-context stress: not run.

## Release artifacts

- `src-tauri/target/release/bundle/nsis/Neyvia_0.1.0_x64-setup.exe`
- `src-tauri/target/release/bundle/msi/Neyvia_0.1.0_x64_en-US.msi`
- `.agent_control/release_artifacts/production-gate-20260712T212123Z.json`
- `.agent_control/proof_digests/ci-release-proof.md`

The production receipt contains SHA-256 hashes for the web build, MSI, and NSIS installer.

## Remaining publication constraints

- Create a reviewed release commit from the current working tree.
- Sign the Windows installer with a trusted code-signing certificate before public distribution.
- Run the new release-proof workflow from that clean commit.

These publication constraints do not prevent supervised local use or NAS distribution of this exact hashed release candidate.
