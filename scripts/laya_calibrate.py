"""Build the labelled corpora, admit the training cases into a fresh LAYA service, measure held-out accuracy.

    python scripts/laya_calibrate.py corpora      build tools/laya/corpora/*.jsonl and tools/laya/route_vocab.json
    python scripts/laya_calibrate.py calibrate    fresh service on port 48843, admit train, evaluate held-out, write evidence
    python scripts/laya_calibrate.py seal         also admit the held-out cases and write tools/laya/memory-seed.sqlite

Evidence: docs/evidence/laya-calibration.json (numbers) and docs/evidence/laya-calibration.md (reading).
Read-only inputs: C:\\Users\\user\\Projects\\nx-c13-taste\\proof (rounds r7-r10) and the deterministic checks in
C:\\Users\\user\\Projects\\nx-taste-cases\\src\\grant_agent\\taste_checks.py (track/taste-cases).
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent import laya_hooks  # noqa: E402

CORPORA = ROOT / "tools" / "laya" / "corpora"
SCRATCH = ROOT / ".agent_control" / "laya-visible" / "calib"
PORT = 48843
PROOF = Path(r"C:\Users\user\Projects\nx-c13-taste\proof")
TASTE_CASES_SRC = Path(r"C:\Users\user\Projects\nx-taste-cases\src")
EVIDENCE = ROOT / "docs" / "evidence"
GATE = 0.95


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ taste triage

def build_taste():
    import importlib.util
    spec = importlib.util.spec_from_file_location("grant_agent.taste_checks", TASTE_CASES_SRC / "grant_agent" / "taste_checks.py")
    taste_checks = importlib.util.module_from_spec(spec)
    sys.modules["grant_agent.taste_checks"] = taste_checks
    spec.loader.exec_module(taste_checks)
    rows = []
    for round_name in ("r7", "r8", "r9", "r10"):
        for artifact in sorted(glob.glob(str(PROOF / round_name / "**" / "artifact.html"), recursive=True)):
            folder = Path(artifact).parent
            report = folder / "render" / "report.json"
            critics = sorted(glob.glob(str(folder / "critic" / "**" / "response.json"), recursive=True))
            if not report.is_file() or not critics:
                continue
            critic = json.loads(Path(critics[-1]).read_text(encoding="utf-8"))
            if not isinstance(critic.get("passes"), bool):
                continue
            checks = taste_checks.page_checks(artifact, json.loads(report.read_text(encoding="utf-8")), base=report.parent)
            page_id = hashlib.sha256(Path(artifact).read_bytes()).hexdigest()[:12]
            rows.append({"id": f"{round_name}/{folder.relative_to(PROOF / round_name).as_posix()}", "group": round_name,
                         "split": "train" if round_name == "r7" else "test",
                         "state": laya_hooks.taste_state(checks, page_id),
                         "label": "ask_critic" if critic["passes"] else "repair_first",
                         "criticQuality": critic.get("quality")})
    write_jsonl(CORPORA / "taste_triage.jsonl", rows)
    return rows


# ------------------------------------------------------------------ page_done (grounded pages)

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip, self.out = 0, []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.out.append(" ".join(data.split()))


def page_texts():
    pages, seen = [], set()
    sources = sorted(glob.glob(str(PROOF / "r7" / "**" / "artifact.html"), recursive=True))[::4]
    sources += sorted(glob.glob(str(PROOF / "r8" / "**" / "*.html"), recursive=True)) + sorted(glob.glob(str(PROOF / "r9" / "**" / "*.html"), recursive=True))
    for path in sources:
        parser = _Text()
        parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
        text = "\n".join(parser.out)
        key = hashlib.sha256(text.encode()).hexdigest()
        if len(text) > 400 and key not in seen:
            seen.add(key)
            pages.append((f"proof:{Path(path).relative_to(PROOF).as_posix()}", text))
    for path in sorted(glob.glob(str(ROOT / "docs" / "manuals" / "*.md"))):
        text = re.sub(r"[`*_#>|]", " ", Path(path).read_text(encoding="utf-8", errors="replace"))
        text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
        key = hashlib.sha256(text.encode()).hexdigest()
        if len(text) > 400 and key not in seen:
            seen.add(key)
            pages.append((f"manual:{Path(path).name}", text))
    return pages


def phrase(text, rng, avoid=""):
    sentences = [s.strip() for s in re.split(r"[.\n!?]", text) if 25 <= len(s.strip()) <= 140]
    rng.shuffle(sentences)
    for sentence in sentences:
        words = sentence.split()
        if len(words) < 5:
            continue
        start = rng.randrange(0, max(1, len(words) - 4))
        fragment = " ".join(words[start:start + rng.choice((4, 5, 6))])
        if fragment and fragment not in avoid and fragment in text:
            return fragment
    return None


def build_page_done(seed=7):
    rng = random.Random(seed)
    pages = page_texts()
    rng.shuffle(pages)
    chosen = pages[:40]
    rows = []
    for index, (name, text) in enumerate(chosen):
        split = "train" if index < 26 else "test"
        other = chosen[(index + 7) % len(chosen)][1]
        mine = phrase(text, rng)
        theirs = phrase(other, rng, avoid=text)
        if not mine or not theirs or theirs in text:
            continue
        page = {"url": "file:///" + name, "title": name}
        current = {"text": text[:3000], "title": name, "url": page["url"]}
        receipt = [{"action": "click", "status": "ok", "summary": "opened the section and read it"}]
        for evidence, receipts, label, kind in ((mine, receipt, "true", "evidence+receipt"), (theirs, receipt, "false", "no-evidence"),
                                                 (mine, [], "false", "evidence-no-receipt"), (theirs, [], "false", "neither")):
            goal = f"Open the page and confirm it shows: {evidence}"
            rows.append({"id": f"{name}#{kind}", "group": name, "split": split, "kind": kind, "label": label,
                         "state": laya_hooks.page_done_state(goal, page, current, receipts, evidence)})
    write_jsonl(CORPORA / "page_done.jsonl", rows)
    return rows


# ------------------------------------------------------------------ CL routing

def layer_id(record_id):
    return "cua" if record_id == "computer-use" else record_id


def manual_texts():
    from grant_agent.neyvia_manuals import get_manual, records
    texts = []
    for record in records():
        layer = layer_id(record["id"])
        texts.append((layer, "description", record["description"]))
        _, _, data = get_manual(record["id"], ROOT / ".neyvia")
        for chapter_name, chapter in data["chapters"].items():
            if chapter.get("title"):
                texts.append((layer, "title", chapter["title"]))
            for name, proc in chapter["procedures"].items():
                texts.append((layer, "procedure", name.replace("-", " ") + ". " + proc["goal"]))
    return texts


def benchmark_tasks(layers):
    rows = []
    d = json.loads((ROOT / "config" / "cl_benchmark_1.1_tasks.json").read_text(encoding="utf-8"))
    for key in ("tasks", "dev"):
        for task in d.get(key, []):
            layer = layer_id(task.get("layer", ""))
            if layer in layers and task.get("text"):
                rows.append((layer, key, task["text"]))
    old = json.loads((ROOT / "config" / "cl_benchmark_tasks.json").read_text(encoding="utf-8"))
    for task in old.get("tasks", old.get("arms", [])) if isinstance(old.get("tasks"), list) else []:
        layer = layer_id(task.get("layer", ""))
        if layer in layers and task.get("goal"):
            rows.append((layer, "old", task["goal"]))
    return rows


def build_vocab(train):
    per_layer = defaultdict(Counter)
    for layer, _, text in train:
        per_layer[layer].update(laya_hooks.tokens(text))
    spread = Counter(token for counts in per_layer.values() for token in counts)
    vocab = {layer: sorted(token for token in counts if spread[token] <= 2 and len(token) >= 4)
             for layer, counts in per_layer.items()}
    return {layer: terms for layer, terms in vocab.items() if terms}


def build_route(seed=11):
    rng = random.Random(seed)
    items = manual_texts()
    layers = {layer for layer, _, _ in items}
    # Hold out a quarter of the manual procedure texts by hash, plus the real benchmark tasks.
    def held(text):
        return int(hashlib.sha256(text.encode()).hexdigest(), 16) % 4 == 0
    train = [row for row in items if not held(row[2])]
    tests = [row for row in items if held(row[2])] + benchmark_tasks(layers)
    vocab = build_vocab(train)
    (ROOT / "tools" / "laya").mkdir(parents=True, exist_ok=True)
    (ROOT / "tools" / "laya" / "route_vocab.json").write_text(json.dumps(
        {"schema": "neyvia.laya.route-vocab.v1", "built": "from the training quarter-split of manual descriptions, chapter titles and procedure goals; held-out procedures and benchmark tasks excluded",
         "layers": vocab}, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    rows = []

    def add(split, index, layer, kind, text, vocab_used):
        candidate = laya_hooks.candidate_layer(text, vocab_used)
        base = {"group": layer, "split": split, "kind": kind, "truth": layer, "id": f"{split}:{index}"}
        if not candidate:
            rows.append({**base, "noCandidate": True, "label": None, "state": None})
        else:
            rows.append({**base, "candidate": candidate, "label": "true" if candidate == layer else "false",
                         "state": laya_hooks.route_state(text, candidate, vocab_used)})

    # Training cases use out-of-fold vocabularies, so their mistakes look like the mistakes the shipped
    # vocabulary makes on requests it has never seen (a case is never routed by a vocabulary that read it).
    folds = 4
    fold_of = lambda text: int(hashlib.sha256(("fold" + text).encode()).hexdigest(), 16) % folds
    for fold in range(folds):
        vocab_fold = build_vocab([row for row in train if fold_of(row[2]) != fold])
        for index, (layer, kind, text) in enumerate(train):
            if fold_of(text) == fold:
                add("train", index, layer, kind, text, vocab_fold)
    for index, (layer, kind, text) in enumerate(tests):
        add("test", index, layer, kind, text, vocab)
    write_jsonl(CORPORA / "cl_route.jsonl", rows)
    return rows


# ------------------------------------------------------------------ service + measurement

def post(url, route, body, timeout=60):
    request = urllib.request.Request(url + route, json.dumps(body, ensure_ascii=False).encode("utf-8"), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def start_service(fresh=True):
    from grant_agent.laya_host import LayaHost, load_config
    if fresh and SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    seed = ROOT / "tools" / "laya" / "memory-seed.sqlite"
    hidden = seed.with_suffix(".hidden") if seed.is_file() and fresh else None
    if hidden:
        seed.rename(hidden)  # a fresh calibration must not start from the shipped memory
    try:
        host = LayaHost(SCRATCH, {**load_config(SCRATCH), "port": PORT, "memoryCapacity": 8192}).start()
        deadline = time.time() + 240
        while time.time() < deadline and not host.ready():
            if host.state in {"unavailable", "disabled"}:
                raise RuntimeError(host.reason)
            time.sleep(2)
        if not host.ready():
            raise RuntimeError("service did not become ready: " + host.reason)
    finally:
        if hidden:
            hidden.rename(seed)
    return host


def raw_decide(url, question, state, memory=True):
    body = post(url, "/v1/decide", {"set": laya_hooks.SET, "questions": [question], "state": state,
                                    "scope": laya_hooks.SCOPES[question], "memory": memory, "capture_state": False})
    return body, body["answers"][question]


def admit(url, question, rows, cap_per_signature=60):
    seen = Counter()
    admitted = 0
    for row in rows:
        if row.get("label") is None:
            continue
        state = row["state"]
        signature = (bool(state.get("layer_hit")), bool(state.get("rival_hit")), row["label"]) if question == "cl_route" else row["label"]
        seen[signature] += 1
        if question == "cl_route" and seen[signature] > cap_per_signature:
            continue  # the memory needs distinct support per abstract signature, not every repeat
        body, _ = raw_decide(url, question, row["state"], memory=False)
        post(url, "/v1/outcome", {"decision_id": body["decision_id"], "question": question, "correct": row["label"], "kind": "verified_effect",
                                  "evidence": {"receipt": row["id"], "verifier": "labelled-corpus", "passed": True}})
        admitted += 1
    return admitted


def wilson_low(correct, n, z=1.96):
    if n == 0:
        return None
    p = correct / n
    return round((p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n), 4)


def evaluate(url, question, rows, memory=True):
    results = []
    for row in rows:
        if row.get("label") is None:
            results.append({"id": row["id"], "truth": None, "outcome": "no-candidate"})
            continue
        started = time.time()
        _, answer = raw_decide(url, question, row["state"], memory=memory)
        probability = answer.get("top_probability", 0)
        answered = str(answer.get("policy", "")).startswith("answer") and probability >= GATE and not answer.get("conflict")
        results.append({"id": row["id"], "label": row["label"], "answer": answer["answer"], "probability": round(probability, 4),
                        "source": answer.get("source"), "conflict": bool(answer.get("conflict")), "outcome": "answered" if answered else "escalated",
                        "correct": answered and answer["answer"] == row["label"], "ms": round((time.time() - started) * 1000)})
    asked = [r for r in results if r["outcome"] in {"answered", "escalated"}]
    answered = [r for r in asked if r["outcome"] == "answered"]
    right = sum(1 for r in answered if r["correct"])
    return {"cases": len(rows), "asked": len(asked), "noCandidate": len(rows) - len(asked), "answered": len(answered),
            "coverage": round(len(answered) / len(asked), 4) if asked else None,
            "accuracyAnswered": round(right / len(answered), 4) if answered else None,
            "accuracyWilsonLow95": wilson_low(right, len(answered)),
            "wrongAnswers": [r["id"] for r in answered if not r["correct"]],
            "bySource": dict(Counter(r.get("source") for r in answered)),
            "labelsAnswered": dict(Counter(r["answer"] for r in answered)),
            "labelsInHeldOut": dict(Counter(r["label"] for r in asked)),
            "medianMs": sorted(r["ms"] for r in asked)[len(asked) // 2] if asked else None}, results


QUESTIONS = {"taste_triage": "taste_triage.jsonl", "page_done": "page_done.jsonl", "cl_route": "cl_route.jsonl"}


def calibrate(seal=False):
    host = start_service(fresh=True)
    url = host.url
    report = {"schema": "neyvia.laya-calibration.v1", "gate": GATE, "model": host.status()["model"], "serviceIdentity": host.last_health and host.last_health.get("identity"),
              "method": "train cases admitted as verified_effect outcomes, then held-out cases decided with memory on; baseline is the same held-out cases with memory off",
              "questions": {}}
    try:
        for question, filename in QUESTIONS.items():
            rows = read_jsonl(CORPORA / filename)
            train = [r for r in rows if r["split"] == "train"]
            test = [r for r in rows if r["split"] == "test"]
            started = time.time()
            admitted = admit(url, question, train)
            baseline, _ = evaluate(url, question, test, memory=False)
            held, detail = evaluate(url, question, test, memory=True)
            report["questions"][question] = {"train": len(train), "admitted": admitted, "heldOut": held, "baselineMemoryOff": baseline,
                                              "heldOutGroups": sorted({r["group"] for r in test})[:12], "seconds": round(time.time() - started)}
            write_jsonl(SCRATCH / f"results-{question}.jsonl", detail)
            print(question, json.dumps({"admitted": admitted, **{k: held[k] for k in ("asked", "answered", "coverage", "accuracyAnswered", "accuracyWilsonLow95")}}), flush=True)
        if seal:
            for question, filename in QUESTIONS.items():
                admit(url, question, [r for r in read_jsonl(CORPORA / filename) if r["split"] == "test"])
            host.stop()
            time.sleep(3)
            shutil.copyfile(SCRATCH / ".neyvia" / "laya" / "system1.sqlite", ROOT / "tools" / "laya" / "memory-seed.sqlite")
            report["sealed"] = {"seed": "tools/laya/memory-seed.sqlite", "bytes": (ROOT / "tools" / "laya" / "memory-seed.sqlite").stat().st_size,
                                "note": "the shipped seed also holds the held-out cases; the numbers above are from the train-only run"}
    finally:
        host.stop()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "laya-calibration.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "corpora"
    if command == "corpora":
        for name, build in (("taste_triage", build_taste), ("cl_route", build_route), ("page_done", build_page_done)):
            rows = build()
            print(name, len(rows), dict(Counter((r["split"], r["label"]) for r in rows)))
    elif command in {"calibrate", "seal"}:
        calibrate(seal=command == "seal")
    else:
        raise SystemExit(__doc__)
