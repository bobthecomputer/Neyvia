"""Token comparison: today's model-facing payloads vs the same content in CL.

Run from the repository root:  python docs/standard/examples/measure.py
o200k counts are exact (tiktoken o200k_base). Claude has no local tokenizer: its column is
ceil(UTF-8 bytes / 3.5), an approximation that must not be quoted as a Claude count.
JSON payloads under today/ are re-serialized compactly before counting, which undercounts today's
spaced JSON. Text payloads (T16/T18 tool results) are counted exactly as the model received them.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = HERE / "today"
EXAMPLES = ["notes", "files", "window", "web", "chart", "codex-run"]

try:
    import tiktoken
    _enc = tiktoken.get_encoding("o200k_base")
    def o200k(text: str) -> int:
        return len(_enc.encode(text, disallowed_special=()))
    METHOD = "o200k_base exact (tiktoken)"
except ImportError:  # pragma: no cover
    def o200k(text: str) -> int:
        return math.ceil(len(text.encode("utf-8")) / 4)
    METHOD = "APPROXIMATION: UTF-8 bytes / 4 (tiktoken not importable)"


def claude_approx(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 3.5)


def today_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
    return raw


def today_parts(name: str) -> dict[str, str]:
    files = sorted(TODAY.glob(name + ".*"))
    manual = [f for f in files if f.name in {name + ".manual.txt", name + ".tools.json"}]
    runtime = [f for f in files if f not in manual]
    return {"manual": "\n".join(today_text(f) for f in manual), "runtime": "\n".join(today_text(f) for f in runtime)}


def cl_parts(name: str) -> dict[str, str]:
    parts = {"L0": [], "L1": [], "L2": [], "runtime": []}
    section = None
    for line in (HERE / (name + ".cl")).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            word = stripped[2:].strip().split(" ")[0].rstrip(":")
            if word in parts:
                section = word
            continue
        if not stripped or stripped.startswith("CL ") or section is None:
            continue
        parts[section].append(line)
    return {key: "\n".join(lines) for key, lines in parts.items()}


def awareness(text: str) -> str:
    """K/Q/M/V lines: awareness that today's format does not carry at all."""
    return "\n".join(l for l in text.splitlines() if l.lstrip()[:2] in {"K ", "Q ", "M ", "V "})


def main() -> int:
    rows, total = [], {"tm": 0, "cm": 0, "c1": 0, "tr": 0, "cr": 0, "tc": 0, "cc": 0, "aw": 0}
    for name in EXAMPLES:
        t, c = today_parts(name), cl_parts(name)
        cl_manual = "\n".join(c[k] for k in ("L0", "L1", "L2") if c[k])
        cl_l1 = "\n".join(c[k] for k in ("L0", "L1") if c[k])
        row = {"layer": name, "tm": o200k(t["manual"]) if t["manual"] else 0, "cm": o200k(cl_manual), "c1": o200k(cl_l1),
               "tr": o200k(t["runtime"]), "cr": o200k(c["runtime"]),
               "tc": claude_approx(t["manual"] + t["runtime"]), "cc": claude_approx(cl_manual + c["runtime"]),
               "aw": o200k(awareness(cl_manual + "\n" + c["runtime"]))}
        rows.append(row)
        for key in total:
            total[key] += row[key]
    total["layer"] = "total"
    print("method:", METHOD)
    print("| layer | today manual+schemas | CL L0-L2 (L0-L1) | today runtime | CL runtime | today total | CL total (new K/Q/M/V) | saved | Claude approx today -> CL |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows + [total]:
        today, cl = r["tm"] + r["tr"], r["cm"] + r["cr"]
        print(f"| {r['layer']} | {r['tm']} | {r['cm']} ({r['c1']}) | {r['tr']} | {r['cr']} | {today} | {cl} ({r['aw']}) | "
              f"{100 * (today - cl) / today:.0f}% | {r['tc']} -> {r['cc']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
