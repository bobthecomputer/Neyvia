# Night route UI and the taste lens — 2026-09-24

## Why

The shell had several palettes stacked by earlier polish layers (finish, pass, state system, workspace), a coral accent that no layer owned, per-surface hues, an icon language split across two libraries, and a typeface ("Geist") that was requested everywhere but never shipped. `neyviaStateSystem.css` also overrode the Appearance theme with `!important`, so the theme never reached the screen. Streaming replies arrived in 3–5 visible jumps because the UI pasted each ~280 ms poll batch at once and the message element remounted on every delta.

## What changed

**Design system** (`web/src/neyvia/neyviaDesignSystem.css`, loaded last by `NeyviaWorkspace.jsx`)
- One token source: the Appearance theme now emits canonical `--ny-*` variables (`neyviaShellPreferences.js`). Every older family (`--neyvia-finish-*`, `--neyvia-pass-*`, `--nv-*`, `--fluxos-*`, `--color-*`, `--bg/--text/...`, `--neyvia-workspace-*`, per-surface and per-kind accent triples) resolves to them.
- Palette from the brand references: ink-navy canvas, route blue (`#2f6bff`, text tint `#7aa5ff`) only for action, focus, selection and live work, north-star gold for Neyvia's voice. Text tiers `#eef2fa / #b7c0d2 / #95a0b5 / #7f8a9f` all clear 4.5:1 from the canvas to a selected row.
- Geist and Geist Mono are bundled (`@fontsource-variable/*`, OFL-1.1) under the family names the CSS already used (`neyviaFonts.css`).
- Lucide icons at one stroke weight; the robot glyphs and the lettered "N" tile are replaced by the north star.
- Sidebar: one raised New Chat action, quiet rows, single-line conversations with a route marker for the selection, row actions on hover or focus, and a dock for spaces.
- Composer: quiet chips and one luminous send. On phones the bar is a two-row grid and tool labels become icons.
- "How we work" and "Mission & evidence" became icon pills with a chevron that flips, opening into floating panels. Reasoning is drawn as an energy bar.
- Settings navigation and the Phone status surface use the same materials. The Phone surface layout issues (no padding, olive host card) predate this pass.

**Streaming and motion** (`NeyviaMessageBody.jsx`, `NeyviaThinking.jsx`, `neyviaLiveMessages.js`)
- A conversation turn keeps one React element for its whole life (`turn:<id>` key). The content-derived key had remounted the reply on every delta.
- The reply flows word by word toward the received text at an adaptive rate. New words fade in lit in the route colour and then settle, a live caret marks the end, and unfinished markdown markers stay hidden. History renders instantly, and the reveal is skipped under reduced motion.
- While thinking, the star orbits and the label shimmers. The reasoning summary shows until words arrive. A light travels around the composer while work is live. The old blinking block caret is removed.

**Taste lens** (`src/grant_agent/taste_lens.py`, `preview.taste` in `native_tools.py`)
- Renders a page at desktop 1440×900 and phone 390×844 in a dark or light scheme. It returns screenshots and measures colliding text, overflow, contrast, typeface and colour discipline, tiny text, tap targets, competing filled primaries, box clutter, radii, type scale, headings, names and alt text.
- Optional `journey`: Laya's `/v1/browser/run` exercises the controls the goal depends on and reports unmet expectations and control coverage. A refused or failed journey blocks the gate.
- Native instructions (`neyvia_agent.py`) append a compact taste contract for chat, executor and verifier roles: render it, run `preview.taste`, look at the screenshots, fix blocking findings, and report the rest.
- Read-only runs may review. A journey needs the run's mutation grant.
- The **Design review** panel (`NeyviaTasteReview.jsx`) runs the same tool from Preview and from the App Factory full-screen preview, which reviews the built `dist/index.html`.

## Evidence

- `npm run test:frontend` 115/115, `scripts/verify-message-rendering.mjs` passed, and the production build passed with fonts bundled.
- Scripted stream through the real UI, with only the send and stream commands simulated and all writes stubbed: thinking state, reasoning summary, caret and composer light were observed. Displayed text grows monotonically with a median step of 14 characters. Final text is exact, markdown is intact (bold plus a 3-item list), and no animation spans are left.
- Lens runs against the redesigned surfaces in dark mode: no text collisions anywhere; Settings 100 with no findings; start and chat views clear. Contrast failures introduced by the first pass were found by the lens and fixed.
- Laya path: journey PASSED (1 step, 0 model calls, 1/1 visible controls exercised). A wrong expectation executed and returned `APP_ASSERTION_FAILED`, which blocked the gate. A missing outcome is rejected before calling Laya. A read-only run returns `approval_required` for a journey.
- The Design review button in the App Factory preview reviewed Journey Proof Notes in about 8 s: both renders loaded, no blocking defect.

## Limits

- Light appearance is not supported yet. Older layers hard-code light text, and a light surface put white on white (found by the lens). Design tokens stay dark (or high contrast) until those layers are migrated.
- The lens measures defects and discipline. It does not judge beauty, brand fit, or whether the page serves its goal. Laya only runs on origins its policy allowlists.
- Backend processes started before this change (`47880`, `8877`, the installed desktop build) need a restart or reinstall to offer `preview.taste` to the Review button. Native agent turns that start from this checkout pick up the contract and tool directly.
- A real model stream was not re-recorded in this pass; the stream proof above is fixture-driven through the production UI.
