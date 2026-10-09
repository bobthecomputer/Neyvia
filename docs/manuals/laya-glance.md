<!-- Generated from manuals/cl/laya-glance.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# laya-glance

## scene
CL 1
L laya-glance v1 -- One Scene core: transcribe, predicates, instant examples and guarded improvement
T t1 json:"{\"type\":\"object\"}"
T t2 "corrective"|"personal"
T t3 "clipped-text"|"raw-error"|"encoded-path"|"internal-id"|"overlap"|"unreadable-contrast"
A neyvia.scene.transcribe(domain:str#..16000 source:t1) -> t1 -- Transcribe one domain source through its registered adapter into a shared CL Scene.
F verify-scene-transcribe "No authored observer check is bound to neyvia.scene.transcribe" -> ask operator blocks:neyvia.scene.transcribe
A neyvia.scene.vocabulary(domain:str#..16000) -> t1 -- Read the registered domain predicates and named fix patterns.
F verify-scene-vocabulary "No authored observer check is bound to neyvia.scene.vocabulary" -> ask operator blocks:neyvia.scene.vocabulary
A neyvia.laya.judge(scene:t1 user?:str#..16000) -> t1 ! -- Apply one shared predicate evaluator and instant episodic admission to a Scene.
F verify-laya-judge "No authored observer check is bound to neyvia.laya.judge" -> ask operator blocks:neyvia.laya.judge
A neyvia.scene.improve(domain:str#..16000 source:t1 budget:t1) -> t1 ! -- Apply only explicitly budgeted reversible adapter fixes; trading is human review only.
F verify-scene-improve "No authored observer check is bound to neyvia.scene.improve" -> ask operator blocks:neyvia.scene.improve
A neyvia.scene.episode(scene:t1 label:any reason:str#..16000 source:str#..16000 user?:str#..16000 layer?:t2) -> t1 ! -- Write a labelled Scene episode immediately without training.
F verify-scene-episode "No authored observer check is bound to neyvia.scene.episode" -> ask operator blocks:neyvia.scene.episode
A neyvia.laya.glance_contracts() -> t1 -- Observe real headless DOM/canvas cases for the CL scene predicates.
C neyvia.laya.glance_contracts live-predicates:neyvia.laya.glance_contracts() .passed == true
A neyvia.laya.glance(scene?:t1 handle?:str#..16000 screenshot?:str#..16000 fuzzy?:bool) -> t1 ! -- Apply the CL broken-UI vocabulary to a perception scene or immutable handle. Unknown facts request one model look.
F verify-laya-glance "No authored observer check is bound to neyvia.laya.glance" -> ask operator blocks:neyvia.laya.glance
A neyvia.laya.glance_proof() -> t1 -- Glance the recorded before/after fix captures from pixels alone: black PDF page, see-through panels, clipped composer chips.
C neyvia.laya.glance_proof pixel-before-after:neyvia.laya.glance_proof() .passed == true
A neyvia.laya.glance_lesson(scene:t1 node:str#..16000 predicate:t3 label:"broken"|"fine" reason:str#..16000 source:str#..16000) -> t1 ! -- Teach one node instantly: broken adds the defect to similar text, fine suppresses a false alarm. No training.
F verify-laya-glance_lesson "No authored observer check is bound to neyvia.laya.glance_lesson" -> ask operator blocks:neyvia.laya.glance_lesson
A neyvia.laya.glance_learn(screenshot:str#..16000 label:"broken"|"fine" reason:str#..16000 source:str#..16000 surface?:str#..16000) -> t1 ! -- Write one labelled screenshot episode; no training or head consolidation.
F verify-laya-glance_learn "No authored observer check is bound to neyvia.laya.glance_learn" -> ask operator blocks:neyvia.laya.glance_learn
C neyvia.laya.glance_contracts live-predicates:neyvia.laya.glance_contracts() .passed == true
C neyvia.laya.glance_proof pixel-before-after:neyvia.laya.glance_proof() .passed == true
P prove-scenes():observed=neyvia.laya.glance_contracts() C live-predicates -- Exercise actual headless DOM/canvas observations and compare before/after defect outcomes
V P prove-scenes -> script why:"typed manual runner; stops at every judgement"
P prove-pixels():proof=neyvia.laya.glance_proof() C pixel-before-after -- Glance the recorded before/after fix captures from pixels: the black PDF page, see-through panels and clipped chips are caught before and absent after
V P prove-pixels -> script why:"typed manual runner; stops at every judgement"
X Missing style or geometry fact -> Preserve unknown and request one model look; never infer a clean screen.
F UI automatic CSS fixes are proposals only. Engine adapters register separately.
F Pixel-only recall is low for overlap (icon collisions), off-screen controls and phone peek sheets whose foreign text lies wholly inside the sheet; a clean pixel verdict is therefore never admitted and escalates to one model look.
F A screenshot glance takes about 0.5 s (OCR ~0.2 s, pixel facts ~0.25 s, judge ~6 ms); the DOM+screenshot gate glance adds the render.
M laya-glance "Broken means a see-through surface, clipped text, raw error, encoded path or internal id, blank expected render, unintended overlap, unreadable contrast, or an off-screen control. Crisp predicates cite observed facts; fuzzy judgement uses instant episodes at nominal 0.95. No training runs or new heads." src:"authored manual" state:verified
M laya-glance "Transcribe from the perception DOM graph when the app is live; a screenshot alone is read by local OCR plus measured pixel facts. With both, the screenshot cross-checks DOM coverage and fills contrast, and pixel findings count only where their calibrated precision reaches 0.95." src:"authored manual" state:verified
M laya-glance "Teach with laya.glance_lesson (one node, effective on the next glance) or laya.glance_learn (one labelled screenshot, updates calibration). Lessons apply only to text-intrinsic predicates; see-through, off-screen and blank renders depend on layout." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.scene_core.judge","grant_agent.laya_glance_contracts.observe"],"claim":"Actual before/after DOM and canvas observations bind typed defects to nodes and fixes.","id":"layag.scene-predicates","impact":["src/grant_agent/scene_core","src/grant_agent/laya_glance.py","src/grant_agent/perception_scene.js"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.laya_glance_proof.run","grant_agent.laya_glance.glance"],"claim":"From pixels alone, the black PDF page, see-through panels and clipped chips are caught on recorded before captures and absent on the after captures.","id":"layag.pixel-before-after","impact":["src/grant_agent/laya_glance_image.py","src/grant_agent/laya_glance.py","src/grant_agent/laya_glance_proof.py","manuals/cl/laya-glance.cl"],"phase":"invariant"}
