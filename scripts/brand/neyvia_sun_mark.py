"""Neyvia sun mark: a broad tree against a banded southern sunset.

One source for every logo asset. Writes the standalone SVGs (mark, light/dark app tiles, maskable tile) and the
path data the in-app ProviderMark registry uses (web/src/neyvia/next/neyviaSunMarkData.js).

    python scripts/brand/neyvia_sun_mark.py            # rewrite the SVG assets and registry data
    node scripts/brand/rasterize_neyvia_icons.mjs      # then the PNG/ICO icons from those SVGs
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INK = "#17110c"
DISC = (256, 240, 204)  # cx, cy, r
VIEW = (36, 20, 440)  # the mark's square view box: x, y, size
BANDS = [(0, "#ffd862"), (100, "#ffc850"), (146, "#ffb544"), (188, "#fd9e39"), (228, "#f88630"), (268, "#f06d29"),
         (306, "#e65424"), (342, "#d6401f"), (378, "#bf2e1c"), (414, "#a3231a")]
# Light coming through the canopy: x, y, rx, ry, rotation.
HOLES = [(198, 272, 15, 9, -20), (314, 272, 15, 9, 20), (230, 248, 12, 8, -35), (282, 248, 12, 8, 35),
         (150, 258, 12, 7, -10), (362, 258, 12, 7, 10), (256, 256, 10, 7, 0), (214, 206, 9, 6, -30),
         (298, 206, 9, 6, 30), (176, 222, 8, 5, -20), (336, 222, 8, 5, 20)]
HOLE_FILL = "#ffcf78"
BRANCHES = [("M248 344C232 312 196 288 142 268", 17), ("M264 344C280 312 316 288 370 268", 17),
            ("M246 336C236 300 216 268 198 232", 14), ("M266 336C276 300 296 268 314 232", 14),
            ("M252 334C250 296 252 246 256 196", 13),
            ("M212 296C186 280 160 260 140 238", 9), ("M300 296C326 280 352 260 372 238", 9),
            ("M226 276C214 248 208 214 206 182", 8), ("M286 276C298 248 304 214 306 182", 8)]
TRUNK = "M190 432C222 424 234 404 238 378C240 360 240 346 238 330L274 330C272 346 272 360 274 378C278 404 290 424 322 432Z"


def _blob(cx, cy, radius, seed):
    rnd = random.Random(seed)
    count = max(7, int(radius / 4.5))
    out = [(cx, cy, radius * 0.8)]
    for index in range(count):
        angle = 2 * math.pi * index / count + rnd.uniform(-0.18, 0.18)
        dist, r = radius * rnd.uniform(0.58, 0.7), radius * rnd.uniform(0.34, 0.44)
        out.append((cx + dist * math.cos(angle), cy + dist * math.sin(angle) * 0.82, r))
    return out


def canopy_circles():
    clusters, steps = [], 11
    for index in range(steps):
        t = math.pi + math.pi * index / (steps - 1)
        x, y = 256 + 140 * math.cos(t), 276 + 132 * math.sin(t) * 0.92
        edge = index in (0, steps - 1)
        clusters.append((x, y - (8 if edge else 0), 33 * (0.86 if edge else 1)))
    clusters += [(256, 196, 54), (196, 228, 40), (316, 228, 40), (256, 150, 40)]
    circles = []
    for index, cluster in enumerate(clusters):
        circles += _blob(*cluster, seed=index * 13 + 5)
    return circles


def circles_path(circles):
    # One path, nonzero fill: overlapping circles merge into a single scalloped canopy.
    return "".join(f"M{x - r:.1f} {y:.1f}a{r:.1f} {r:.1f} 0 1 0 {2 * r:.1f} 0a{r:.1f} {r:.1f} 0 1 0 {-2 * r:.1f} 0Z"
                   for x, y, r in circles)


def ellipse_path(x, y, a, b, deg):
    t = math.radians(deg)
    dx, dy = a * math.cos(t), a * math.sin(t)
    return (f"M{x - dx:.1f} {y - dy:.1f}A{a} {b} {deg} 1 0 {x + dx:.1f} {y + dy:.1f}"
            f"A{a} {b} {deg} 1 0 {x - dx:.1f} {y - dy:.1f}Z")


def ground_path():
    cx, cy, r = DISC
    y = 428
    half = math.sqrt(r * r - (y - cy) ** 2)
    return f"M{cx - half:.1f} {y}Q{cx} 404 {cx + half:.1f} {y}A{r} {r} 0 0 1 {cx - half:.1f} {y}Z"


def disc_path():
    cx, cy, r = DISC
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0Z"


def band_stops():
    # Hard stops: each band is a flat colour, like a screen-printed sunset.
    top, bottom = DISC[1] - DISC[2], DISC[1] + DISC[2]
    stops = []
    for index, (y, color) in enumerate(BANDS):
        end = BANDS[index + 1][0] if index + 1 < len(BANDS) else bottom
        if end <= top:
            continue
        stops.append([round((max(y, top) - top) / (bottom - top), 4), color])
        stops.append([round((min(end, bottom) - top) / (bottom - top), 4), color])
    return stops


def registry_entry():
    view = " ".join(str(v) for v in (*VIEW, VIEW[2]))
    tree = [{"d": TRUNK}, {"d": ground_path()}, {"d": circles_path(canopy_circles())}]
    branches = [{"d": d, "stroke": w} for d, w in BRANCHES]
    return {
        "id": "neyvia", "label": "Neyvia", "color": INK, "ink": False, "viewBox": view,
        "gradients": [
            {"id": "sun", "x1": 0, "y1": DISC[1] - DISC[2], "x2": 0, "y2": DISC[1] + DISC[2],
             "units": "userSpaceOnUse", "stops": band_stops()},
            {"id": "glow", "type": "radial", "cx": 256, "cy": 232, "r": 200, "units": "userSpaceOnUse",
             "stops": [[0, "#fff3c4", 0.95], [0.45, "#ffd36a", 0.35], [1, "#ffb347", 0]]},
        ],
        "paths": [{"d": disc_path(), "fill": "url(#sun)"}, {"d": disc_path(), "fill": "url(#glow)"},
                  *[{**p, "fill": INK} for p in tree],
                  *[{"d": ellipse_path(*h), "fill": HOLE_FILL} for h in HOLES],
                  *[{**b, "fill": INK} for b in branches]],
        "mono": {"viewBox": view, "paths": [*tree, *branches]},
    }


def standalone_inner():
    entry = registry_entry()
    defs = []
    for gradient in entry["gradients"]:
        radial = gradient.get("type") == "radial"
        tag = "radialGradient" if radial else "linearGradient"
        keys = ("cx", "cy", "r") if radial else ("x1", "y1", "x2", "y2")
        attrs = " ".join(f'{k}="{gradient[k]}"' for k in keys)
        stops = "".join(f'<stop offset="{s[0]}" stop-color="{s[1]}"' + (f' stop-opacity="{s[2]}"' if len(s) > 2 else "") + "/>"
                        for s in gradient["stops"])
        defs.append(f'<{tag} id="{gradient["id"]}" {attrs} gradientUnits="userSpaceOnUse">{stops}</{tag}>')
    body = []
    for path in entry["paths"]:
        if path.get("stroke"):
            body.append(f'<path d="{path["d"]}" fill="none" stroke="{path["fill"]}" stroke-width="{path["stroke"]}" '
                        'stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            body.append(f'<path d="{path["d"]}" fill="{path["fill"]}"/>')
    return f'<defs>{"".join(defs)}</defs>{"".join(body)}'


def mark_svg(inner):
    x, y, size = VIEW
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {size} {size}" role="img" aria-label="Neyvia">'
            f"<title>Neyvia</title>{inner}</svg>\n")


def tile_svg(inner, background, scale, radius=112):
    # The mark centred in a 512 tile at `scale` of the tile's width.
    x, y, size = VIEW
    width = 512 * scale
    offset = (512 - width) / 2
    factor = width / size
    rect = f'<rect width="512" height="512" rx="{radius}" fill="{background}"/>' if background else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Neyvia">'
            f'<title>Neyvia</title>{rect}<g transform="translate({offset - x * factor:.2f} {offset - y * factor:.2f}) '
            f'scale({factor:.4f})">{inner}</g></svg>\n')


def main():
    inner = standalone_inner()
    brand = ROOT / "docs" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    outputs = {
        brand / "neyvia-sun-mark.svg": mark_svg(inner),
        brand / "neyvia-app-icon-light.svg": tile_svg(inner, "#fbf6ec", 0.78),
        brand / "neyvia-app-icon-dark.svg": tile_svg(inner, "#16110d", 0.78),
        brand / "neyvia-app-icon-maskable.svg": tile_svg(inner, "#fbf6ec", 0.62, radius=0),
        ROOT / "src-tauri" / "icons" / "neyvia-icon.svg": tile_svg(inner, None, 0.96),
        ROOT / "web" / "public" / "icons" / "neyvia-mark.svg": mark_svg(inner),
        ROOT / "web" / "src" / "neyvia" / "next" / "neyviaSunMarkData.js": (
            "// Generated by scripts/brand/neyvia_sun_mark.py. Edit the script, not this file.\n"
            "// Neyvia's own mark: a broad tree against a banded southern sunset (in-house, no third-party source).\n"
            f"export const NEYVIA_SUN_MARK = {json.dumps(registry_entry(), separators=(',', ':'))};\n"),
    }
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(text):,} bytes)")


if __name__ == "__main__":
    main()
