<!-- Generated from manuals/cl/remote.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# remote

## overview
CL 1
L remote v1 -- Owner-enabled remote windows
T t1{sessions:json:"{\"type\":\"array\"}" connections:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
S remote.connections:t1=neyvia.remote.state()
A neyvia.remote.state() -> t2 -- Read owner-enabled remote sessions and connections; never reveals capabilities.
F verify-remote-state "No authored observer check is bound to neyvia.remote.state" -> ask operator blocks:neyvia.remote.state
A neyvia.remote.windows(connectionId:str) -> t2 -- List only windows the host has explicitly allowed on an existing connection.
F verify-remote-windows "No authored observer check is bound to neyvia.remote.windows" -> ask operator blocks:neyvia.remote.windows
A neyvia.remote.snapshot(connectionId:str windowId:int) -> t2 -- Observe the owner-selected window with password values/actions omitted; typing into protected or unclassified focused fields refuses
C neyvia.remote.snapshot window-visible:neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) .window_id == windowId
A neyvia.remote.log(connectionId:str since_seq?:0..) -> t2 -- Read the shared redacted T16 log; no recording or input text.
F verify-remote-log "No authored observer check is bound to neyvia.remote.log" -> ask operator blocks:neyvia.remote.log
C neyvia.remote.snapshot window-visible:neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) .window_id == windowId
P observe-allowed-window(connectionId:str windowId:int):allowed=neyvia.remote.windows(connectionId:connectionId); snapshot=neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) C window-visible -- Observe an already owner-connected window with password values redacted and exact live field input guards
V P observe-allowed-window -> script why:"typed manual runner; stops at every judgement"
J protected-field host-entry|stop:"The host refuses typing into a protected or unclassified focused field. Is credential entry needed?" -- Never ask for credentials, clipboard, files, hotkeys or a broader grant; human enters only on host
V J protected-field -> human:operator why:"explicit choice required"
X Session stopped or host disappeared -> Owner enables a new session on host; never reconnect automatically
X Control changed or background pattern unavailable -> Refresh once; unsupported app needs host use, never foreground fallback
F Claude owns embedded and standalone UI; rendered product journey pending
F Real second PC over tailnet and Zen controls have not been proven
F Protection relies on truthful UIA password/control metadata; opaque focused fields refuse typing when their control classification is unavailable
F No product recording implementation; frames and redacted log are volatile
M remote "Host enable/kill: loopback owner, one-use 120-second invite, exact executable/PID/start/window pin, 1-60 minute expiry" src:"authored manual" state:verified
M remote "Native Being controlled remotely indicator owns Stop now; closing it, lost backend heartbeat or physical input revokes" src:"authored manual" state:verified
M remote "Relay owner HTTP /api/ui/remote: connect/disconnect/windows/snapshot/frame/input/log; bot tools only observe existing connections" src:"authored manual" state:verified
M remote "Input: background click/type_text/navigation press_key/one-step vertical scroll if native patterns support it; no global keyboard, clipboard, launches, grants or approvals" src:"authored manual" state:verified
M remote "Enter credentials on host. Password values/actions are omitted from text projections, and protected or unclassified focused fields refuse typing; no account/provider credentials or cookies forwarded" src:"authored manual" state:verified
M remote "Frames/session/input logs have no disk recording; shared log redacts text/results/element labels before queuing" src:"authored manual" state:verified
M remote "Unknown password state does not exclude a window. The native driver omits password values/actions and checks both the exact target and actual focused control before remote typing. Protected and unclassified focused controls refuse input. Paul enters credentials on the host." src:"authored manual" state:verified
M remote "Remote UIA projections are bounded and refreshed incrementally; projectionTruncated marks a partial view. A missing control needs a new observation or host interaction, never guessed input." src:"authored manual" state:verified
M remote "The remote bot API only observes existing owner connections; snapshot is a fresh protected read, never an input/grant effect. Real remote native window/input and the visible host indicator require an outside allowed device or agent desktop." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.x_following_sources.normalize_x_handle","grant_agent.proofs_e_wz.self_check"],"claim":"X handles normalize leading @ and reject every value outside the existing 1-15 ASCII username characters before provider access.","id":"proofs-e-wz.x-handle","impact":["following enumeration","timeline requests"],"phase":"pre"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.fetch_following_accounts","grant_agent.proofs_e_wz.check_following","grant_agent.proofs_e_wz.self_check"],"claim":"Following enumeration returns unique case-insensitive handles within its configured account cap, accurate counts, HTTPS source provenance and exhaustion/truncation flags consistent with pagination.","id":"proofs-e-wz.x-following","impact":["source collector","following digest"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.collect_following_digest_sources","grant_agent.proofs_e_wz.check_source_bundle","grant_agent.proofs_e_wz.self_check"],"claim":"Only public following accounts enter timeline requests; exactly one success or failure represents each request and all summary counts equal the collected data.","id":"proofs-e-wz.x-public-timelines","impact":["public timeline collection","protected account privacy"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.write_following_source_bundle","grant_agent.proofs_e_wz.check_source_artifacts","grant_agent.proofs_e_wz.self_check"],"claim":"Every written source JSON equals its collected data and the manifest describes exact byte lengths and SHA-256 digests; the returned manifest digest matches the durable manifest.","id":"proofs-e-wz.x-artifacts","impact":["following source artifacts","hashed manifest"],"phase":"post"}

