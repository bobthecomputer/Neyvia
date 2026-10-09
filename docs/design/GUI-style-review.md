# Neyvia style-consistency review

Scope: the new shell under web/src/neyvia/next and named application CSS/inline styles. `node scripts/design_review.mjs review <output> --ref=<commit>` records every finding with severity, category, path, line, selector and value. Source hashes normalize CRLF to LF.

The matched baseline is 2e491f4a0, before UI edits. The complete severity-ordered listing is D:/NeyviaRuns/gui/review-before-final.json. The current source gate writes scripts/evidence/GUI-style-review.json; it blocks new literals, stale generated references, invalid negative timing variables and CSS/JS spring duration disagreement.

| Severity / category | Before | After source gate |
|---|---:|---:|
| High: literal colours | 437 | 0 |
| Medium: spacing | 3627 | 0 |
| Medium: radius | 475 | 0 |
| Medium: type sizes | 453 | 0 |
| Medium: shadows | 378 | 0 |
| Medium: timing | 133 | 0 |
| Total occurrences | 5503 | 0 |

These are literal occurrences, not 5503 independent usability bugs. A declaration containing four padding values contributes four occurrences. Raw fallback values inside var() are audited too. Token definitions, canvas/data palettes, branded vectors, third-party xterm, geometry and JS spring physics are excluded. The model palette owners remain explicit source-backed tokens. The report does not claim every application surface has been rendered or audited for accessibility.

Changes use shared spacing, type, radius, elevation and motion scales; preserve app-specific skins, white PDF paper and device previews; and give shared buttons/loading/segmented choices native disabled behavior. Primary hover and press fills preserve foreground contrast. Input and app-skin focus rings are opaque. Text size scales exactly once.

Verification lives in manuals/cl/design.cl, chapter style-consistency. The procedure executes the source gate, twelve adverse/positive literal cases and 40 skin/theme contrast cases (1320 assertions) and four shell-theme cases (132 assertions). It passed twice through the attached Neyvia MCP server, compiled to script 93e6dca3f600a6d7343f1e124603a6817d520eec204bbe77788cf1df8e3276d8, and replayed without model calls. These calculations cover named flat surfaces and primary fills. Images, composite gradients, disabled contrast and every application journey are outside the contrast calculation.

The Obscura comparison is [D:/NeyviaRuns/gui/index.html](D:/NeyviaRuns/gui/index.html): twenty matched screenshots of Shell, Settings, App Factory, Files and Notes, in Forest/dark and Morning/light, with per-theme capture receipts, screenshot SHA-256 and build-index SHA-256. The Shell light capture includes the Settings window used to select Morning. Two additional Settings screenshots accompany the real Medium → Large → Medium journey: brand text changes from 20px to 22px in both themes. The driver restores Medium by observing its selected control and the intentionally absent default text-size attribute.

Twelve shared-primitives crops record real rest, hover, mouse-down, keyboard focus, reduced-motion preference and phone-width observations. Ten of eighteen checks pass: hover fill changes, loading is named and native-disabled, disabled clicks do nothing, radio arrows skip the disabled option, and the phone has no horizontal overflow, in both themes. Eight checks fail: pressed feedback, focus-visible matching, visible focus ring and reduced-motion duration, in both themes. The available hash-admitted C2g engine reports no :active or :focus-visible state and no animation-duration value. The latest admitted C2h executable is absent. The rendered-state CL procedure therefore remains failed; source declarations and passing contrast calculations do not establish these rendered states. No alternate browser, injected pseudo state or visible window is used.

The production npx vite build passes with --configLoader runner and an absolute output under D:/NeyviaRuns/gui/build-after. The shared-control lab build and CL compiler equality check also pass. The branch incorporates track/int-final through 778cd5685 locally; nothing is pushed or promoted. GUI-rendered-screens.json, GUI-rendered-states.json and GUI-verification.json keep the successful and failed boundaries separate. Generated native run receipts and compiled artifacts are preserved at D:/NeyviaRuns/gui/harness-evidence-20261006-final. To regenerate the runnable local cache, use scripts/gui_harness.py --chapter style-consistency --procedure review-owned-styles (or verify-rendered-screens); each route runs twice, compiles and replays.

No paid Graphical files or component-learning libraries are included. D:/NeyviaRuns/components has been removed through silent Recycle Bin cleanup. This GUI task authors no LAYA training changes; upstream integration changes remain intact.
