# Neyvia taste follow-through — 24 September 2026

## Intended result

Take the useful lessons from the night-route redesign, encode them as reusable taste guidance, and close its stated verification gaps without claiming a release that has not passed a release gate.

## Taste guidance first

- Commit `849b7c2` updates `.codex/skills/neyvia-aesthetic-innovation-master/SKILL.md` and `.codex/skills/neyvia-design-taste-v2/SKILL.md`.
- The guidance now treats the accepted navy, route-blue, north-star-gold, Geist, and single-icon direction as a reference; user screenshots take precedence. It requires the made artifact to dominate Preview, a rendered review beyond a numerical gate, and explicit boundaries between fixtures, live models, source UI, and installed UI.
- `docs/neyvia-taste-skill-revision-20260924.md` records four concrete instruction-coverage cases, 0/4 before and 4/4 after. This measures the revised instructions, not model quality.

## Product changes

- Made Light and Warm actually emit their selected theme tokens. Choosing a theme in Settings now selects the matching color mode. Replaced an older white-text lock with theme text tokens, and darkened faint text for Light and Warm contrast.
- Kept the live answer animation while making its first rendered word legible from the first frame.
- Design review now keeps screenshot captures in a disclosure beneath the live app. A URL change invalidates an in-flight or previous review so a new page cannot display stale findings.
- App Factory's Workspace badge now uses the backend catalog's workspace path when the shell has no selected folder. It no longer presents the previous chat title as a workspace name.

## Evidence

- Authenticated render measurements: Agent desktop, Settings desktop, Phone desktop, and Agent at 390 px in Light, Warm, Neutral, and High Contrast: 16 views, zero measured text contrast failures and zero text collisions. Captures and JSON are under `proof/taste-finish-20260924/{light-third,warm-third,dark-final,contrast-final}`. These are deterministic checks on visible text, not a beauty score or whole-product audit.
- The six user-supplied visual references are preserved under `proof/taste-finish-20260924/reference` alongside the new captures.
- Running UI journey: clicked every appearance swatch, checked its active color mode, reloaded to verify persistence, loaded the saved App Factory job, ran Design review in Preview, and opened its two captures. All checks passed; no React page error occurred. See `proof/taste-finish-20260924/journey/journey.json` and screenshots. The earlier “Maximum update depth exceeded” event did not recur, so its cause remains unproven.
- Source checks: 115/115 frontend tests, message-rendering safety check, and production frontend build passed. The final Windows bundle also built with `--no-sign`.
- Live Luna through the updated web UI: reasoning summary and answer deltas arrived before request completion, and final text rendered. First visible words were about 27 seconds after send; completion about 34 seconds. See `proof/taste-finish-20260924/live-stream/ui-stream-check.json`. This is functional streaming, not satisfactory latency.
- Installed desktop (before the final App Factory label-only rebuild) sent one short GPT-6 Luna turn: 13 answer chunks, one reasoning-summary chunk, first visible answer about 23 seconds, completion about 25 seconds, no visible error. See `proof/taste-finish-20260924/installed-desktop-ui-stream.json`.
- Final installer SHA-256 `8BEA457F0F0E22E578315A58C115E7D488E14D05B5E3FB11D5602151CA2C597B`; installed executable SHA-256 `378E5568B87CAEFC737B178427A725C6A4121F04AEE4EEA6893E5CEC83D1EC32`. The installer exited 0 and hashes of three local credential/connection-state files stayed identical. See `proof/taste-finish-20260924/final-install-receipt.json`.
- L-A-Y-A exercised the final installed process PID 35584 through Agent → Library → Agent → Settings → Agent. The cold journey passed in 3242 ms with four model selections; the warm journey passed in 1887 ms using four verified bindings and zero selection-model calls. See `proof/taste-finish-20260924/laya-final-installed-receipt.json` and `laya-final-installed-warm-receipt.json`. This proves this named desktop navigation journey only.

