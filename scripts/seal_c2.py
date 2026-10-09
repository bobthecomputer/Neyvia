"""Verify retained production runs, derive their metrics, and append the C2 ledger."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.laya_client.contracts import digest
from grant_agent.laya_client.calibration import BrowserCalibration, temperature_probabilities
import efficiency_log as ledger

def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()

def quantile(values, q):
    a = sorted(values); pos = (len(a)-1)*q
    return a[math.floor(pos)] + (a[math.ceil(pos)]-a[math.floor(pos)])*(pos-math.floor(pos))

def metrics(rows, temperature):
    data = []
    for row in rows:
        answer = row["response"]["answers"]["decision"]
        p = temperature_probabilities(answer["p"], temperature)
        data.append((p[answer["answer"]], answer["answer"] == row["gold"], p, row["gold"]))
    buckets = [[] for _ in range(10)]
    for conf, correct, _, _ in data: buckets[min(9, int(conf*10))].append((conf,correct))
    accepted = [r for r in data if r[0] >= .8]
    return {"count": len(data), "accuracy": statistics.mean(r[1] for r in data),
            "mean_confidence": statistics.mean(r[0] for r in data),
            "ece": sum(len(b)/len(data)*abs(statistics.mean(r[0] for r in b)-statistics.mean(r[1] for r in b)) for b in buckets if b),
            "brier": statistics.mean(sum((v-(k==gold))**2 for k,v in p.items()) for _,_,p,gold in data),
            "nll": statistics.mean(-math.log(max(p[gold],1e-12)) for _,_,p,gold in data),
            "hit_rate": len(accepted)/len(data), "accepted_accuracy": statistics.mean(r[1] for r in accepted) if accepted else None,
            "escalated": len(data)-len(accepted)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    browser = read("scripts/evidence/C2.json")
    assert browser["sourceStable"] and not browser.get("fatal"), "Incomplete browser execution"
    for path, expected in browser["sourceHashes"].items(): assert sha(path) == expected, path
    checks = {r["label"]: r for r in browser["checks"]}
    required = ["obscura tables and stable capture", "obscura delayed effect", "obscura selection",
                "obscura unstyled iframe fill and verify", "obscura stale revision refuses effect",
                "obscura invalid predicate refuses before effect", "obscura false postcondition stays unconfirmed",
                "obscura grounded LAYA decision through real HTTP", "obscura navigation acknowledgement", "obscura auth wall asks Paul"]
    assert all(checks[label]["ok"] for label in required)
    assert not checks["obscura iframe fill and verify"]["ok"], "Reassess styled-iframe limitation if it changes"
    assert all(not r["response"].get("selected_action") for r in browser["laya"])
    assert all(r["response"]["browser_policy"]["policy"] == "escalate" for r in browser["laya"])
    assert all(r['response'].get('available') is True and r['response']['decision']['answers']['decision']['source'] == 'laya' for r in browser['laya'])
    laya = read("scripts/evidence/C2-laya-consistency.json")
    cases = read("scripts/evidence/C2-laya-cases.json")["cases"]
    assert digest(cases) == laya["cases_digest"]
    calibration = BrowserCalibration(ROOT / "scripts/evidence/C2-laya-calibration.json")
    assert calibration.spec["family"] == "browser_factual"
    assert calibration.spec["identity_digest"] == digest(laya["identity"])
    deterministic = 0
    for case, row in zip(cases, laya["rows"], strict=True):
        assert all(row[k] == v for k,v in case.items())
        response = row["response"]; answer = response["answers"]["decision"]
        assert response["identity"] == laya["identity"] and response["memory_enabled"] is False
        assert response["runtime"]["execution"] != "exact_base_cache"
        assert all(r["memory_enabled"] is False and r["runtime"]["execution"] != "exact_base_cache" for r in row["repeats"])
        assert all(r['identity'] == laya['identity'] for r in row['repeats'])
        assert all(r["answer"] == answer["answer"] and r["p"] == answer["p"] for r in row["repeats"])
        assert calibration.confidence(response, answer) is None
        deterministic += 1
    heldout = [r for r in laya["rows"] if r["split"] == "heldout"]
    fitting = [r for r in laya["rows"] if r["split"] == "calibration"]
    choices = [1,1.25,1.5,2,3,4,6,8,12,16]
    chosen = min(choices, key=lambda t: metrics(fitting,t)["nll"])
    assert chosen == calibration.temperature
    for key, t in (("heldout_before",1),("heldout_after",chosen)):
        measured = metrics(heldout,t)
        for k,v in measured.items():
            expected = laya[key][k]
            assert v == expected if v is None else math.isclose(v,expected,abs_tol=1e-12), (key,k,v,expected)
    timings = [r["http_ms"] for r in laya["rows"]] + [p["http_ms"] for r in laya["rows"] for p in r["repeats"]]
    assert deterministic == laya["determinism"]["identical"]
    assert math.isclose(statistics.median(timings),laya["latency_ms"]["http_p50"])
    assert math.isclose(quantile(timings,.95),laya["latency_ms"]["http_p95"])
    native = read("scripts/evidence/C2-attempt6.json")
    assert not next(c for c in native["checks"] if c["label"] == "real native runtime journey")["ok"]
    for path in ('src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js','src/grant_agent/browser_dom.js'):
        assert native['sourceHashes'][path] == sha(path), 'Native build source changed: '+path
    native_binary = Path(native['binary']['native']['path']).resolve()
    assert native_binary.is_relative_to(ROOT)
    assert hashlib.sha256(native_binary.read_bytes()).hexdigest() == native['binary']['native']['sha256']
    samples = {r["metric"]: r["samples"] for r in browser["benchmark"] if "samples" in r}
    summary = {"schema":"neyvia.C2-verification@1", "verified_recorded_boundary":True, "C2_complete":False,
               "sourceHashes":browser["sourceHashes"],
               "native_binary":native['binary']['native'],
               "receipts":{p:sha(p) for p in ["scripts/evidence/C2.json","scripts/evidence/C2-attempt6.json","scripts/evidence/C2-native-startup.log","scripts/evidence/C2-laya-consistency.json","scripts/evidence/C2-laya-cases.json","scripts/evidence/C2-laya-calibration.json"]},
               "latency_ms":{k:{"n":len(v),"p50":statistics.median(v),"p95":quantile(v,.95)} for k,v in samples.items()},
               "LAYA":{"determinism":laya["determinism"],"heldout":laya["heldout_after"],"latency_ms":laya["latency_ms"]},
               "missing":browser["missing"]+["Full native mechanism and rendered desktop journey unproven", "No action-selection confidence corpus; factual artifact cannot grant an action"]}
    (ROOT/"scripts/evidence/C2-verification.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    specs = []
    def receipt(id,path): return {"id":id,"path":path,"sha256":sha(path),"kind":"raw"}
    def metric(name,unit,calc,reason): return {"name":name,"unit":unit,"calculation":calc,"ci_request":{"method":"not-estimable","reason":reason}}
    base = {"schema":ledger.SCHEMA,"evidence_status":"raw-verified", "models":["none: shared DOM projection + Obscura v0.2.3; native startup blocked"],
            "tasks":{"description":"One owned dynamic page; unstyled/styled iframe, stale/effect/auth refusal; five live public pages", "repetitions":"12 captures; 5 fill/save pairs; each public page once", "independent_unit":"page; repeated warm requests are not independent deployment trials"},
            "limitations":summary["missing"],"receipts":[receipt("raw","scripts/evidence/C2.json")],
            "method":"Actual isolated product owner HTTP routes and registered browser.observe; explicit 48711/48712/48713. Public original WebVoyager task IDs are scripted direct-URL factual acquisition, not autonomous benchmark completion. Native failure retained separately."}
    latency_spec = {**base,"id":"C2-obscura-final-"+browser["startedAt"],"study":"C2 actual browser projection and verified-effect latency","metrics":[]}
    for kind in samples:
        # Filtered selection requires every row to carry the filtered key.
        index=next(i for i,r in enumerate(browser["benchmark"]) if r.get("metric")==kind)
        selector={"receipt":"raw","pointer":f"/benchmark/{index}/samples"}
        for q in (.5,.95):latency_spec["metrics"].append(metric(kind+f"_p{int(q*100)}","ms",{"op":"quantile","args":[selector,q]},"Single warm fixture; no independent deployment repetitions"))
    specs.append(latency_spec)
    public_indices=[i for i,r in enumerate(browser["benchmark"]) if "task" in r]
    public_spec={**base,"id":"C2-public-acquisition-"+browser["startedAt"],"study":"C2 live public dictionary acquisition","metrics":[metric("successful_scripted_lookups","count",{"op":"sum","args":[{"receipt":"raw","pointer":f"/benchmark/{i}/success"} for i in public_indices]},"Three fixed direct-URL lookups; no autonomous task-completion or generalization claim")]}
    specs.append(public_spec)
    laya_spec={"schema":ledger.SCHEMA,"id":"C3-laya-browser-factual-"+laya["cases_digest"][:12],"study":"C3 frozen LAYA browser factual consistency",
               "evidence_status":"raw-verified","models":["LAYA English frozen CPU fp32 checkpoint "+laya["identity"]["checkpoint_sha256"]],
               "method":"27 real uncached/no-memory inferences over nine frozen browser states; four fitting/five held-out validation states. Conservative temperature NLL fit on fitting only, validation Brier/ECE veto. Sealer independently recomputes each score and rejects factual calibration for actions.",
               "tasks":{"description":"Nine real browser factual choice states; action-selection transfer unproven","repetitions":3,"independent_unit":"browser state"},
               "receipts":[receipt("raw","scripts/evidence/C2-laya-consistency.json")],"limitations":["Small factual validation panel; held-out data used for veto, not an untouched final test", "CPU measurements under concurrent build; no GPU or sub-100ms claim", "Zero accepted held-out decisions at .8; no action calibration or whole-model promotion"],"metrics":[]}
    for field,unit in [("accuracy","fraction"),("ece","absolute probability error"),("brier","squared probability error"),("hit_rate","fraction"),("escalated","count")]:
        laya_spec["metrics"].append(metric("heldout_"+field,unit,{"receipt":"raw","pointer":"/heldout_after/"+field},"Five validation states; not an independent deployment sample"))
    for field in ("http_p50","http_p95"):
        laya_spec["metrics"].append(metric(field,"ms",{"receipt":"raw","pointer":"/latency_ms/"+field},"Nine states × three CPU repeats under concurrent build"))
    laya_spec["metrics"].append(metric("repeat_identical_states","count",{"receipt":"raw","pointer":"/determinism/identical"},"Nine fixed states; identity and raw probabilities checked separately"))
    specs.append(laya_spec)
    if args.append:
        existing={r["id"] for r in ledger.read_ledger(ledger.LEDGER)}
        for spec in specs:
            if spec["id"] not in existing: ledger.append(spec,report=ROOT/"docs/research/efficiency-log.md")
    print(json.dumps({"ok":True,"partial":True,"latency_ms":summary["latency_ms"],"LAYA":summary["LAYA"],"result_ids":[s["id"] for s in specs]}))

if __name__ == "__main__": main()
