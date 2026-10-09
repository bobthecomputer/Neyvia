"""CL 1.1 token comparison against today's model-facing payloads (exact o200k via tiktoken).

Run from the repository root: python docs/standard/1.1/examples/measure.py
Per task, today's arm (a) starts with the layer's rendered manual chapter + tool schemas.
CL 1.1 starts with the core primer + the L0 index of all layers, and loads one layer's L1
on first touch. Both are charged on every fresh task (no amortization in the gate numbers).
JSON under today/ is re-serialized compactly first (a lower bound for today).
Sections named "host" are the compiled host contract and are never sent to the model.
"""
import json
import sys
from pathlib import Path

import tiktoken

HERE = Path(__file__).resolve().parent
TODAY = HERE.parents[1] / "examples" / "today"
PRIMER = HERE.parent / "primer.md"
LAYERS = ["notes", "files", "window", "web", "chart", "codex-run"]
enc = tiktoken.get_encoding("o200k_base")
tok = lambda text: len(enc.encode(text, disallowed_special=()))


def today(name):
    def text(p):
        raw = p.read_text(encoding="utf-8")
        return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":")) if p.suffix == ".json" else raw
    files = sorted(TODAY.glob(name + ".*"))
    start = [f for f in files if f.name in {name + ".manual.txt", name + ".tools.json"}]
    return "\n".join(map(text, start)), "\n".join(text(f) for f in files if f not in start)


def sections(name):
    out, cur = {"L0": [], "L1": [], "runtime": [], "host": []}, None
    for line in (HERE / (name + ".cl")).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("--"):
            word = s[2:].strip().split(" ")[0]
            cur = word if word in out and s[2:].strip() == word else cur
            continue
        if s and not s.startswith("CL ") and cur:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def main():
    primer = tok(PRIMER.read_text(encoding="utf-8"))
    secs = {n: sections(n) for n in LAYERS}
    l0 = tok("\n".join(secs[n]["L0"] for n in LAYERS))
    print(f"core primer {primer} | L0 index (6 layers) {l0} | cold start {primer + l0}")
    print("| layer | today start (manual+schemas) | CL 1.1 start (primer+L0+L1) | L1 | today runtime | CL 1.1 runtime | start saved | runtime saved |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    tot = [0] * 5
    for n in LAYERS:
        t_start, t_run = today(n)
        l1 = tok(secs[n]["L1"])
        row = [tok(t_start), primer + l0 + l1, l1, tok(t_run), tok(secs[n]["runtime"])]
        tot = [a + b for a, b in zip(tot, row)]
        print(f"| {n} | {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {100*(row[0]-row[1])/row[0]:.0f}% | {100*(row[3]-row[4])/row[3]:.0f}% |")
    print(f"| total | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} | {100*(tot[0]-tot[1])/tot[0]:.0f}% | {100*(tot[3]-tot[4])/tot[3]:.0f}% |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
