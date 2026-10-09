# Neyvia session controls and Laya review — 2026-09-23

## Result in editable source

- Agent and Builder now have one top-right Updates control with an update-ready or failure indicator. It opens Settings → Updates. The web indicator comes from the real app-shell status; the desktop label does not claim an installed update is ready.
- A neighboring device control opens **Where Neyvia is working**. It distinguishes the browser's device, run-file locality, and live control evidence. The local host row checks the existing `laya.native.capabilities` tool when opened and says **Named navigation ready** only when that preflight succeeds. It does not call preflight a completed screen action. Other PC, NAS, and Phone remain **No live control receipt** until the product has target-bound session evidence. Network-attached file storage is never presented as an execution host.
- **Edit system prompt** is directly visible beside Load workflow in the Agent and Builder composers. The dialog edits Common, Chat, Reader, Planner, Executor, and Verifier prompts.
- The full-width generic saved-task notice is gone. A compact notice appears for an unsent draft from another device, a genuine revision conflict, or a local draft sync error. Opening an existing conversation no longer immediately saves its unchanged draft over another device's checkpoint. A notice can be dismissed for one remote revision.
- The device popover's **Open computer use** action now reaches Lab → Computer Use proof. The duplicate mobile Update button was removed.
- Full-screen surfaces no longer start behind an opacity animation. Laya's background Chrome kept the Settings animation at zero opacity indefinitely, which made visible DOM controls non-actionable. The full-screen content is now immediately readable and clickable.
- The web app-shell status timeout now says **Update issue** instead of falsely declaring the shell **Current** without a service-worker receipt. The top-right button keeps a stable accessible action name while announcing its changing status separately.

## Rendered proof

The reusable packet runner is `scripts/capture_neyvia_session_ui.ps1`. Its final `proof/ui-review-20260923/session-ui/ledger.json` records **9/9 passing Laya browser journeys**, **9/9 fresh hashed screenshots**, **13 exact actions across those journeys**, and **zero model calls**. The nine journeys took **54,326 ms** in total; the median journey took **5,309 ms**. The five-action state walk took **8,252 ms**, including screenshot fallback; its five action calls totaled **828 ms** and their independent postcondition checks **21 ms**. These are measured local runs, not general latency guarantees. The packet covers Agent idle, device details with live Laya capability, Computer Use navigation, prompt editor and Planner tab, Update settings and Check, Builder idle, and the batched state walk. Each action has independent DOM expectations in its receipt.

I also inspected the Agent, device popover, and prompt dialog at a **390 × 844** browser viewport. Their controls were visible and fit the width. The temporary viewport override and test tab were removed afterward. In an independent in-app browser session, **Check** reported **Current** and **Last checked** after a real service-worker query. Laya's isolated background Chrome has no active worker, so its same action reported **Update failed**, **Retry**, and **Last checked**; the receipt deliberately accepts the handled failure path. The user-facing localhost endpoint at port 47880 and the Laya test endpoint at port 8877 served the same built HTML and asset names after the final build.

Laya's installed Neyvia native workflow still passed after the local service restart: **4 verified transitions, 2,846 ms, zero selection-model calls**, bound to one installed desktop process. This proves that named installed-app navigation only. The provider reports `generic_native_app_coverage=false`; the new source UI has not been installed into that desktop build.

The image generator received actual final Agent, popover, prompt, and Update screenshots. `proof/ui-review-20260923/session-ui/design-concept-final-states.png` is a **concept**, not a product screenshot or behavioral proof. The rendered screenshots and hashes in the Laya ledger remain the acceptance evidence.

## Laya efficiency finding

An optional per-action screenshot experiment caused Chrome capture timeouts and made a five-action run take about **25.6 seconds** with only three intermediate frames. I restored that experiment, then found a narrower capture issue: Settings at **1120 × 780** times out in the background Chrome target even when its DOM assertions pass. The local Laya runner now clears stale screenshot evidence before every run and, only after action/postcondition verification, retries a failed screenshot at **1280 × 800**. It records `screenshot_method` so the alternate viewport cannot be mistaken for the action viewport. The final packet used seven direct captures and two recorded reflow captures. The runner's final SHA-256 is `75f3250dd805aad7581ad5c5160b1267c1b3757a9d8fcdeb49fb1f23dfd4c8d8`, and a byte-identical copy is saved at `proof/ui-review-20260923/session-ui/laya-journey-runner-capture-fallback.py`. Intermediate screenshots still need their own validated fix before becoming a release gate.

## Release gaps

- The packet is scoped to changed controls. Its state walk discovered **57 named visible controls and exercised 5**; it is not an exhaustive all-button audit.
- Update-failed was induced and captured in Laya; a normal **Current** check passed in the in-app browser. Update-ready, remote-draft, and conflict visual states were not induced in this live account. A signed native update install was not exercised.
- Cross-device PC, NAS, and phone control need backend sessions with fresh source, target, direction, operation, and postcondition receipts before the top-right control can show them as active.
- The installed desktop app is a separate build. These source changes are ready for a desktop candidate build and installed-app review, not a public release claim.

The editable source, generated web build, screenshots, Laya receipts, and concept are preserved in the scoped WIP snapshot. Public `current` was not changed.
