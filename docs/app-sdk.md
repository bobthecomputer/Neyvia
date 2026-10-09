# Neyvia App SDK (A1)

`node scripts/fluxio-cli.mjs app new pwa --path <new-folder> --name <name>`
creates a working counter app, CL 1.1 model manual, executable host contract,
shared state bridge and portable Python server. Kinds: `web`, `pwa`, `expo`,
`desktop`. Existing folders are refused. No dependency installer is invoked.

Run `python <app>/server.py --port <explicit-port>`, then
`neyvia app verify --project <app> --url http://127.0.0.1:<port>/`.
CL 1.1 must be integrated for verification. This development branch explicitly
uses `--cl-source C:/Users/example/Projects/nx-integrate-cl`; an owner can select
another trusted checkout through `NEYVIA_CL_SOURCE`. Model arguments cannot
select an arbitrary executable source tree.

The web UI and `neyvia.app_sdk.action` execute the identical reducer and commit
through one cross-process-locked CAS ledger. Action identity and state changes
are persisted together. An independent user view sees agent changes. A static
phone export uses device storage instead and visibly says “Saved on this
device”; that state is exposed by its in-page agent bridge, not the PC store.
Expo's React Native UI uses the same reducer with serialized AsyncStorage
commits. Its device bridge is unproven without the native runtime.

`host-contract.json` supplies initial state, action contracts, procedure journey
and observer-based goal. Verification executes controls, agent actions and
reloads, then evaluates CL 1.1 goals against fresh T18 DOM/accessibility state
or T16 native UIA. It checks served assets against source hashes. A compiled
Windows target must match this project's recorded executable and current
source. A failed step refuses completion and keeps adverse observations.
WindowsForms background Invoke refusal uses T16's explicit target-only
BM_CLICK route; receipts record the refusal, delivery and foreground/cursor
preservation.

Each SDK command is registered in `neyvia_app_sdk.COMMANDS`, backend dispatch,
workspace native tool definitions, the desktop allow-list and its existing
generic Tauri IPC. Commands: `app_sdk_new_command`, `app_sdk_describe_command`,
`app_sdk_state_command`, `app_sdk_action_command`, `app_sdk_verify_command`,
`app_sdk_preview_command`, `app_sdk_build_command`. Every mutation claims and
releases the work board. The canonical CLI wrappers call the same generator.

Mobile Studio's token route serves the same shared ledger. Native build
admission requires current source-bound build and runtime receipts. Android
uses an existing shell, cached Gradle, local Capacitor and `--offline`; missing
tools block. Expo export invokes only the app's installed CLI with
`EXPO_OFFLINE=1`. Expo dependencies target the supported SDK 55 family
([Expo's release notes](https://expo.dev/changelog/sdk-55)); installation and
native device proof were not performed.

Autopilot accepts an explicit `appGoal` only with verification in the caller's
tool scope. It persists a host action identity before the real gateway call.
Completion and re-admission run a fresh journey; an interrupted intent is
reconciled before new completion evidence is requested.

Reproduce from this worktree with system Python:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$python3='C:/Users/example/AppData/Local/Programs/Python/Python313/python.exe'
& $python3 scripts/prove_A1.py
& $python3 scripts/prove_A1_exports.py
& $python3 scripts/prove_A1_wiring.py
```

These commands use only ports 48545–48549. The first makes one actual
`gpt-6-luna` CLI proposal call; `--reuse-luna <recorded-luna-folder>` explicitly
replays it without another provider invocation. Receipts distinguish replay
from the original live model call and count provider-reported tokens including
the harness. There is no comparative efficiency claim from this one task.

`scripts/evidence/A1.json` is the acceptance index. It links raw model output,
source snapshots, screenshots, positive and negative goals, canonical CL
`done` results, Mobile/desktop/Autopilot checks and missing build prerequisites.
The Mobile receipt proves the actual token preview route and production
executor with a preselected typed plan, not a model-authored Autopilot plan or
the rendered Neyvia shell frame. Chrome/IAB were unavailable; T18 supplied the
owned browser journey. Physical Android/iPhone, Expo native and signed
distribution are unproven. No public service was started or changed.

Publication note: local account paths and network identifiers in this document are neutral examples.