## proofs-e-wz
CL 1
L remote v1 -- PROOFS-e W-Z: live contracts and scratch self-checks
X A local fixture is mistaken for a real provider, signed desktop release or whole-suite replacement -> Read the source-bound receipt, per-case coverage map and unresolved frontier before retirement or promotion
F Backend suite and paired-desktop controller scenarios remain pending unless every original predicate has a real action site and observed scratch procedure.
F Hidden-process AST scanner self-tests protect test-only tooling and are retained pending lead retirement review; no source-text scan is relabeled as production proof.
F Legacy desktop-ui/fluxioHelpers.js is absent; its workspace-selection tests remain pending impact/history review.
F The original bootstrap test expected newest merged turn first; its coverage row explicitly supersedes that stale assertion with observed chronological ordering, preserving all other bootstrap/lazy-detail predicates.
M remote "Self-check entry: grant_agent.proofs_e_wz.self_check; CLI: neyvia verify --root <workspace> --area proofs-e-wz" src:"authored manual" state:verified
M remote "Manifest: config/proofs/proofs-e-wz.json; host sites enforce these contracts on every corresponding real action." src:"authored manual" state:verified
M remote "Fixtures use disposable SQLite stores, real owned Python child commands, localhost HTTP port 48503 and bounded source transport injection." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.x_following_sources.normalize_x_handle","grant_agent.proofs_e_wz.self_check"],"claim":"X handles normalize leading @ and reject every value outside the existing 1-15 ASCII username characters before provider access.","id":"proofs-e-wz.x-handle","impact":["following enumeration","timeline requests"],"phase":"pre"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.fetch_following_accounts","grant_agent.proofs_e_wz.check_following","grant_agent.proofs_e_wz.self_check"],"claim":"Following enumeration returns unique case-insensitive handles within its configured account cap, accurate counts, HTTPS source provenance and exhaustion/truncation flags consistent with pagination.","id":"proofs-e-wz.x-following","impact":["source collector","following digest"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.collect_following_digest_sources","grant_agent.proofs_e_wz.check_source_bundle","grant_agent.proofs_e_wz.self_check"],"claim":"Only public following accounts enter timeline requests; exactly one success or failure represents each request and all summary counts equal the collected data.","id":"proofs-e-wz.x-public-timelines","impact":["public timeline collection","protected account privacy"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.write_following_source_bundle","grant_agent.proofs_e_wz.check_source_artifacts","grant_agent.proofs_e_wz.self_check"],"claim":"Every written source JSON equals its collected data and the manifest describes exact byte lengths and SHA-256 digests; the returned manifest digest matches the durable manifest.","id":"proofs-e-wz.x-artifacts","impact":["following source artifacts","hashed manifest"],"phase":"post"}

