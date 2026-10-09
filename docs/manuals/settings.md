<!-- Generated from manuals/cl/settings.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# settings

## overview
CL 1
L settings v1 -- Persistent settings, privacy and owner proposals
T t1{revision:int settings:json:"{\"type\":\"object\"}" network:json:"{\"type\":\"object\"}" ..}
T t2{revision:int settings:json:"{\"type\":\"object\"}" network:json:"{\"type\":\"object\"}" setup:json:"{\"type\":\"object\"}" ..}
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"object\",\"properties\":{\"density\":{\"type\":\"string\",\"enum\":[\"calm\",\"workshop\",\"grove\"]},\"theme\":{\"type\":\"string\",\"enum\":[\"forest\",\"morning\",\"sunset\",\"night-green\"]},\"initiative\":{\"type\":\"string\",\"enum\":[\"suggest\",\"act-and-tell\",\"silent\"]},\"projectInitiative\":{\"type\":\"object\",\"additionalProperties\":{\"type\":\"string\",\"enum\":[\"suggest\",\"act-and-tell\",\"silent\"]}},\"localOnly\":{\"type\":\"boolean\"},\"cleanup\":{\"type\":\"object\"},\"nightShift\":{\"type\":\"object\"},\"toolAutoUpdate\":{\"type\":\"string\",\"enum\":[\"ask\",\"off\",\"allow\"]},\"look\":{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"font\":{\"type\":\"string\",\"enum\":[\"neyvia\",\"windows\",\"inter\",\"geist\",\"editorial\"]},\"textSize\":{\"type\":\"string\",\"enum\":[\"s\",\"m\",\"l\"]},\"background\":{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"kind\":{\"type\":\"string\",\"enum\":[\"theme\",\"preset\",\"solid\",\"image\"]},\"preset\":{\"type\":\"string\",\"maxLength\":40},\"color\":{\"type\":\"string\",\"pattern\":\"^(#[0-9a-f]{6})?$\"},\"image\":{\"type\":\"string\",\"maxLength\":40},\"dim\":{\"type\":\"integer\",\"minimum\":0,\"maximum\":90},\"blur\":{\"type\":\"integer\",\"minimum\":0,\"maximum\":40}}}}}},\"additionalProperties\":false}"
T t5{revision:int ..}
T t6{ok:bool setup:json:"{\"type\":\"object\"}" ..}
S settings.preferences:t1=neyvia.settings.get()
S settings.current:t2=neyvia.settings.get()
A neyvia.settings.get() -> t3 -- Read persisted preferences and network enforcement
C neyvia.settings.get enforced:neyvia.settings.get() .network.enforced == true
C neyvia.settings.get local_only:neyvia.settings.get() .network.localOnly == true
A neyvia.settings.propose(patch:t4 expectedRevision:0..) -> t3 -- Queue an exact owner approval; no preference changes yet
F verify-propose "No authored observer check is bound to neyvia.settings.propose" -> ask operator blocks:neyvia.settings.propose
A neyvia.settings.setup() -> t3 -- Emit setup.open resume=true without deleting installed state
F verify-setup "No authored observer check is bound to neyvia.settings.setup" -> ask operator blocks:neyvia.settings.setup
A neyvia.settings.network_check() -> t3 -- Attempt nine forbidden operations and report actual policy refusals
F verify-network_check "No authored observer check is bound to neyvia.settings.network_check" -> ask operator blocks:neyvia.settings.network_check
A neyvia.settings.get() -> t5 -- Observe canonical settings revision, policy and setup state
F verify-settings-get "No authored observer check is bound to neyvia.settings.get" -> ask operator blocks:neyvia.settings.get
A neyvia.settings.setup() -> t6 ! -- Persist setup.requestedAt and emit setup.open without erasing installation
C neyvia.settings.setup setup-requested:matches(neyvia.view.state() .state {properties:{dom:{properties:{setup:{properties:{mounted:{const:true}} required:["mounted"] type:"object"}} required:["setup"] type:"object"} fresh:{const:true}} required:["fresh" "dom"] type:"object"})
A neyvia.settings.propose(patch:t4 expectedRevision:0..) -> t3 ! -- Save an exact patch approval request; repeat approved proposal returns its durable receipt
F verify-settings-propose "No authored observer check is bound to neyvia.settings.propose" -> ask operator blocks:neyvia.settings.propose
C neyvia.settings.get enforced:neyvia.settings.get() .network.enforced == true
C neyvia.settings.get local_only:neyvia.settings.get() .network.localOnly == true
C neyvia.view.state setup-requested:matches(neyvia.view.state() .state {properties:{dom:{properties:{setup:{properties:{mounted:{const:true}} required:["mounted"] type:"object"}} required:["setup"] type:"object"} fresh:{const:true}} required:["fresh" "dom"] type:"object"})
P read-preferences():preferences=neyvia.settings.get() C enforced -- Read canonical settings with installed enforcement
V P read-preferences -> script why:"typed manual runner; stops at every judgement"
P check-local-only():preferences=neyvia.settings.get() C local_only; proof=neyvia.settings.network_check() -- Verify actual denied TCP UDP DNS HTTP HTTPS async and child operations while local-only is enabled
V P check-local-only -> script why:"typed manual runner; stops at every judgement"
P propose-change(patch:t4 expectedRevision:0..):proposal=neyvia.settings.propose(expectedRevision:expectedRevision patch:patch) -- Queue an owner-reviewed settings change
V P propose-change -> script why:"typed manual runner; stops at every judgement"
P re-enter-setup():setup=neyvia.settings.setup() -- Open existing setup with installed state retained
V P re-enter-setup -> script why:"typed manual runner; stops at every judgement"
P reenter-setup():requested=neyvia.settings.setup() C setup-requested -- Request setup and observe its durable request timestamp
V P reenter-setup -> script why:"typed manual runner; stops at every judgement"
P verify-effect-propose(patch:t4 expectedRevision:0..):effect=neyvia.settings.propose(expectedRevision:expectedRevision patch:patch) -- Verify the actual effect through fresh owning observers
V P verify-effect-propose -> script why:"typed manual runner; stops at every judgement"
J owner-change approve|decline:"Should this exact proposal change the workspace settings?" -- Only the signed-in PC owner can apply the proposal through the approval UI; never self-approve or bypass the saved revision.
V J owner-change -> human:operator why:"explicit choice required"
X Settings changed since observation -> Read settings.get again and review a fresh proposal; stale revisions never overwrite newer state.
X Local-only activation reports active children -> Finish or stop only owned CLI/MCP jobs, then retry. Unknown children are refused; the OS System32 console host is not a job.
X External operation is blocked -> Use literal loopback services or ask the owner to disable local-only. Never silently substitute a provider.
F Rendered Settings/setup controls require Claude UI proof.
F T10 owns aggregate night budgets and quiet GPU hours; this source uses the current live resource policy.
F Application egress enforcement does not confine hostile native code or unrelated PC applications.
M settings "Density calm/workshop/grove; theme forest/morning/sunset/night-green maps to existing dark/light/sunset/night bus values." src:"authored manual" state:verified
M settings "Suggest queues housekeeping, act-and-tell archives reversibly with notification, silent archives reversibly without toast; per-project overrides take precedence." src:"authored manual" state:verified
M settings "The durable Settings revision, cleanupPolicy and nightshift.resources commit together." src:"authored manual" state:verified
M settings "Setup summaries retain recent action status without nesting prior results. Full action receipts remain available for detailed inspection." src:"authored manual" state:verified
M settings "Settings Prompts opens the existing system prompt editor through get_agent_prompt_library_command; Save role/override uses save_agent_prompt_library_command with expectedRevision. Selected .txt/.md files stay editable before saving. Native import_agent_prompt_file_command errors expose Choose a file through the browser file input; this path does not prove the physical native dialog." src:"authored manual" state:verified
M settings "Radio groups use one selected Tab stop; arrows select with wraparound, Home selects the first choice and End the last." src:"authored manual" state:verified
M settings "toolAutoUpdate defaults to ask. The owner may choose off or allow through settings.update; proposals require owner approval. Global CLI updates never run from development/worktree/scratch roots, even with allow. Each update records a compact tool.update activity event and retains its full receipt." src:"authored manual" state:verified
M settings "In Settings > Tool updates, Global CLI updates offers Ask first, Off and Allow automatic updates. The saved PC revision governs this setting; a conflict refreshes the record and asks the owner to choose again. This control does not override development/scratch or local-only refusal." src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_revision/check_committed","proofs_settings.self_check"],"claim":"Only the current integer expectedRevision may write; a successful canonical update persists exactly one revision increment.","id":"settings.revision-cas","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.snapshot/check_rejection","proofs_settings.self_check"],"claim":"Rejected invalid control patches change no canonical state and emit no events.","id":"settings.invalid-preserves","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Within the same transaction, canonical cleanup/night resources/density/theme storage equals the normalized Settings value.","id":"settings.canonical-mirrors","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Every update emits durable identical receipt events; a nightShift patch emits exactly one normalized policy update.","id":"settings.night-policy-event","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Legacy theme selection updates the same canonical preference and mirror storage.","id":"settings.legacy-theme","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> proofs_settings.check_view","proofs_settings.self_check"],"claim":"Ambient and transparency controls persist their exact value before returning success.","id":"settings.view-durable","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:mergeRuntimes -> checkedProofsEModel"],"claim":"Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source","id":"runtime.mergeRuntimes","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:runtimeSummary -> checkedProofsEModel"],"claim":"Ready and installed counts come from rendered runtime rows without inventing detection","id":"runtime.runtimeSummary","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaShellPreferences.js:normalizeNeyviaShellPreferences -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.normalize","impact":["neyviaShellPreferences"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaMotion.js:neyviaMotionCssVariables -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.motion","impact":["neyviaMotion"],"phase":"post"}

