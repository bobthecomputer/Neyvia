<!-- Generated from manuals/cl/scroll-generator.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# scroll-generator

## overview
CL 1
L scroll-generator v1 -- Scroll generator: notes to source-bound study cards
T t1{ok:bool packs:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3 [str#1..]#1..20
T t4 json:"{\"type\":\"object\",\"properties\":{\"chapters\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"minLength\":1}},\"concepts\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"minLength\":1}}},\"additionalProperties\":false}"
T t5 [{cardId:str#1.. action:"approve"|"drop"|"edit" card?:json:"{\"type\":\"object\"}"}]
S scroll-generator.pack:t1=neyvia.scroll.state(pack:pack)
A neyvia.scroll.validate(pack:str#1..) -> t2 ! -- Run schema/DAG/source/maths/card-mix checks without model calls.
C neyvia.scroll.validate valid:neyvia.scroll.validate(pack:pack) .ok == true
A neyvia.scroll.stats(pack:str#1..) -> t2 -- Read actual generation usage, price-qualified card/hour costs and review approval rate.
F verify-stats "No authored observer check is bound to neyvia.scroll.stats" -> ask operator blocks:neyvia.scroll.stats
A neyvia.scroll.import(paths:t3 packId?:str#1.. title?:str#1.. subject?:str#1..) -> t2 ! -- Hash Markdown/text study notes and create a workspace pack draft using zero-token ingest/split/candidate scripts.
F verify-import "No authored observer check is bound to neyvia.scroll.import" -> ask operator blocks:neyvia.scroll.import
A neyvia.scroll.concepts(pack:str#1..) -> t2 ! -- Confirm concepts through the validated Luna cascade; graph-sanity is the only large graph judgement.
F verify-concepts "No authored observer check is bound to neyvia.scroll.concepts" -> ask operator blocks:neyvia.scroll.concepts
A neyvia.scroll.generate(pack:str#1.. scope?:t4 requestId:str#1..) -> t2 ! -- Start a durable cards/answer-check job. Reuse requestId for transport retries; models cannot run arbitrary tools.
F verify-generate "No authored observer check is bound to neyvia.scroll.generate" -> ask operator blocks:neyvia.scroll.generate
A neyvia.scroll.job(requestId:str#1..) -> t2 -- Observe a persisted job and its last stage, progress and actionable failure.
F verify-job "No authored observer check is bound to neyvia.scroll.job" -> ask operator blocks:neyvia.scroll.job
A neyvia.scroll.review(pack:str#1.. decisions?:t5 chapter?:str#1.. action?:"approve") -> t2 ! -- Approve, drop or edit real draft cards. Flagged answers need an explicit individual decision.
F verify-review "No authored observer check is bound to neyvia.scroll.review" -> ask operator blocks:neyvia.scroll.review
A neyvia.scroll.pack(pack:str#1..) -> t2 ! -- Validate and zip an entirely reviewed pack and its hashed source texts; pending/flagged cards block export.
F verify-pack "No authored observer check is bound to neyvia.scroll.pack" -> ask operator blocks:neyvia.scroll.pack
A neyvia.scroll.preview(pack:str#1.. device?:str#1..) -> t2 ! -- Copy the approved generated pack into the real phone prototype and open Mobile Studio on the same state.
F verify-preview "No authored observer check is bound to neyvia.scroll.preview" -> ask operator blocks:neyvia.scroll.preview
A neyvia.scroll.send(pack:str#1..) -> t2 ! -- Create a single-download 15-minute capability for this approved archive; requires explicit backend URL.
F verify-send "No authored observer check is bound to neyvia.scroll.send" -> ask operator blocks:neyvia.scroll.send
A neyvia.scroll.state(pack?:str#1..) -> t2 -- Read the exact pack/graph/review/job state shown to the user.
F verify-state "No authored observer check is bound to neyvia.scroll.state" -> ask operator blocks:neyvia.scroll.state
C neyvia.scroll.validate valid:neyvia.scroll.validate(pack:pack) .ok == true
P validate-pack(pack:str#1..):validation=neyvia.scroll.validate(pack:pack) C valid -- Reject invalid cards before review/export
V P validate-pack -> script why:"typed manual runner; stops at every judgement"
P import-notes(paths:t3 packId:str#1..):result=neyvia.scroll.import(packId:packId paths:paths) -- Import bounded study notes and verify their hashes in the durable pack
V P import-notes -> script why:"typed manual runner; stops at every judgement"
P review-cards(pack:str#1.. decisions:t5):result=neyvia.scroll.review(decisions:decisions pack:pack) -- Apply card decisions and verify each reviewed card in the durable pack
V P review-cards -> script why:"typed manual runner; stops at every judgement"
P export-pack(pack:str#1..):result=neyvia.scroll.pack(pack:pack) -- Export a fully reviewed validated archive and verify its bytes
V P export-pack -> script why:"typed manual runner; stops at every judgement"
P preview-pack(pack:str#1..):result=neyvia.scroll.preview(pack:pack) -- Materialize the approved pack in Mobile Studio and verify the generated files
V P preview-pack -> script why:"typed manual runner; stops at every judgement"
P send-pack(pack:str#1..):result=neyvia.scroll.send(pack:pack) -- Create a one-download pack capability bound to the exported archive
V P send-pack -> script why:"typed manual runner; stops at every judgement"
X Model unavailable or same-tier retry exhausted -> Read job error and generation receipt; restore requested gpt-6-luna route, then resume a new scoped generation request. No substituted models.
X Independent answer disagrees -> One answer-dispute judgement; unresolved cards stay flagged until review.
X Card teaches what it tests -> Separate the teach card and recall card; prerequisites must already have teaching cards.
X Unsupported answer or wrong MCQ -> Use the hashed source span, exact correct count and mistake reasons; never invent supporting notes.
X Generated variation is passed off as a course example -> Only course_example copies an exact quote and span from the imported note; adaptations identify generatedAdaptation and variantOf.
X A teaching card is flicked past or a question is on an untaught part -> Exposure is persisted only after completed reading or worked steps; tests require taught parts, eight cards lag, and changed wording five to ten cards after a miss.
F Markdown/text import works. PDF/OCR extraction is not attached.
F Formula arithmetic comparison uses installed SymPy; unavailable symbolic checking is reported through a small independent solution.
F Source numbered worked examples can be extracted; every generated procedure example is a named big judgement.
F Validated packs can compile after three real grounded manual runs. Compiled validation remains input/manual/provenance-bound and rechecks current cards.
F Validated packs can compile after three real grounded manual runs. Compiled validation remains input/manual/provenance-bound and rechecks current cards.
F Maths/physics default to paul-seven-part.v1: FORMULA, WHEN?, WHAT DO I WRITE?, PATTERN, COURSE EXAMPLE, YOUR EXERCISE, VARIATIONS/TRAPS per actionable concept. The CL source is authoritative.
F scroll.validate executes the seven-part completeness, exact quoted course span, changed exercise reference and independently checked solution gates in addition to schema/DAG/source/maths/mix.
F Pattern cards teach If I see X -> try Y; pattern_drill asks recognition after the pattern is taught. Your exercises and generated variants require all supporting teaching parts and an eight-card lag.
F CL pack actions require fresh source, review, validation and artifact checks; model generation still depends on the configured Luna runtime.
M scroll-generator "R2: >=50 percent graded cards are recall (flashcard/cloze/why/order/spot/faded worked); truefalse <=20 percent. No reward cards in packs." src:"authored manual" state:verified
M scroll-generator "Fact <=60 words; explainer <=120; reading <=40 seconds. Non-recap cards have source doc/span and stage/tier/run provenance." src:"authored manual" state:verified
M scroll-generator "Every prerequisite/tested concept has a teaching card. A graded card never teaches its tested concept." src:"authored manual" state:verified
M scroll-generator "Models: gpt-6-luna through T14 for wording/concepts/re-solve; gpt-6.1-sol only graph-sanity, worked-example, answer-dispute." src:"authored manual" state:verified
M scroll-generator "R14: worked all steps -> fade1 last step blank -> fade2 later half blank -> order/full problem. Keep the original answers." src:"authored manual" state:verified
M scroll-generator "Mistake catalogue: forgetting the inner derivative; multiplying derivatives in product rule; dropping a constant; sign inversion; confusing a converse; moving a step before its prerequisite." src:"authored manual" state:verified
M scroll-generator "fact examples: 'Slope is rise over run.'; 'A derivative is the slope of the tangent.'" src:"authored manual" state:verified
M scroll-generator "explainer examples: 'Secant slopes tend to the tangent slope as the interval shrinks.'; 'The product rule differentiates one factor at a time and adds both changes.'" src:"authored manual" state:verified
M scroll-generator "worked examples: 'Differentiate x^3: exponent 3 comes down, lower exponent to 2, obtain 3x^2.'; 'For x^2*exp(x), find 2x and exp(x), then add 2x*exp(x)+x^2*exp(x). Why: each factor changes.'" src:"authored manual" state:verified
M scroll-generator "flashcard examples: front 'What is rise over run called?' back 'Slope.'; front 'Differentiate x^3.' back '3x^2.'" src:"authored manual" state:verified
M scroll-generator "cloze examples: before 'Slope is ', blank 'rise over run', after '.'; before 'd/dx x^3 = ', blank '3x^2', after '.'" src:"authored manual" state:verified
M scroll-generator "why examples: front 'Why multiply by the inner derivative?' back 'It accounts for the inner function changing.'; front 'Why does the product rule have two terms?' back 'Either factor can change.'" src:"authored manual" state:verified
M scroll-generator "truefalse examples: 'The derivative of x^3 is 3x^2.' true with power-rule reason; 'The derivative of f*g is fprime*gprime.' false with both correct terms." src:"authored manual" state:verified
M scroll-generator "mcq examples: differentiate x^3 -> 3x^2 correct, x^2 wrong missing coefficient, 3x^3 wrong unchanged exponent; differentiate (3x+1)^2 -> 6(3x+1) correct, 2(3x+1) wrong missing inner derivative, 6x wrong lost inner expression." src:"authored manual" state:verified
M scroll-generator "order examples: power rule -> identify exponent, multiply coefficient, lower exponent; chain rule -> identify inner function, differentiate outer, multiply inner derivative." src:"authored manual" state:verified
M scroll-generator "spot examples: lines ['n=3','derivative=x^2'], wrong 1, fix 'derivative=3x^2'; lines ['u=3x+1','derivative=2u'], wrong 1, fix 'derivative=6u'." src:"authored manual" state:verified
M scroll-generator "recap examples: 'Slope: rise/run. Derivative: tangent slope.'; 'Product: fprime*g+f*gprime. Chain: outer derivative times inner derivative.'" src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.proofs_scroll_export_journey.self_check","grant_agent.neyvia_scroll.export","grant_agent.neyvia_scroll.download","grant_agent.scroll_pack.write_scrollpack","grant_agent.scroll_pack.read_scrollpack"],"claim":"A reviewed Unicode pack exports with exact source/card semantics and sends a one-download QR SVG capability; the first route payload equals the archive and repeat/expired requests refuse with 410. The check asserts SVG path geometry only; it does not decode a QR or claim a phone/UI consumer.","id":"p22.scroll.reviewed-export-singleuse-outcome","impact":["Scroll Study reviewed export","one-use phone delivery","Unicode archive roundtrip"],"phase":"post"}