## Open limits for an independent evaluator

1. The 25–34 second Luna latency remains too slow for a short chat. The UI streams honestly once the model produces deltas; no measured two-times speed improvement is claimed. Instrument Codex app-server startup, session establishment, and first-token latency separately before choosing a transport or reuse change.
2. This entry records the earlier release candidate. The live backend and UI route changed later on 24 September; see the source-only checkpoint below before evaluating the current checkout.
3. Design review reports deterministic contrast/layout findings; its clear result is not proof of excellent taste, task success, or installed-app behavior. Its checked page was Journey Proof Notes, not every possible generated app.
4. L-A-Y-A's named native journey verifies installed navigation only. It does not prove arbitrary computer control, every button, App Factory installation, or mobile control.
5. The installer is unsigned; the update signing gate and public release promotion are still open. NAS public `current` was not changed.

## Source-only checkpoint after the later UI request

The operator explicitly asked not to build again yet. These edits are visible at `http://127.0.0.1:1421/control?surface=agent` through Vite source serving. The private Tailscale route `https://asuspsdlb.example.invalid:8443/control?surface=agent` and local port 47881 both returned HTTP 200 but still serve the previous production bundle and backend process. Port 47880 is no longer listening. No installer, public candidate, or NAS `current` was updated for this checkpoint.

- Agent composer actions for attach, workflow, and system prompt are icon-only with accessible names. The reasoning marker is a star, and the add button uses the route-blue accent.
- Saved chat opens with one continuation input at the bottom. Open chat tabs persist, switch, close, drag to reorder, and support Alt+Arrow reordering. Desktop switching and drag persistence were exercised; a 390 px phone pass caught clipped tabs, which were corrected and visually checked.
- The sidebar places Priority/Recent/Projects above search. Old orchestration reports with no activity for 14 days leave the default Open view while remaining searchable under All. The real default list changed from 61 to 49 rows; the remaining 49 are active chat records, not orchestration reports. The most recent mission or conversation timestamp drives recency so new mission activity is not hidden behind an older conversation timestamp.
- Future Codex app-server tool calls retain their recorded command, input, output, provider-supplied purpose (when present), item ID, and status in the turn receipt. Started and completed records for one item become one disclosure in the UI. Stream deltas are excluded from the tool list. This source path has **not** been exercised with a new live tool-using model turn or loaded into the still-running 47881 backend, so tool-code display is a source-verified change, not an installed-app claim. Historical receipts that never recorded a command cannot show one retroactively.
- Frontend source checks: 119/119 tests passed; the two edited backend Python modules parsed; `git diff --check` passed. The source preview showed Preview and App Factory routes, saved-chat continuation, tabs, and responsive Agent views without a current page error. A React dependency-array warning in dev logs predates the page reload and came from hot swapping a hook dependency list during editing.
- L-A-Y-A ran the **previously installed desktop bundle** after these source edits and verified Chat → Library → Chat → Settings → Chat with observed postconditions in about 2.47 s. Receipt: `proof/taste-finish-20260924/laya-source-final-receipt.json`. This does not verify the unbuilt source in the installed desktop. L-A-Y-A currently advertises named Neyvia navigation, not generic control of arbitrary Windows apps; generic native preview/computer use remains open.
- The latest scoped 15-file source snapshot was copied to NAS WIP at `/volume1/Saclay/projects/syntelos/work-in-progress/20260924-145900-neyvia-ui-source-unbuilt` and verified with tree SHA-256 `b59548fe02e0cb54ac535f9dbdb80b65c6a2db5323993bf459f632cba5a65312`. The local transfer receipt is `.agent_control/nas_transfers/neyvia_wip_20260924_125613_f762ee78.json`; public `current` remained unchanged. This snapshot contains the files touched for this follow-through, not the entire dirty workspace.

Publication note: local account paths and network identifiers in this document are neutral examples.
