"""Use this checkout's real read-only stdio MCP, without changing attachments."""
import json
import hashlib
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/"src"))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from grant_agent.transition_memory import atomic_json

evidence = REPO/"scripts/evidence"
origin = evidence/"C10-tools-runs/valid-before/web-runtime/.agent_control/web_documents.sqlite3"
root = evidence/"C10-tools-runs/mcp-runtime"
database = root/".agent_control/web_documents.sqlite3"
database.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(origin) as source, sqlite3.connect(database) as destination:
    source.backup(destination)
env = {**os.environ,"NEYVIA_TOOL_AUTO_UPDATE":"0","NEYVIA_COORDINATOR_AUTOSTART":"0","FLUXIO_WATCHDOG_AUTOSTART":"0"}
process = subprocess.Popen([sys.executable,str(REPO/"src/grant_agent/neyvia_mcp_bootstrap.py"),"--root",str(root),"--read-only"],
    cwd=REPO,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",
    **hidden_windows_subprocess_kwargs())
responses = queue.Queue()
def read():
    for line in process.stdout:
        try: responses.put(json.loads(line))
        except ValueError: continue
threading.Thread(target=read,daemon=True).start()
sequence = 0
def rpc(name, arguments):
    global sequence
    sequence += 1
    message = {"jsonrpc":"2.0","id":sequence,"method":"tools/call","params":{"name":name,"arguments":arguments}}
    if name == "initialize": message.update(method="initialize",params=arguments)
    process.stdin.write(json.dumps(message)+"\n")
    process.stdin.flush()
    result = responses.get(timeout=60)
    if result.get("error"): raise ValueError(result["error"])
    return result["result"]
try:
    initialization = rpc("initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"C10-real-tool-gate","version":"1"}})
    process.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"})+"\n");process.stdin.flush()
    if "--contracts" in sys.argv:
        from c10_tools import report
        report()
        report_path = root/"tool-gate/receipt.json"
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_bytes((evidence/"C10-tools.json").read_bytes())
        manual = rpc("neyvia.cl",{"lines":'help("research-assistant")'})
        authored = json.loads((REPO/"manuals/research-assistant.manual.json").read_text(encoding="utf-8"))
        outcomes = []
        for name in authored["chapters"]["tool-gate"]["procedures"]:
            result = rpc("neyvia.cl",{"lines":f'run research-assistant.{name}(path="tool-gate/receipt.json")'})
            value = result.get("structuredContent",{})
            outcomes.append({"procedure":name,"ok":value.get("ok",False),"result":result})
        receipt = {"schema":"neyvia.C10.tools.CL-contracts.v1","protocolVersion":initialization.get("protocolVersion"),
            "reportSha256":hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "boundary":"Real task-local initialized read-only MCP; byte-identical benchmark receipt, authored CL checks; no model/provider call",
            "manualLoaded":not manual.get("isError"),"contracts":len(outcomes),"passed":sum(row["ok"] for row in outcomes),"rows":outcomes}
        atomic_json(evidence/"C10-tools-contracts.json",receipt)
        print(json.dumps({k:v for k,v in receipt.items() if k!="rows"}))
        print(json.dumps([{k:v for k,v in row.items() if k!="result"} for row in outcomes]))
        sys.exit(0)
    manual = rpc("neyvia.cl",{"lines":'help("web")'})
    described = rpc("neyvia.tools.describe",{"name":"web.dedupe"})
    saved = json.loads((evidence/"C10-tools-runs/valid-before/web-read.json").read_text(encoding="utf-8"))["rows"]
    rows = []
    for i in range(20):
        first = saved[i % len(saved)]["document"]
        second = saved[(i+1) % len(saved)]["document"]
        members = [first,first] if i%2 == 0 else [first,second]
        started = time.perf_counter()
        result = rpc("neyvia.native.call",{"toolId":"web.dedupe","arguments":{"documents":members}})
        value = result.get("structuredContent",{})
        while isinstance(value.get("result"),dict): value=value["result"]
        rows.append({"id":i,"members":members,"correct":not result.get("isError") and len(value.get("groups",[]))==len(set(members)),
                     "ms":(time.perf_counter()-started)*1000,"result":result})
    receipt = {"schema":"neyvia.C10.tools.mcp.v1","boundary":"Fresh task-local real read-only stdio MCP; attached server and public services untouched",
               "protocolVersion":initialization.get("protocolVersion"),"serverInfo":initialization.get("serverInfo"),
               "manualLoaded":not manual.get("isError"),"toolDescribed":not described.get("isError"),
               "cases":20,"correct":sum(r["correct"] for r in rows),"rows":rows}
    atomic_json(evidence/"C10-tools-mcp-initialized.json",receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!="rows"}))
finally:
    process.stdin.close()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate();process.wait(timeout=10)