## proofs-e-frontend
CL 1
L settings v1 -- PROOFS-e frontend action contracts
X Host/backend or rendered behavior has not been inspected. -> Run the matching feature proof before claiming that boundary; frontend helper receipts prove only the called production helpers.
F Covered helper receipts enforce only the production actions declared by these contracts. UI geometry, browser authority, service-worker lifecycle, backend dispatch and mutation are retained case by case until their own real action contracts and receipts exist.
M settings "preferences.normalize: Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency." src:"authored manual" state:verified
M settings "preferences.motion: Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency." src:"authored manual" state:verified
M settings "Self-check: node scripts/proofs-e-frontend.mjs --root <scratch directory> --json" src:"authored manual" state:verified
M settings "Startup procedures: preferences.motion-accessibility" src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_revision/check_committed","proofs_settings.self_check"],"claim":"Only the current integer expectedRevision may write; a successful canonical update persists exactly one revision increment.","id":"settings.revision-cas","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.snapshot/check_rejection","proofs_settings.self_check"],"claim":"Rejected invalid control patches change no canonical state and emit no events.","id":"settings.invalid-preserves","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Within the same transaction, canonical cleanup/night resources/density/theme storage equals the normalized Settings value.","id":"settings.canonical-mirrors","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Every update emits durable identical receipt events; a nightShift patch emits exactly one normalized policy update.","id":"settings.night-policy-event","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Legacy theme selection updates the same canonical preference and mirror storage.","id":"settings.legacy-theme","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> proofs_settings.check_view","proofs_settings.self_check"],"claim":"Ambient and transparency controls persist their exact value before returning success.","id":"settings.view-durable","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:mergeRuntimes -> checkedProofsEModel"],"claim":"Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source","id":"runtime.mergeRuntimes","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:runtimeSummary -> checkedProofsEModel"],"claim":"Ready and installed counts come from rendered runtime rows without inventing detection","id":"runtime.runtimeSummary","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaShellPreferences.js:normalizeNeyviaShellPreferences -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.normalize","impact":["neyviaShellPreferences"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaMotion.js:neyviaMotionCssVariables -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.motion","impact":["neyviaMotion"],"phase":"post"}

