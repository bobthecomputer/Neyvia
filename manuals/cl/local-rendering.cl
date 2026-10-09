CL 1
L local-rendering v1 -- Authored executable manual
-- @manual {"chapters":{"mounted":{"title":"Current mounted shell"}},"clVersion":"1.1","id":"local-rendering","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"neyvia.folder.open":"t1","neyvia.notes.open":"t1","neyvia.notify":"t2","neyvia.onboarding.open":"t3","neyvia.view.arrange":"t4","neyvia.view.float":"t5","neyvia.view.scene":"t6","neyvia.view.state":"t7","neyvia.voice.command":"t8"},"tool_metadata":{"neyvia.folder.open":{"mutability_class":"write"},"neyvia.notes.open":{"mutability_class":"write"},"neyvia.notify":{"mutability_class":"write"},"neyvia.onboarding.open":{"mutability_class":"write"},"neyvia.view.arrange":{"mutability_class":"write"},"neyvia.view.float":{"mutability_class":"write"},"neyvia.view.scene":{"mutability_class":"write"},"neyvia.view.state":{"mutability_class":"read"},"neyvia.voice.command":{"mutability_class":"write"}}}
T t1 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"path\"],\"allOf\":[{\"properties\":{\"path\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t2{message?:str msg?:str level?:json:"{\"type\":\"string\",\"enum\":[\"info\",\"success\",\"warning\",\"error\"]}" ..}
T t3{step?:json:"{\"type\":\"string\",\"enum\":[\"welcome\",\"runtimes\",\"interests\",\"tour\"]}" ..}
T t4{order?:[json:"{\"type\":\"string\",\"enum\":[\"sidebar\",\"main\",\"panel\",\"canopy\"]}"] dock?:json:"{\"type\":\"string\",\"enum\":[\"left\",\"right\"]}" canopy?:json:"{\"type\":\"string\",\"enum\":[\"auto\",\"on\",\"off\"]}" sidebarHidden?:bool widgets?:[{id:json:"{\"type\":\"string\",\"enum\":[\"continue\",\"needs\",\"running\",\"nightshift\",\"projects\",\"usage\"]}" size?:json:"{\"type\":\"string\",\"enum\":[\"s\",\"m\",\"l\"]}" ..}] ..}
T t5 json:"{\"type\":\"object\",\"properties\":{\"id\":{\"type\":\"string\"},\"floating\":{\"type\":\"boolean\"}},\"required\":[\"id\"],\"allOf\":[{\"properties\":{\"id\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t6{name?:str save?:str ..}
T t7{..}
T t8 json:"{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\",\"maxLength\":500},\"language\":{\"type\":\"string\"},\"context\":{\"type\":\"object\"},\"dryRun\":{\"type\":\"boolean\"},\"final\":{\"type\":\"boolean\"},\"requestId\":{\"type\":\"string\"}},\"required\":[\"text\"],\"allOf\":[{\"properties\":{\"text\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t9 json:"{\"type\":\"object\"}"
T t10{state:json:"{\"type\":\"object\"}" ..}
T t11{path:str ..}
T t12{message:str level:json:"{\"type\":\"string\",\"enum\":[\"info\",\"success\",\"warning\",\"error\"]}" ..}
T t13{step:json:"{\"type\":\"string\",\"enum\":[\"welcome\",\"runtimes\",\"interests\",\"tour\"]}" ..}
T t14{order:[json:"{\"type\":\"string\",\"enum\":[\"sidebar\",\"main\",\"panel\",\"canopy\"]}"] dock:json:"{\"type\":\"string\",\"enum\":[\"left\",\"right\"]}" sidebarHidden:bool ..}
T t15{id:str floating:bool ..}
T t16{name:str ..}
T t17{text:str#..500 requestId:str ..}
T t18{save:str ..}
L local-rendering.mounted v1 -- Current mounted shell
-- @record {"chapter":"mounted","data":{"args":{},"inputs":{"$cl_type":"t9"},"shape":{"$cl_type":"t9"},"tool":"neyvia.view.state"},"key":"shell","section":"state"}
S local-rendering.shell:json:"{\"type\":\"object\"}"=neyvia.view.state()
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.folder.open","tool":"neyvia.folder.open"},"key":"folder-open","section":"actions"}
A neyvia.folder.open(path:str) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-folder-open "No authored observer check is bound to neyvia.folder.open" -> ask operator blocks:neyvia.folder.open
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notes.open","tool":"neyvia.notes.open"},"key":"notes-open","section":"actions"}
A neyvia.notes.open(path:str) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-notes-open "No authored observer check is bound to neyvia.notes.open" -> ask operator blocks:neyvia.notes.open
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notify","tool":"neyvia.notify"},"key":"notify","section":"actions"}
A neyvia.notify(message?:str msg?:str level?:json:"{\"type\":\"string\",\"enum\":[\"info\",\"success\",\"warning\",\"error\"]}") -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-notify "No authored observer check is bound to neyvia.notify" -> ask operator blocks:neyvia.notify
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.onboarding.open","tool":"neyvia.onboarding.open"},"key":"onboarding-open","section":"actions"}
A neyvia.onboarding.open(step?:json:"{\"type\":\"string\",\"enum\":[\"welcome\",\"runtimes\",\"interests\",\"tour\"]}") -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-onboarding-open "No authored observer check is bound to neyvia.onboarding.open" -> ask operator blocks:neyvia.onboarding.open
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.view.arrange","tool":"neyvia.view.arrange"},"key":"view-arrange","section":"actions"}
A neyvia.view.arrange(order?:[json:"{\"type\":\"string\",\"enum\":[\"sidebar\",\"main\",\"panel\",\"canopy\"]}"] dock?:json:"{\"type\":\"string\",\"enum\":[\"left\",\"right\"]}" canopy?:json:"{\"type\":\"string\",\"enum\":[\"auto\",\"on\",\"off\"]}" sidebarHidden?:bool widgets?:[{id:json:"{\"type\":\"string\",\"enum\":[\"continue\",\"needs\",\"running\",\"nightshift\",\"projects\",\"usage\"]}" size?:json:"{\"type\":\"string\",\"enum\":[\"s\",\"m\",\"l\"]}" ..}]) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-arrange "No authored observer check is bound to neyvia.view.arrange" -> ask operator blocks:neyvia.view.arrange
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.view.float","tool":"neyvia.view.float"},"key":"view-float","section":"actions"}
A neyvia.view.float(id:str floating?:bool) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-float "No authored observer check is bound to neyvia.view.float" -> ask operator blocks:neyvia.view.float
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.view.scene","tool":"neyvia.view.scene"},"key":"view-scene","section":"actions"}
A neyvia.view.scene(name?:str save?:str) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-scene "No authored observer check is bound to neyvia.view.scene" -> ask operator blocks:neyvia.view.scene
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.view.state","tool":"neyvia.view.state"},"key":"view-state","section":"actions"}
A neyvia.view.state() -> {state:json:"{\"type\":\"object\"}" ..} -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-view-state "No authored observer check is bound to neyvia.view.state" -> ask operator blocks:neyvia.view.state
-- @record {"chapter":"mounted","data":{"effect":"Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes","pre":"The current mounted owner shell or an explicit note in its selected folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.voice.command","tool":"neyvia.voice.command"},"key":"voice-command","section":"actions"}
A neyvia.voice.command(text:str#..500 language?:str context?:json:"{\"type\":\"object\"}" dryRun?:bool final?:bool requestId?:str) -> json:"{\"type\":\"object\"}" ! -- Fresh real mounted DOM, exact delivered event, runtime and requested state; notes conserve body bytes
F verify-voice-command "No authored observer check is bound to neyvia.voice.command" -> ask operator blocks:neyvia.voice.command
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t11"},"steps":[{"action":"folder-open","args":{"path":{"$input":"path"}},"save":"rendered"}]},"key":"folder-open","section":"procedures"}
P folder-open(path:str):rendered=neyvia.folder.open(path:path) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P folder-open -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t11"},"steps":[{"action":"notes-open","args":{"path":{"$input":"path"}},"save":"rendered"}]},"key":"notes-open","section":"procedures"}
P notes-open(path:str):rendered=neyvia.notes.open(path:path) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P notes-open -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t12"},"steps":[{"action":"notify","args":{"level":{"$input":"level"},"message":{"$input":"message"}},"save":"rendered"}]},"key":"notify","section":"procedures"}
P notify(message:str level:json:"{\"type\":\"string\",\"enum\":[\"info\",\"success\",\"warning\",\"error\"]}"):rendered=neyvia.notify(level:level message:message) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P notify -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t13"},"steps":[{"action":"onboarding-open","args":{"step":{"$input":"step"}},"save":"rendered"}]},"key":"onboarding-open","section":"procedures"}
P onboarding-open(step:json:"{\"type\":\"string\",\"enum\":[\"welcome\",\"runtimes\",\"interests\",\"tour\"]}"):rendered=neyvia.onboarding.open(step:step) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P onboarding-open -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t14"},"steps":[{"action":"view-arrange","args":{"dock":{"$input":"dock"},"order":{"$input":"order"},"sidebarHidden":{"$input":"sidebarHidden"}},"save":"rendered"}]},"key":"view-arrange","section":"procedures"}
P view-arrange(order:[json:"{\"type\":\"string\",\"enum\":[\"sidebar\",\"main\",\"panel\",\"canopy\"]}"] dock:json:"{\"type\":\"string\",\"enum\":[\"left\",\"right\"]}" sidebarHidden:bool):rendered=neyvia.view.arrange(dock:dock order:order sidebarHidden:sidebarHidden) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-arrange -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t15"},"steps":[{"action":"view-float","args":{"floating":{"$input":"floating"},"id":{"$input":"id"}},"save":"rendered"}]},"key":"view-float","section":"procedures"}
P view-float(id:str floating:bool):rendered=neyvia.view.float(floating:floating id:id) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-float -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t16"},"steps":[{"action":"view-scene","args":{"name":{"$input":"name"}},"save":"rendered"}]},"key":"view-scene","section":"procedures"}
P view-scene(name:str):rendered=neyvia.view.scene(name:name) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-scene -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t7"},"steps":[{"action":"view-state","args":{},"save":"rendered"}]},"key":"view-state","section":"procedures"}
P view-state():rendered=neyvia.view.state() -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P view-state -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion","inputs":{"$cl_type":"t17"},"steps":[{"action":"voice-command","args":{"requestId":{"$input":"requestId"},"text":{"$input":"text"}},"save":"rendered"}]},"key":"voice-command","section":"procedures"}
P voice-command(text:str#..500 requestId:str):rendered=neyvia.voice.command(requestId:requestId text:text) -- Observe or enact the requested real mounted shell effect; queued ACKs never satisfy completion
V P voice-command -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"goal":"Save the exact current observed layout, density and theme","inputs":{"$cl_type":"t18"},"steps":[{"action":"view-scene","args":{"save":{"$input":"save"}},"save":"rendered"}]},"key":"view-scene-save","section":"procedures"}
P view-scene-save(save:str):rendered=neyvia.view.scene(save:save) -- Save the exact current observed layout, density and theme
V P view-scene-save -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"mounted","data":{"failure":"The command was queued but the app never mounted","recovery":"Read view.state; require a fresh owner runtime, actual visible DOM and subject matching. Close/unmount or stale heartbeat invalidates done."},"key":"0","section":"pitfalls"}
X The command was queued but the app never mounted -> Read view.state; require a fresh owner runtime, actual visible DOM and subject matching. Close/unmount or stale heartbeat invalidates done.
-- @record {"chapter":"mounted","data":"Spoken commands beyond locally witnessed Notes opening and returning to chat need their own typed mounted effects.","key":"0","section":"frontier"}
F Spoken commands beyond locally witnessed Notes opening and returning to chat need their own typed mounted effects.
-- @record {"chapter":"mounted","data":"App SDK preview and verification need a running owned app and source-bound mounted frame.","key":"1","section":"frontier"}
F App SDK preview and verification need a running owned app and source-bound mounted frame.
-- @record {"chapter":"mounted","data":"view.state reads renderer:shell from the same authenticated app-state route; it never claims a UI effect from acknowledgement alone.","key":"0","section":"guidance"}
M local-rendering "view.state reads renderer:shell from the same authenticated app-state route; it never claims a UI effect from acknowledgement alone." src:"authored manual" state:verified
-- @record {"chapter":"mounted","data":"PDF uses real MuPDF RGBA when Canvas2D transforms are absent, retaining PDF.js text/search; observed source and entire pixel hashes are required for CL completion.","key":"1","section":"guidance"}
M local-rendering "PDF uses real MuPDF RGBA when Canvas2D transforms are absent, retaining PDF.js text/search; observed source and entire pixel hashes are required for CL completion." src:"authored manual" state:verified
