CL 1
L laya-ui-fix v1 -- UI fix actions on the shared Scene core: CSS/token patches and recorded library patches on a web source tree, re-observed by a fresh private render
A scene.improve(domain:str, source:object, budget:object) -> receipt -- source = {tree, state, variant, ports, runs}; keeps a fix only when findings strictly shrink and no guard regresses
A scene.transcribe(domain:str, source:object) -> scene -- build the tree (cached per web/src digest), render the state in admitted headless Obscura, observe DOM + pixel facts
P fix-ui(source, budget): scene.improve("ui", source, budget)
P prove-fixes(): run scripts/core_ui_fix_proof.py -- three P22 bugs at 9589de605 on CORE ports 49114/49115; writes scripts/evidence/CORE-ui-fix.json
P prove-gate(): run scripts/core_gate_seam_proof.py -- P22 request through scripts/laya_glance_gate.py on CORE ports 49116/49117; writes scripts/evidence/CORE-gate-seam.json
C fix.verify bugs: proof.bugs == 3 -- block black PDF page, see-through floating panel and clipped composer chips were all exercised
C fix.verify observed: proof.observedBefore == proof.bugs -- block each bug is found on a fresh render of its pre-fix tree
C fix.verify reverted: proof.wrongReverted == proof.bugs -- block each plausible wrong candidate was applied, judged and reverted
C fix.verify restored: proof.treeRestored == proof.bugs -- block every revert restored the source tree byte-identical (digest)
C fix.verify kept: proof.namedKept == proof.bugs -- block each named fix was kept by the shared core
C fix.verify gone: proof.goneAfter == proof.bugs -- block no finding of the bug remains on the final render
C fix.verify guards: proof.guardRegressions == 0 -- block no kept fix lowered the minimum font size or raised page errors
C fix.verify private: proof.privateRender == true -- block renders use the admitted headless Obscura engine only
C fix.verify training: proof.training == false -- block outcomes are instant episodes; no fitting
C gate.verify contract: proof.answersContract == true -- block the command echoes the commit and returns one row per surface and variant
C gate.verify before: proof.preFixAdmitted == false -- block the pre-fix candidate is not admitted
C gate.verify named: proof.preFixBrokenRows > 0 -- block broken rows name the defect and its fix action
F CSS/token fixes are override rules appended to the stylesheet that already styles the element; LAYA does not refactor CSS.
F Recorded library patches (config/laya_ui_fix_library.json) are selected and verified by LAYA, not authored by it.
F Pixel-only findings (see-through, blank render) are below calibrated 0.95 as glance verdicts; improve still targets them because a fresh render either shows them or not.
F One render per source digest and state: a restored tree re-observes as the same Scene; a build and render take about 2 minutes on this laptop.
