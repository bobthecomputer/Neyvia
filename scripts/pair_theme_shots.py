"""Join <view>-<a>.png and <view>-<b>.png side by side into <view>-pair.png (plan 19 R3).

python scripts/pair_theme_shots.py proof/r3-light/before [--themes dark,light] [--scale 0.5]
"""
import argparse
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("folder", type=Path)
parser.add_argument("--themes", default="dark,light")
parser.add_argument("--scale", type=float, default=0.5)
args = parser.parse_args()
left, right = args.themes.split(",")
for a in sorted(args.folder.glob(f"*-{left}.png")):
    view = a.name[: -len(f"-{left}.png")]
    b = args.folder / f"{view}-{right}.png"
    if not b.exists():
        continue
    one, two = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    h = min(max(one.height, two.height), 2400)
    canvas = Image.new("RGB", (one.width + two.width + 12, h), (128, 128, 128))
    canvas.paste(one.crop((0, 0, one.width, min(one.height, h))), (0, 0))
    canvas.paste(two.crop((0, 0, two.width, min(two.height, h))), (one.width + 12, 0))
    if args.scale != 1:
        canvas = canvas.resize((int(canvas.width * args.scale), int(canvas.height * args.scale)), Image.LANCZOS)
    canvas.save(args.folder / f"{view}-pair.png", optimize=True)
    print(view)
