<!-- Generated from manuals/cl/modules.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# modules

## overview
CL 1
L modules v1 -- Reusable repository modules, public APIs and optional mods
T t1 json:"{\"type\":\"object\"}"
S modules.catalog:t1=neyvia.modules.list()
S modules.module:t1=neyvia.modules.get(id:id)
A neyvia.modules.list(query?:str offset?:0.. limit?:1..100) -> t1 -- Read and search Neyvia's generated module map, with saved enabled state.
F verify-modules-list "No authored observer check is bound to neyvia.modules.list" -> ask operator blocks:neyvia.modules.list
A neyvia.modules.get(id:str) -> t1 -- Read a module's source ownership, manuals, actions, dependencies and contracts.
F verify-modules-get "No authored observer check is bound to neyvia.modules.get" -> ask operator blocks:neyvia.modules.get
A neyvia.modules.source(id:str path:str) -> t1 -- Read an exact owned module source file; never opens an unrelated workspace path.
F verify-modules-source "No authored observer check is bound to neyvia.modules.source" -> ask operator blocks:neyvia.modules.source
A neyvia.modules.validate() -> t1 -- Check every scoped file is owned, the map is current and manual actions exist.
C neyvia.modules.validate map-current:neyvia.modules.validate() .ok == true
C neyvia.modules.validate private-sources-closed:neyvia.modules.validate() .publicSources == {privateExcluded:true privateReadRefused:true}
A neyvia.marketplace.list() -> t1 -- Read installed developer-source apps and mods with manuals, contracts and saved lifecycle state.
F verify-marketplace-list "No authored observer check is bound to neyvia.marketplace.list" -> ask operator blocks:neyvia.marketplace.list
A neyvia.marketplace.get(id:str) -> t1 -- Read one installed source app or mod's current immutable version and lifecycle state.
F verify-marketplace-get "No authored observer check is bound to neyvia.marketplace.get" -> ask operator blocks:neyvia.marketplace.get
A neyvia.marketplace.install(source:str ref?:str) -> t1 ! -- Install a trusted local folder or GitHub git URL into an immutable private snapshot; no dependency installs.
C neyvia.marketplace.install installed-off:neyvia.marketplace.get(id:id) .item.state == "disabled"
A neyvia.marketplace.set(id:str enabled:bool) -> t1 ! -- Enable or disable an installed source app or mod, protecting active dependencies.
C neyvia.marketplace.set enabled-state:neyvia.modules.get(id:id) .module.enabled == enabled
C neyvia.marketplace.set enable-source:neyvia.marketplace.get(id:id) .item.state == "active"
C neyvia.marketplace.set disable-source:neyvia.marketplace.get(id:id) .item.state == "disabled"
A neyvia.marketplace.update(id:str) -> t1 ! -- Snapshot the installed item's original folder or git source; preserve prior versions and enabled state.
F verify-marketplace-update "No authored observer check is bound to neyvia.marketplace.update" -> ask operator blocks:neyvia.marketplace.update
A neyvia.marketplace.read(id:str) -> t1 -- Read an installed item's executable manual and declared contracts without running its code.
F verify-marketplace-read "No authored observer check is bound to neyvia.marketplace.read" -> ask operator blocks:neyvia.marketplace.read
A neyvia.marketplace.remove(id:str) -> t1 ! -- Remove a disabled source app or mod that nothing depends on; its snapshots move aside, recoverable.
F verify-marketplace-remove "No authored observer check is bound to neyvia.marketplace.remove" -> ask operator blocks:neyvia.marketplace.remove
C neyvia.modules.validate map-current:neyvia.modules.validate() .ok == true
C neyvia.modules.get enabled-state:neyvia.modules.get(id:id) .module.enabled == enabled
C neyvia.marketplace.get enable-source:neyvia.marketplace.get(id:id) .item.state == "active"
C neyvia.marketplace.get disable-source:neyvia.marketplace.get(id:id) .item.state == "disabled"
C neyvia.marketplace.get installed-off:neyvia.marketplace.get(id:id) .item.state == "disabled"
C neyvia.modules.validate private-sources-closed:neyvia.modules.validate() .publicSources == {privateExcluded:true privateReadRefused:true}
P verify-map():map=neyvia.modules.validate() C map-current; public=neyvia.modules.validate() C private-sources-closed -- Every scoped source file has an owner, every action exists and generated data is current
V P verify-map -> script why:"typed manual runner; stops at every judgement"
P set-optional(id:str enabled:bool):changed=neyvia.marketplace.set(enabled:enabled id:id) C enabled-state -- Change optional module availability and observe the persisted result
V P set-optional -> script why:"typed manual runner; stops at every judgement"
P enable-source(id:str):changed=neyvia.marketplace.set(enabled:true id:id) C enable-source -- Persist and observe source item state active
V P enable-source -> script why:"typed manual runner; stops at every judgement"
P disable-source(id:str):changed=neyvia.marketplace.set(enabled:false id:id) C disable-source -- Persist and observe source item state disabled
V P disable-source -> script why:"typed manual runner; stops at every judgement"
P install-off(source:str id:str):installed=neyvia.marketplace.install(source:source) C installed-off -- A new source app or mod installs turned off; the owner turns it on after reviewing it
V P install-off -> script why:"typed manual runner; stops at every judgement"
X Module map drifted or manual names a missing action -> Fix ownership/action registration; compile CL, regenerate the module map and rerun modules.verify-map().
X Optional module is disabled or required by an enabled dependant -> Enable required dependencies first; disable dependants before their dependency. Core switches are refused.
F Trusted repository-local mods only; no downloading or executing untrusted packages. Changing a mod action schema requires restarting the owned backend to rebuild its tool catalog.
F Source inspection is read-only; edit the named file in your editor. External connector runtime readiness is described by game-dev.cl, not inferred from registry presence.
M modules "MODULES.md indexes source-derived modules. modules/<id>/README.md lists each purpose, public API, files, CL manual, contracts and dependencies." src:"authored manual" state:verified
M modules "Core modules stay enabled. Source apps and mods use one workspace-local marketplace lifecycle; every mod action and hosted app SDK call uses its saved gate." src:"authored manual" state:verified
M modules "Run modules.verify-map() after source changes. Rebuild config/neyvia.modules.json with system Python scripts/generate_module_map.py; review before commit." src:"authored manual" state:verified
M modules "The registry maps existing implementation units; a generated purpose or import dependency is a static description, not a claim of independently replaceable ABI." src:"authored manual" state:verified
M modules "Read neyvia chapter modding-neyvia and docs/BUILDING_APPS_AND_MODS.md. Reuse neyvia-sdk for sign-in/providers, memory, LAYA verification, CL and app hosting rather than copying architecture." src:"authored manual" state:verified
M modules "Marketplace > Apps & mods is the store over these actions: cards with state, a details view (plain actions, what it asks for, promises, versions, source, manual), an enable switch, Update, Remove with an in-place confirm, and Add from source. Its rendered proof is the install, enable, open, disable and remove journey that scripts/mod_render.py drives through Obscura on the owned backend." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.contract_diff.changed_lines","grant_agent.contract_diff._line_inventories","grant_agent.contract_coverage.classify","grant_agent.contract_coverage.model","grant_agent.contract_measurements.admission","grant_agent.proofs_path_policy_outcomes.path_policy_classification"],"claim":"A real Git diff leaves deleted paths exempt, requires file-level evidence for surviving files with removed lines and binary changes, preserves changed-line locations for Unicode and spaced paths across bounded large pathspec batches, and classifies generated output, third-party trees and CI workflow configuration by policy.","id":"p22.path-policy-outcomes","impact":["Path policy and measured changed-line admission"],"phase":"post"}
-- @proof {"checkedAt":["src/neyvia_sdk/client.py","grant_agent.proofs_python_sdk_journey.self_check"],"claim":"The Python SDK maps an HTTP 400 service refusal to NeyviaError with the original status, code, message, and request command.","id":"p22.python-sdk-http-boundary","impact":["Python SDK HTTP 400 refusal mapping"],"phase":"post"}
