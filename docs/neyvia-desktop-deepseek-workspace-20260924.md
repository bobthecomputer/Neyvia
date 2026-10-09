# Neyvia desktop checkpoint — 2026-09-24

The installed Windows app now exposes the workspace menu. Its options were rendered in the accessibility tree but clipped by `overflow-x: auto` on the composer action row. The row now allows the menu to paint; the menu scrolls when there are many workspaces. Selecting a workspace clears an old chat or mission URL binding, and the selected workspace persists across restarts.

## Verified paths

- Installer: `src-tauri/target/release/bundle/nsis/Neyvia_0.1.0_x64-setup.exe`; SHA-256 `873A60D7FF1D4793A60FBFAD986004D6263C4B2CE2073F695FFAD14D7218C5E4`. Local unsigned build; silent installation exited 0.
- Installed desktop workspace menu opened visibly. `Add folder` opened the connected-root browser. A disposable folder was saved as a second workspace, selected, and remained selected after the installed desktop app restarted. See `proof/neyvia-workspace-installed-open.png` and `proof/neyvia-workspace-persisted-after-restart.png`.
- The disposable profile `workspace_ee19dc45` had zero missions and was removed; Neyvia (`workspace_primary`) is active again. The disposable folder under `proof/workspace-switch-fixture` remains because automatic approval review rejected local filesystem removal. It contains only the test README.
- DeepSeek V4.1 Flash is selected in the final installed app. The reasoning control accepts Max and was restored to Model default. A prior live Go call accepted the `reasoning_effort` parameter; a real user chat through the final installer was not sent.
- The system prompt editor opens with role tabs and an `Import .txt or .md` control. No prompt text was altered; the prompt store SHA-256 stayed `DE14AE7ACEA87D0A35E3D91840769394B305C91D1AAE3C5C134A5868F01453A4` through installation.
- Reopening an existing chat showed its history and the normal composer. The clear-all dialog was opened and cancelled; real user conversations were not deleted. Bulk-delete behavior and stale-revision rejection passed with disposable backend fixtures.
- `npm run test:frontend`: 119 passed. `npm run frontend:build`: passed. Final Laya native receipt `proof/neyvia-workspace-final-after-cleanup-laya.json` reports `completed`, `postcondition_verified`, and execution in the installed process. Laya's allowlisted workflow covers desktop navigation; workspace switching itself was checked with Windows UI Automation and post-restart observation.
- Installed JBHEAVEN workflow skill at `C:\Users\example\AppData\Local\Neyvia\backend\.codex\skills\jbheaven-enhanced-workflow\SKILL.md` hashes identically to source. It is guidance, not an automatically executable skill.

Scoped WIP snapshot: `/volume1/Saclay/projects/syntelos/work-in-progress/20260924-225015-neyvia-deepseek-workspace` (25 files, 4,748,814 bytes, tree SHA-256 `4e980e44f5202db2aaf28983c5227959325735cb9a4a7648a12450131f514916`). The NAS receipt confirms the public `current` target stayed unchanged. No source was committed or public NAS release changed at this checkpoint.

Publication note: local account paths and network identifiers in this document are neutral examples.