## user-side
CL 1
L remote v1 -- Share an app and use another PC
T t1{sessions:json:"{\"type\":\"array\"}" connections:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
S remote.connections:t1=neyvia.remote.state()
A neyvia.remote.state() -> t2 -- Read owner-enabled remote sessions and connections; never reveals capabilities.
F verify-remote-state "No authored observer check is bound to neyvia.remote.state" -> ask operator blocks:neyvia.remote.state
A neyvia.remote.windows(connectionId:str) -> t2 -- List only windows the host has explicitly allowed on an existing connection.
F verify-remote-windows "No authored observer check is bound to neyvia.remote.windows" -> ask operator blocks:neyvia.remote.windows
A neyvia.remote.snapshot(connectionId:str windowId:int) -> t2 -- Observe the owner-selected window with password values/actions omitted; typing into protected or unclassified focused fields refuses
C neyvia.remote.snapshot window-visible:neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) .window_id == windowId
A neyvia.remote.log(connectionId:str since_seq?:0..) -> t2 -- Read the shared redacted T16 log; no recording or input text.
F verify-remote-log "No authored observer check is bound to neyvia.remote.log" -> ask operator blocks:neyvia.remote.log
C neyvia.remote.snapshot window-visible:neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) .window_id == windowId
P observe-allowed-window(connectionId:str windowId:int):allowed=neyvia.remote.windows(connectionId:connectionId); snapshot=neyvia.remote.snapshot(connectionId:connectionId windowId:windowId) C window-visible -- Observe an already owner-connected window with password values redacted and exact live field input guards
V P observe-allowed-window -> script why:"typed manual runner; stops at every judgement"
J protected-field host-input|stop:"A protected or unclassified focused field refused input." -- Tell Paul to type credentials on the host himself; never collect or forward them. Refresh the field after host input.
V J protected-field -> human:operator why:"explicit choice required"
J ended-connection new-code|stop:"The host stopped sharing." -- Only the host may create a new one-use grant; never retry the old invitation.
V J ended-connection -> human:operator why:"explicit choice required"
X Typing does nothing -> No text box is picked: click the text box in the picture (or its row under Controls) first; typing goes only there
X Enter, Tab, Delete, shortcuts or paste do nothing -> Refused on purpose; click the app's own button instead, or do it at that PC
X The code expired before connecting -> The share row says so; Stop it and Allow again for a new code
X Sharing stopped by itself -> Using the sharing PC's own mouse or keyboard, closing the native warning, expiry or a backend restart all stop it; the Ended list says which
F Real second PC over the tailnet remains unproven. FOLLOW uses two isolated local backends with the configured proof flag.
F Actual Zen enable, relay observation, live PNG, desktop bridge PNG and kill passed in FOLLOW without recording its text/pixels. Zen typing and site actions remain unproven.
F Chrome and IAB are unavailable in FOLLOW; new rendered desktop and web screen journeys remain unverified.
M remote "STATE screen: pane.show({\"kind\":\"preview\",\"target\":\"remote\" | \"remote:host\" | \"remote:use\" | \"remote:<connectionId>\"}) Ã¢â€ â€™ the Remote control stage; standalone at /control?view=remote&side=host|use[&connection=<id>]" src:"authored manual" state:verified
M remote "STATE shares-and-connections: neyvia.remote.state({}) Ã¢â€ â€™ {\"sessions\":[RemoteSession],\"connections\":[RemoteConnection]}; the screen and the warning poll GET /api/ui/remote/state (1 s while anything is live, 5 s otherwise)" src:"authored manual" state:verified
M remote "STATE warning: visible on every Neyvia screen of the sharing PC while any RemoteSession.status is \"enabled\" (gold, \"Waiting for the other PC\") or \"connected\" (amber, \"Being controlled remotely\"); click opens pane remote:host" src:"authored manual" state:verified
M remote "ACTIONS share (human, sharing PC only)=POST /api/ui/remote {op:\"targets\"} then {op:\"enable\",args:{windowIds,minutes:5|15|30|60,name}}; pre=Paul ticks open windows himself; only explicitly selected host windows are shared; password fields and unknown focused controls refuse remote typing; effect=one-use code shown on screen for 120 s (memory only), warning + native indicator appear; reversible by Stop now" src:"authored manual" state:verified
M remote "ACTIONS stop (human, sharing PC only)=POST /api/ui/remote {op:\"kill\",args:{sessionId?}}; from the warning (Stop now / Stop all now) or a share row; effect=session stopped at once, other PC's view ends; reversible=no (a new share needs a new code)" src:"authored manual" state:verified
M remote "ACTIONS connect (human, other PC)=POST /api/ui/remote {op:\"connect\",args:{url,invite}}; pre=numeric tailnet address + code typed by Paul; the code is never stored, the address is remembered per browser; effect=connection opens the live view" src:"authored manual" state:verified
M remote "ACTIONS use (human, other PC)=POST /api/ui/remote {op:\"input\"} kinds click (button under the pointer, or a Controls list row), type_text (only into a text box Paul picked), press_key (backspace, arrows, home, end, page up/down, escape), scroll (one step up/down on a scrollable control); effect=background input on the shared window, logged by:\"remote\" with text redacted" src:"authored manual" state:verified
M remote "ACTIONS disconnect (human, other PC)=POST /api/ui/remote {op:\"disconnect\",args:{connectionId}}; effect=ends the share on the sharing PC too" src:"authored manual" state:verified
M remote "CHECKS warning-live: neyvia.remote.state({}) {\"path\":\"sessions[*].indicator.visible\",\"op\":\"contains\",\"value\":true} while a share is live" src:"authored manual" state:verified
M remote "CHECKS view-live: neyvia.remote.snapshot({\"connectionId\":{\"$input\":\"connectionId\"},\"windowId\":{\"$input\":\"windowId\"}}) {\"path\":\"window_id\",\"op\":\"eq\",\"value\":{\"$input\":\"windowId\"}}" src:"authored manual" state:verified
M remote "CHECKS effect-landed: neyvia.remote.log({\"connectionId\":{\"$input\":\"connectionId\"}}) {\"path\":\"entries[*].by\",\"op\":\"contains\",\"value\":\"remote\"}" src:"authored manual" state:verified
M remote "GUIDANCE Copy: \"Share an app\" / \"Use another PC\"; \"Being controlled remotely\"; \"Stop now\"; passwords are always \"type them at that PC itself\"" src:"authored manual" state:verified
M remote "GUIDANCE Files: web/src/neyvia/next/NxRemote.jsx (screen), NxRemoteBanner.jsx (shared state + warning), nxRemoteApi.js (routes), nxRemoteModel.js (keys, hit tests, refusal words), nxRemote.css; the live picture reuses the computer-use preview's .nx-pv-* classes" src:"authored manual" state:verified
M remote "Desktop JSON and live PNG frames use the same authenticated bridge: remote_frame_command returns a memory-only bounded PNG with captureId, frame sequence and SHA256. The renderer reconstructs it without an HTTP origin exception." src:"authored manual" state:verified
M remote "Remote UIA projections are bounded and refreshed incrementally; projectionTruncated marks a partial view. A missing control needs a new observation or host interaction, never guessed input." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.x_following_sources.normalize_x_handle","grant_agent.proofs_e_wz.self_check"],"claim":"X handles normalize leading @ and reject every value outside the existing 1-15 ASCII username characters before provider access.","id":"proofs-e-wz.x-handle","impact":["following enumeration","timeline requests"],"phase":"pre"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.fetch_following_accounts","grant_agent.proofs_e_wz.check_following","grant_agent.proofs_e_wz.self_check"],"claim":"Following enumeration returns unique case-insensitive handles within its configured account cap, accurate counts, HTTPS source provenance and exhaustion/truncation flags consistent with pagination.","id":"proofs-e-wz.x-following","impact":["source collector","following digest"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.collect_following_digest_sources","grant_agent.proofs_e_wz.check_source_bundle","grant_agent.proofs_e_wz.self_check"],"claim":"Only public following accounts enter timeline requests; exactly one success or failure represents each request and all summary counts equal the collected data.","id":"proofs-e-wz.x-public-timelines","impact":["public timeline collection","protected account privacy"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.x_following_sources.write_following_source_bundle","grant_agent.proofs_e_wz.check_source_artifacts","grant_agent.proofs_e_wz.self_check"],"claim":"Every written source JSON equals its collected data and the manifest describes exact byte lengths and SHA-256 digests; the returned manifest digest matches the durable manifest.","id":"proofs-e-wz.x-artifacts","impact":["following source artifacts","hashed manifest"],"phase":"post"}
