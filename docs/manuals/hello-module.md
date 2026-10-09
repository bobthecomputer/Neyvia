<!-- Generated from manuals/cl/hello-module.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# hello-module

## overview
CL 1
L hello-module v1 -- A real optional personal greeting mod
T t1 json:"{\"type\":\"object\"}"
A neyvia.mod.hello.greet(name:str#1..80) -> t1 -- Read a personal greeting for the supplied name.
C neyvia.mod.hello.greet greeting:neyvia.mod.hello.greet(name:"Paul") .greeting == "Hello, Paul!"
C neyvia.mod.hello.greet greeting:neyvia.mod.hello.greet(name:"Paul") .greeting == "Hello, Paul!"
P verify-greeting():greeting=neyvia.mod.hello.greet(name:"Paul") C greeting -- Call the installed optional mod and verify the exact personal greeting
V P verify-greeting -> script why:"typed manual runner; stops at every judgement"
F This example is a deterministic local action, not an AI model call.
M hello-module "The example lives in apps/hello-module. Its action is registered automatically at backend startup; the existing marketplace manages apps and mods." src:"authored manual" state:verified
M hello-module "Run hello-module.verify-greeting(); call mod.hello.greet(name='your name') to build a personal greeting." src:"authored manual" state:verified
M hello-module "Install apps/hello-module through marketplace.install, then enable it with modules.set-optional(id='hello-module', enabled=true). Disable it to prove subsequent greeting calls fail." src:"authored manual" state:verified
