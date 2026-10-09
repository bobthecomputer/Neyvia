"""Durable adaptive-work state: explicit blockers, evidence, constraints and focus."""
from __future__ import annotations
import copy, hashlib, json, re, uuid, os, time
from datetime import datetime, timezone
from pathlib import Path
from .durability import atomic_write_json, append_jsonl_durable
from .harness_jobs import _exclusive_job_lock

SCHEMA = "neyvia.adaptive_work.v1"
def _now(): return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def _id(v):
    text = str(v)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}", text):
        # Context sessions can contain provider-specific punctuation. Hash the
        # original rather than silently aliasing distinct sessions.
        return "session-" + hashlib.sha256(text.encode()).hexdigest()
    return text
def _hash(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class AdaptiveWorkStore:
    def __init__(self, root: str|Path, work_id: str):
        self.root=Path(root).resolve(); self.work_id=_id(work_id); self.base=self.root/".agent_control"/"adaptive_work"; self.base.mkdir(parents=True,exist_ok=True)
        self.path=self.base/f"{self.work_id}.json"; self.events=self.base/f"{self.work_id}.events.jsonl"
        with _exclusive_job_lock(self.path):
            if not self.path.exists(): self._write(self._empty())
    def _empty(self): return {"schema":SCHEMA,"workId":self.work_id,"revision":0,"focus":{"text":"","source":"","changedAt":None},"problems":[],"dependencies":[],"evidence":[],"constraints":[],"focusHistory":[]}
    def _read(self):
        try: state=json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError: state=self._empty()
        except (OSError,json.JSONDecodeError) as exc: raise ValueError(f"corrupt adaptive work state: {self.path}") from exc
        if self.path.exists() and state.get("schema") != SCHEMA: raise ValueError(f"corrupt adaptive work state: {self.path}")
        if state.get("schema")!=SCHEMA: raise ValueError("invalid adaptive work state")
        if state.get("integritySha256") != _hash({k:v for k,v in state.items() if k != "integritySha256"}):
            raise ValueError("adaptive work integrity mismatch")
        return state
    def _write(self,state): state["integritySha256"]=_hash({k:v for k,v in state.items() if k!="integritySha256"}); atomic_write_json(self.path,state)
    def _mutate(self,event,payload,fn):
        with _exclusive_job_lock(self.path):
            state=self._read(); fn(state); state["revision"]+=1; state["updatedAt"]=_now(); self._write(state); append_jsonl_durable(self.events,{"schema":SCHEMA,"event":event,"revision":state["revision"],"payload":payload,"createdAt":state["updatedAt"]}); return copy.deepcopy(state)
    def snapshot(self): return copy.deepcopy(self._read())
    def record_problem(self, problem, *, status="open", blocker="", source=""):
        row={"id":f"problem-{uuid.uuid4().hex[:12]}","text":str(problem),"status":status,"blocker":blocker,"source":source,"createdAt":_now()}
        return self._mutate("problem_recorded",row,lambda s:s["problems"].append(row))
    def record_dependency(self, dependency, *, status="open", source=""):
        row={"id":f"dependency-{uuid.uuid4().hex[:12]}","text":str(dependency),"status":status,"source":source,"createdAt":_now()}
        return self._mutate("dependency_recorded",row,lambda s:s["dependencies"].append(row))
    def update_problem(self, problem_id, *, status="open", need="inspect"):
        if status not in {"open", "resolved", "blocked"} or need not in {"inspect", "generate", "implement", "compare", "test", "retrieve", "reflect"}:
            raise ValueError("Unsupported problem status or next action")
        def apply(s):
            row = next((r for r in s["problems"] if r["id"] == problem_id), None)
            if row is None: raise KeyError(problem_id)
            row.update(status=status, need=need)
        return self._mutate("problem_updated", {"problemId":problem_id,"status":status,"need":need}, apply)
    def record_evidence(self, claim, *, status="unverified", identity="", sha256="", source=""):
        # This is a reporting API. A caller-provided label or hash cannot prove
        # a claim; trusted verification remains in operation/proof receipts.
        status = "unverified" if status in ("reported", "observed", "claimed", "verified") else status
        if status not in {"unverified", "failed", "contradicted", "stale"}:
            raise ValueError("Unsupported evidence observation status")
        row={"id":f"evidence-{uuid.uuid4().hex[:12]}","claim":str(claim),"status":status,"identity":identity,"sha256":sha256,"source":source,"createdAt":_now()}
        def apply(s):
            for old in s["evidence"]:
                if old.get("claim")==row["claim"] and old.get("status")=="unverified" and status in {"failed", "contradicted"}: old["status"]="contradicted"; row.setdefault("contradicts",[]).append(old["id"])
            s["evidence"].append(row)
        return self._mutate("evidence_recorded",row,apply)
    def record_constraint(self, text, *, source=""):
        row={"id":f"constraint-{uuid.uuid4().hex[:12]}","text":str(text),"source":source,"createdAt":_now()}
        return self._mutate("constraint_recorded",row,lambda s:s["constraints"].append(row))
    def change_focus(self, text, *, source=""):
        def apply(s):
            s["focus"]={"text":str(text),"source":source,"changedAt":_now()}; s["focusHistory"].append(copy.deepcopy(s["focus"]))
        return self._mutate("focus_changed",{"text":str(text),"source":source},apply)
    def next_action(self):
        s=self._read();
        if any(x.get("status")=="contradicted" for x in s["evidence"]): return {"kind":"test","reason":"contradictory_evidence","source":"adaptive-work"}
        problem = next((x for x in s["problems"] if x.get("status")=="open"), None)
        if problem: return {"kind":problem.get("need","inspect"),"problemId":problem["id"],"reason":"open_problem","source":"adaptive-work","proposal":True}
        if any(x.get("status")=="open" for x in s["dependencies"]): return {"kind":"retrieve","reason":"open_dependency","source":"adaptive-work"}
        if any(x.get("status") in ("unverified","contradicted") for x in s["evidence"]): return {"kind":"test","reason":"evidence_unverified_or_contradicted","source":"adaptive-work"}
        return {"kind":"reflect","reason":"no_open_problem_dependency_or_evidence_gap","source":"adaptive-work"}
    def packet(self, *, token_budget=700):
        s=self._read(); packet={"schema":"neyvia.adaptive_work.packet.v1","workId":self.work_id,"revision":s["revision"],"focus":s["focus"],"constraints":s["constraints"],"problems":s["problems"][-8:],"dependencies":s["dependencies"][-8:],"evidence":s["evidence"][-8:],"nextAction":self.next_action(),"retrieval":{"statePath":str(self.path),"eventsPath":str(self.events)}}
        packet["constraints"] = list(packet["constraints"])
        limit=max(720,int(token_budget)*4)
        while len(json.dumps(packet,ensure_ascii=False,separators=(",",":")))>limit and (packet["evidence"] or packet["dependencies"] or packet["problems"]):
            target=packet["evidence"] or packet["dependencies"] or packet["problems"]; target.pop(0)
        def size(): return len(json.dumps(packet,ensure_ascii=False,separators=(",",":")))
        packet["omitted"] = {key: len(s[key])-len(packet[key]) for key in ("evidence","dependencies","problems")}
        while size()>limit and packet["constraints"]:
            packet["constraints"].pop(); packet["omitted"]["constraints"]=packet["omitted"].get("constraints",0)+1
        if size()>limit: packet["focus"]={"text": str(s["focus"].get("text", ""))[:80], "truncated":True}
        if size()>limit: packet["focus"]={"truncated":True}
        if size()>limit:
            packet={"schema":packet["schema"],"workId":self.work_id,"revision":s["revision"],"truncated":True,"retrieval":{"statePath":str(self.path)}}
        missing = len(s["constraints"]) - len(packet.get("constraints", []))
        if missing:
            packet["executionReady"] = False
            packet["requiredConstraintsOmitted"] = missing
            packet["nextAction"] = {"kind": "retrieve", "reason": "protected_constraints_omitted", "tool": "work.state"}
            if size()>limit:
                packet={"schema":packet["schema"],"workId":self.work_id,"revision":s["revision"],
                        "executionReady":False,"requiredConstraintsOmitted":len(s["constraints"]),
                        "nextAction":{"kind":"retrieve","reason":"protected_constraints_omitted","tool":"work.state"}}
        return packet
