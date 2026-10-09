<!-- Generated from manuals/cl/agent-view.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# agent-view

## watch
CL 1
L agent-view v1 -- Watch and steer agents: live mirrors of their own surfaces, comments bound to a frame or step, and a bounded time-lapse
T t1{ok:bool runs:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"string\",\"enum\":[\"stream\",\"timeline\",\"feedback\"]}"
T t3{ok:bool area:str checks:json:"{\"type\":\"array\"}" ..}
S agent-view.runs:t1=neyvia.agentview.state()
A neyvia.agentview.state() -> t1 -- Read every mirrored run: surfaces, the last steps in plain words, Paul's comments with their delivery state, and the time-lapse bounds
C neyvia.agentview.state runs-readable:neyvia.agentview.state() .ok == true
A neyvia.agentview.check(area:t2) -> t3 -- Drive the production agent view with real pictures and files and return each contract's observation
C neyvia.agentview.check stream-contract:neyvia.agentview.check(area:"stream") .ok == true
C neyvia.agentview.check timeline-contract:neyvia.agentview.check(area:"timeline") .ok == true
C neyvia.agentview.check feedback-contract:neyvia.agentview.check(area:"feedback") .ok == true
C neyvia.agentview.check stream-contract:neyvia.agentview.check(area:"stream") .ok == true
C neyvia.agentview.check timeline-contract:neyvia.agentview.check(area:"timeline") .ok == true
C neyvia.agentview.check feedback-contract:neyvia.agentview.check(area:"feedback") .ok == true
C neyvia.agentview.state runs-readable:neyvia.agentview.state() .ok == true
P verify-agent-view():stream=neyvia.agentview.check(area:"stream") C stream-contract; timeline=neyvia.agentview.check(area:"timeline") C timeline-contract; feedback=neyvia.agentview.check(area:"feedback") C feedback-contract; runs=neyvia.agentview.state() C runs-readable -- Prove the live stream sends only changed regions at the viewer's rate and stops when unwatched, the time-lapse stays inside its count and byte bounds while keeping first, last and commented frames, and a comment is bound to the exact frame, step and element and reaches the agent once
V P verify-agent-view -> script why:"typed manual runner; stops at every judgement"
X A comment stays 'Waiting for its next step' -> The agent has not called the driver or the browser since. Its chat is thinking or stuck: steer the chat itself, or Take control in the preview
X The live view says it can't show the surface -> The window closed, was minimized, or the driver paused itself (zero-disturbance guard). The time-lapse still holds every kept keyframe
X Several runs of one chat look merged -> A run is one agent chat (app and chat id); its windows and pages are surfaces of that run, picked with the chips above the picture
F Native surfaces stream at most 1.5 fps: their captures share the driver's guard and capture lanes with the agent, which always goes first
F A running Codex or Claude Code turn is steered at once only while its run accepts steering; otherwise the comment arrives with the agent's next computer-use or browser step
F Side, full screen and bubble placement come from the shared placement layer; the view measures its own size and visibility to pick 4, 3 or 0.5 fps or stop
M agent-view "Paul watches a rendered copy of your surface (agent desktop window or Obscura page), never the real window. Every action you take is outlined and said in plain words in his step list." src:"authored manual" state:verified
M agent-view "Say what you are about to try with preview_note (computer use); it appears in the step list and the time-lapse." src:"authored manual" state:verified
M agent-view "Paul's comments arrive as 'Paul did since your last call: Feedback from Paul on your screen ...' in computer-use results, or as ownerFeedback in browser results. Each names the frame time, the element he pointed at and the step it is about: treat it as steering and act on it before continuing." src:"authored manual" state:verified
M agent-view "Contract: src/grant_agent/neyvia_agentview.py (routes /api/ui/agentview: runs, frame, timeline, keyframe, feedback). User side: web/src/neyvia/next/agentview/ (Agents at work app, agentview pane per run)." src:"authored manual" state:verified
M agent-view "Live journey: scripts/prove_agentview.py on an isolated backend; receipt and screenshots in docs/evidence/agentview/." src:"authored manual" state:verified
-- @proof {"checkedAt":["src/grant_agent/neyvia_agentview.py:SurfaceFrames.delta -> contract"],"claim":"A frame answer is 'same' only for the version held, a delta only from that version and inside the frame under the full-frame share, otherwise one full frame","id":"agentview.delta","impact":["live view bytes","picture correctness"],"phase":"post"}
-- @proof {"checkedAt":["src/grant_agent/neyvia_agentview.py:AgentView.frame -> contract"],"claim":"Each frame request renews capture for 2.5 s at 0.2-5 fps (native surfaces at most 1.5 fps); without requests nothing is captured beyond the time-lapse watch","id":"agentview.demand","impact":["capture cost","driver load"],"phase":"post"}
-- @proof {"checkedAt":["src/grant_agent/neyvia_agentview.py:AgentView.enforce_bounds -> contract"],"claim":"A run keeps at most its keyframe count and bytes; first, last and commented keyframes always stay; dropped files are deleted","id":"agentview.bounds","impact":["disk use","time-lapse coverage"],"phase":"invariant"}
-- @proof {"checkedAt":["src/grant_agent/neyvia_agentview.py:AgentView.feedback -> contract"],"claim":"A comment is pinned to the exact frame version (or keyframe) Paul saw and the step he picked, and has one delivery channel: steer, computer-use log or next browser result","id":"agentview.feedback","impact":["steering","time-lapse pins"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/agentview/nxAgentViewModel.js:pollDelay -> checked","scripts/p22_release_models.mjs"],"claim":"The view polls only while visible and in sight, at its size's rate, slowing on a still picture and backing off on errors","id":"agentview.poll","impact":["live view cost"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/agentview/nxAgentViewModel.js:applyFrame -> checked","scripts/p22_release_models.mjs"],"claim":"Changed regions stack only on the version they came from; anything else asks for one full frame","id":"agentview.applyFrame","impact":["picture correctness"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/agentview/nxAgentViewModel.js:feedbackPayload -> checked","scripts/p22_release_models.mjs"],"claim":"A comment sent from the view carries the shown frame version or the time-lapse keyframe, the picked step and the clicked point","id":"agentview.feedbackPayload","impact":["steering"],"phase":"post"}
