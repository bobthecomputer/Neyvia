CL 1
L photocraft v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Agent-usable PhotoCraft (ArtCraft/storytold, a Photoshop-style editor in Rust) for video frames: inspect, run engine commands, convert."}},"clVersion":"1.1","id":"photocraft","kind":"environment","schema":"neyvia.manual.v1","schemas":{"neyvia.mod.photocraft.commands":"t1","neyvia.mod.photocraft.convert":"t4","neyvia.mod.photocraft.info":"t2","neyvia.mod.photocraft.run":"t3","neyvia.mod.photocraft.verify":"t5"},"tool_metadata":{"neyvia.mod.photocraft.commands":{"mutability_class":"read"},"neyvia.mod.photocraft.convert":{"mutability_class":"artifact_write"},"neyvia.mod.photocraft.info":{"mutability_class":"read"},"neyvia.mod.photocraft.run":{"mutability_class":"artifact_write"},"neyvia.mod.photocraft.verify":{"mutability_class":"artifact_write"}}}
T t1{filter?:str#..200}
T t2{file:str#..4000}
T t3{file:str#..4000 steps:[{id:str#..200 params?:json:"{\"type\":\"object\"}" ..}]#..500 out:str#..4000}
T t4{input:str#..4000 out:str#..4000}
T t5{}
T t6 json:"{\"type\":\"object\"}"
T t7 json:"{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"
L photocraft.overview v1 -- Agent-usable PhotoCraft (ArtCraft/storytold, a Photoshop-style editor in Rust) for video frames: inspect, run engine commands, convert.
-- @record {"chapter":"overview","data":{"effect":"List PhotoCraft engine commands matching a filter.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":true,"schema":"neyvia.mod.photocraft.commands","tool":"neyvia.mod.photocraft.commands"},"key":"mod.photocraft.commands","section":"actions"}
A neyvia.mod.photocraft.commands(filter?:str#..200) -> json:"{\"type\":\"object\"}" -- List PhotoCraft engine commands matching a filter.
F verify-mod-photocraft-commands "No authored observer check is bound to neyvia.mod.photocraft.commands" -> ask operator blocks:neyvia.mod.photocraft.commands
-- @record {"chapter":"overview","data":{"effect":"Observe an image document (size, mode, layer tree) as a CL Scene.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":true,"schema":"neyvia.mod.photocraft.info","tool":"neyvia.mod.photocraft.info"},"key":"mod.photocraft.info","section":"actions"}
A neyvia.mod.photocraft.info(file:str#..4000) -> json:"{\"type\":\"object\"}" -- Observe an image document (size, mode, layer tree) as a CL Scene.
F verify-mod-photocraft-info "No authored observer check is bound to neyvia.mod.photocraft.info" -> ask operator blocks:neyvia.mod.photocraft.info
-- @record {"chapter":"overview","data":{"effect":"Open an image, run engine commands in order and save the result.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.photocraft.run","tool":"neyvia.mod.photocraft.run"},"key":"mod.photocraft.run","section":"actions"}
A neyvia.mod.photocraft.run(file:str#..4000 steps:[{id:str#..200 params?:json:"{\"type\":\"object\"}" ..}]#..500 out:str#..4000) -> json:"{\"type\":\"object\"}" ! -- Open an image, run engine commands in order and save the result.
F verify-mod-photocraft-run "No authored observer check is bound to neyvia.mod.photocraft.run" -> ask operator blocks:neyvia.mod.photocraft.run
-- @record {"chapter":"overview","data":{"effect":"Convert an image between formats.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.photocraft.convert","tool":"neyvia.mod.photocraft.convert"},"key":"mod.photocraft.convert","section":"actions"}
A neyvia.mod.photocraft.convert(input:str#..4000 out:str#..4000) -> json:"{\"type\":\"object\"}" ! -- Convert an image between formats.
F verify-mod-photocraft-convert "No authored observer check is bound to neyvia.mod.photocraft.convert" -> ask operator blocks:neyvia.mod.photocraft.convert
-- @record {"chapter":"overview","data":{"effect":"Real round trip on a Neyvia capture: inspect, convert, and compare the decoded pixels.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.photocraft.verify","tool":"neyvia.mod.photocraft.verify"},"key":"mod.photocraft.verify","section":"actions"}
A neyvia.mod.photocraft.verify() -> json:"{\"type\":\"object\"}" ! -- Real round trip on a Neyvia capture: inspect, convert, and compare the decoded pixels.
C neyvia.mod.photocraft.verify verified:neyvia.mod.photocraft.verify() .passed == true
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"passed","value":true},"tool":"neyvia.mod.photocraft.verify"},"key":"verified","section":"checks"}
C neyvia.mod.photocraft.verify verified:neyvia.mod.photocraft.verify() .passed == true
-- @record {"chapter":"overview","data":{"goal":"Run the real round trip and check its outcome contracts","inputs":{"$cl_type":"t7"},"steps":[{"action":"mod.photocraft.verify","args":{},"check":"verified","save":"verified"}]},"key":"verify-photocraft","section":"procedures"}
P verify-photocraft():verified=neyvia.mod.photocraft.verify() C verified -- Run the real round trip and check its outcome contracts
V P verify-photocraft -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"failure":"The local tool is missing","recovery":"Build or point the NEYVIA_* path at it; the action refuses rather than downloading anything."},"key":"0","section":"pitfalls"}
X The local tool is missing -> Build or point the NEYVIA_* path at it; the action refuses rather than downloading anything.
-- @record {"chapter":"overview","data":{"failure":"A render exists but is wrong","recovery":"Read the outcome block (duration, frames, black/frozen runs, clipping); never call a render good from its exit code."},"key":"1","section":"pitfalls"}
X A render exists but is wrong -> Read the outcome block (duration, frames, black/frozen runs, clipping); never call a render good from its exit code.
-- @record {"chapter":"overview","data":"Built from source with the local Rust toolchain into D:/NeyviaRuns/video/track-video/target; set NEYVIA_PHOTOCRAFT_CLI to use another build.","key":"0","section":"frontier"}
F Built from source with the local Rust toolchain into D:/NeyviaRuns/video/track-video/target; set NEYVIA_PHOTOCRAFT_CLI to use another build.
-- @record {"chapter":"overview","data":"Adapted, not forked: every action runs the unmodified upstream program. PhotoCraft by the ArtCraft team, MIT OR Apache-2.0, https://github.com/storytold/photocraft.","key":"1","section":"frontier"}
F Adapted, not forked: every action runs the unmodified upstream program. PhotoCraft by the ArtCraft team, MIT OR Apache-2.0, https://github.com/storytold/photocraft.
-- @record {"chapter":"overview","data":"Use PhotoCraft for frame work (grades, crops, exports) before a frame goes into a cut.","key":"0","section":"guidance"}
M photocraft "Use PhotoCraft for frame work (grades, crops, exports) before a frame goes into a cut." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Installs switched off from Marketplace > Apps & mods; read this manual and the declared permissions, then enable it.","key":"1","section":"guidance"}
M photocraft "Installs switched off from Marketplace > Apps & mods; read this manual and the declared permissions, then enable it." src:"authored manual" state:verified
