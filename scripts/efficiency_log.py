"""Receipt-backed efficiency ledger. Standard library only; never launches a provider.

Run `python scripts/efficiency_log.py --help`. See docs/research/schema.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "neyvia.efficiency-result.v1"
LEDGER = ROOT / "docs/research/results.jsonl"


def read_json(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    if Path(path).suffix == ".jsonl": return [json.loads(line) for line in text.splitlines() if line.strip()]
    if Path(path).suffix != ".json": return text
    return json.loads(text)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pointer(value, path):
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError(f"JSON pointer must start with /: {path}")
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def flatten(value):
    return [item for part in value for item in flatten(part)] if isinstance(value, list) else [value]


def evaluate(expr, receipts):
    if isinstance(expr, list):
        return [evaluate(item, receipts) for item in expr]
    if not isinstance(expr, dict):
        return expr
    if "receipt" in expr:
        value = pointer(receipts[expr["receipt"]], expr.get("pointer", ""))
        if "field" in expr or "where" in expr:
            if not isinstance(value, list):
                raise ValueError("Filtered receipt selection requires an array")
            value = [r for r in value if all(pointer(r, k) == v for k, v in expr.get("where", {}).items())]
            if not value: raise ValueError("Receipt selection matched no records; absence is not a measured zero")
            if "field" in expr:
                value = [pointer(r, expr["field"]) for r in value]
        return value
    op = expr["op"]
    args = [evaluate(a, receipts) for a in expr.get("args", [])]
    values = flatten(args)
    if op == "sum": return sum(values)
    if op == "count": return len(values)
    if op == "unique_count": return len(set(values))
    if op == "mean": return statistics.mean(values)
    if op == "median": return statistics.median(values)
    if op == "min": return min(values)
    if op == "max": return max(values)
    if op == "subtract": return args[0] - args[1]
    if op == "divide": return args[0] / args[1]
    if op == "multiply": return math.prod(args)
    if op == "decode_field":
        data = args[0]
        return [pointer(json.loads(item),args[1]) for item in data] if isinstance(data,list) else pointer(json.loads(data),args[1])
    if op == "reduction_percent": return 100 * (1 - args[1] / args[0])
    if op == "quantile":
        ordered = sorted(flatten(args[0]))
        pos = (len(ordered) - 1) * args[1]
        low = math.floor(pos)
        return ordered[low] + (ordered[math.ceil(pos)] - ordered[low]) * (pos - low)
    if op in ("multiclass_brier", "top_label_ece", "public_chance_intelligence"):
        records = args[0]
        source = {r["id"]:r for r in (args[1] if len(args)>1 else records)}
        if op == "multiclass_brier":
            scores = []
            for r in records:
                if not r["valid"]: continue
                gold = source[r["id"]]
                scores.append(sum((r["probs"].get(label,0)-(label==str(gold["expected"])))**2 for label in gold["probs"]))
            return statistics.mean(scores)
        if op == "top_label_ece":
            bins = [[] for _ in range(10)]
            for r in records:
                if r["valid"]:
                    c=max(r["probs"].values());bins[min(9,int(c*10))].append((c,r["correct"]))
            n=sum(len(b) for b in bins)
            return sum(len(b)/n*abs(statistics.mean(c for c,y in b)-statistics.mean(y for c,y in b)) for b in bins if b)
        weights={"easy":.14,"standard":.28,"hard":.30}
        tiers={}
        for r in records:
            gold=source[r["id"]]
            tiers.setdefault(gold["tier"],[]).append((r["correct"],1/len(gold["probs"])))
        return sum(weights[t]*max(0,min(100,100*(statistics.mean(c for c,b in v)-statistics.mean(b for c,b in v))/(1-statistics.mean(b for c,b in v)))) for t,v in tiers.items())/sum(weights[t] for t in tiers)
    raise ValueError(f"Unknown calculation: {op}")


def confidence(request, receipts):
    if request["method"] == "not-estimable":
        if not request.get("reason"):
            raise ValueError("Missing CI reason")
        return request.copy()
    if request["method"] != "cluster-bootstrap-mean":
        raise ValueError("Only cluster-bootstrap-mean or not-estimable is supported")
    values = flatten(evaluate(request["values"], receipts))
    clusters = flatten(evaluate(request["clusters"], receipts))
    if len(values) != len(clusters) or not values:
        raise ValueError("CI sample/cluster mismatch")
    groups = {}
    for key, value in zip(clusters, values): groups.setdefault(str(key), []).append(value)
    if len(groups) < 2:
        raise ValueError("A sampling CI needs at least two independent clusters")
    rng = random.Random(request.get("seed", 417))
    units = [(math.fsum(group), len(group)) for group in groups.values()]
    resamples = request.get("resamples", 2000)
    if not 100 <= resamples <= 10000: raise ValueError("CI resamples must be 100..10000")
    # Resample sufficient statistics, not every repeated observation on every draw.
    # Entire task groups stay together; this is the same weighted panel mean.
    boot = []
    for _ in range(resamples):
        draw = rng.choices(units, k=len(units))
        boot.append(math.fsum(total for total, n in draw) / sum(n for total, n in draw))
    boot.sort()
    level = request.get("level", .95)
    if not 0 < level < 1: raise ValueError("CI level must be between zero and one")
    def q(frac):
        pos = (len(boot)-1)*frac
        return boot[math.floor(pos)] + (boot[math.ceil(pos)]-boot[math.floor(pos)])*(pos-math.floor(pos))
    return {"method": request["method"], "level": level, "low": q((1-level)/2), "high": q((1+level)/2),
            "clusters": len(groups), "observations": len(values), "seed": request.get("seed",417), "resamples": resamples,
            "scope": "Conditional on this task panel; repeated trials within a task stay together. No population or held-out guarantee."}


def receipt_ids(expr):
    if isinstance(expr, dict):
        return ({expr["receipt"]} if "receipt" in expr else set()).union(*(receipt_ids(v) for v in expr.values()))
    if isinstance(expr, list): return set().union(*(receipt_ids(v) for v in expr))
    return set()


def load_receipts(row, base=ROOT):
    result = {}
    for receipt in row["receipts"]:
        if not isinstance(receipt,dict) or not all(k in receipt for k in ("id","path","sha256","kind")):
            raise ValueError("Invalid receipt descriptor")
        if receipt["kind"] not in ("raw","aggregate","prose"): raise ValueError("Unknown receipt kind")
        if not isinstance(receipt["id"],str) or not receipt["id"]: raise ValueError("Empty receipt id")
        name = receipt["id"]
        if name in result: raise ValueError(f"Duplicate receipt id: {name}")
        path = base / receipt["path"]
        if digest(path) != receipt["sha256"]: raise ValueError(f"Receipt hash mismatch: {receipt['path']}")
        result[name] = read_json(path)
    return result


def validate(row, base=ROOT, prepare=False):
    required = {"schema", "id", "study", "method", "models", "tasks", "limitations", "receipts", "metrics", "evidence_status"}
    if not isinstance(row,dict): raise ValueError("A result must be a JSON object")
    if required - row.keys(): raise ValueError(f"Missing fields: {sorted(required-row.keys())}")
    if row["schema"] != SCHEMA: raise ValueError("Unsupported result schema")
    if not isinstance(row["id"],str) or not row["id"]: raise ValueError("Empty result id")
    for field in ("study", "method"):
        if not isinstance(row[field],str) or not row[field].strip(): raise ValueError(f"Empty {field}")
    if row["evidence_status"] not in ("raw-verified", "aggregate-only", "unverified"):
        raise ValueError("Unknown evidence_status")
    if not isinstance(row["models"],list) or not row["models"]: raise ValueError("Missing model identity or explicit no-model designation")
    if not isinstance(row["limitations"],list) or not row["limitations"]: raise ValueError("State what was not shown")
    if not isinstance(row["tasks"],dict) or not all(k in row["tasks"] for k in ("description","repetitions","independent_unit")):
        raise ValueError("Missing task description/repetitions/independent unit")
    if not isinstance(row["receipts"],list) or not isinstance(row["metrics"],list): raise ValueError("Receipts and metrics must be arrays")
    receipts = load_receipts(row, base)
    names = set()
    for metric in row["metrics"]:
        if not isinstance(metric,dict) or not all(k in metric for k in ("name","unit","calculation","ci_request")):
            raise ValueError("Invalid metric descriptor")
        if metric["name"] in names: raise ValueError("Duplicate metric name")
        names.add(metric["name"])
        ids = receipt_ids(metric["calculation"])
        if not ids: raise ValueError("A measured number must reference a receipt")
        if row["evidence_status"] == "raw-verified" and not any(r["id"] in ids and r["kind"] == "raw" for r in row["receipts"]):
            raise ValueError("Raw-verified metric has no raw source")
        value = evaluate(metric["calculation"], receipts)
        if not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError("Metric must be a finite scalar")
        ci = confidence(metric["ci_request"], receipts)
        if prepare:
            metric["value"], metric["ci"] = value, ci
        else:
            if metric["value"] != value: raise ValueError(f"Recalculation mismatch: {row['id']}/{metric['name']}")
            if metric["ci"] != ci: raise ValueError(f"CI mismatch: {row['id']}/{metric['name']}")
    if not row["metrics"] and row["evidence_status"] != "unverified": raise ValueError("Verified result needs metrics")
    return row


def read_ledger(path):
    rows = read_json(path) if Path(path).exists() else []
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids): raise ValueError("Duplicate result id in ledger")
    return rows


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w",encoding="utf-8",newline="\n") as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


@contextmanager
def ledger_lock(path):
    lock = Path(str(path)+".lock")
    lock.parent.mkdir(parents=True,exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode());os.close(fd)
        yield
    finally: lock.unlink()


def render(rows):
    text = ["# Efficiency research log", "", "Generated from `results.jsonl` by `scripts/efficiency_log.py`. Every displayed measured number has a receipt calculation; verify with `python scripts/efficiency_log.py verify`. Schema and future-benchmark workflow: [schema.md](schema.md).", "",
            "Historical results are conditional on their recorded fixtures, versions and model routes. Raw verification means arithmetic and byte integrity, not an independent regrading of every outcome or an attestation of deployed model weights. Duplicated worktree receipts are not independent runs. Failed attempts and unavailable measurements stay visible. The import scope and exclusions are recorded in [coverage.json](coverage.json).", ""]
    highlights=[('manual-recovery',['baseline_successes','manual-v2_successes','baseline_totalTokens','manual-v2_totalTokens']),
                ('cl11-scored-2-gpt-6-luna-b-vs-a',['cold_context_mean_reduction','first_touch_context_mean_reduction','provider_tokens_mean_reduction','paired_success_difference']),
                ('t14-cascade',['cascade-warm_tokens','cascade-cold_tokens']),
                ('t17-autopilot',['token_reduction','human_checkins']),
                ('cl-skill',['final_token_reduction','cl-initial_tokens','cl-final-checks_checksPassed']),
                ('laya-r2-retained',['correct','tasks','p50_latency','p95_latency']),
                ('dictation-engine-w1',['short_samples','short_mean_wer','short_p50','short_p95'])]
    text += ["## Receipt-backed highlights", "", "Read each study's limits before using these numbers. Percent reductions are positive savings; supplied cold context and first-touch context are separate.", "", "| Study | Recomputed measures |", "|---|---|"]
    for id,metrics in highlights:
        r=next((r for r in rows if r['id']==id),None)
        if r:
            chosen=[m for name in metrics for m in r['metrics'] if m['name']==name]
            text.append(f"| `{id}` | "+"; ".join(f"{m['name']} = {m['value']:.9g} {m['unit']}" for m in chosen)+" |")
    text.append("")
    for row in rows:
        text += [f"## {row['study']} (`{row['id']}`)", "", f"Evidence: **{row['evidence_status']}**. Models: {', '.join(row['models'])}.", "", row["method"], "", f"Tasks: {row['tasks']['description']}. Repetitions: {row['tasks']['repetitions']}; independent unit: {row['tasks']['independent_unit']}.", ""]
        if row["metrics"]:
            text += ["| Measure | Value | Unit | Confidence interval |", "|---|---:|---|---|"]
            for m in row["metrics"]:
                c=m["ci"]
                ci=(f"{c['level']:.0%}: [{c['low']:.6g}, {c['high']:.6g}] ({c['clusters']} task clusters)") if "low" in c else c["reason"]
                text.append(f"| {m['name']} | {m['value']:.9g} | {m['unit']} | {ci.replace('|','/')} |")
            text.append("")
        text += ["What was not shown: " + " ".join(row["limitations"]), "", "Receipts (exact bytes; original paths are in JSONL):"]
        for r in row["receipts"]:
            link=os.path.relpath(ROOT/r["path"], ROOT/"docs/research").replace("\\","/")
            text.append(f"- [{r['id']}]({link}): `{r['sha256']}` ({r['kind']})")
        text.append("")
    return "\n".join(text).rstrip()+"\n"


def append(spec, ledger=LEDGER, report=None, base=ROOT):
    row = validate(spec,base,prepare=True)
    with ledger_lock(ledger):
        rows=read_ledger(ledger)
        for old in rows: validate(old,base)
        if any(old["id"]==row["id"] for old in rows): raise ValueError(f"Result already exists: {row['id']}")
        rows.append(row)
        atomic_write(ledger,"".join(json.dumps(r,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n" for r in rows))
        if report: atomic_write(report,render(rows))
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["append","verify","render"])
    parser.add_argument("--result",type=Path,help="Benchmark result spec; values/CIs are computed from its receipts")
    parser.add_argument("--ledger",type=Path,default=LEDGER)
    parser.add_argument("--report",type=Path,default=ROOT/"docs/research/efficiency-log.md")
    args=parser.parse_args()
    try:
        if args.command=="append":
            if not args.result: parser.error("append requires --result")
            row=append(read_json(args.result),args.ledger,args.report)
            print(json.dumps({"ok":True,"appended":row["id"],"metrics":len(row["metrics"])}))
        else:
            rows=read_ledger(args.ledger)
            if not rows: raise ValueError("Empty ledger")
            for row in rows: validate(row)
            expected=render(rows)
            if args.command=="render": atomic_write(args.report,expected)
            elif not args.report.exists() or args.report.read_text(encoding="utf-8")!=expected: raise ValueError("Markdown projection is stale; run render")
            print(json.dumps({"ok":True,"results":len(rows),"metrics":sum(len(r['metrics']) for r in rows),"receipts":len({p['sha256'] for r in rows for p in r['receipts']})}))
    except (ValueError,KeyError,TypeError,OSError,IndexError,OverflowError,ZeroDivisionError) as e:
        print(json.dumps({"ok":False,"error":str(e)}));return 1
    return 0


if __name__=="__main__": sys.exit(main())
