# Browser side pane

## State observers
- `neyvia.browser.state` reports the managed headless runtime session id, live tabs and renderer acknowledgements.
- `neyvia.browser.observe(tabId)` reads the exact shared page; its semantic revision excludes transient geometry.
- `neyvia.pane.state()` observes the live page before comparing the mounted renderer's session and content revision; queued, stale and unavailable panes remain unverified.

## Typed actions
- Owner `browser_call_command {op:"headless.start",args:{port:<assigned port>}}` admits the local Obscura executable and companion by `C2f-engine-admission.json` (C2d binary receipt only when the newer admission is absent); no environment setup, download, Chromium fallback or stealth.
- `neyvia.browser.open(url,engine:"obscura")` opens a headless tab; omitted engine defaults to headless for bot calls.
- `neyvia.pane.show(kind:"browser",target:<live headless tab id>)` requests its right pane; arbitrary URLs and disconnected sessions are refused.
- Owner renderer `browser_call_command` ops `frame`, `frame.input`, `pane.ack` and `action` share the same tab and runtime; acknowledgements follow an actually loaded image and require its current session id and page revision.
- Clicking the pane image sends scaled image coordinates to that headless page's CDP mouse; it never moves the desktop cursor.
- The pane's Apply, Submit and page buttons invoke actual observed semantic actions; Take over here revokes the agent grant while retaining the headless page.

## Executable checks
- `neyvia.pane.state().verified` is true only after exact live content acknowledgement; an event by itself is unverified.
- `neyvia.browser.action(...).verification.verified` confirms observed effects; uncertain actions are never replayed.
- `node scripts/c2f_pane_proof.cjs` starts only owned headless processes on explicit 48726–48729 ports and records real runtime/rendered controls and refusal receipts.

## Procedures
- Start the admitted engine with an explicit assigned port; open a headless tab; show its tab id; wait for `pane.state` observed; inspect the page and act through observed controls.

## Judgement points
- Sign-in, CAPTCHA and secret controls require Paul; the pane never bypasses them.
- Assign a separate profile and space for independent parallel tasks; one profile worker preserves sequential page actions.

## Pitfalls
- Never equate queued pane delivery with mounted content.
- Never substitute an external iframe, popup or visible desktop promotion for the controlled headless page.
- Old runtime/content acknowledgements become stale when the page changes or the engine restarts.

## Frontier
- Obscura pixel-frame availability depends on its actual CDP capture implementation; DOM projection and controls remain explicit if capture is unavailable.
- Browser feature parity and arbitrary native apps need separate proof.
