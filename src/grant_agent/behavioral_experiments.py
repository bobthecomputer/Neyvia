"""Durable observable API experiment ledger; no activation or causal claims."""
from __future__ import annotations
import hashlib,json,math
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Mapping
from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock

def _now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _hash(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class BehavioralExperimentLedger:
    schema="neyvia.behavioral_experiments.v1"
    def __init__(self,path): self.path=Path(path).resolve(); self.path.parent.mkdir(parents=True,exist_ok=True); self.state=self._read()
    def _read(self):
        if not self.path.is_file(): return {"schema":self.schema,"experiments":{}}
        s=json.loads(self.path.read_text(encoding="utf-8"))
        if s.get("schema")!=self.schema: raise ValueError("unsupported behavioral experiment schema")
        for e in s.get("experiments",{}).values():
            if e.get("definitionHash")!=_hash(e.get("definition") or {}): raise ValueError("behavioral experiment definition tampered")
            for row in e.get("observations",[]):
                body=dict(row); got=body.pop("evidenceHash","")
                if got!=_hash(body): raise ValueError("behavioral observation tampered")
        return s
    @contextmanager
    def _locked(self):
        with _exclusive_job_lock(self.path): yield
    def _save(self): atomic_write_json(self.path,self.state)
    def create(self,experiment_id,*,baseline_input,variant_input,acceptance,requested_route,budget,seed=None):
        kind=acceptance.get("kind") if isinstance(acceptance,Mapping) else ""
        if kind not in {"response_contains","variant_differs"} or (kind=="response_contains" and not str(acceptance.get("text") or "")): raise ValueError("supported nonempty observable criterion required")
        max_calls=budget.get("maxCalls") if isinstance(budget,Mapping) else None
        if not isinstance(max_calls,(int,float)) or isinstance(max_calls,bool) or not math.isfinite(float(max_calls)) or max_calls<=0: raise ValueError("budget.maxCalls must be positive and finite")
        with self._locked():
            self.state=self._read()
            if experiment_id in self.state["experiments"]: raise FileExistsError(experiment_id)
            d={"experimentId":experiment_id,"baselineInput":baseline_input,"variantInput":variant_input,"acceptance":dict(acceptance),"requestedRoute":dict(requested_route),"budget":dict(budget),"seed":seed,"createdAt":_now()}
            self.state["experiments"][experiment_id]={"definition":d,"definitionHash":_hash(d),"observations":[]}; self._save(); return d
    def record(self,experiment_id,*,variant,response,actual_route,latency_ms=None,cost=None):
        if variant not in {"baseline","variant"} or not isinstance(actual_route,Mapping) or not actual_route.get("runtime") or not actual_route.get("model"): raise ValueError("variant and caller-reported actual route are required")
        for n,v in (("latency_ms",latency_ms),("cost",cost)):
            if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(float(v)) or v<0): raise ValueError(f"{n} must be finite and non-negative")
        with self._locked():
            self.state=self._read(); e=self._get(experiment_id)
            if len(e["observations"])>=float(e["definition"]["budget"]["maxCalls"]): raise ValueError("experiment call budget exhausted")
            req=e["definition"].get("requestedRoute") or {}; match=bool(req) and all(str(actual_route.get(k) or "")==str(req.get(k) or "") for k in ("runtime","model"))
            b={"variant":variant,"response":response,"actualRoute":dict(actual_route),"routeMatch":match,"latencyMs":latency_ms,"cost":cost,"observedAt":_now(),"status":"observed","evidenceVerified":False,"limitations":["caller-reported API evidence; independent verification absent"]}
            e["observations"].append({**b,"evidenceHash":_hash(b)}); self._save(); return b
    def compare(self,experiment_id):
        with self._locked():
            self.state=self._read(); e=self._get(experiment_id); g={"baseline":[],"variant":[]}
            for r in e["observations"]:
                if r.get("variant") in g:g[r["variant"]].append(r)
            if not g["baseline"] or len(g["baseline"])!=len(g["variant"]): return {"status":"inconclusive","criterionPassed":False,"evidenceVerified":False,"pairs":[],"limitations":["exact baseline and variant observation counts must match"]}
            if any(not r.get("routeMatch") for rows in g.values() for r in rows): return {"status":"invalid_comparison","criterionPassed":False,"evidenceVerified":False,"pairs":[],"limitations":["requested and caller-reported routes mismatch"]}
            c=e["definition"]["acceptance"]; pairs=[{"criterionPassed":(str(c["text"]) in str(v["response"]) if c["kind"]=="response_contains" else b["response"]!=v["response"]),"baseline":b,"variant":v} for b,v in zip(g["baseline"],g["variant"])]
            return {"status":"compared","criterionPassed":all(p["criterionPassed"] for p in pairs),"evidenceVerified":False,"pairs":pairs,"limitations":["observable matched-input comparison only"]}
    def _get(self,i):
        if i not in self.state["experiments"]: raise KeyError(i)
        return self.state["experiments"][i]
