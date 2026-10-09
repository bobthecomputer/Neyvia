# Native browser proof

This standalone shell uses the product's `browser_runtime.rs` and projection script.
It does not run product startup, and it is never a product installer binary.

For C2b the shell creates the first WebView2 window on a worker after setup
returns, so Windows can pump its main message loop while the controller initializes.
The profile stays in the owned worktree proof root; no user profile is imported.
Use the assigned ports explicitly:

```powershell
cargo build --offline --manifest-path scripts/browser-probe/Cargo.toml --target-dir D:/CodexScratch/nx-c2-browser-C2b-native
$env:C2B_NATIVE_BACKEND_PORT='48725'
$env:C2B_NATIVE_FIXTURE_PORT='48726'
$env:C2B_NATIVE_ENGINE_PORT='48727'
$env:C2B_NATIVE_EXE='D:\CodexScratch\nx-c2-browser-C2b-native\debug\browser-proof.exe'
$env:NEYVIA_OBSCURA_EXE='C:\Users\user\Projects\nx-t20-browser\.agent_control\T20\obscura-v0.2.3\bin\obscura.exe'
node scripts/c2b_native_benchmark.cjs
```

The harness uses the real owner HTTP bridge, production native runtime and
production Obscura executor. It retains styled same-origin iframe fill/save,
hidden-control and secret refusal, navigation, auth walls, and an impossible
postcondition. Native capture writes `scripts/evidence/C2b-native.png` when the
native journey works; `C2b-native.json` preserves failures rather than claiming
that a successful build proves startup. It stops only its own spawned processes.
Cross-origin iframe grants, physical takeover and the full product shell are
separate proof boundaries.

```powershell
cargo build --offline --manifest-path scripts/browser-probe/Cargo.toml --target-dir src-tauri/target/browser-probe
node scripts/verify_T20.cjs
```

For INT6, set `T20_PROOF_SCOPE=INT6`, `T20_BACKEND_PORT=48354`,
`T20_FIXTURE_PORT=48355`, `T20_HEADLESS_PORT=48356`, and explicit task-local
`T20_NATIVE_EXE`, `NEYVIA_OBSCURA_EXE`, and `T20_EVIDENCE` paths.
