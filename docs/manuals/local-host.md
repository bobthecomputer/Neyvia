<!-- Generated from manuals/cl/local-host.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-host

## host
CL 1
L local-host v1 -- Owned process and plugin effects
T t1 json:"{\"type\":\"object\"}"
T t2{path:str sha256:str ~"^[a-f0-9]{64}$"}
T t3 [str]
A codex.plugins.call(server:str tool:str arguments?:t1 effect?:t2) -> t1 ! -- Fresh exact kernel process and owner state or independently observed requested file bytes
F verify-codex-plugins-call "No authored observer check is bound to codex.plugins.call" -> ask operator blocks:codex.plugins.call
A host.inspect_preview(sessionId:str url:str) -> t1 ! -- Fresh exact kernel process and owner state or independently observed requested file bytes
F verify-host-inspect_preview "No authored observer check is bound to host.inspect_preview" -> ask operator blocks:host.inspect_preview
A host.launch(executable:str arguments?:t3 timeoutSeconds?:1..86400) -> t1 ! -- Fresh exact kernel process and owner state or independently observed requested file bytes
F verify-host-launch "No authored observer check is bound to host.launch" -> ask operator blocks:host.launch
A host.launch_file(path:str arguments?:t3 timeoutSeconds?:1..86400) -> t1 ! -- Fresh exact kernel process and owner state or independently observed requested file bytes
F verify-host-launch_file "No authored observer check is bound to host.launch_file" -> ask operator blocks:host.launch_file
A host.stop(sessionId:str expectedRevision?:0..) -> t1 ! -- Fresh exact kernel process and owner state or independently observed requested file bytes
F verify-host-stop "No authored observer check is bound to host.stop" -> ask operator blocks:host.stop
P codex-plugins-call(server:str tool:str arguments:t1 effect:t2):effect=codex.plugins.call(arguments:arguments effect:effect server:server tool:tool) -- Fresh exact kernel process and owner state or independently observed requested file bytes
V P codex-plugins-call -> script why:"typed manual runner; stops at every judgement"
P host-inspect_preview(sessionId:str url:str):effect=host.inspect_preview(sessionId:sessionId url:url) -- Fresh exact kernel process and owner state or independently observed requested file bytes
V P host-inspect_preview -> script why:"typed manual runner; stops at every judgement"
P host-launch(executable:str arguments:t3 timeoutSeconds:1..86400):effect=host.launch(arguments:arguments executable:executable timeoutSeconds:timeoutSeconds) -- Fresh exact kernel process and owner state or independently observed requested file bytes
V P host-launch -> script why:"typed manual runner; stops at every judgement"
P host-launch_file(path:str arguments:t3 timeoutSeconds:1..86400):effect=host.launch_file(arguments:arguments path:path timeoutSeconds:timeoutSeconds) -- Fresh exact kernel process and owner state or independently observed requested file bytes
V P host-launch_file -> script why:"typed manual runner; stops at every judgement"
P host-stop(sessionId:str expectedRevision:0..):effect=host.stop(expectedRevision:expectedRevision sessionId:sessionId) -- Fresh exact kernel process and owner state or independently observed requested file bytes
V P host-stop -> script why:"typed manual runner; stops at every judgement"
F A responding preview URL does not establish which process owns its socket.
F Plugin effects are limited to the explicitly declared guarded file byte postcondition; other plugin effects stay unproven.
M local-host "Launch only approved headless programs for background journeys." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.proofs_local_host_journey.self_check","grant_agent.creative_tools.CreativeToolRuntime.call","grant_agent.installed_programs.InstalledPrograms.prepare_file","grant_agent.installed_programs.InstalledPrograms.launch_file","grant_agent.installed_programs.InstalledPrograms.launch","grant_agent.installed_programs.InstalledPrograms._work","grant_agent.installed_programs.InstalledPrograms.status","grant_agent.cl.fixcl4_host_effects.snapshot_for","grant_agent.cl.fixcl4_host_effects.checks_for","grant_agent.cl.fixcl4_host_effects._verify","grant_agent.cl.fixcl4_host_effects.process_identity"],"claim":"A scoped host.launch_file journey runs an existing script through Neyvia's local host owner, freshly observes the completed session and exact nonce-bearing output, and refuses a source path outside the selected workspace without adding a session.","id":"p22.local-host.managed-process-journey","impact":["local-host managed process launch","host.launch_file","workspace path boundary"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.proofs_installed_preflight_journey.self_check","grant_agent.proofs_installed_preflight_journey._journey","grant_agent.installed_programs.InstalledPrograms.discover","grant_agent.installed_programs.InstalledPrograms.prepare_file","grant_agent.runtimes.runtime_adapter_map"],"claim":"Installed program discovery identifies the current Python executable and resolves an owned scratch script to it without starting the script; an outside-root path is refused, dependency readiness remains unverified, and no delegated provider route or worker process is invented.","id":"runtime.program.local-python-preflight","impact":["local program availability and command resolution","managed workspace root refusal","truthful readiness without provider execution"],"phase":"invariant"}
