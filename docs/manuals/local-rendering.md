<!-- Generated from manuals/cl/local-rendering.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-rendering

## mounted
CL 1
L local-rendering v1 -- Current mounted shell
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"info\",\"success\",\"warning\",\"error\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"welcome\",\"runtimes\",\"interests\",\"tour\"]}"
T t4 [json:"{\"type\":\"string\",\"enum\":[\"sidebar\",\"main\",\"panel\",\"canopy\"]}"]
T t5 json:"{\"type\":\"string\",\"enum\":[\"left\",\"right\"]}"
T t6 json:"{\"type\":\"string\",\"enum\":[\"auto\",\"on\",\"off\"]}"
T t7 [{id:json:"{\"type\":\"string\",\"enum\":[\"continue\",\"needs\",\"running\",\"nightshift\",\"projects\",\"usage\"]}" size?:json:"{\"type\":\"string\",\"enum\":[\"s\",\"m\",\"l\"]}" ..}]
T t8{state:json:"{\"type\":\"object\"}" ..}
S local-rendering.shell:t1=neyvia.view.state()
A neyvia.folder.open(path:str) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-folder-open "No authored observer check is bound to neyvia.folder.open" -> ask operator blocks:neyvia.folder.open
A neyvia.notes.open(path:str) -> t1 ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-notes-open "No authored observer check is bound to neyvia.notes.open" -> ask operator blocks:neyvia.notes.open
A neyvia.notify(message?:str msg?:str level?:t2) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-notify "No authored observer check is bound to neyvia.notify" -> ask operator blocks:neyvia.notify
A neyvia.onboarding.open(step?:t3) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-onboarding-open "No authored observer check is bound to neyvia.onboarding.open" -> ask operator blocks:neyvia.onboarding.open
A neyvia.view.arrange(order?:t4 dock?:t5 canopy?:t6 sidebarHidden?:bool widgets?:t7) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-arrange "No authored observer check is bound to neyvia.view.arrange" -> ask operator blocks:neyvia.view.arrange
A neyvia.view.float(id:str floating?:bool) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-float "No authored observer check is bound to neyvia.view.float" -> ask operator blocks:neyvia.view.float
A neyvia.view.scene(name?:str save?:str) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-scene "No authored observer check is bound to neyvia.view.scene" -> ask operator blocks:neyvia.view.scene
A neyvia.view.state() -> t8 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-state "No authored observer check is bound to neyvia.view.state" -> ask operator blocks:neyvia.view.state
A neyvia.voice.command(text:str#..500 language?:str context?:t1 dryRun?:bool final?:bool requestId?:str) -> t1 -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-voice-command "No authored observer check is bound to neyvia.voice.command" -> ask operator blocks:neyvia.voice.command
P folder-open(path:str):rendered=neyvia.folder.open(path:path) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P folder-open -> script why:"typed manual runner; stops at every judgement"
P notes-open(path:str):rendered=neyvia.notes.open(path:path) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P notes-open -> script why:"typed manual runner; stops at every judgement"
P notify(message:str level:t2):rendered=neyvia.notify(level:level message:message) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P notify -> script why:"typed manual runner; stops at every judgement"
P onboarding-open(step:t3):rendered=neyvia.onboarding.open(step:step) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P onboarding-open -> script why:"typed manual runner; stops at every judgement"
P view-arrange(order:t4 dock:t5 sidebarHidden:bool):rendered=neyvia.view.arrange(dock:dock order:order sidebarHidden:sidebarHidden) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-arrange -> script why:"typed manual runner; stops at every judgement"
P view-float(id:str floating:bool):rendered=neyvia.view.float(floating:floating id:id) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-float -> script why:"typed manual runner; stops at every judgement"
P view-scene(name:str):rendered=neyvia.view.scene(name:name) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-scene -> script why:"typed manual runner; stops at every judgement"
P view-state():rendered=neyvia.view.state() -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-state -> script why:"typed manual runner; stops at every judgement"
P voice-command(text:str#..500 requestId:str):rendered=neyvia.voice.command(requestId:requestId text:text) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P voice-command -> script why:"typed manual runner; stops at every judgement"
P view-scene-save(save:str):rendered=neyvia.view.scene(save:save) -- Save the exact current observed layout, density and theme
V P view-scene-save -> script why:"typed manual runner; stops at every judgement"
X The command was queued but the app never mounted -> Read view.state; require a fresh owner runtime, actual visible DOM and subject matching. Close/unmount or stale heartbeat invalidates done.
F Spoken commands beyond locally witnessed Notes opening and returning to chat need their own typed mounted effects.
F App SDK preview and verification need a running owned app and source-bound mounted frame.
M local-rendering "view.state reads renderer:shell from the same authenticated app-state route; it never claims a UI effect from acknowledgement alone." src:"authored manual" state:verified
M local-rendering "PDF uses real MuPDF RGBA when Canvas2D transforms are absent, retaining PDF.js text/search; observed source and entire pixel hashes are required for CL completion." src:"authored manual" state:verified
