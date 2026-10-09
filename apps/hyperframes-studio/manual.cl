CL 1
L hyperframes-studio v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"HyperFrames Studio hosted in Neyvia: open a project's timeline, code and live preview privately"}},"clVersion":"1.1","id":"hyperframes-studio","kind":"environment","schema":"neyvia.manual.v1","schemas":{"neyvia.mod.hyperframes.studio":"t1"},"tool_metadata":{"neyvia.mod.hyperframes.studio":{"mutability_class":"external_action"}}}
T t1{project:str#..4000 action:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"start\",\"stop\",\"status\"]}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3{project:str#..4000 ..}
L hyperframes-studio.overview v1 -- HyperFrames Studio hosted in Neyvia: open a project's timeline, code and live preview privately
-- @record {"chapter":"overview","data":{"effect":"Start, stop or read the Studio server for a project; the app embeds it.","pre":"The hyperframes mod is installed and enabled","returns":{"$cl_type":"t2"},"reversible":true,"schema":"neyvia.mod.hyperframes.studio","tool":"neyvia.mod.hyperframes.studio"},"key":"mod.hyperframes.studio","section":"actions"}
A neyvia.mod.hyperframes.studio(project:str#..4000 action:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"start\",\"stop\",\"status\"]}") -> json:"{\"type\":\"object\"}" ! -- Start, stop or read the Studio server for a project; the app embeds it.
C neyvia.mod.hyperframes.studio studio-status:neyvia.mod.hyperframes.studio(action:"status" project:project) .ok == true
-- @record {"chapter":"overview","data":{"args":{"action":"status","project":{"$input":"project"}},"expect":{"op":"eq","path":"ok","value":true},"tool":"neyvia.mod.hyperframes.studio"},"key":"studio-status","section":"checks"}
C neyvia.mod.hyperframes.studio studio-status:neyvia.mod.hyperframes.studio(action:"status" project:project) .ok == true
-- @record {"chapter":"overview","data":{"goal":"Start the Studio for a project, read its status, stop it","inputs":{"$cl_type":"t3"},"steps":[{"action":"mod.hyperframes.studio","args":{"action":"start","project":{"$input":"project"}},"check":"studio-status","save":"started"},{"action":"mod.hyperframes.studio","args":{"action":"stop","project":{"$input":"project"}},"save":"stopped"}]},"key":"verify-studio","section":"procedures"}
P verify-studio(project:str#..4000):started=neyvia.mod.hyperframes.studio(action:"start" project:project) C studio-status; stopped=neyvia.mod.hyperframes.studio(action:"stop" project:project) -- Start the Studio for a project, read its status, stop it
V P verify-studio -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":"Adapted, not forked: every action runs the unmodified upstream program. HyperFrames Studio by HeyGen, Apache-2.0, https://github.com/heygen-com/hyperframes.","key":"0","section":"frontier"}
F Adapted, not forked: every action runs the unmodified upstream program. HyperFrames Studio by HeyGen, Apache-2.0, https://github.com/heygen-com/hyperframes.
-- @record {"chapter":"overview","data":"The app page asks for a project folder and embeds the Studio from 127.0.0.1:49165; no browser window opens.","key":"0","section":"guidance"}
M hyperframes-studio "The app page asks for a project folder and embeds the Studio from 127.0.0.1:49165; no browser window opens." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Agents edit the same project through the hyperframes mod and see the Studio update.","key":"1","section":"guidance"}
M hyperframes-studio "Agents edit the same project through the hyperframes mod and see the Studio update." src:"authored manual" state:verified
