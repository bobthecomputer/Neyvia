"""Real compiled native UI build/action/app-written effect proof, not a suite."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from grant_agent.cua_native import NativeWorker


def run():
    scratch=ROOT/".agent_control/c1b-native"/str(time.time_ns())
    scratch.mkdir(parents=True)
    state=scratch/"window.txt"
    framework=Path(os.environ.get("WINDIR","C:/Windows"))/"Microsoft.NET/Framework64/v4.0.30319"
    binary=scratch/"C1bNativeProbe.exe"
    source=ROOT/"tools/cua-driver-win/c1-probe.cs"
    subprocess.run([str(framework/"csc.exe"),"/nologo","/target:winexe","/out:"+str(binary),str(source),
        "/reference:"+str(framework/"System.Windows.Forms.dll"),"/reference:"+str(framework/"System.Drawing.dll")],
        capture_output=True,check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    worker=NativeWorker();proc=None
    receipt={"schema":"neyvia.c1b.native-proof.v1","boundary":"Real disposable WinForms app; not the 15-app cohort","runs":[],"ok":False,
        "sourceSha256":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            "src/grant_agent/cua_fast.py","src/grant_agent/cua_native.py","tools/cua-driver-win/NativeWorker.cs",
            "tools/cua-driver-win/json-host.cs","tools/cua-driver-win/c1-probe.cs","scripts/prove_c1b_native.py")}}
    try:
        receipt["desktop"]=worker.request("desktopStatus",timeout=30)
        proc=subprocess.Popen([str(binary),str(state)],creationflags=subprocess.CREATE_NO_WINDOW)
        until=time.monotonic()+55
        while not state.exists() and time.monotonic()<until:time.sleep(.05)
        if not state.exists():raise RuntimeError("Owned application launch did not complete")
        h=state.read_text().strip();w=worker.request("window",{"windowId":h})
        if w["pid"]!=proc.pid:raise RuntimeError("Owned window PID mismatch")
        receipt["window"]={k:w[k] for k in ("windowId","pid","processStartTime","processName")}
        worker.request("windows")
        # First-use protection metadata has an independent MTA startup. Retry
        # observation without dispatching anything until safe fields are known.
        for _ in range(20):
            observed=worker.request("inspect",{"windowId":h,"maxDepth":12,"maxNodes":256})
            if any(r["role"]=="Edit" and r["name"]=="Task input" and not r["isPassword"] for r in observed["tree"]):break
            time.sleep(.05)
        for repeat in range(5):
            observed=worker.request("inspect",{"windowId":h,"maxDepth":12,"maxNodes":256})
            edits=[r for r in observed["tree"] if r["role"]=="Edit" and r["name"]=="Task input" and r["enabled"] and not r["isPassword"] and not r["offscreen"]]
            buttons=[r for r in observed["tree"] if r["role"]=="Button" and r["name"]=="Apply"]
            if len(edits)!=1 or len(buttons)!=1:raise RuntimeError("Unique safe real controls unavailable: "+json.dumps(observed))
            value="C1b verified "+str(repeat)
            first=worker.request("cycle",{"windowId":h,"elementId":edits[0]["id"],"action":"editSetValue","text":value,
                "expect":[{"selector":{"id":edits[0]["id"]},"value_equals":value}]})
            second=worker.request("cycle",{"windowId":h,"elementId":buttons[0]["id"],"action":"buttonClick",
                "expect":[{"selector":{"role":"Text","name":"Applied: "+value},"name_contains":value}]})
            written=state.with_name("window.txt.result").read_text()
            passed=first["check"]["status"]==second["check"]["status"]=="satisfied" and written=="Applied: "+value
            receipt["runs"].append({"edit":first,"apply":second,"fileEffect":written,"passed":passed})
            if not passed:raise RuntimeError("Real control/app-written effect verification failed")
        # Stale/foreign token refusal is executed on the actual native client.
        try:
            worker.request("action",{"windowId":h,"elementId":"win32:1","action":"value","text":"must not arrive"})
            raise RuntimeError("Foreign token was accepted")
        except ValueError as exc:receipt["foreignTokenRefused"]=str(exc)
        observed=worker.request("inspect",{"windowId":h,"maxNodes":256})
        receipt["refusals"]={}
        for label in ("Read-only fixture","API key","Password"):
            matches=[r for r in observed["tree"] if r["name"]==label]
            if len(matches)!=1:raise RuntimeError("Protection fixture label unavailable: "+label)
            row=matches[0]
            if label in {"API key","Password"} and (not row["isPassword"] or "value" in row):raise RuntimeError("Protected fixture exposed a value")
            try:
                worker.request("action",{"windowId":h,"elementId":row["id"],"action":"editSetValue","text":"must not arrive"})
                raise RuntimeError("Protected/read-only fixture accepted mutation")
            except ValueError as exc:receipt["refusals"][label]=str(exc)
        option=next(r for r in observed["tree"] if r["name"]=="Include heading")
        receipt["toggle"]=worker.request("cycle",{"windowId":h,"elementId":option["id"],"action":"toggle",
            "expect":[{"selector":{"id":option["id"]},"toggle_equals":1}]})
        if receipt["toggle"]["check"]["status"]!="satisfied":raise RuntimeError("Checkbox state did not change")
        lock=next(r for r in observed["tree"] if r["name"]=="Lock input")
        worker.request("action",{"windowId":h,"elementId":lock["id"],"action":"buttonClick"})
        try:
            worker.request("action",{"windowId":h,"elementId":edits[0]["id"],"action":"editSetValue","text":"must not arrive"})
            raise RuntimeError("Disabled fixture accepted mutation")
        except ValueError as exc:receipt["refusals"]["disabledAfterSnapshot"]=str(exc)
        png=worker.request("capture",{"windowId":h},timeout=.2)
        import base64
        path=ROOT/"scripts/evidence/C1b-native.png"
        path.write_bytes(base64.b64decode(png["pngBase64"]))
        receipt["capture"]={"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        values=sorted(r[k]["elapsedMs"] for r in receipt["runs"] for k in ("edit","apply"))
        def quantile(q):
            position=(len(values)-1)*q;lo=int(position)
            return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(position-lo)
        receipt["atomicLatency"]={"n":len(values),"p50Ms":quantile(.5),"p95Ms":quantile(.95),
            "includes":"NativeClient cycle: observe, dispatch, fresh control check; separate two-step file check recorded per run",
            "cohort":"one disposable compiled WinForms app, five repeats of each of two actions"}
        receipt["ok"]=True
    except Exception as exc:
        receipt["error"]=type(exc).__name__+": "+str(exc)
    finally:
        worker.close()
        if proc and proc.poll() is None:
            proc.terminate();proc.wait(timeout=5)
        encoded=json.dumps(receipt,ensure_ascii=False,indent=2)+"\n"
        (scratch/"receipt.json").write_text(encoded,encoding="utf-8")
        (ROOT/"scripts/evidence/C1b-native.json").write_text(encoded,encoding="utf-8")
    print(json.dumps({"ok":receipt["ok"],"verifiedRuns":sum(r["passed"] for r in receipt["runs"]),"error":receipt.get("error")}),flush=True)
    return receipt["ok"]


if __name__=="__main__":sys.exit(0 if run() else 1)
