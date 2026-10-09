<!-- Generated from manuals/cl/local-evolver.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-evolver

## evolution
CL 1
L local-evolver v1 -- Frozen local manual compression
T t1 json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}"
T t2 json:"{\"type\":\"object\"}"
A neyvia.evolver.run(domain:t1 requestId:str#1.. maxTrials?:1..2) -> t2 ! -- Run real manual_json_local_v1 parse, compiler, roundtrip and token measurements on matched seeded cases
F verify-run "No authored observer check is bound to neyvia.evolver.run" -> ask operator blocks:neyvia.evolver.run
P verify-local-manual-evolution(domain:t1 requestId:str#1..):saved=neyvia.evolver.run(domain:domain maxTrials:1 requestId:requestId) -- Finish a real frozen paired lossless compression trial, reconfirm on two fresh heldout panels, and update the local Pareto front
V P verify-local-manual-evolution -> script why:"typed manual runner; stops at every judgement"
X A queued job or synthetic score is called an evaluated improvement -> Wait for actual parse/compiled artifacts; compare current bytes, paired seeds, frozen panels and counted engine trials.
X Compression removes instructions or protected checks -> Retain the rejected candidate; exact semantic and compiler roundtrip gates prevent promotion.
F manual_json_local_v1 measures lossless JSON compression, not model task accuracy.
F Other domain routes retain their named GPT-6 Luna transport and need separate matched provider evaluations.
M local-evolver "No models or downloads are used in this named local domain." src:"authored manual" state:verified
M local-evolver "Reuse requestId after interruptions; frozen judges and manual inputs cannot be changed inside an established domain." src:"authored manual" state:verified
M local-evolver "Local-only blocks all managed children, including this offline Rust engine; preserve that policy." src:"authored manual" state:verified
