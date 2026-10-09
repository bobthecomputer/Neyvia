"""Permissive PDF helpers: pypdf (BSD) reads text and fonts and writes PDFs, pypdfium2 (Apache-2.0/BSD-3, PDFium) renders pages.

Everything imports lazily so opening Neyvia never loads a PDF library.
Canvas coordinates use a top-left origin in points, like most callers expect.
"""
from __future__ import annotations

import io
from pathlib import Path


def _reader(source):
    from pypdf import PdfReader
    if isinstance(source, (bytes, bytearray)):
        return PdfReader(io.BytesIO(bytes(source)))
    return PdfReader(str(source))


def page_count(source) -> int:
    return len(_reader(source).pages)


def page_texts(source) -> list[str]:
    return [page.extract_text() or "" for page in _reader(source).pages]


def text(source) -> str:
    """All page text joined by newlines."""
    return "\n".join(page_texts(source))


def fonts(source) -> set[tuple[str, bool]]:
    """(base font name without subset tag, embedded) for every font used on any page."""
    found = set()

    def visit(font):
        font = font.get_object()
        name = str(font.get("/BaseFont", "")).lstrip("/").split("+")[-1]
        descriptor = font.get("/FontDescriptor")
        for child in font.get("/DescendantFonts", []) or []:
            descriptor = descriptor or child.get_object().get("/FontDescriptor")
        embedded = False
        if descriptor is not None:
            descriptor = descriptor.get_object()
            embedded = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
        found.add((name, embedded))

    for page in _reader(source).pages:
        resources = page.get("/Resources")
        table = resources.get_object().get("/Font") if resources is not None else None
        if table is not None:
            for font in table.get_object().values():
                visit(font)
    return found


def page_size(source, index: int = 0) -> tuple[float, float]:
    box = _reader(source).pages[index].mediabox
    return float(box.width), float(box.height)


def render(source, index: int = 0, scale: float = 1.0, dpi: float | None = None):
    """Render page `index` (0-based) on white as an RGB PIL image; dpi overrides scale (72 points per inch)."""
    import pypdfium2
    if dpi is not None:
        scale = dpi / 72
    document = pypdfium2.PdfDocument(bytes(source) if isinstance(source, (bytes, bytearray)) else str(source))
    try:
        return document[index].render(scale=scale).to_pil().convert("RGB")
    finally:
        document.close()


def locked(source) -> bool:
    return bool(_reader(source).is_encrypted)


