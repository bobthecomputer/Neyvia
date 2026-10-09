CL 1
L pdf v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"PDF shared state, pages, search, highlights and extraction"},"proofs-e-shell":{"title":"PROOFS-e shell state and action contracts"}},"clVersion":"1.1","id":"pdf","kind":"environment","proofs":{"area":"frontend-models","manifests":["config/proofs/frontend-models.json"],"startup":{"procedures":["pdf.read-highlight-navigate"],"runner":"scripts/proofs-frontend-models.mjs","scratchRootRequired":true}},"schema":"neyvia.manual.v1","schemas":{"neyvia.pdf.extract_text":"t1","neyvia.pdf.goto":"t2","neyvia.pdf.highlight":"t3","neyvia.pdf.open":"t4","neyvia.pdf.search":"t5","neyvia.pdf.state":"t6","neyvia.pdf.zoom":"t7","proofs-e-shell.status":"t6"},"tool_metadata":{"neyvia.pdf.extract_text":{"mutability_class":"read"},"neyvia.pdf.goto":{"mutability_class":"none"},"neyvia.pdf.highlight":{"mutability_class":"none"},"neyvia.pdf.open":{"mutability_class":"none"},"neyvia.pdf.search":{"mutability_class":"none"},"neyvia.pdf.state":{"mutability_class":"read"},"neyvia.pdf.zoom":{"mutability_class":"none"},"neyvia.verify.status":{"mutability_class":"none"}}}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:itemRect -> checkedModelAction"],"claim":"Character highlights preserve PDF baseline, proportional x range and descender bounds","id":"pdf.text-geometry","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:searchTexts -> checkedModelAction"],"claim":"Return every bounded nonoverlapping case-insensitive occurrence in page/run order with actual text geometry","id":"pdf.search","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:stepZoom -> checkedModelAction"],"claim":"Zoom moves to nearest supported step in the requested direction and clamps at endpoints","id":"pdf.zoom","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:displayName -> checkedModelAction"],"claim":"A PDF is named by its file name, never an encoded route, query or internal path","id":"pdf.display-name","impact":["PDF loading text, toolbar name and reported state"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxPdfModel.js:clampPage -> checkedModelAction"],"claim":"Page navigation rounds/coerces input and stays within 1..page count","id":"pdf.page","impact":["PDF highlights/search/navigation"],"phase":"post"}
-- @proof {"id":"p22.pdf-render","phase":"post","claim":"Canvas contains ink and its selectable text layer contains the known phrase","checkedAt":["scripts/p22_render.py","web/src/neyvia/next/nxOutcomeObservation.js","web/src/neyvia/next/NxPdfPage.jsx","web/src/neyvia/next/nxPdfModel.js","src/grant_agent/neyvia_pdf_api.py","src/grant_agent/neyvia_pdf_tools.py","src/grant_agent/cl/pdf_effects.py","scripts/p22_build.mjs"],"impact":["web/src/neyvia/next/nxShellObserve.js","scripts/placement_shots.py","config/proofs/fast-ui.json"]}
T t1{page?:1.. maxChars?:512..100000 ..}
T t2{page:1.. ..}
T t3{page:1.. text?:str rects?:json:"{\"type\":\"array\"}" note?:str ..}
T t4 json:"{\"type\":\"object\",\"properties\":{\"source\":{\"type\":\"string\"},\"page\":{\"type\":\"integer\",\"minimum\":1}},\"required\":[\"source\"],\"allOf\":[{\"properties\":{\"source\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t5{query?:str maxHits?:1..10000 ..}
T t6{..}
T t7{scale:json:"{\"oneOf\":[{\"type\":\"number\",\"minimum\":0.25,\"maximum\":5},{\"type\":\"string\",\"enum\":[\"fit-width\"]}]}" ..}
T t8{}
T t9{state:json:"{\"type\":[\"object\",\"null\"]}" requested:json:"{\"type\":\"object\"}" ..}
T t10 json:"{\"type\":\"object\"}"
T t11{source:str page:1.. phrase:str}
T t12{source:str phrase:str page:1.. markIndex:0..}
T t13{scale:json:"{\"oneOf\":[{\"type\":\"number\",\"minimum\":0.25,\"maximum\":5},{\"type\":\"string\",\"enum\":[\"fit-width\"]}]}"}
T t14{phrase:str#1..}
T t15{ok:bool ..}
T t16 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
L pdf.overview v1 -- PDF shared state, pages, search, highlights and extraction
-- @record {"chapter":"overview","data":{"args":{},"inputs":{"$cl_type":"t8"},"shape":{"$cl_type":"t9"},"tool":"neyvia.pdf.state"},"key":"current","section":"state"}
S pdf.current:{state:json:"{\"type\":[\"object\",\"null\"]}" requested:json:"{\"type\":\"object\"}" ..}=neyvia.pdf.state()
-- @record {"chapter":"overview","data":{"effect":"Return app-observed PDF state and separately requested source/page","pre":"Selected root bus is readable; PDF may be unopened","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.pdf.state","tool":"neyvia.pdf.state"},"key":"pdf.state","section":"actions"}
A neyvia.pdf.state() -> {state:json:"{\"type\":[\"object\",\"null\"]}" requested:json:"{\"type\":\"object\"}" ..} -- Return app-observed PDF state and separately requested source/page
C neyvia.pdf.state visible-source:neyvia.pdf.state() .state.source == source
C neyvia.pdf.state visible-text:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["text"] == phrase
C neyvia.pdf.state visible-page:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["page"] == page
C neyvia.pdf.state fresh-page:neyvia.pdf.state() .fresh == true
C neyvia.pdf.state canvas-not-blank:neyvia.pdf.state() .outcome.nonBlank == true
C neyvia.pdf.state text-layer-ready:neyvia.pdf.state() .outcome.textLayerPresent == true
C neyvia.pdf.state text-layer-phrase:neyvia.pdf.state() .outcome.text has phrase
-- @record {"chapter":"overview","data":{"effect":"Read real page text with explicit truncation; no OCR","pre":"Open PDF source still valid; page in range; maxChars 512–100000","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.pdf.extract_text","tool":"neyvia.pdf.extract_text"},"key":"pdf.extract_text","section":"actions"}
A neyvia.pdf.extract_text(page?:1.. maxChars?:512..100000) -> json:"{\"type\":\"object\"}" -- Read real page text with explicit truncation; no OCR
C neyvia.pdf.extract_text page-text:neyvia.pdf.extract_text(page:page) .text has phrase
-- @record {"chapter":"overview","data":{"effect":"Emit page navigation; actual visible page awaits app state report","pre":"Open PDF source still valid; integer page 1..page count","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.pdf.goto","tool":"neyvia.pdf.goto"},"key":"pdf.goto","section":"actions"}
A neyvia.pdf.goto(page:1..) -> json:"{\"type\":\"object\"}" -- Emit page navigation; actual visible page awaits app state report
F verify-pdf-goto "No authored observer check is bound to neyvia.pdf.goto" -> ask operator blocks:neyvia.pdf.goto
-- @record {"chapter":"overview","data":{"effect":"Emit highlight overlay request with optional note; does not rewrite PDF or confirm rendering","pre":"Open PDF and valid page; either nonempty finite four-coordinate rectangles or text found on that page (first 100000 chars)","returns":{"$cl_type":"t10"},"reversible":false,"schema":"neyvia.pdf.highlight","tool":"neyvia.pdf.highlight"},"key":"pdf.highlight","section":"actions"}
A neyvia.pdf.highlight(page:1.. text?:str rects?:json:"{\"type\":\"array\"}" note?:str) -> json:"{\"type\":\"object\"}" -- Emit highlight overlay request with optional note; does not rewrite PDF or confirm rendering
F verify-pdf-highlight "No authored observer check is bound to neyvia.pdf.highlight" -> ask operator blocks:neyvia.pdf.highlight
-- @record {"chapter":"overview","data":{"effect":"Read PDF metadata, persist requested source/page and emit open; preserve source, uiVerified=false","pre":"Existing local .pdf under workspace/repo/registered project, %PDF- header within 1024 bytes, selected page within page count","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.pdf.open","tool":"neyvia.pdf.open"},"key":"pdf.open","section":"actions"}
A neyvia.pdf.open(source:str page?:1..) -> json:"{\"type\":\"object\"}" -- Read PDF metadata, persist requested source/page and emit open; preserve source, uiVerified=false
C neyvia.pdf.open requested-source:neyvia.pdf.state() .requested.source == source
-- @record {"chapter":"overview","data":{"effect":"Search parsed PDF text, emit the query and require a fresh renderer report of that query and its hit count","pre":"Open PDF source still valid; literal query, maxHits 1–10000","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.pdf.search","tool":"neyvia.pdf.search"},"key":"pdf.search","section":"actions"}
A neyvia.pdf.search(query?:str maxHits?:1..10000) -> json:"{\"type\":\"object\"}" -- Search parsed PDF text, emit the query and require a fresh renderer report of that query and its hit count
F verify-pdf-search "No authored observer check is bound to neyvia.pdf.search" -> ask operator blocks:neyvia.pdf.search
-- @record {"chapter":"overview","data":{"effect":"Emit zoom request; user app reports rendered scale separately","pre":"Open PDF with valid page; scale is fit-width or numeric 0.25–5","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.pdf.zoom","tool":"neyvia.pdf.zoom"},"key":"pdf.zoom","section":"actions"}
A neyvia.pdf.zoom(scale:json:"{\"oneOf\":[{\"type\":\"number\",\"minimum\":0.25,\"maximum\":5},{\"type\":\"string\",\"enum\":[\"fit-width\"]}]}") -> json:"{\"type\":\"object\"}" -- Emit zoom request; user app reports rendered scale separately
F verify-pdf-zoom "No authored observer check is bound to neyvia.pdf.zoom" -> ask operator blocks:neyvia.pdf.zoom
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"requested.source","value":{"$path":"source"}},"tool":"neyvia.pdf.state"},"key":"requested-source","section":"checks"}
C neyvia.pdf.state requested-source:neyvia.pdf.state() .requested.source == source
-- @record {"chapter":"overview","data":{"args":{"page":{"$input":"page"}},"expect":{"op":"contains","path":"text","value":{"$input":"phrase"}},"tool":"neyvia.pdf.extract_text"},"key":"page-text","section":"checks"}
C neyvia.pdf.extract_text page-text:neyvia.pdf.extract_text(page:page) .text has phrase
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"state.source","value":{"$path":"source"}},"tool":"neyvia.pdf.state"},"key":"visible-source","section":"checks"}
C neyvia.pdf.state visible-source:neyvia.pdf.state() .state.source == source
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":["state","highlights",{"$input":"markIndex"},"text"],"value":{"$input":"phrase"}},"tool":"neyvia.pdf.state"},"key":"visible-text","section":"checks"}
C neyvia.pdf.state visible-text:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["text"] == phrase
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":["state","highlights",{"$input":"markIndex"},"page"],"value":{"$input":"page"}},"tool":"neyvia.pdf.state"},"key":"visible-page","section":"checks"}
C neyvia.pdf.state visible-page:neyvia.pdf.state() ["state"] ["highlights"] [markIndex] ["page"] == page
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"fresh","value":true},"tool":"neyvia.pdf.state"},"key":"fresh-page","section":"checks"}
C neyvia.pdf.state fresh-page:neyvia.pdf.state() .fresh == true
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"outcome.nonBlank","value":true},"tool":"neyvia.pdf.state"},"key":"canvas-not-blank","section":"checks"}
C neyvia.pdf.state canvas-not-blank:neyvia.pdf.state() .outcome.nonBlank == true
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"outcome.textLayerPresent","value":true},"tool":"neyvia.pdf.state"},"key":"text-layer-ready","section":"checks"}
C neyvia.pdf.state text-layer-ready:neyvia.pdf.state() .outcome.textLayerPresent == true
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"contains","path":"outcome.text","value":{"$input":"phrase"}},"tool":"neyvia.pdf.state"},"key":"text-layer-phrase","section":"checks"}
C neyvia.pdf.state text-layer-phrase:neyvia.pdf.state() .outcome.text has phrase
-- @record {"chapter":"overview","data":{"goal":"Open a local PDF, search a passage, review the chosen page and emit a highlight overlay","inputs":{"$cl_type":"t11"},"steps":[{"action":"pdf.open","args":{"page":{"$input":"page"},"source":{"$path":"source"}},"check":"requested-source","save":"opened"},{"action":"pdf.search","args":{"query":{"$input":"phrase"}},"save":"hits"},{"action":"pdf.extract_text","args":{"page":{"$input":"page"}},"check":"page-text","save":"text"},{"judge":"passage"},{"action":"pdf.goto","args":{"page":{"$input":"page"}},"save":"navigated","when":{"judge":"passage","option":"highlight"}},{"action":"pdf.highlight","args":{"page":{"$input":"page"},"text":{"$input":"phrase"}},"save":"highlightRequest","when":{"judge":"passage","option":"highlight"}}]},"key":"find-and-highlight","section":"procedures"}
P find-and-highlight(source:str page:1.. phrase:str):opened=neyvia.pdf.open(page:page source:source) C requested-source; hits=neyvia.pdf.search(query:phrase); text=neyvia.pdf.extract_text(page:page) C page-text; J passage=highlight; navigated=neyvia.pdf.goto(page:page); highlightRequest=neyvia.pdf.highlight(page:page text:phrase) -- Open a local PDF, search a passage, review the chosen page and emit a highlight overlay
V P find-and-highlight -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Open and verify text on a known page; no rendering claim","inputs":{"$cl_type":"t11"},"steps":[{"action":"pdf.open","args":{"page":{"$input":"page"},"source":{"$path":"source"}},"check":"requested-source","save":"opened"},{"action":"pdf.extract_text","args":{"page":{"$input":"page"}},"check":"page-text","save":"text"}]},"key":"open-and-read","section":"procedures"}
P open-and-read(source:str page:1.. phrase:str):opened=neyvia.pdf.open(page:page source:source) C requested-source; text=neyvia.pdf.extract_text(page:page) C page-text -- Open and verify text on a known page; no rendering claim
V P open-and-read -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"After user app acknowledgement, verify source and the selected observed highlight text/page","inputs":{"$cl_type":"t12"},"steps":[{"action":"pdf.state","args":{},"check":"visible-source","save":"source"},{"action":"pdf.state","args":{},"check":"visible-text","save":"text"},{"action":"pdf.state","args":{},"check":"visible-page","save":"page"}]},"key":"verify-visible-highlight","section":"procedures"}
P verify-visible-highlight(source:str phrase:str page:1.. markIndex:0..):source=neyvia.pdf.state() C visible-source; text=neyvia.pdf.state() C visible-text; page=neyvia.pdf.state() C visible-page -- After user app acknowledgement, verify source and the selected observed highlight text/page
V P verify-visible-highlight -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Set a PDF zoom and verify the user app reports the requested scale","inputs":{"$cl_type":"t13"},"steps":[{"action":"pdf.zoom","args":{"scale":{"$input":"scale"}},"save":"zoomed"}]},"key":"set-visible-zoom","section":"procedures"}
P set-visible-zoom(scale:json:"{\"oneOf\":[{\"type\":\"number\",\"minimum\":0.25,\"maximum\":5},{\"type\":\"string\",\"enum\":[\"fit-width\"]}]}"):zoomed=neyvia.pdf.zoom(scale:scale) -- Set a PDF zoom and verify the user app reports the requested scale
V P set-visible-zoom -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"The current mounted page has real ink and the requested phrase in its selectable text layer","inputs":{"$cl_type":"t14"},"steps":[{"action":"pdf.state","args":{},"check":"fresh-page","save":"observed0"},{"action":"pdf.state","args":{},"check":"canvas-not-blank","save":"observed1"},{"action":"pdf.state","args":{},"check":"text-layer-ready","save":"observed2"},{"action":"pdf.state","args":{},"check":"text-layer-phrase","save":"observed3"}]},"key":"verify-rendered-page","section":"procedures"}
P verify-rendered-page(phrase:str#1..):observed0=neyvia.pdf.state() C fresh-page; observed1=neyvia.pdf.state() C canvas-not-blank; observed2=neyvia.pdf.state() C text-layer-ready; observed3=neyvia.pdf.state() C text-layer-phrase -- The current mounted page has real ink and the requested phrase in its selectable text layer
V P verify-rendered-page -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Read hits and page text; input page must be the intended occurrence, not simply first hit. Text highlights exact phrase; use rectangles only for visual selection with known PDF-point coordinates.","options":["highlight","leave"],"question":"Which occurrence deserves the highlight?"},"key":"passage","section":"judge"}
J passage highlight|leave:"Which occurrence deserves the highlight?" -- Read hits and page text; input page must be the intended occurrence, not simply first hit. Text highlights exact phrase; use rectangles only for visual selection with known PDF-point coordinates.
V J passage -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"Open or goto page outside PDF count","recovery":"Read metadata.pages and choose 1-based existing page"},"key":"0","section":"pitfalls"}
X Open or goto page outside PDF count -> Read metadata.pages and choose 1-based existing page
-- @record {"chapter":"overview","data":{"failure":"Highlight text was not found","recovery":"Extract same page, correct literal text or use explicit finite rectangle coordinates; never claim successful overlay"},"key":"1","section":"pitfalls"}
X Highlight text was not found -> Extract same page, correct literal text or use explicit finite rectangle coordinates; never claim successful overlay
-- @record {"chapter":"overview","data":{"failure":"Extracted text truncated / search hits truncated","recovery":"Increase bounded maxChars/maxHits or narrow page/query; absence in a truncated result is inconclusive"},"key":"2","section":"pitfalls"}
X Extracted text truncated / search hits truncated -> Increase bounded maxChars/maxHits or narrow page/query; absence in a truncated result is inconclusive
-- @record {"chapter":"overview","data":{"failure":"Command returned uiVerified=false","recovery":"Read state.state observedAt/page/highlights after app consumption; requested is only intent"},"key":"3","section":"pitfalls"}
X Command returned uiVerified=false -> Read state.state observedAt/page/highlights after app consumption; requested is only intent
-- @record {"chapter":"overview","data":{"failure":"Scanned PDF has empty text","recovery":"Text extraction has no OCR; take separate OCR route with its own evidence"},"key":"4","section":"pitfalls"}
X Scanned PDF has empty text -> Text extraction has no OCR; take separate OCR route with its own evidence
-- @record {"chapter":"overview","data":"OCR, encrypted-document handling and semantic match selection are unmapped","key":"0","section":"frontier"}
F OCR, encrypted-document handling and semantic match selection are unmapped
-- @record {"chapter":"overview","data":"Highlights are overlays; no tool persists annotations into PDF bytes","key":"1","section":"frontier"}
F Highlights are overlays; no tool persists annotations into PDF bytes
-- @record {"chapter":"overview","data":"Browser upload handles and remote URLs are not valid local PDF sources","key":"2","section":"frontier"}
F Browser upload handles and remote URLs are not valid local PDF sources
-- @record {"chapter":"overview","data":"CL PDF effects require a fresh ready renderer report for the same guarded source; a queued event alone does not complete the action.","key":"3","section":"frontier"}
F CL PDF effects require a fresh ready renderer report for the same guarded source; a queued event alone does not complete the action.
-- @record {"chapter":"overview","data":"Rectangle-only highlight geometry is not present in the renderer state report, so CL refuses rectangle arguments until a geometry observer is wired.","key":"4","section":"frontier"}
F Rectangle-only highlight geometry is not present in the renderer state report, so CL refuses rectangle arguments until a geometry observer is wired.
-- @record {"chapter":"overview","data":"Source: src/grant_agent/neyvia_pdf_tools.py (safe_pdf, call_pdf, report_pdf_state), pdf_document.py; scripts/verify-grounded-manuals.mjs.","key":"0","section":"guidance"}
M pdf "Source: src/grant_agent/neyvia_pdf_tools.py (safe_pdf, call_pdf, report_pdf_state), pdf_document.py; scripts/verify-grounded-manuals.mjs." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Choose markIndex from observed state.highlights, not a search-hit index; null state or wrong source/page/text fails verification. Source: web/src/neyvia/next/NxPdfApp.jsx reports real highlights.","key":"1","section":"guidance"}
M pdf "Choose markIndex from observed state.highlights, not a search-hit index; null state or wrong source/page/text fails verification. Source: web/src/neyvia/next/NxPdfApp.jsx reports real highlights." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"A PDF search is a visible renderer mutation; CL requires the reported query and hits, while extracted text remains a source read.","key":"2","section":"guidance"}
M pdf "A PDF search is a visible renderer mutation; CL requires the reported query and hits, while extracted text remains a source read." src:"authored manual" state:verified
L pdf.proofs-e-shell v1 -- PROOFS-e shell state and action contracts
-- @record {"chapter":"proofs-e-shell","data":{"args":{},"inputs":{"$cl_type":"t6"},"shape":{"$cl_type":"t15"},"tool":"neyvia.verify.status"},"key":"receipt","section":"state"}
S pdf.receipt:{ok:bool ..}=neyvia.verify.status()
-- @record {"chapter":"proofs-e-shell","data":{"effect":"Read the latest verification receipt without repeating shell actions","pre":"Selected local workspace; read only","returns":{"$cl_type":"t16"},"reversible":true,"schema":"proofs-e-shell.status","tool":"neyvia.verify.status"},"key":"status","section":"actions"}
A neyvia.verify.status() -> json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}" -- Read the latest verification receipt without repeating shell actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-shell","data":{"args":{},"expect":{"op":"eq","path":"ok","value":true},"tool":"neyvia.verify.status"},"key":"observed","section":"checks"}
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-shell","data":{"goal":"Observe the latest shell proof receipt without replaying mutations","inputs":{"$cl_type":"t6"},"steps":[{"action":"status","args":{},"check":"observed","save":"receipt"}]},"key":"read-shell-proof-receipt","section":"procedures"}
P read-shell-proof-receipt():receipt=neyvia.verify.status() C observed -- Observe the latest shell proof receipt without replaying mutations
V P read-shell-proof-receipt -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"proofs-e-shell","data":{"failure":"A queue or shell state receipt is treated as rendered app proof","recovery":"Inspect the owned running UI and actual PDF/output/provider separately"},"key":"0","section":"pitfalls"}
X A queue or shell state receipt is treated as rendered app proof -> Inspect the owned running UI and actual PDF/output/provider separately
-- @record {"chapter":"proofs-e-shell","data":"Rendered shell journeys and PDF loading require owned UI proof","key":"0","section":"frontier"}
F Rendered shell journeys and PDF loading require owned UI proof
-- @record {"chapter":"proofs-e-shell","data":"Provider execution and actual artifact publishing are separate proof boundaries","key":"1","section":"frontier"}
F Provider execution and actual artifact publishing are separate proof boundaries
-- @record {"chapter":"proofs-e-shell","data":"pdf.open selects the Documents PDF app; later commands require it open and enter the ordered inbox; invalid pages/scales/text are refused","key":"0","section":"guidance"}
M pdf "pdf.open selects the Documents PDF app; later commands require it open and enter the ordered inbox; invalid pages/scales/text are refused" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions","key":"1","section":"guidance"}
M pdf "Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions" src:"authored manual" state:verified
