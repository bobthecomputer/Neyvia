<!-- Generated from manuals/cl/game-dev.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# game-dev

## bridges
CL 1
L game-dev v1 -- Operate native game editors and Babylon through exact sessions and checked receipts
T t1{engines:json:"{\"type\":\"array\"}" sessions:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"unity\",\"roblox\",\"blender\",\"godot\",\"babylon\"]}"
T t4 json:"{\"type\":\"string\",\"enum\":[\"Edit\",\"Play\",\"Client\",\"Server\"]}"
S game-dev.live:t1=neyvia.gamedev.status()
A neyvia.gamedev.status() -> t2 -- Observe installation separately from heartbeat connection
F verify-status "No authored observer check is bound to neyvia.gamedev.status" -> ask operator blocks:neyvia.gamedev.status
A neyvia.gamedev.sessions(engine?:t3 projectPath?:str context?:t4) -> t2 -- Observe exact engine/project/context/session/capabilities; never select by engine alone
C neyvia.gamedev.sessions one-editor-session:matches(neyvia.gamedev.sessions(context:"Edit" engine:engine projectPath:projectPath) .sessions {items:{properties:{clientId:{minLength:1 type:"string"} status:{const:"connected"}} required:["sessionId" "clientId"] type:"object"} maxItems:1 minItems:1 type:"array"})
A neyvia.gamedev.setup(engine:t3 projectPath:str) -> t2 ! -- Copy local bridge package and create a project-scoped token; no editor/system install
C neyvia.gamedev.setup configured:neyvia.gamedev.project_status(engine:engine projectPath:projectPath) .configured == true
A neyvia.gamedev.action(sessionId:str action:str args?:t2 requestId?:str) -> t2 ! -- Queue an affinity-bound native operation once; success is determined by native completion, not queue admission
C neyvia.gamedev.action complete:neyvia.gamedev.receipt(requestId:requestId) .status == "succeeded"
A neyvia.gamedev.receipt(requestId:str) -> t2 -- Observe queue/running/terminal result, error and elapsed time; pending is not completed
C neyvia.gamedev.receipt complete:neyvia.gamedev.receipt(requestId:requestId) .status == "succeeded"
A neyvia.gamedev.asset_validate(path:str) -> t2 ! -- Run official Khronos Validator; invalid exports cannot be loaded by action
C neyvia.gamedev.asset_validate valid-asset:neyvia.gamedev.asset_validate(path:path) .valid == true
A neyvia.gamedev.receipts(sessionId?:str limit?:1..200) -> t2 -- Observe durable action receipts and reported UI selection separately from native bridge observations
F verify-gamedev-receipts "No authored observer check is bound to neyvia.gamedev.receipts" -> ask operator blocks:neyvia.gamedev.receipts
A neyvia.gamedev.state() -> t2 -- Observe durable action receipts and reported UI selection separately from native bridge observations
F verify-gamedev-state "No authored observer check is bound to neyvia.gamedev.state" -> ask operator blocks:neyvia.gamedev.state
A neyvia.gamedev.project_status(engine:t3 projectPath:str) -> t2 -- Read exact bridge package hashes and configuration affinity separately from connection
F verify-project-status "No authored observer check is bound to neyvia.gamedev.project_status" -> ask operator blocks:neyvia.gamedev.project_status
C neyvia.gamedev.receipt complete:neyvia.gamedev.receipt(requestId:requestId) .status == "succeeded"
C neyvia.gamedev.asset_validate valid-asset:neyvia.gamedev.asset_validate(path:path) .valid == true
C neyvia.gamedev.project_status configured:neyvia.gamedev.project_status(engine:engine projectPath:projectPath) .configured == true
C neyvia.gamedev.sessions one-editor-session:matches(neyvia.gamedev.sessions(context:"Edit" engine:engine projectPath:projectPath) .sessions {items:{properties:{clientId:{minLength:1 type:"string"} status:{const:"connected"}} required:["sessionId" "clientId"] type:"object"} maxItems:1 minItems:1 type:"array"})
P discover-live-editors():availability=neyvia.gamedev.status(); native=neyvia.gamedev.sessions() -- Find installed editors and exact connected native contexts before operating
V P discover-live-editors -> script why:"typed manual runner; stops at every judgement"
P review-completed-action(requestId:str):receipt=neyvia.gamedev.receipt(requestId:requestId) C complete -- Check a terminal native receipt after polling until it stops being queued/running
V P review-completed-action -> script why:"typed manual runner; stops at every judgement"
P validate-export-before-engine-load(path:str):validation=neyvia.gamedev.asset_validate(path:path) C valid-asset -- Reject broken glTF resources before any engine import
V P validate-export-before-engine-load -> script why:"typed manual runner; stops at every judgement"
P setup-project(engine:t3 projectPath:str):setup=neyvia.gamedev.setup(engine:engine projectPath:projectPath) C configured -- Install a project-local bridge and prove its current package hashes/configuration; native connection requires a separate session heartbeat
V P setup-project -> script why:"typed manual runner; stops at every judgement"
P operate-exact-session(sessionId:str action:str args:t2 requestId:str):request=neyvia.gamedev.action(action:action args:args requestId:requestId sessionId:sessionId) C complete -- Queue exactly one affinity-bound native operation; poll this same request and review native completion before claiming scene behavior
V P operate-exact-session -> script why:"typed manual runner; stops at every judgement"
P inspect-one-editor-session(engine:t3 projectPath:str):native=neyvia.gamedev.sessions(context:"Edit" engine:engine projectPath:projectPath) C one-editor-session -- In a disposable project with exactly one native editor instance, observe one connected client-affine session after registration retry; multiple real instances remain ambiguous
V P inspect-one-editor-session -> script why:"typed manual runner; stops at every judgement"
X Editor is detected but no native session is connected -> Use setup then enable the project-local plugin in its actual editor; inspect heartbeat before actions
X Action is queued/running -> Poll the same requestId until terminal; do not call it complete or queue a fresh retry
X Backend restart, timeout or ambiguous completion -> Inspect native state first; interrupted actions are failed and never automatically replayed
X Changed request payload reuses an ID -> Inspect previous receipt, then choose a new ID only for a new explicit intent
X Roblox simulation stop preserves edits -> Require preserveChanges:true for simulation; player EndTest uses exact Server session, then observe Edit playResult
F Native Unity, Blender and Roblox defining editor journeys remain unproven. Godot and rendered Babylon journeys are recorded by the UI integration owner in plans/15-handoff.md followups; FOLLOW replay proves shared backend receipts, not a new editor installation.
F Unity glTF loading requires an existing project importer
F Roblox StudioTestService play/end APIs and actual Client/Server plugin contexts remain unverified without Studio
M game-dev "Observer/action/check tools share HTTP /api/backend, bot state and desktop forwarding; existing generic Tauri IPC carries gamedev_*_command." src:"authored manual" state:verified
M game-dev "Unity: select/inspect path is scene hierarchy or Assets/...; guarded script edit uses source+expectedSha256; component edit path/component/property/value or vector; run/stop/reload; test mode EditMode/PlayMode only with existing Test Framework." src:"authored manual" state:verified
M game-dev "Godot Edit: inspect; select/edit node relative to scene, property and value; script edit path res://...gd, source, expectedSha256; validate path res://...gd; run -> observe separate Play session; Play interact node,input invokes game's explicit neyvia_interact method." src:"authored manual" state:verified
M game-dev "Roblox: exact studio_id and Edit/Client/Server affinity; Instance path, script source+expectedSource; run mode play uses StudioTestService (if available); stop mode play requires Server and final Edit playResult observation; simulation stop requires preserveChanges:true; read actual console." src:"authored manual" state:verified
M game-dev "Blender: inspect/select/edit object and location/rotation/scale; render path PNG and camera; export path GLB/glTF and selectedOnly; validate then load_asset path." src:"authored manual" state:verified
M game-dev "Babylon: edit op create/transform/material, name, position/rotation/scaling/color finite triples, expectedRevision; run/stop; interact name,rotateY radians; test name,position/minVertices; export path GLB with expectedSha256 for overwrite; validate then load_asset path GLB." src:"authored manual" state:verified
M game-dev "Export/import proof is boundary-specific. NullEngine runs real scene geometry and loader but cannot prove rendered pixels, clicks or Blender rendering." src:"authored manual" state:verified
M game-dev "Engine APIs remain native; do not unify Unity Components, Roblox Instances and Godot Nodes." src:"authored manual" state:verified
M game-dev "Private .neyvia/gamedev-bridge.json must remain out of source control. Never expose its token in UI or receipts." src:"authored manual" state:verified
M game-dev "Game Dev action log reads gamedev_receipts_command so bot and UI actions share durable results. Screen reports use POST /api/ui/app-state app=game-dev and appear through neyvia.gamedev.state; reported selection never establishes native engine success." src:"authored manual" state:verified
M game-dev "Native bridges use the literal loopback port in the selected project capability configuration, excluding public port 47881. Unity batchmode/nographics, Godot --headless --editor, and Blender --background preserve the actual native scene operations. A pending request is not a completed edit; use the same requestId and reread inspect after success." src:"authored manual" state:verified
M game-dev "Observe sessions with explicit engine, projectPath and context before action. CL fills sessionId only when this current observation contains one exact native session; it never guesses a native session from the chat identity." src:"authored manual" state:verified
M game-dev "Unity, Godot and Blender register with a stable per-instance clientId. Identical retry replies preserve the native session; changed affinity or capabilities refuse reuse. Separate editor instances keep separate identities, so CL still refuses ambiguous session selection. Unity idle polls never execute empty nested request objects." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.neyvia_gamedev.handle_command","grant_agent.neyvia_gamedev.validate_asset","grant_agent.proofs_games_journey.export_validation_journey","scripts/gamedev/scene-runtime.js:NeyviaScene.dispatch","scripts/gamedev/scene-runtime.js:NeyviaScene.persist"],"claim":"A local Babylon NullEngine journey creates and edits real mesh geometry, preserves the edit across scene save/reopen, refuses an unsupported primitive without changing the saved scene, exports a GLB that passes Khronos validation, diagnoses a broken glTF reference, and refuses paths outside the selected workspace.","id":"gamedev.export-validation-journey","impact":["Game Dev project export validation and engine import boundary"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:keepSelection -> checkedProofsEModel"],"claim":"Native selection never changes implicitly; browser reload affinity follows only one same-project/context replacement","id":"gamedev.keepSelection","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:tabForStage -> checkedProofsEModel"],"claim":"Explicit known tabs win, then launcher app aliases, then embedded Browser 3D","id":"gamedev.tabForStage","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:visibleFields -> checkedProofsEModel"],"claim":"Conditional controls show exactly fields whose predicates hold","id":"gamedev.visibleFields","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:initialValues -> checkedProofsEModel"],"claim":"Form defaults resolve duplicate keys according to their condition","id":"gamedev.initialValues","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:buildArgs -> checkedProofsEModel"],"claim":"Visible fields become exact bridge args; vectors/numbers are finite, JSON text must parse as an object and wildcard fields are flattened","id":"gamedev.buildArgs","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:actionFields -> checkedProofsEModel"],"claim":"Godot edit/interact and Unity test forms retain their typed bridge fields/defaults; other actions return valid field arrays","id":"gamedev.actionFields","impact":["Game Dev typed action forms and engine bridge args"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:sessionLabel","web/src/neyvia/next/nxGameDevModel.js:keepSelection -> checkedProofsEModel","scripts/uifix2_contracts.py:c4_gamedev_names_and_selection","scripts/p22_release_models.mjs"],"claim":"Sessions are named in words (Browser 3D editor, Editor), never with raw environment ids or a literal null; a reloaded browser-webgl or browser-null scene stays selected","id":"gamedev.sessionLabel","impact":["Game Dev sessions list and session card"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_gamedev.report_state","grant_agent.ui_command_bus.UICommandBus.put","grant_agent.ui_command_bus.UICommandBus.get","grant_agent.proofs_surface_games_extra.screen_state_persists_and_refuses_invalid_tab"],"claim":"Game Dev screen selection persists the exact tab, project and UI client through the backend state bus; an unknown tab is refused and leaves the last valid selection unchanged.","id":"p22.gamedev.screen-state-persistence","impact":["Game Dev selected editor/project screen state and invalid-tab refusal"],"phase":"post"}

