CL 1
L local-app-open v1 -- Authored executable manual
-- @manual {"chapters":{"apps":{"title":"Acknowledged text opening"}},"clVersion":"1.1","id":"local-app-open","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"neyvia.app.open":"t1","neyvia.artifact.open":"t2"},"tool_metadata":{"neyvia.app.open":{"mutability_class":"none"},"neyvia.artifact.open":{"mutability_class":"none"}}}
T t1 json:"{\"type\":\"object\",\"properties\":{\"app\":{\"type\":\"string\"},\"target\":{\"type\":\"string\"}},\"required\":[\"app\"],\"allOf\":[{\"properties\":{\"app\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t2 json:"{\"type\":\"object\",\"properties\":{\"id\":{\"type\":\"string\"}},\"required\":[\"id\"],\"allOf\":[{\"properties\":{\"id\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t3 json:"{\"type\":\"object\"}"
T t4{app:str target:str ..}
T t5{id:str ..}
L local-app-open.apps v1 -- Acknowledged text opening
-- @record {"chapter":"apps","data":{"effect":"Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime","pre":"A displayable guarded text file; app must resolve to file pane, artifact must have exact available published bytes","returns":{"$cl_type":"t3"},"reversible":true,"schema":"neyvia.app.open","tool":"neyvia.app.open"},"key":"neyvia-app-open","section":"actions"}
A neyvia.app.open(app:str target?:str) -> json:"{\"type\":\"object\"}" -- Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime
F verify-neyvia-app-open "No authored observer check is bound to neyvia.app.open" -> ask operator blocks:neyvia.app.open
-- @record {"chapter":"apps","data":{"effect":"Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime","pre":"A displayable guarded text file; app must resolve to file pane, artifact must have exact available published bytes","returns":{"$cl_type":"t3"},"reversible":true,"schema":"neyvia.artifact.open","tool":"neyvia.artifact.open"},"key":"neyvia-artifact-open","section":"actions"}
A neyvia.artifact.open(id:str) -> json:"{\"type\":\"object\"}" -- Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime
F verify-neyvia-artifact-open "No authored observer check is bound to neyvia.artifact.open" -> ask operator blocks:neyvia.artifact.open
-- @record {"chapter":"apps","data":{"goal":"Show the exact file or text publication in the owned Neyvia pane","inputs":{"$cl_type":"t4"},"steps":[{"action":"neyvia-app-open","args":{"app":{"$input":"app"},"target":{"$input":"target"}},"save":"opened"}]},"key":"open-neyvia-app-open","section":"procedures"}
P open-neyvia-app-open(app:str target:str):opened=neyvia.app.open(app:app target:target) -- Show the exact file or text publication in the owned Neyvia pane
V P open-neyvia-app-open -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"apps","data":{"goal":"Show the exact file or text publication in the owned Neyvia pane","inputs":{"$cl_type":"t5"},"steps":[{"action":"neyvia-artifact-open","args":{"id":{"$input":"id"}},"save":"opened"}]},"key":"open-neyvia-artifact-open","section":"procedures"}
P open-neyvia-artifact-open(id:str):opened=neyvia.artifact.open(id:id) -- Show the exact file or text publication in the owned Neyvia pane
V P open-neyvia-artifact-open -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"apps","data":{"failure":"A queued event is mistaken for content displayed on screen","recovery":"Wait for the real mounted pane observation; absent renderer, stale heartbeat, hidden/replaced runtime or byte drift refuses completion."},"key":"0","section":"pitfalls"}
X A queued event is mistaken for content displayed on screen -> Wait for the real mounted pane observation; absent renderer, stale heartbeat, hidden/replaced runtime or byte drift refuses completion.
-- @record {"chapter":"apps","data":"app.open admits only aliases resolving to file panes with an existing displayable text target.","key":"0","section":"frontier"}
F app.open admits only aliases resolving to file panes with an existing displayable text target.
-- @record {"chapter":"apps","data":"artifact.open admits only published plain text using the artifact preview; markdown and binary previews remain frontier.","key":"1","section":"frontier"}
F artifact.open admits only published plain text using the artifact preview; markdown and binary previews remain frontier.
-- @record {"chapter":"apps","data":"notes.open, onboarding.open and app_sdk.preview currently route to standalone apps/overlays without pane mounted-content acknowledgements.","key":"2","section":"frontier"}
F notes.open, onboarding.open and app_sdk.preview currently route to standalone apps/overlays without pane mounted-content acknowledgements.
-- @record {"chapter":"apps","data":"Use Neyvia own renderer. Never substitute queue delivery or fabricate a renderer report.","key":"0","section":"guidance"}
M local-app-open "Use Neyvia own renderer. Never substitute queue delivery or fabricate a renderer report." src:"authored manual" state:verified
-- @record {"chapter":"apps","data":"A fresh completion conserves publication metadata, exact text bytes, pane identity and runtime identity.","key":"1","section":"guidance"}
M local-app-open "A fresh completion conserves publication metadata, exact text bytes, pane identity and runtime identity." src:"authored manual" state:verified
