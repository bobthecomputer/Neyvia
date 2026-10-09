# C2 browser and C3 consistency handoff

This is a **partial local implementation**, not a completed native-browser release
or an autonomous WebVoyager score. See `evidence/C2.json` for the final real owner
HTTP and registered-tool runs, `C2-verification.json` for independently recomputed
metrics and byte bindings, and `C2-laya-consistency.json` for all 27 model inferences.
Failed attempts remain under `evidence/C2-attempt*.json`.

The shared `browser_dom.js` projects bounded controls, tables, text, authentication
and same-origin frames. Both native and explicit Obscura executors use it. Actions
bind the current revision, execute once, and check a fresh observation. An explicit
`expect` JSON Pointer with `equals` or `contains` checks the requested result;
a generic changed revision confirms an effect, not completion of the user's goal.
Invalid predicates, stale revisions, secret controls, and authentication walls
refuse execution. Delayed effects are polled for at most two seconds without replay.

LAYA receives the goal and supplied candidates with current page evidence. Selected
arguments remain bound to safe observed controls and the observation revision.
The measured calibration artifact covers factual choices only: it cannot grant
an action. Without a matching action calibration, inference returns escalation.
Escalation names the existing checked model/owner route; it does not secretly call
another provider. The 0.8 factual threshold accepted zero of five validation states.

## Reproduce

Use the required system Python 3.13; no pytest, install, download, credential or NAS
access is needed. Run from this worktree. Use only assigned ports 48711–48719.
The existing frozen English checkpoint is reused; the authorized September 30
LAYA project supplies its service/runtime. The task-local launcher handles the
installed Transformers 5 import and nonpersistent rotary-buffer compatibility.
It does not edit that project, train weights or download a model.

```powershell
$python3 = 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'
& $python3 scripts/c2_laya_consistency.py serve --port 48717 `
  --project C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement `
  --model C:/Users/user/Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english `
  --calibration C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/calibration/system1.json `
  --database .agent_control/C2/laya.sqlite
# In a separate shell:
$env:C2_BACKEND_PORT='48711'
$env:C2_FIXTURE_PORT='48712'
$env:C2_ENGINE_PORT='48713'
$env:NEYVIA_LAYA_URL='http://127.0.0.1:48717'
$env:NEYVIA_LAYA_BROWSER_CALIBRATION=(Resolve-Path scripts/evidence/C2-laya-calibration.json).Path
$env:NEYVIA_OBSCURA_EXE='C:\Users\user\Projects\nx-t20-browser\.agent_control\T20\obscura-v0.2.3\bin\obscura.exe'
# Explicit focused headless run; remove this variable to include the native attempt.
$env:C2_SKIP_NATIVE='1'
node scripts/c2_browser_benchmark.cjs
```

The harness exits **1** while the styled-iframe check fails. Its receipts keep that
failure. It creates isolated disposable state and stops its own backend and engine.
Retain an existing receipt before rerunning: ledger hashes bind exact bytes. Repeat
inference with `c2_laya_consistency.py evaluate --port 48717 --cases ... --output ...`.
`seal_c2.py` verifies the retained browser/consistency/source boundary; `--append`
adds three canonical research rows and updates the generated research view.

The native build used `cargo build --offline --manifest-path
scripts/browser-probe/Cargo.toml --target-dir .agent_control/C2/native-build`.
Set `C2_NATIVE_EXE` to that task-local `debug/browser-proof.exe` for its run. Both
the original bare-window and isolated main-webview attempts blocked during native
window creation, before the bridge attached. `C2-native-startup.log` and attempt6
retain the final failure; no final native screenshot or user-input takeover proof
is claimed. An earlier table observation is historical evidence only.

## Remaining gates

- Fix or diagnose native window creation on an interactive host, then prove the
  final WebView2 actions, navigation, capture and takeover journey.
- Obscura v0.2.3 misreports child BODY visibility when the parent has CSS; the
  styled iframe remains failed. Unstyled same-origin fill/save is actually proven.
  Body-omitted iframe parsing is also limited. Hidden controls are not force-clicked.
- Cross-origin frames, closed shadow roots and canvas require explicit additional
  observation/authority. Same-origin support does not imply those capabilities.
- Add a distinct action-selection calibration/validation corpus. Four fitting and
  five factual validation states, including a validation veto, do not establish
  general action confidence or a held-out final test. All factual gold answers in
  this small panel are affirmative; negative-state coverage remains missing.
- Run paired browser-use and frontier comparisons with an explicitly available
  provider/browser surface. Neither comparator was available here. Five public
  pages and three scripted dictionary acquisitions do not prove autonomous
  benchmark completion, account handling, or model efficiency gains.

Paul's next input is needed only for an interactive native host and a comparator
route to complete those external proof gates. No service restart, public promotion,
push, merge or NAS sync was performed.