## proofs-e-models
CL 1
L game-dev v1 -- PROOFS-e: production model contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S game-dev.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the most recent verification receipt without invoking production actions again
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-model-proof-receipt():receipt=neyvia.verify.status() C observed -- Read the latest receipt after the production model self-check runner
V P read-model-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X Model transforms are reported as proof of a native app/provider/device effect -> Use the real owning feature procedure and its observed runtime
F Rendered browser/desktop journeys are separate from pure model proof
F Remote device, game editor and provider behavior require their real runtimes
M game-dev "gamedev.keepSelection: Native selection never changes implicitly; browser reload affinity follows only one same-project/context replacement" src:"authored manual" state:verified
M game-dev "gamedev.tabForStage: Explicit known tabs win, then launcher app aliases, then embedded Browser 3D" src:"authored manual" state:verified
M game-dev "gamedev.visibleFields: Conditional controls show exactly fields whose predicates hold" src:"authored manual" state:verified
M game-dev "gamedev.initialValues: Form defaults resolve duplicate keys according to their condition" src:"authored manual" state:verified
M game-dev "gamedev.buildArgs: Visible fields become exact bridge args; vectors/numbers are finite, JSON text must parse as an object and wildcard fields are flattened" src:"authored manual" state:verified
M game-dev "gamedev.actionFields: Godot edit/interact and Unity test forms retain their typed bridge fields/defaults; other actions return valid field arrays" src:"authored manual" state:verified
M game-dev "Startup runner: scripts/proofs-e-models.mjs --root <owned-scratch>; area proofs-e-models checks real model actions and corrupted output refusals" src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.neyvia_gamedev.handle_command","grant_agent.neyvia_gamedev.validate_asset","grant_agent.proofs_games_journey.export_validation_journey","scripts/gamedev/scene-runtime.js:NeyviaScene.dispatch","scripts/gamedev/scene-runtime.js:NeyviaScene.persist"],"claim":"A local Babylon NullEngine journey creates and edits real mesh geometry, preserves the edit across scene save/reopen, refuses an unsupported primitive without changing the saved scene, exports a GLB that passes Khronos validation, diagnoses a broken glTF reference, and refuses paths outside the selected workspace.","id":"gamedev.export-validation-journey","impact":["Game Dev project export validation and engine import boundary"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:keepSelection -> checkedProofsEModel"],"claim":"Native selection never changes implicitly; browser reload affinity follows only one same-project/context replacement","id":"gamedev.keepSelection","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:tabForStage -> checkedProofsEModel"],"claim":"Explicit known tabs win, then launcher app aliases, then embedded Browser 3D","id":"gamedev.tabForStage","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:visibleFields -> checkedProofsEModel"],"claim":"Conditional controls show exactly fields whose predicates hold","id":"gamedev.visibleFields","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:initialValues -> checkedProofsEModel"],"claim":"Form defaults resolve duplicate keys according to their condition","id":"gamedev.initialValues","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:buildArgs -> checkedProofsEModel"],"claim":"Visible fields become exact bridge args; vectors/numbers are finite, JSON text must parse as an object and wildcard fields are flattened","id":"gamedev.buildArgs","impact":["gamedev frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:actionFields -> checkedProofsEModel"],"claim":"Godot edit/interact and Unity test forms retain their typed bridge fields/defaults; other actions return valid field arrays","id":"gamedev.actionFields","impact":["Game Dev typed action forms and engine bridge args"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxGameDevModel.js:sessionLabel","web/src/neyvia/next/nxGameDevModel.js:keepSelection -> checkedProofsEModel","scripts/uifix2_contracts.py:c4_gamedev_names_and_selection","scripts/p22_release_models.mjs"],"claim":"Sessions are named in words (Browser 3D editor, Editor), never with raw environment ids or a literal null; a reloaded browser-webgl or browser-null scene stays selected","id":"gamedev.sessionLabel","impact":["Game Dev sessions list and session card"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_gamedev.report_state","grant_agent.ui_command_bus.UICommandBus.put","grant_agent.ui_command_bus.UICommandBus.get","grant_agent.proofs_surface_games_extra.screen_state_persists_and_refuses_invalid_tab"],"claim":"Game Dev screen selection persists the exact tab, project and UI client through the backend state bus; an unknown tab is refused and leaves the last valid selection unchanged.","id":"p22.gamedev.screen-state-persistence","impact":["Game Dev selected editor/project screen state and invalid-tab refusal"],"phase":"post"}
