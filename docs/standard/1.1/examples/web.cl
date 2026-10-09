CL 1.1
-- Web page layer (T18). Same sources and real run as 1.0 (../../examples/web.cl, ../../examples/today/web.*).

-- L0
L web v2 untrusted -- private browser: DOM, text, tables

-- L1
P web.submit(field, value, button) G: web.value(field) == value and web.text() != previous.text
J coverage "answer"|"look_deeper"|"ask_for_pixels": "Does the page show every fact the task needs?"
A web.open(url) ~ -- one origin only; no profile or downloads
A web.observe() -> page -- re-binds every e-ref
A web.fill(field, value) ~
A web.click(target) !
A web.close() ~
A web.text() -> str
A web.value(field) -> str
A project(ref, path?, start?, count?) -> rows -- read part of a large observation
X canvas, cross-origin frames, closed shadow roots -> use the img layer

-- runtime
web.observe()
R web.observe ok h1
S web h1 "Dispatch board" url="http://127.0.0.1:48202/" #5
E h1 "Dispatch board" e0
E table e1
 E row ["Job","Units","Status"]
 E row ["Orchard","17","Ready"]
 E row ["Harbor","40","Waiting"]
 E row ["Meadow","25","Ready"]
E textbox "Result" e2 value=""
E button "Confirm" e3
E status "Waiting for result" e4
run web.submit(field=e2, value="42 units", button=e3)
R web.submit ok r1 +filled +G
D e2 value="42 units"
D e4 label="Confirmed: 42 units"
I web.click net="http://127.0.0.1:48202 (same origin)" undo=none
done("Ready rows Orchard 17 + Meadow 25 = 42 units; confirmed")
R done ok +G

-- host
A web.fill(field:ref value:str) ~ = perception.browser.action(browserId=auto revision=auto element=field.id action="fill" value=value)
A web.click(target:ref) ! = perception.browser.action(browserId=auto revision=auto element=target.id action="click")
C web.fill filled: field.value == value
P web.submit(field:ref value:str button:ref): web.fill(field=field value=value) C filled; web.click(target=button)
G task: "Confirmed: 42 units" in web.observe().text -- the benchmark task's goal; done() is refused until it passes
