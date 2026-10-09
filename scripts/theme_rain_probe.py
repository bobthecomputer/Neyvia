"""Matrix rain proof (plan 29 section 5): frame cost, pause rules and a frame, in Neyvia's Obscura engine.

python scripts/theme_rain_probe.py --ports 49251,49252 [--out D:/NeyviaRuns/29-THEME/rain]

Each case loads the Terminal theme with rain switched on and reads window.__nxRain (NxRain.jsx times the
drawing part of every frame with performance.now): frames, average and worst ms per frame, frames over 1 ms.
Cases: wide screen (rain on), wide + reduced motion (must draw nothing), phone width (no side bands: nothing),
ambient off (nothing), rain off (no canvas).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
import theme_shots as t  # noqa: E402

STATS = "() => { const c = document.querySelector('.nx-rain'); const s = window.__nxRain || null; return { canvas: !!c, w: c ? c.clientWidth : 0, h: c ? c.clientHeight : 0, stats: s ? { frames: s.frames, avgMs: s.avgMs, maxMs: s.maxMs, over1ms: s.over1ms, paused: s.paused } : null }; }"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ports", required=True)
    parser.add_argument("--out", default=r"D:\NeyviaRuns\29-THEME\rain")
    parser.add_argument("--dist", default=r"D:\NeyviaRuns\29-THEME\dist-shots")
    parser.add_argument("--seconds", type=float, default=8)
    args = parser.parse_args()
    ports = [int(p) for p in args.ports.split(",")]
    from grant_agent.browser_obscura import managed_executable
    exe = os.environ.get("NEYVIA_OBSCURA_EXE") or str(managed_executable())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rig = t.Rig(args.dist, out, ports, exe, r"D:\NeyviaRuns\29-THEME\engine")
    rig.start()
    results = {}
    cases = [
        ("wide-rain-on", "1440", {"nx.os.rain": True}, False, None),
        ("wide-reduced-motion", "1440", {"nx.os.rain": True}, True, None),
        ("phone-no-bands", "390", {"nx.os.rain": True}, False, None),
        ("ambient-off", "1440", {"nx.os.rain": True, "nx.os.ambient": False}, False, None),
        ("rain-off", "1440", {}, False, None),
    ]
    try:
        for name, width, extra, reduced, _ in cases:
            rig.session("terminal", t.VIEWPORTS[width], extra=extra, reduced=reduced)
            time.sleep(args.seconds)
            results[name] = rig.js(STATS)
            if name == "wide-rain-on":
                rig.page.screenshot(path=str(out / "rain-terminal-1440.png"))
            print(name, json.dumps(results[name]), flush=True)
    finally:
        rig.stop()
    (out / "rain-receipt.json").write_text(json.dumps({"engine": exe, "cases": results, "errors": rig.errors}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
