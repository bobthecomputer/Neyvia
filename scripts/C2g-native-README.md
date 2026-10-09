# C2g browser engines

The task browser uses the admitted Obscura fork first. Its C2g patch adds routed
incremental SSE, a real EventSource parser, CSS/JavaScript dark preferences and
same-document anchor navigation. The host exposes explicit color and motion
preferences, observed HTML drag data transfer and the additional owned port range.

Source preparation: on the preserved C2f source with its fetch-retention patch,
run `node scripts/c2g_patch_engine.cjs`, then
`node scripts/c2g_finalize_engine_patch.cjs`. The resulting portable patch is
`scripts/obscura-v024-C2g-capabilities.patch`. Build using
`node scripts/c2g_build_obscura.cjs --registry-cache`; all inputs are already
admitted local assets and Cargo stays offline. Keep the previous hash-bound
engine pair; stop any task process using the target output before final linking.
Stage the finished pair with `node scripts/c2g_admit_obscura.cjs --stage`, run
`scripts/c2g_browser_abilities.py <staged-obscura-exe>` with system Python, then
run `node scripts/c2g_admit_obscura.cjs`. Admission checks source and binary
digests against the completed build and the actual Obscura journey.

Fragment capture follow-up: after applying the capabilities patch to fresh
preserved C2f sources, run `node scripts/c2g_patch_fragment_render.cjs`. This
adds only `scripts/obscura-v024-C2g-fragment-render-key.patch`; the original
capabilities patch and admitted binary pair remain intact. Build with
`node scripts/c2g_build_obscura.cjs --registry-cache --receipt
C2g-engine-fragment-build.json --fragment-render-key`. Stage with
`node scripts/c2g_admit_obscura.cjs --stage --build
C2g-engine-fragment-build.json --output C2g-engine-fragment-admission.json`.
Run the ability journey with a distinct output filename, then the actual
`scripts/c2g_scroll_background.py <staged-exe> after` screenshot regression.
Admit with the same build/output options, `--proof
C2g-browser-fragment-abilities.json --scroll-proof
C2g-scroll-background-after.json`. Switching the running backend is separate
and requires coordination with its owner after an active benchmark completes.

For a normal WebView2 retry, use `scripts/c2g_launch_native.py <assigned-port>
<explicit-task-local-native-exe>` with system Python. This reuses the C1 track's
`AgentDesktop` launcher and `ZeroDisturbanceGuard` read-only. It creates a fresh
private desktop, resumes the owned process only after job containment, never
changes the input desktop and renews window-guard leases. No normal-desktop or
singleton-browser fallback exists. The agent user-agent and webdriver flag stay
explicitly advertised. It never solves login/CAPTCHA challenges.

Graceful stop: create `.agent_control/C2g/private-native-<port>/stop.request`, wait
for the controller to exit, then inspect `native-launcher-receipt.json`.
`native-live-guard.json` carries periodic current isolation evidence. Credentials
and the memory-only bridge capability are absent from these files.

Real feature journeys are `scripts/c2g_browser_abilities.py <obscura-exe>` and
`scripts/c2g_native_abilities.cjs`. They use owned fixtures and record actual
network chunks, font loads, DOM effects and captures. Native proof is kept
separate from Obscura proof. All proof calls use explicit ports 48721–48729.
