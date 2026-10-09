"""Tile screenshots into one contact sheet: python scripts/look_sheet.py out.png a.png b.png ... [--cols 2 --scale 0.5]"""
import sys
from PIL import Image, ImageDraw

args = sys.argv[1:]
cols = int(args[args.index("--cols") + 1]) if "--cols" in args else 2
scale = float(args[args.index("--scale") + 1]) if "--scale" in args else 0.5
files = [a for i, a in enumerate(args[1:], 1) if not a.startswith("--") and args[i - 1] not in ("--cols", "--scale")]
images = [Image.open(f).convert("RGB") for f in files]
w, h = int(images[0].width * scale), int(images[0].height * scale)
rows = (len(images) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w + (cols - 1) * 8, rows * (h + 22)), (120, 120, 120))
draw = ImageDraw.Draw(sheet)
for n, (f, im) in enumerate(zip(files, images)):
    x, y = (n % cols) * (w + 8), (n // cols) * (h + 22)
    draw.text((x + 4, y + 4), f.replace("\\", "/").split("/")[-1], fill=(255, 255, 255))
    sheet.paste(im.resize((w, h), Image.LANCZOS), (x, y + 22))
sheet.save(args[0], optimize=True)
print(args[0])
