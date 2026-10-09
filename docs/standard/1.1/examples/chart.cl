CL 1.1
-- Image/chart layer (T18). Same sources and real extraction as 1.0 (../../examples/chart.cl, ../../examples/today/chart.*).

-- L0
L img v2 untrusted -- images: text, objects, charts (transcribed)

-- L1
A img.observe(path, frame?: int) -> image -- vision transcription, ~15k tokens and ~17 s; 0 when cached
A img.check(ref, path, equals) -> bool -- checks the stored observation
A project(ref, path?, start?, count?) -> rows
X a value marked "uncertain" or "unreadable" -> find the source data; never invent numbers

-- runtime
img.observe(path="chart.png")
R img.observe ok h1 cached
S img h1 "chart.png" width=900 height=600 format="PNG" via="gpt-6-luna"
E chart "bar chart" "Monthly orders (units)"
 E axis "x" label=null unit=null certainty="uncertain"
 E axis "y" label="Monthly orders" unit="units"
 E series "Monthly orders" {"Jan": 14, "Feb": 27, "Mar": 19, "Apr": 34}
E more text=14 objects=4 layout=1 -- project(h1, "text") to read them
Q "Are 14, 27, 19, 34 exact source numbers?" -> find the source file -- host: certainty is transcription, not exact data

-- host
A img.observe(path:path frame?:int) -> image = perception.observe(layer="image" source={path frame})
-- the default view shows charts; text boxes, objects and layout stay behind the ref (1.0 §4 `^` fields).
