<!-- Generated from manuals/cl/pdf.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# pdf

## overview
CL 1
L pdf v1 -- PDF shared state, pages, search, highlights and extraction
T t1{state:json:"{\"type\":[\"object\",\"null\"]}" requested:json:"{\"type\":\"object\"}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"array\"}"
T t4 json:"{\"oneOf\":[{\"type\":\"number\",\"minimum\":0.25,\"maximum\":5},{\"type\":\"string\",\"enum\":[\"fit-width\"]}]}"
S pdf.current:t1=neyvia.pdf.state()
A neyvia.pdf.state() -> t1 -- Return app-observed PDF state and separately requested source/page
C neyvia.pdf.state visible-source:neyvia.pdf.state() .state.source == source
C neyvia.pdf.state visible-text:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["text"] == phrase
C neyvia.pdf.state visible-page:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["page"] == page
C neyvia.pdf.state fresh-page:neyvia.pdf.state() .fresh == true
C neyvia.pdf.state canvas-not-blank:neyvia.pdf.state() .outcome.nonBlank == true
C neyvia.pdf.state text-layer-ready:neyvia.pdf.state() .outcome.textLayerPresent == true
C neyvia.pdf.state text-layer-phrase:neyvia.pdf.state() .outcome.text has phrase
A neyvia.pdf.extract_text(page?:1.. maxChars?:512..100000) -> t2 -- Read real page text with explicit truncation; no OCR
C neyvia.pdf.extract_text page-text:neyvia.pdf.extract_text(page:page) .text has phrase
A neyvia.pdf.goto(page:1..) -> t2 -- Emit page navigation; actual visible page awaits app state report
F verify-pdf-goto "No authored observer check is bound to neyvia.pdf.goto" -> ask operator blocks:neyvia.pdf.goto
A neyvia.pdf.highlight(page:1.. text?:str rects?:t3 note?:str) -> t2 -- Emit highlight overlay request with optional note; does not rewrite PDF or confirm rendering
F verify-pdf-highlight "No authored observer check is bound to neyvia.pdf.highlight" -> ask operator blocks:neyvia.pdf.highlight
A neyvia.pdf.open(source:str page?:1..) -> t2 -- Read PDF metadata, persist requested source/page and emit open; preserve source, uiVerified=false
C neyvia.pdf.open requested-source:neyvia.pdf.state() .requested.source == source
A neyvia.pdf.search(query?:str maxHits?:1..10000) -> t2 -- Search parsed PDF text, emit the query and require a fresh renderer report of that query and its hit count
F verify-pdf-search "No authored observer check is bound to neyvia.pdf.search" -> ask operator blocks:neyvia.pdf.search
A neyvia.pdf.zoom(scale:t4) -> t2 -- Emit zoom request; user app reports rendered scale separately
F verify-pdf-zoom "No authored observer check is bound to neyvia.pdf.zoom" -> ask operator blocks:neyvia.pdf.zoom
C neyvia.pdf.state requested-source:neyvia.pdf.state() .requested.source == source
C neyvia.pdf.extract_text page-text:neyvia.pdf.extract_text(page:page) .text has phrase
C neyvia.pdf.state visible-source:neyvia.pdf.state() .state.source == source
C neyvia.pdf.state visible-text:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["text"] == phrase
C neyvia.pdf.state visible-page:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["page"] == page
C neyvia.pdf.state fresh-page:neyvia.pdf.state() .fresh == true
C neyvia.pdf.state canvas-not-blank:neyvia.pdf.state() .outcome.nonBlank == true
C neyvia.pdf.state text-layer-ready:neyvia.pdf.state() .outcome.textLayerPresent == true
C neyvia.pdf.state text-layer-phrase:neyvia.pdf.state() .outcome.text has phrase
P find-and-highlight(source:str page:1.. phrase:str):opened=neyvia.pdf.open(page:page source:source) C requested-source; hits=neyvia.pdf.search(query:phrase); text=neyvia.pdf.extract_text(page:page) C page-text; J passage=highlight; navigated=neyvia.pdf.goto(page:page); highlightRequest=neyvia.pdf.highlight(page:page text:phrase) -- Open a local PDF, search a passage, review the chosen page and emit a highlight overlay
V P find-and-highlight -> script why:"typed manual runner; stops at every judgement"
P open-and-read(source:str page:1.. phrase:str):opened=neyvia.pdf.open(page:page source:source) C requested-source; text=neyvia.pdf.extract_text(page:page) C page-text -- Open and verify text on a known page; no rendering claim
V P open-and-read -> script why:"typed manual runner; stops at every judgement"
P verify-visible-highlight(source:str phrase:str page:1.. markIndex:0..):source=neyvia.pdf.state() C visible-source; text=neyvia.pdf.state() C visible-text; page=neyvia.pdf.state() C visible-page -- After user app acknowledgement, verify source and the selected observed highlight text/page
V P verify-visible-highlight -> script why:"typed manual runner; stops at every judgement"
P set-visible-zoom(scale:t4):zoomed=neyvia.pdf.zoom(scale:scale) -- Set a PDF zoom and verify the user app reports the requested scale
V P set-visible-zoom -> script why:"typed manual runner; stops at every judgement"
P verify-rendered-page(phrase:str#1..):observed0=neyvia.pdf.state() C fresh-page; observed1=neyvia.pdf.state() C canvas-not-blank; observed2=neyvia.pdf.state() C text-layer-ready; observed3=neyvia.pdf.state() C text-layer-phrase -- The current mounted page has real ink and the requested phrase in its selectable text layer
V P verify-rendered-page -> script why:"typed manual runner; stops at every judgement"
J passage highlight|leave:"Which occurrence deserves the highlight?" -- Read hits and page text; input page must be the intended occurrence, not simply first hit. Text highlights exact phrase; use rectangles only for visual selection with known PDF-point coordinates.
V J passage -> human:operator why:"explicit choice required"
X Open or goto page outside PDF count -> Read metadata.pages and choose 1-based existing page
X Highlight text was not found -> Extract same page, correct literal text or use explicit finite rectangle coordinates; never claim successful overlay
X Extracted text truncated / search hits truncated -> Increase bounded maxChars/maxHits or narrow page/query; absence in a truncated result is inconclusive
X Command returned uiVerified=false -> Read state.state observedAt/page/highlights after app consumption; requested is only intent
X Scanned PDF has empty text -> Text extraction has no OCR; take separate OCR route with its own evidence
F OCR, encrypted-document handling and semantic match selection are unmapped
F Highlights are overlays; no tool persists annotations into PDF bytes
F Browser upload handles and remote URLs are not valid local PDF sources
F CL PDF effects require a fresh ready renderer report for the same guarded source; a queued event alone does not complete the action.
F Rectangle-only highlight geometry is not present in the renderer state report, so CL refuses rectangle arguments until a geometry observer is wired.
M pdf "Source: src/grant_agent/neyvia_pdf_tools.py (safe_pdf, call_pdf, report_pdf_state), pdf_document.py; scripts/verify-grounded-manuals.mjs." src:"authored manual" state:verified
M pdf "Choose markIndex from observed state.highlights, not a search-hit index; null state or wrong source/page/text fails verification. Source: web/src/neyvia/next/NxPdfApp.jsx reports real highlights." src:"authored manual" state:verified
M pdf "A PDF search is a visible renderer mutation; CL requires the reported query and hits, while extracted text remains a source read." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:itemRect -> checkedModelAction"],"claim":"Character highlights preserve PDF baseline, proportional x range and descender bounds","id":"pdf.text-geometry","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:searchTexts -> checkedModelAction"],"claim":"Return every bounded nonoverlapping case-insensitive occurrence in page/run order with actual text geometry","id":"pdf.search","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:stepZoom -> checkedModelAction"],"claim":"Zoom moves to nearest supported step in the requested direction and clamps at endpoints","id":"pdf.zoom","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:displayName -> checkedModelAction"],"claim":"A PDF is named by its file name, never an encoded route, query or internal path","id":"pdf.display-name","impact":["PDF loading text, toolbar name and reported state"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:clampPage -> checkedModelAction"],"claim":"Page navigation rounds/coerces input and stays within 1..page count","id":"pdf.page","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_render.py","web/src/neyvia/next/nxOutcomeObservation.js","web/src/neyvia/next/NxPdfPage.jsx","web/src/neyvia/next/nxPdfModel.js","src/grant_agent/neyvia_pdf_api.py","src/grant_agent/neyvia_pdf_tools.py","src/grant_agent/cl/pdf_effects.py","scripts/p22_build.mjs"],"claim":"Canvas contains ink and its selectable text layer contains the known phrase","id":"p22.pdf-render","impact":["web/src/neyvia/next/nxShellObserve.js","scripts/placement_shots.py","config/proofs/fast-ui.json"],"phase":"post"}

