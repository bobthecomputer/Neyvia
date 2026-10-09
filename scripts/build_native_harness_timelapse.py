"""Build a compact GIF from the three real native-harness proof frames."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FRAME_SPECS = (
    ("01-before-native-harness-evidence.png", "BEFORE · blocked readiness", 1800),
    ("02-after-native-harness.png", "AFTER · measurable native harness", 1800),
    ("03-native-run-timeline.png", "PROOF · completed DeepSeek V4 Flash run", 2600),
)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
    except OSError:
        return ImageFont.load_default()


def _baseline_evidence_plate(proof_dir: Path) -> Path:
    raw = Image.open(proof_dir / "01-before-native-harness.png").convert("RGB")
    raw.save(proof_dir / "01-before-native-harness-raw.jpg", format="JPEG", quality=95)
    canvas = Image.new("RGB", (776, 411), "#080c0b")
    draw = ImageDraw.Draw(canvas)
    capture_width = 180
    scale = min(capture_width / raw.width, 379 / raw.height)
    capture = raw.resize(
        (round(raw.width * scale), round(raw.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas.paste(capture, (24 + (capture_width - capture.width) // 2, 16))
    draw.line((226, 24, 226, 387), fill="#26322e", width=1)
    draw.text((254, 30), "LIVE NAS BASELINE", fill="#8ca39a", font=_font(13, bold=True))
    draw.text((254, 62), "NEYVIA Native was blocked", fill="#f1f7f4", font=_font(27, bold=True))
    draw.text((254, 110), "Version probe timed out after 3 seconds.", fill="#d4dfda", font=_font(16))
    rows = (
        ("Readiness", "Blocked"),
        ("Measured summary fields", "2"),
        ("Timeline milestones", "0"),
    )
    y = 162
    for label, value in rows:
        draw.text((254, y), label.upper(), fill="#789087", font=_font(11, bold=True))
        draw.text((520, y - 5), value, fill="#f1f7f4", font=_font(19, bold=True))
        draw.line((254, y + 28, 746, y + 28), fill="#1e2925", width=1)
        y += 54
    draw.text((254, 342), "Captured in authenticated Chrome before the repair", fill="#8ca39a", font=_font(13))
    draw.text((254, 366), "Raw full-page frame retained beside this evidence plate", fill="#8ca39a", font=_font(13))
    output = proof_dir / "01-before-native-harness-evidence.png"
    canvas.save(output, format="PNG", optimize=False)
    raw.close()
    return output


def _normalize_png(path: Path) -> None:
    image = Image.open(path).convert("RGB")
    temporary = path.with_suffix(".normalized.png")
    image.save(temporary, format="PNG", optimize=False)
    image.close()
    temporary.replace(path)


def _letterbox(source: Image.Image, label: str, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "#090d0c")
    image = source.convert("RGB")
    image.thumbnail((size[0], size[1] - 52), Image.Resampling.LANCZOS)
    x = (size[0] - image.width) // 2
    y = 52 + (size[1] - 52 - image.height) // 2
    canvas.paste(image, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, size[0], 52), fill="#101715")
    draw.text((22, 17), label, fill="#e7f3ed", font=ImageFont.load_default())
    return canvas


def build(proof_dir: Path) -> Path:
    _baseline_evidence_plate(proof_dir)
    _normalize_png(proof_dir / "02-after-native-harness.png")
    _normalize_png(proof_dir / "03-native-run-timeline.png")
    sources = [Image.open(proof_dir / name) for name, _label, _duration in FRAME_SPECS]
    width = max(image.width for image in sources)
    height = max(image.height for image in sources) + 52
    frames = [
        _letterbox(image, label, (width, height))
        for image, (_name, label, _duration) in zip(sources, FRAME_SPECS, strict=True)
    ]
    output = proof_dir / "native-harness-improvement-timelapse.gif"
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=[duration for _name, _label, duration in FRAME_SPECS],
        loop=0,
        optimize=False,
        disposal=2,
    )
    for image in sources:
        image.close()
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", type=Path, required=True)
    output = build(parser.parse_args().proof_dir.resolve())
    print(f"{output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
