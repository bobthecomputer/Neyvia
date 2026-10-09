"""Before/after pairs for the app design pass: docs/evidence/appdesign/final/NN-<app>-<theme>.png
(first pass) and final2/ (second pass: --second, before = the first pass's after set).

Each pair crops the app's window out of the 1440x900 Obscura shots (before = track/int-final,
after = this track) and puts them side by side with a label. python scripts/appdesign_final.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/evidence/appdesign"
OUT = BASE / "final"
MAIN = (288, 0, 1060, 870)
SIDE = (960, 0, 1440, 870)

PAIRS = [
    ("app-factory", "forest", MAIN), ("app-factory", "morning", MAIN), ("app-factory", "sunset-side", SIDE),
    ("3d-studio", "forest", MAIN), ("3d-studio", "morning", MAIN),
    ("terminal", "night", MAIN), ("terminal", "morning", MAIN),
    ("pdf", "forest", MAIN), ("notes", "sunset", MAIN), ("files", "night", MAIN),
    ("image-studio", "forest", MAIN), ("image-studio", "morning", MAIN),
    ("research", "morning", MAIN), ("research", "forest-side", SIDE),
    ("mobile-studio", "sunset", MAIN), ("app-preview", "night", MAIN), ("browser", "forest", MAIN),
    ("cua-preview", "sunset", MAIN), ("laya", "morning", MAIN),
]
EXTRAS = ["app-factory-forest-full-typing", "app-factory-morning-full-iphone", "app-factory-forest-full-android", "app-factory-morning-full-browser",
          "app-factory-forest-side-typing", "3d-page-forest-no-webgl", "3d-page-morning-no-webgl"]


SECOND = [  # (before shot in after/, after shot in after2/, crop)
    ("terminal-forest", "terminal-forest-content", MAIN), ("terminal-morning", "terminal-morning-content", MAIN), ("terminal-night", "terminal-night", MAIN),
    ("notes-forest", "notes-forest-welcome", MAIN), ("notes-morning", "notes-morning-welcome", MAIN), ("notes-sunset", "notes-sunset", MAIN),
    ("notes-forest", "notes-forest-note", MAIN),
    ("files-forest", "files-forest-grid", MAIN), ("files-morning", "files-morning-grid", MAIN), ("files-night", "files-night", MAIN),
    ("pdf-forest", "pdf-forest", MAIN), ("pdf-morning", "pdf-morning", MAIN),
    ("research-forest", "research-forest-content", MAIN), ("research-morning", "research-morning", MAIN), ("research-sunset-side", "research-sunset-side", SIDE),
    ("image-studio-forest", "image-studio-forest", MAIN), ("image-studio-morning", "image-studio-morning", MAIN),
    ("browser-forest", "browser-forest", MAIN), ("browser-morning", "browser-morning", MAIN),
    ("cua-preview-sunset", "cua-preview-sunset", MAIN), ("laya-night", "laya-night", MAIN),
]


def pair(index: int, app: str, variant: str, crop, sets=("before", "after"), names=None, out=None) -> Path | None:
    before_name, after_name = names or (f"{app}-{variant}", f"{app}-{variant}")
    before, after = BASE / sets[0] / f"{before_name}.png", BASE / sets[1] / f"{after_name}.png"
    if not (before.exists() and after.exists()):
        return None
    left, right = (Image.open(path).convert("RGB").crop(crop) for path in (before, after))
    w, h = left.size
    canvas = Image.new("RGB", (w * 2 + 30, h + 34), (22, 22, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 10), f"BEFORE  {before_name}", fill=(200, 200, 200))
    draw.text((w + 20, 10), f"AFTER  {after_name}", fill=(235, 235, 235))
    canvas.paste(left, (10, 30))
    canvas.paste(right, (w + 20, 30))
    target = (out or OUT) / f"{index:02d}-{after_name}.png"
    canvas.save(target, optimize=True)
    return target


if __name__ == "__main__":
    import sys
    if "--second" in sys.argv:
        out = BASE / "final2"
        out.mkdir(parents=True, exist_ok=True)
        made = [pair(i + 1, "", "", crop, ("after", "after2"), (b, a), out) for i, (b, a, crop) in enumerate(SECOND)]
        print(sum(1 for item in made if item), "second-pass pairs")
        raise SystemExit(0)
    OUT.mkdir(parents=True, exist_ok=True)
    made = [pair(i + 1, *row) for i, row in enumerate(PAIRS)]
    for offset, name in enumerate(EXTRAS):
        source = BASE / "after" / f"{name}.png"
        if source.exists():
            Image.open(source).convert("RGB").save(OUT / f"{len(PAIRS) + offset + 1:02d}-{name}.png", optimize=True)
    print(sum(1 for item in made if item), "pairs")
