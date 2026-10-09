CL 1
L hello-module v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"A real optional personal greeting mod"}},"clVersion":"1.1","id":"hello-module","kind":"environment","schema":"neyvia.manual.v1","schemas":{"neyvia.mod.hello.greet":"t1"},"tool_metadata":{"neyvia.mod.hello.greet":{"mutability_class":"read"}}}
T t1{name:str#1..80 ..}
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"
L hello-module.overview v1 -- A real optional personal greeting mod
-- @record {"chapter":"overview","data":{"effect":"Read a personal greeting for the supplied name.","pre":"Selected workspace; module is mapped and any optional dependencies are enabled","returns":{"$cl_type":"t2"},"reversible":true,"schema":"neyvia.mod.hello.greet","tool":"neyvia.mod.hello.greet"},"key":"mod.hello.greet","section":"actions"}
A neyvia.mod.hello.greet(name:str#1..80) -> json:"{\"type\":\"object\"}" -- Read a personal greeting for the supplied name.
C neyvia.mod.hello.greet greeting:neyvia.mod.hello.greet(name:"Paul") .greeting == "Hello, Paul!"
-- @record {"chapter":"overview","data":{"args":{"name":"Paul"},"expect":{"op":"eq","path":"greeting","value":"Hello, Paul!"},"tool":"neyvia.mod.hello.greet"},"key":"greeting","section":"checks"}
C neyvia.mod.hello.greet greeting:neyvia.mod.hello.greet(name:"Paul") .greeting == "Hello, Paul!"
-- @record {"chapter":"overview","data":{"goal":"Call the installed optional mod and verify the exact personal greeting","inputs":{"$cl_type":"t3"},"steps":[{"action":"mod.hello.greet","args":{"name":"Paul"},"check":"greeting","save":"greeting"}]},"key":"verify-greeting","section":"procedures"}
P verify-greeting():greeting=neyvia.mod.hello.greet(name:"Paul") C greeting -- Call the installed optional mod and verify the exact personal greeting
V P verify-greeting -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":"This example is a deterministic local action, not an AI model call.","key":"0","section":"frontier"}
F This example is a deterministic local action, not an AI model call.
-- @record {"chapter":"overview","data":"The example lives in apps/hello-module. Its action is registered automatically at backend startup; the existing marketplace manages apps and mods.","key":"0","section":"guidance"}
M hello-module "The example lives in apps/hello-module. Its action is registered automatically at backend startup; the existing marketplace manages apps and mods." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Run hello-module.verify-greeting(); call mod.hello.greet(name='your name') to build a personal greeting.","key":"1","section":"guidance"}
M hello-module "Run hello-module.verify-greeting(); call mod.hello.greet(name='your name') to build a personal greeting." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Install apps/hello-module through marketplace.install, then enable it with modules.set-optional(id='hello-module', enabled=true). Disable it to prove subsequent greeting calls fail.","key":"2","section":"guidance"}
M hello-module "Install apps/hello-module through marketplace.install, then enable it with modules.set-optional(id='hello-module', enabled=true). Disable it to prove subsequent greeting calls fail." src:"authored manual" state:verified
