"""Contact sheet for scripts/appdesign_shots.py: one row per app, one column per theme, each cell the
app's window cropped from the 1440x900 shot. python scripts/appdesign_sheet.py <set> [--side]"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
THEMES = ["forest", "morning", "sunset", "night"]


def sheet(folder: Path, apps: list[str], suffix: str = "", crop=(288, 0, 1060, 870), scale=0.5, out_name="sheet.png") -> Path:
    cell_w, cell_h = int((crop[2] - crop[0]) * scale), int((crop[3] - crop[1]) * scale)
    pad, label = 6, 18
    canvas = Image.new("RGB", (len(THEMES) * (cell_w + pad) + pad, len(apps) * (cell_h + pad + label) + pad), (24, 24, 26))
    draw = ImageDraw.Draw(canvas)
    for r, app in enumerate(apps):
        for c, theme in enumerate(THEMES):
            path = folder / f"{app}-{theme}{suffix}.png"
            x, y = pad + c * (cell_w + pad), pad + r * (cell_h + pad + label)
            draw.text((x + 2, y + 2), f"{app} / {theme}{suffix}", fill=(220, 220, 220))
            if path.exists():
                image = Image.open(path).convert("RGB").crop(crop).resize((cell_w, cell_h), Image.LANCZOS)
                canvas.paste(image, (x, y + label))
    target = folder / out_name
    canvas.save(target)
    return target


if __name__ == "__main__":
    folder = ROOT / "docs/evidence/appdesign" / sys.argv[1]
    apps = sorted({p.stem.rsplit("-", 1)[0] for p in folder.glob("*-forest.png")})
    print(sheet(folder, apps[: len(apps) // 2], out_name="sheet-a.png"))
    print(sheet(folder, apps[len(apps) // 2:], out_name="sheet-b.png"))
