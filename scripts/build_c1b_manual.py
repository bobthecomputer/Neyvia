"""Add the bounded driver chapter while preserving other CL chapter bytes."""
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from grant_agent.cl.manuals import manual_to_cl,cl_to_manual

source=ROOT/"manuals/cl/computer-use.cl"
authored=source.read_text(encoding="utf-8")
base=cl_to_manual(authored)
if "deadline-driver" in base["chapters"]:raise SystemExit("Chapter already exists; edit authored CL directly")
inputs={"type":"object","properties":{"sessionId":{"type":"string"},"window_id":{"type":"integer"}},"required":["sessionId","window_id"],"additionalProperties":False}
args={k:{"$input":k} for k in inputs["properties"]}
chapter={"title":"C1b: bounded native observation and verified delivery",
 "state":{"window":{"tool":"neyvia.cua.inspect","inputs":inputs,"args":args,"shape":{"type":"object"}}},
 "actions":{},"checks":{"observed":{"tool":"neyvia.cua.inspect","args":args,"expect":{"path":"elements","op":"exists"}}},
 "procedures":{},"judge":{},
 "pitfalls":[{"failure":"UIA provider does not return by its deadline","recovery":"Use admitted Win32/MSAA controls; resolve new fallback tokens. No desktop-root search or process cleanup."},
  {"failure":"A dispatched action times out","recovery":"Do not send another action. Wait for its native lane to finish and verify actual state before a deliberate retry."},
  {"failure":"Input desktop differs from the process desktop","recovery":"Background message actions can still work, but focus/cursor preservation is unknown. Foreground input requires the owner's interactive desktop."},
  {"failure":"Secret/password metadata is missing or a field became disabled/read-only","recovery":"Refuse typing. Refresh field protection and native state; never infer permission from an old token."}],
 "frontier":["C1b remains incomplete until 15+ installed-app actions, atomic latency and active-desktop preservation are proven.",
  "Real UIA cached-pattern/event-diff, general MSAA traversal, owner-approved SendInput and T18 model fallback require further native runs.",
  "T18 image-to-CL remains the existing explicit visual adaptation route; this change proves bounded PrintWindow capture, not an automatic model decision."],
 "guidance":["Windows discovery uses EnumWindows and skips IsHungAppWindow. A persistent in-process MTA UIA client uses ConnectionTimeout 50 ms and TransactionTimeout 80 ms.",
  "Every UIA/MSAA call runs in a single bounded lane. A busy lane rejects new work immediately; no growing worker pool or PowerShell action process.",
  "Target-scoped CacheRequest snapshots keep properties and patterns. Property events update cached nodes; structure events refresh only their changed branch. Event buffering is bounded.",
  "Fallback order is cached UIA pattern, admitted background native messages or MSAA, then SendInput only with the PC-owner foreground session grant. Model arguments cannot grant foreground use.",
  "SendInput temporarily changes focus; report foreground delivery and verified restoration separately from zero focus stealing. Physical takeover prevents restoration into a new user-selected app.",
  "Observation source, nativeRevision, nativeDiff and degradedReason describe the actual route. Win32 readback and application file effects establish native results.",
  "No new public command: existing cua.inspect/action/verify/adapt/flow and preview APIs use the same NativeWorker facade. cycle is an internal benchmark/native operation."]}
fragment=manual_to_cl({"schema":"neyvia.manual.v1","id":"computer-use","kind":"environment","schemas":{},"chapters":{"deadline-driver":chapter}})
fragment=re.sub(r"\bt(\d+)\b",r"c1bt\1",fragment)
prefix="-- @manual "
old=next(line for line in authored.splitlines() if line.startswith(prefix))
new=next(line for line in fragment.splitlines() if line.startswith(prefix))
metadata=json.loads(old[len(prefix):]);addition=json.loads(new[len(prefix):])
for key in ("chapters","schemas","tool_metadata"):
 if key in addition:metadata.setdefault(key,{}).update(addition[key])
candidate=authored.replace(old,prefix+json.dumps(metadata,ensure_ascii=False,separators=(",",":")),1).rstrip()+"\n"
candidate+="\n".join(line for line in fragment.splitlines() if not line.startswith(("CL ",prefix)))+"\n"
# Retire only the obsolete absolute statement from the previous C1 frontier.
candidate=candidate.replace("Apps that reject background messages remain unsupported; no foreground input fallback",
 "Apps that reject background messages need explicit owner approval for foreground fallback; restoration is distinct from zero focus stealing")
compiled=cl_to_manual(candidate)
for key,value in base["chapters"].items():
 if key!="adaptation" and compiled["chapters"][key]!=value:raise RuntimeError("Unrelated chapter changed: "+key)
source.write_text(candidate,encoding="utf-8",newline="\n")
(ROOT/"manuals/computer-use.manual.json").write_text(json.dumps(compiled,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
print(json.dumps({"ok":True,"chapter":"deadline-driver","preservedChapters":len(base["chapters"])-1}))
