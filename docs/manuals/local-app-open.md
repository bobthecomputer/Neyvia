<!-- Generated from manuals/cl/local-app-open.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-app-open

## apps
CL 1
L local-app-open v1 -- Acknowledged text opening
T t1 json:"{\"type\":\"object\"}"
A neyvia.app.open(app:str target?:str) -> t1 -- Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime
F verify-neyvia-app-open "No authored observer check is bound to neyvia.app.open" -> ask operator blocks:neyvia.app.open
A neyvia.artifact.open(id:str) -> t1 -- Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime
F verify-neyvia-artifact-open "No authored observer check is bound to neyvia.artifact.open" -> ask operator blocks:neyvia.artifact.open
P open-neyvia-app-open(app:str target:str):opened=neyvia.app.open(app:app target:target) -- Show the exact file or text publication in the owned Neyvia pane
V P open-neyvia-app-open -> script why:"typed manual runner; stops at every judgement"
P open-neyvia-artifact-open(id:str):opened=neyvia.artifact.open(id:id) -- Show the exact file or text publication in the owned Neyvia pane
V P open-neyvia-artifact-open -> script why:"typed manual runner; stops at every judgement"
X A queued event is mistaken for content displayed on screen -> Wait for the real mounted pane observation; absent renderer, stale heartbeat, hidden/replaced runtime or byte drift refuses completion.
F app.open admits only aliases resolving to file panes with an existing displayable text target.
F artifact.open admits only published plain text using the artifact preview; markdown and binary previews remain frontier.
F notes.open, onboarding.open and app_sdk.preview currently route to standalone apps/overlays without pane mounted-content acknowledgements.
M local-app-open "Use Neyvia own renderer. Never substitute queue delivery or fabricate a renderer report." src:"authored manual" state:verified
M local-app-open "A fresh completion conserves publication metadata, exact text bytes, pane identity and runtime identity." src:"authored manual" state:verified
