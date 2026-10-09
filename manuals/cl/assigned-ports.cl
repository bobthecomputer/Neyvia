CL 1
L assigned-ports v1 -- Proof harnesses accept an explicitly assigned port block and scratch output root; historical owned ports and outputs stay the default
A ports.assign(block:str, owner:str) -> block -- contiguous block a-b of at least two ports; refused when it overlaps another track's registered block (plan 27 section 0, plans/12-board.md); a sub-block of the caller's own block is fine
A ports.pair(index:int) -> pair -- pairs come from the block start: (first, first+1), (first+2, first+3), ...
A scratch.output(relative:str) -> path -- evidence and manual writes go under the scratch root; runtime state under <scratch>/.agent_control on the same drive
P prove-ports(): run scripts/assigned_ports_proof.py -- helper checks plus the real harness, UI-render and glance port gates (no port bound); writes scripts/evidence/PORTS-assigned.json
P use(block, scratch): run <proof script> --port-block 49171-49179 --scratch-root D:/NeyviaRuns/X -- laya3d_contracts, laya3d_kronos, laya3d_engines, core_ui_fix_proof, core_gate_seam_proof, laya_glance_gate, laya_anim
C ports.verify defaults: proof.defaultsUnchanged == true -- block with nothing passed the gates keep their historical owned ports and output locations
C ports.verify accepted: proof.customAccepted == true -- block a non-default free block (49171-49179) is accepted by every gate and hands out pairs from its start
C ports.verify overlap: proof.overlapRefused == true -- block a block overlapping another track (ANIM 49151-49159 for CORE, 49165-49175 straddling VIDEO) is refused
C ports.verify own: proof.ownSubBlockAccepted == true -- block a sub-block of the caller's own registered block is accepted
C ports.verify malformed: proof.malformedRefused == true -- block descending, single-port and non-numeric blocks are refused
C ports.verify outside: proof.outsideRefused == true -- block with a block assigned, ports outside it are refused by the harness, UI render and glance gates
C ports.verify scratch: proof.scratchRedirected == true -- block with a scratch root, evidence and manual writes land under it and runtime state leaves the shared folders
F The registry is a static copy of the plan 27 section 0 and plans/12-board.md blocks as of 7 Oct 2026; a new track block must be added to grant_agent/assigned_ports.REGISTERED.
F NEYVIA_ASSIGNED_PORTS set without an owner accepts only blocks that overlap no registered block; --port-block passes the script's own track as owner.