## proofs-e-models
CL 1
L settings v1 -- PROOFS-e: production model contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S settings.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the most recent verification receipt without invoking production actions again
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-model-proof-receipt():receipt=neyvia.verify.status() C observed -- Read the latest receipt after the production model self-check runner
V P read-model-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X Model transforms are reported as proof of a native app/provider/device effect -> Use the real owning feature procedure and its observed runtime
F Rendered browser/desktop journeys are separate from pure model proof
F Remote device, game editor and provider behavior require their real runtimes
M settings "runtime.mergeRuntimes: Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source" src:"authored manual" state:verified
M settings "runtime.runtimeSummary: Ready and installed counts come from rendered runtime rows without inventing detection" src:"authored manual" state:verified
M settings "Startup runner: scripts/proofs-e-models.mjs --root <owned-scratch>; area proofs-e-models checks real model actions and corrupted output refusals" src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_revision/check_committed","proofs_settings.self_check"],"claim":"Only the current integer expectedRevision may write; a successful canonical update persists exactly one revision increment.","id":"settings.revision-cas","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.snapshot/check_rejection","proofs_settings.self_check"],"claim":"Rejected invalid control patches change no canonical state and emit no events.","id":"settings.invalid-preserves","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Within the same transaction, canonical cleanup/night resources/density/theme storage equals the normalized Settings value.","id":"settings.canonical-mirrors","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Every update emits durable identical receipt events; a nightShift patch emits exactly one normalized policy update.","id":"settings.night-policy-event","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Legacy theme selection updates the same canonical preference and mirror storage.","id":"settings.legacy-theme","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> proofs_settings.check_view","proofs_settings.self_check"],"claim":"Ambient and transparency controls persist their exact value before returning success.","id":"settings.view-durable","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:mergeRuntimes -> checkedProofsEModel"],"claim":"Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source","id":"runtime.mergeRuntimes","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:runtimeSummary -> checkedProofsEModel"],"claim":"Ready and installed counts come from rendered runtime rows without inventing detection","id":"runtime.runtimeSummary","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaShellPreferences.js:normalizeNeyviaShellPreferences -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.normalize","impact":["neyviaShellPreferences"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaMotion.js:neyviaMotionCssVariables -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.motion","impact":["neyviaMotion"],"phase":"post"}