## proofs-e-shell
CL 1
L pdf v1 -- PROOFS-e shell state and action contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S pdf.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the latest verification receipt without repeating shell actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-shell-proof-receipt():receipt=neyvia.verify.status() C observed -- Observe the latest shell proof receipt without replaying mutations
V P read-shell-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X A queue or shell state receipt is treated as rendered app proof -> Inspect the owned running UI and actual PDF/output/provider separately
F Rendered shell journeys and PDF loading require owned UI proof
F Provider execution and actual artifact publishing are separate proof boundaries
M pdf "pdf.open selects the Documents PDF app; later commands require it open and enter the ordered inbox; invalid pages/scales/text are refused" src:"authored manual" state:verified
M pdf "Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions" src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:itemRect -> checkedModelAction"],"claim":"Character highlights preserve PDF baseline, proportional x range and descender bounds","id":"pdf.text-geometry","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:searchTexts -> checkedModelAction"],"claim":"Return every bounded nonoverlapping case-insensitive occurrence in page/run order with actual text geometry","id":"pdf.search","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:stepZoom -> checkedModelAction"],"claim":"Zoom moves to nearest supported step in the requested direction and clamps at endpoints","id":"pdf.zoom","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:displayName -> checkedModelAction"],"claim":"A PDF is named by its file name, never an encoded route, query or internal path","id":"pdf.display-name","impact":["PDF loading text, toolbar name and reported state"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:clampPage -> checkedModelAction"],"claim":"Page navigation rounds/coerces input and stays within 1..page count","id":"pdf.page","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_render.py","web/src/neyvia/next/nxOutcomeObservation.js","web/src/neyvia/next/NxPdfPage.jsx","web/src/neyvia/next/nxPdfModel.js","src/grant_agent/neyvia_pdf_api.py","src/grant_agent/neyvia_pdf_tools.py","src/grant_agent/cl/pdf_effects.py","scripts/p22_build.mjs"],"claim":"Canvas contains ink and its selectable text layer contains the known phrase","id":"p22.pdf-render","impact":["web/src/neyvia/next/nxShellObserve.js","scripts/placement_shots.py","config/proofs/fast-ui.json"],"phase":"post"}
