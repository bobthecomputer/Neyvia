# Neyvia flagship handoff — 23 September 2026

## Project goal

Neyvia should turn a conversation into useful software and reliable agent action across the user's own devices. The same editable artifact should carry its source, live preview, replayable behavior checks, build, installation, update history, and receipts. Personalization should guide future behavior through explicit, recoverable memory and accepted visual preferences. Cross-device control should be added one named, observable journey at a time.

This is a direction and a local WIP checkpoint, not a claim of a general app generator or a measured advantage over other models.

## Working local journey

1. An operator created **Journey Proof Notes** from the visible App Factory form. This is the deterministic notes starter selected from a brief, with editable files in `apps/journey-proof-notes-20260923`.
2. App Factory assembles a source package and runs static checks. A later source edit invalidates those claims and the native build. Resume creates a new package; the UI shows behavior as unverified until the new journey passes.
3. Preview is a full-screen route that remembers the selected app and survives reload. The rendered app was used to save a note; the note remained after Preview reload.
4. `Test app` runs source-bound saved browser journeys in an isolated authenticated page: add a named item, assert its checkbox appears, reload and assert it remains, remove it, then reload and assert absence. Two screenshots and their hashes are bound into the runtime proof. The final add run is `3f7444a770564025af3e24a21a1e3324`; the removal run is the same ID plus `-remove`. Both report `verified` for source SHA-256 `c77ca3880df2f2311edacd81891fa5286d18e3fecbaad5c371b69b37ba4e5492`.
5. The tested revision compiled to a Windows executable with SHA-256 `1ec4e646c29cd9c45238575e39dff49c3632ed58e60dd8985f9c497d0f6256e9`. App Factory installed it for this user. The active executable hash and Start Menu shortcut target were checked independently. The executable launched as a window titled **Journey Proof Notes**; read-only Windows UI Automation saw the `REVISION 2` marker and `Save note` control.
6. The UI updated from revision 1 to revision 2, rolled back to the intact revision 1, then restored revision 2. A web-thread COM initialization bug discovered on the first rollback attempt was fixed and the button journey repeated successfully. Public NAS `current` was not changed.
7. Laya's browser provider ran against the generated revision 2 through its allowlisted local origin. The first model-choice run filled the note but clicked `Export JSON` three times and failed. A bounded runner correction now applies declared field preconditions, invokes the exact observed `Save note` action once, and verifies list/count effects. The second Laya receipt is `PASSED`: two actions, zero model selection calls, independent assertions, and screenshot SHA-256 `af3a72b3db92dd9dce6de11452ccc18b319b90b750611aa5f1625d5f9fb7a2b0`. The job, Situation frames, failed/passed Laya receipts, runner, installation manifest, and screenshots are preserved under `proof/neyvia-app-journey-20260923/`.

## Other relevant state

- Settings personalization and bounded working memory are wired as documented in `docs/personalization-laya-checkpoint-20260923.md`. The memory can preserve preferences and accepted comparisons; it is behavioral guidance and retrieval, not changed model weights. The installed Neyvia navigation workflow also passed through Laya, but Laya's native provider reports no generic native app coverage.
- Assistant messages can display an HTML artifact in an inline sandboxed frame. The App Factory job and the inline chat artifact are still separate artifact paths, so an HTML app made in a chat is not yet the exact package that App Factory builds. The sandboxed inline frame also does not yet provide durable app storage. The user's reference is the interactive quiz in `C:\Users\example\OneDrive\Images\Screenshots\Capture d'écran 2026-09-21 142545.png`: a compact, usable activity embedded directly in the conversation.
- The Unreal Agent source review at pinned commit `b7c9bf1c5c2fa4127255c07727a7c8413e23944a` is in `docs/unreal-agent-assessment-20260923.md`. Its serializable operation boundary and omission accounting merit a controlled experiment; no runner replacement or comparative win has been proved.
- The Agent composer now exposes attached-file chips and sends bounded file bytes to the selected chat runtime. A local web journey proved one text-file read and a completed answer through Neyvia Native; the backend rejects malformed attachment data before runtime dispatch. Laya also opened the prompt editor in the rebuilt web app through its allowlisted local test origin and verified the dialog and text area. This is source/web proof, not a new installed desktop release. The exact boundary and Laya retest are in `proof/ui-review-20260923/chat-attachment-journey.json` and `docs/neyvia-desktop-ui-review-20260923.md`.

## Material gaps and next proof gates

| Capability | Current boundary | Next proof |
| --- | --- | --- |
| App from conversation | App Factory still chooses notes/checklist starters and asks for a separate form. | Make one chat-authored app the same source-bound artifact that Preview tests and Windows builds. Show a design correction in chat, rerun its journey, and prove the installed bytes match. |
| Installed app behavior | Exact executable and shortcut were verified; window and UIA content were observed. | Run the same add/reload/remove journey inside the installed WebView through a named Laya native workflow, with fresh process/window binding and postconditions. |
| In-chat HTML | Inline frame exists, but it is not the App Factory artifact and storage is not durable. | Serve a versioned artifact on an isolated origin, keep its app data across reload, and let the same source open in inline chat and full Preview. |
| Accessibility and navigation | Full-screen Preview route and reload now work; the wider sidebar, phone composer, and confusing internal status language remain. | Test task finding, keyboard navigation, readable labels, narrow viewport, and error recovery with users. Use the 10 September rendered packet as the baseline. |
| Phone, remote PC, NAS | Broader control and installation journeys have no end-to-end receipt in this checkpoint. | Prove one real physical device journey per target: bind device, perform a reversible action, inspect fresh state, disconnect/recover, and retain a scoped receipt. |
| Harness and memory advantage | No model-matched competition benchmark or permanent model-weight improvement. | Compare ten held-out app briefs and failure cases against plain Codex/Claude with the same model, authority, budget and acceptance checks. Measure success, repair rounds, latency, tokens, cost, and exact retrieval after context omission. |

## Review request for another model

Independently reproduce the local app journey, inspect both saved Situation runs and Laya's failed/passed receipts, and challenge each claim at its observed boundary. Prioritize a single chat-to-package artifact, installed-app journey replay, and a measured ten-brief comparison. Do not infer cross-device coverage, universal speed, or model improvement from the notes starter proof.

Publication note: local account paths and network identifiers in this document are neutral examples.
