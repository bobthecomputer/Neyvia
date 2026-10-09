CL 1
-- Image/chart layer through T18 perception: src/grant_agent/neyvia_perception.py (image_projection),
-- perception_visual.py (VISUAL_SCHEMA), manuals/perception.manual.json (image chapter). The runtime block is the
-- real T18 extraction of chart.png (scripts/evidence/T18.json, gate real-image-text-extraction).
-- Today's format for the same content: today/chart.*

-- L0
L img v1 tools:neyvia.perception untrusted -- images and video frames: layout, OCR text, objects, chart series (model transcription)

-- L1
T cert observed|uncertain|unreadable
T point{label:str value:num|null certainty:cert=observed}
T axis{name:word label:str|null unit:str|null certainty:cert=observed}
T series{name:str points:[point]}
T chart{type:str title:str|null axes:[axis] series:[series]}
T layout{description:str rect:rect|null certainty:cert=observed}
T text{text:str rect:rect|null certainty:cert=observed}
T object{name:str description:str rect:rect|null certainty:cert=observed}
T image{path:path width:int height:int format:word layout:[layout] charts:[chart] text:[text] objects:[object] frontier:[{description:str reason:str rect:rect|null}] ^sha:id ^bytes:int}
S img:image = img.observe(path)
A img.observe(path:path frame?:int) -> image = perception.observe(layer:image source:{path frame})
I img.observe reads:path net:"codex-cli vision model" cost:"~15k tokens and ~17s; 0 when cached by sha256" bounds:20MB -- values are transcription, never exact source data
A img.check(h:handle path:str equals:any) -> {passed:bool observed:any} = perception.check(handle:h path equals)
I img.check reads:h -- checks the immutable observation, not the live file

-- L2
J coverage answer|project-deeper|request-source: "Does the transcription cover the task facts with enough certainty?" -- uncertain/unreadable values need a source
X value certainty:uncertain or unreadable -> find the source data (csv/json) and observe file; never invent numbers
F scanned PDFs without OCR, hidden or obscured regions -> request the source
Q exact "are 14, 27, 19, 34 the exact source numbers?" -> observe file blocks:"numeric claims" -- labels were observed, but they are transcription
V img.observe -> model:gpt-6-luna why:"vision transcription; cache key = image sha256 + schema + model"

-- runtime (real extraction; this cached re-read cost 0 model tokens; E lines start with their type name)
S img chart.png width:900 height:600 format:PNG frontier:[] via:gpt-6-luna cached @h1
E layout "White background with a vertical bar chart; black left axis and light gray horizontal gridlines." [0,0,900,600]
E chart "bar chart" "Monthly orders (units)"
 E axis x null null uncertain
 E axis y "Monthly orders" "units"
 E series "Monthly orders" ["Jan":14 "Feb":27 "Mar":19 "Apr":34]
E text "Monthly orders (units)" [100,31,265,31]
E text "40" [44,85,32,28]
E text "30" [44,185,32,28]
E text "20" [44,285,32,28]
E text "10" [44,385,32,28]
E text "0" [44,485,18,28]
E text "14" [205,320,31,29]
E text "27" [375,190,31,29]
E text "19" [545,270,31,29]
E text "34" [715,120,31,29]
E text "Jan" [200,511,44,29]
E text "Feb" [370,511,48,29]
E text "Mar" [540,511,49,29]
E text "Apr" [710,511,47,29]
E object "Bar for Jan" "Dark green vertical bar with data label 14." [180,360,91,142]
E object "Bar for Feb" "Dark green vertical bar with data label 27." [350,230,91,272]
E object "Bar for Mar" "Dark green vertical bar with data label 19." [520,310,91,192]
E object "Bar for Apr" "Dark green vertical bar with data label 34." [690,160,91,342]