## proofs-e-shell
CL 1
L settings v1 -- PROOFS-e shell state and action contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S settings.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the latest verification receipt without repeating shell actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-shell-proof-receipt():receipt=neyvia.verify.status() C observed -- Observe the latest shell proof receipt without replaying mutations
V P read-shell-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X A queue or shell state receipt is treated as rendered app proof -> Inspect the owned running UI and actual PDF/output/provider separately
F Rendered shell journeys and PDF loading require owned UI proof
F Provider execution and actual artifact publishing are separate proof boundaries
M settings "Themes and scenes use bus reducer guards; malformed layouts/unknown scenes/themes retain explicit bus errors" src:"authored manual" state:verified
M settings "Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions" src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_revision/check_committed","proofs_settings.self_check"],"claim":"Only the current integer expectedRevision may write; a successful canonical update persists exactly one revision increment.","id":"settings.revision-cas","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.snapshot/check_rejection","proofs_settings.self_check"],"claim":"Rejected invalid control patches change no canonical state and emit no events.","id":"settings.invalid-preserves","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Within the same transaction, canonical cleanup/night resources/density/theme storage equals the normalized Settings value.","id":"settings.canonical-mirrors","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Every update emits durable identical receipt events; a nightShift patch emits exactly one normalized policy update.","id":"settings.night-policy-event","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> neyvia_settings.update -> proofs_settings.check_committed","proofs_settings.self_check"],"claim":"Legacy theme selection updates the same canonical preference and mirror storage.","id":"settings.legacy-theme","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_view_tools.call -> proofs_settings.check_view","proofs_settings.self_check"],"claim":"Ambient and transparency controls persist their exact value before returning success.","id":"settings.view-durable","impact":["canonical Settings","view preferences","Night Shift resource admission"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:mergeRuntimes -> checkedProofsEModel"],"claim":"Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source","id":"runtime.mergeRuntimes","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxRuntimeModel.js:runtimeSummary -> checkedProofsEModel"],"claim":"Ready and installed counts come from rendered runtime rows without inventing detection","id":"runtime.runtimeSummary","impact":["runtime frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaShellPreferences.js:normalizeNeyviaShellPreferences -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.normalize"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.normalize","impact":["neyviaShellPreferences"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/neyviaMotion.js:neyviaMotionCssVariables -> checkedFrontendAction","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion","web/src/neyvia/neyviaFrontendContracts.js:FRONTEND_CONTRACTS.preferences.motion"],"claim":"Valid visual preferences preserve independent choices and reduce-motion disables motion without changing transparency.","id":"preferences.motion","impact":["neyviaMotion"],"phase":"post"}
