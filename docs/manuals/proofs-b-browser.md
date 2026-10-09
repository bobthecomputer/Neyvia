<!-- Generated from manuals/cl/proofs-b-browser.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# proofs-b-browser

## proofs-b-harness-browser
CL 1
L proofs-b-browser v1 -- PROOFS-b: actual local Harness blocker and capacity presentation
T t1{ok:true available:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\"]}"
S proofs-b-browser.latest:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Observe the existing proof boundary without replaying actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-latest():receipt=neyvia.verify.status() C observed -- Read the latest browser proof boundary
V P read-latest -> script why:"typed manual runner; stops at every judgement"
X A local saved-state browser journey is mistaken for successful provider inference or real capacity scheduling -> Read the fixture provenance and contract scope; infer only the rendered labels/actions and preserved local records.
X An older served bundle is mistaken for the checked implementation -> Require source stability, actual fetched bundle bytes matching the owned build, and the semantic guard in a loaded bundle.
F General conversation-fabric verifier case and 75 desktop source cases remain unproven.
F Native desktop/device, real provider inference and actual worker capacity scheduling are separate proof boundaries.
M proofs-b-browser "Every HarnessesSurface render consumes checkHarnessView labels, terminal/attention flags, cleanup/retry permissions and receipt output." src:"authored manual" state:verified
M proofs-b-browser "Trusted startup runner: scripts/proofs-b-browser.mjs --root <owned scratch root> --json." src:"authored manual" state:verified
M proofs-b-browser "The runner starts only its own loopback backend48472 and Chrome CDP48478 with a fresh browser profile and isolated backend homes; page requests are limited to the exact fixture origin." src:"authored manual" state:verified
M proofs-b-browser "Only Chrome receives conventional Windows USERPROFILE/APPDATA path metadata reconstructed from HOMEDRIVE and HOMEPATH, because isolated metadata prevents its DevTools admission. CDP attests the actual user-data-dir equals the fresh owned profile. Node/backend/provider homes remain isolated; the runner never reads operator profile or credential files." src:"authored manual" state:verified
M proofs-b-browser "The fixture skips nested proof startup to prevent recursive verifier launch; parent startup readiness is proven separately." src:"authored manual" state:verified
M proofs-b-browser "Real actions select waiting and blocked records, prepare retry, inspect exact original receipt hashes, and explicitly cancel/clean up while preserving blocker evidence." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/HarnessesSurface.jsx:receiptView and rendered flags/controls/output","web/src/neyvia/proofsBViewContracts.js:checkHarnessView","grant_agent.harness_jobs.HarnessJobStore.cancel"],"claim":"Every Harness render consumes a checked view: blocked is actionable and nonterminal, cleanup/retry follow durable lifecycle, and blocked or cleaned-up blocker output preserves the structured result. A real Chrome fixture proves retry preserves original receipt bytes and explicit cleanup preserves the blocker result.","id":"proofs-b.browser.blocked-receipt","impact":["Harness receipt","retry and cleanup controls","original blocker evidence"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/HarnessesSurface.jsx:receiptView and queue rows","web/src/neyvia/proofsBViewContracts.js:checkHarnessView"],"claim":"Every receipt and queue label, including the accessible queue name, is checked against durable waitingReason: execution-capacity is waiting for capacity rather than active execution.","id":"proofs-b.browser.capacity-label","impact":["receipt status","visible queue label","accessible queue label"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/HarnessesSurface.jsx:receiptView.output","web/src/neyvia/proofsBViewContracts.js:checkHarnessView"],"claim":"When a capacity-wait job has no result/error, the checked receipt output explains the workspace capacity wait and explicitly says no execution slot is claimed.","id":"proofs-b.browser.capacity-explanation","impact":["execution-wait context","operator execution claims"],"phase":"post"}
