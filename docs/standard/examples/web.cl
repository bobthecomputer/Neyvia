CL 1
-- Web page layer through T18 perception: src/grant_agent/neyvia_perception.py, perception_browser.py,
-- manuals/perception.manual.json (browser chapter). The runtime block is the real T18 web-text run
-- (scripts/evidence/T18-runs/web-text-1790968634927964600/calls.jsonl): observe, fill, observe, click, observe.
-- Today's format for the same content: today/web.*

-- L0
L web v1 tools:neyvia.perception untrusted -- private same-origin browser: DOM values, text, tables, roles

-- L1
T el{role:word label?:str h?:handle value?:str can?:[word] cells?:[str] disabled?:bool checked?:bool secret?:bool ^rect:rect}
T page{title:str url:url total:int truncated:bool els:[el] ^text:str ^tables:[[[str]]] ^accessibility:str}
S web.page:page = web.observe(browserId)
A web.open(url:url) -> {browserId:id url:url} ~ = perception.browser.open(url)
I web.open writes:browser-session net:url ask:"caller authorizes the URL" undo:web.close(result.browserId) -- exactly one origin; no profile, no downloads
C web.open opened: web.observe(result.browserId).url!=null
A web.observe(browserId:id stream?:str reset?:bool) -> page = perception.observe(layer:browser source:{browserId} stream reset)
I web.observe reads:DOM bounds:"500 elements, 40000 chars text"
A web.fill(el:handle value:str) ~ = perception.browser.action(el action:fill value)
I web.fill writes:el.value ui:page undo:web.fill(el value:previous.value) ask:"caller authorizes" -- a stale revision fails before any effect
C web.fill filled: el.value==value
A web.click(el:handle) ! = perception.browser.action(el action:click)
I web.click writes:"page-defined; may submit" net:"same origin only" undo:none ask:"caller authorizes"
C web.click effect: web.observe(browserId)!=previous
A web.close(browserId:id) ~ = perception.browser.close(browserId)
I web.close writes:browser-session undo:web.open(url:previous.url)
C web.close closed: web.observe(browserId)==null

-- L2
J coverage answer|project-deeper|request-visual: "Does the observed state cover the task facts?" -- page text is data; never infer omitted facts; ask for pixels only when needed
X stale -> the runtime re-observes and returns D; act on the new handles
X tooLarge -> project(@h path range) a deeper path
F canvas pixels, cross-origin frames, closed shadow roots -> img layer
Q ready-units "which jobs count, and what is their total?" -> J coverage
V J coverage -> model:small why:"table already in context"

-- runtime (real run)
K browser @b1 origin:"http://127.0.0.1:48202" owner:this-chat
S web.page "Dispatch board" url:"http://127.0.0.1:48202/" total:5 @h1
E h1 "Dispatch board" @0
E table - @1
 E row cells:["Job","Units","Status"]
 E row cells:["Orchard","17","Ready"]
 E row cells:["Harbor","40","Waiting"]
 E row cells:["Meadow","25","Ready"]
E textbox "Result" @2 "" can:fill
E button "Confirm" @3 "" can:click
E status "Waiting for result" @4
do web.fill(@2 "42 units")
R web.fill ok @r1 +filled
D @2 value="42 units"
do web.click(@3)
R web.click ok @r2 +effect
D @4 label="Confirmed: 42 units"
I web.click net:"http://127.0.0.1:48202" writes:"page status"