class Canvas:
    """A small PDF writer for generated fixtures: text, shapes, curves, PNG images, metadata."""

    FONTS = {"helv": "Helvetica", "hebo": "Helvetica-Bold", "cour": "Courier", "tiro": "Times-Roman"}

    def __init__(self, width: float = 595, height: float = 842):
        self.pages: list[dict] = []
        self.metadata: dict = {}
        self.add_page(width, height)

    def add_page(self, width: float | None = None, height: float | None = None):
        last = self.pages[-1] if self.pages else {"w": 595, "h": 842}
        self.pages.append({"w": width or last["w"], "h": height or last["h"], "ops": [], "fonts": {}, "images": [], "alphas": []})
        return len(self.pages) - 1

    @property
    def _page(self):
        return self.pages[-1]

    def _y(self, y):
        return self._page["h"] - y

    @staticmethod
    def _rgb(color):
        return "%.4f %.4f %.4f" % tuple(color)

    def _style(self, fill, stroke, width, opacity=None):
        ops = []
        if opacity is not None:
            alphas = self._page["alphas"]
            if opacity not in alphas:
                alphas.append(opacity)
            ops.append(f"/GS{alphas.index(opacity)} gs")
        if fill is not None:
            ops.append(self._rgb(fill) + " rg")
        if stroke is not None:
            ops.append(self._rgb(stroke) + " RG %.3f w" % width)
        return ops

    @staticmethod
    def _paint(fill, stroke):
        return "B" if fill is not None and stroke is not None else "f" if fill is not None else "S" if stroke is not None else "n"

    def text(self, point, string, size=11, font="helv", color=(0, 0, 0), rotate=0):
        page = self._page
        name = self.FONTS.get(font, font)
        key = page["fonts"].setdefault(name, f"F{len(page['fonts'])}")
        safe = str(string).encode("cp1252", "replace").decode("latin-1")
        safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        cos, sin = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rotate % 360]
        page["ops"].append(f"BT {self._rgb(color)} rg /{key} {size} Tf {cos} {sin} {-sin} {cos} {point[0]:.2f} {self._y(point[1]):.2f} Tm ({safe}) Tj ET")

    def rect(self, box, fill=None, stroke=None, width=1.0, radius=0.0):
        x0, y0, x1, y1 = box
        top, bottom = self._y(y0), self._y(y1)
        ops = ["q", *self._style(fill, stroke, width)]
        r = min(radius * min(x1 - x0, y1 - y0), (x1 - x0) / 2, (y1 - y0) / 2) if radius else 0
        if r:
            k = r * 0.5523
            ops.append(f"{x0 + r:.2f} {bottom:.2f} m {x1 - r:.2f} {bottom:.2f} l {x1 - r + k:.2f} {bottom:.2f} {x1:.2f} {bottom + r - k:.2f} {x1:.2f} {bottom + r:.2f} c "
                       f"{x1:.2f} {top - r:.2f} l {x1:.2f} {top - r + k:.2f} {x1 - r + k:.2f} {top:.2f} {x1 - r:.2f} {top:.2f} c "
                       f"{x0 + r:.2f} {top:.2f} l {x0 + r - k:.2f} {top:.2f} {x0:.2f} {top - r + k:.2f} {x0:.2f} {top - r:.2f} c "
                       f"{x0:.2f} {bottom + r:.2f} l {x0:.2f} {bottom + r - k:.2f} {x0 + r - k:.2f} {bottom:.2f} {x0 + r:.2f} {bottom:.2f} c h {self._paint(fill, stroke)}")
        else:
            ops.append(f"{x0:.2f} {bottom:.2f} {x1 - x0:.2f} {y1 - y0:.2f} re {self._paint(fill, stroke)}")
        ops.append("Q")
        self._page["ops"].append(" ".join(ops))

    def circle(self, center, radius, fill=None, stroke=None, width=1.0):
        cx, cy, k = center[0], self._y(center[1]), radius * 0.5523
        path = (f"{cx + radius:.2f} {cy:.2f} m {cx + radius:.2f} {cy + k:.2f} {cx + k:.2f} {cy + radius:.2f} {cx:.2f} {cy + radius:.2f} c "
                f"{cx - k:.2f} {cy + radius:.2f} {cx - radius:.2f} {cy + k:.2f} {cx - radius:.2f} {cy:.2f} c "
                f"{cx - radius:.2f} {cy - k:.2f} {cx - k:.2f} {cy - radius:.2f} {cx:.2f} {cy - radius:.2f} c "
                f"{cx + k:.2f} {cy - radius:.2f} {cx + radius:.2f} {cy - k:.2f} {cx + radius:.2f} {cy:.2f} c h")
        self._page["ops"].append(" ".join(["q", *self._style(fill, stroke, width), path, self._paint(fill, stroke), "Q"]))

    def line(self, start, end, color=(0, 0, 0), width=1.0):
        self._page["ops"].append(" ".join(["q", *self._style(None, color, width),
                                           f"{start[0]:.2f} {self._y(start[1]):.2f} m {end[0]:.2f} {self._y(end[1]):.2f} l S", "Q"]))

    def bezier(self, p0, c1, c2, p3, color=(0, 0, 0), width=1.0, opacity=None):
        pts = [(p[0], self._y(p[1])) for p in (p0, c1, c2, p3)]
        self._page["ops"].append(" ".join(["q", *self._style(None, color, width, opacity),
            f"{pts[0][0]:.2f} {pts[0][1]:.2f} m {pts[1][0]:.2f} {pts[1][1]:.2f} {pts[2][0]:.2f} {pts[2][1]:.2f} {pts[3][0]:.2f} {pts[3][1]:.2f} c S", "Q"]))

    def image(self, box, png: bytes):
        from PIL import Image
        with Image.open(io.BytesIO(png)) as source:
            rgb = source.convert("RGB")
            size, data = rgb.size, rgb.tobytes()
        page = self._page
        page["images"].append((size, data))
        x0, y0, x1, y1 = box
        page["ops"].append(f"q {x1 - x0:.2f} 0 0 {y1 - y0:.2f} {x0:.2f} {self._y(y1):.2f} cm /Im{len(page['images']) - 1} Do Q")

    def tobytes(self) -> bytes:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject
        writer = PdfWriter()
        for spec in self.pages:
            page = writer.add_blank_page(width=spec["w"], height=spec["h"])
            stream = DecodedStreamObject()
            stream.set_data("\n".join(spec["ops"]).encode("latin-1"))
            page[NameObject("/Contents")] = writer._add_object(stream)
            resources = DictionaryObject()
            fonts_dict = DictionaryObject()
            for base, key in spec["fonts"].items():
                fonts_dict[NameObject("/" + key)] = writer._add_object(DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/" + base), NameObject("/Encoding"): NameObject("/WinAnsiEncoding")}))
            resources[NameObject("/Font")] = fonts_dict
            if spec["images"]:
                xobjects = DictionaryObject()
                for index, ((width, height), data) in enumerate(spec["images"]):
                    image = DecodedStreamObject()
                    image.set_data(data)
                    image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                                  NameObject("/Width"): NumberObject(width), NameObject("/Height"): NumberObject(height),
                                  NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
                    xobjects[NameObject(f"/Im{index}")] = writer._add_object(image.flate_encode())
                resources[NameObject("/XObject")] = xobjects
            if spec["alphas"]:
                states = DictionaryObject()
                for index, alpha in enumerate(spec["alphas"]):
                    states[NameObject(f"/GS{index}")] = DictionaryObject({NameObject("/CA"): FloatObject(alpha), NameObject("/ca"): FloatObject(alpha)})
                resources[NameObject("/ExtGState")] = states
            page[NameObject("/Resources")] = resources
        if self.metadata:
            writer.add_metadata({"/" + key.capitalize(): value for key, value in self.metadata.items()})
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    def save(self, path) -> None:
        Path(path).write_bytes(self.tobytes())
