"""Paul's study documents: the neyvia-study LaTeX class, Tectonic builds and outcome checks.

The class lives in templates/latex/neyvia-study (course and sheet variants, Inter
bundled under the SIL OFL). Builds use one Tectonic binary (XeTeX) whose package
cache sits on D:/NeyviaRuns/tectonic; no TeX distribution is installed. Every
function returns plain JSON-able dicts so the documents manual
(manuals/cl/documents.cl), the workspace tools and scripts/study_docs.py share
one implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "templates" / "latex" / "neyvia-study"
RUNS = Path(os.environ.get("NEYVIA_DOCS_RUNS", "D:/NeyviaRuns/docs"))
TECTONIC_HOME = Path(os.environ.get("NEYVIA_TECTONIC_HOME", "D:/NeyviaRuns/tectonic"))
TECTONIC_VERSION = "0.17.0"
TECTONIC_URL = ("https://github.com/tectonic-typesetting/tectonic/releases/download/"
                f"tectonic%40{TECTONIC_VERSION}/tectonic-{TECTONIC_VERSION}-x86_64-pc-windows-msvc.zip")
MAX_DOWNLOAD = 200 * 1024 * 1024
VARIANTS = ("course", "sheet")
BLOCKS = {"1": "definition", "2": "method", "3": "reflex", "4": "worked", "5": "traps", "6": "practice"}
# Pages per chapter a document may use before the page check fails.
PAGE_LIMITS = {"course": 60, "sheet": 15}
OVERFULL_LIMIT_PT = 1.0
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# --------------------------------------------------------------------------- toolchain

def tectonic_path() -> Path:
    configured = os.environ.get("NEYVIA_TECTONIC")
    if configured:
        return Path(configured)
    return TECTONIC_HOME / "bin" / ("tectonic.exe" if os.name == "nt" else "tectonic")


def toolchain(install: bool = False) -> dict:
    """Report (or install from the official GitHub release) the Tectonic binary."""
    binary = tectonic_path()
    if not binary.is_file() and install:
        import urllib.request
        TECTONIC_HOME.joinpath("dl").mkdir(parents=True, exist_ok=True)
        archive = TECTONIC_HOME / "dl" / f"tectonic-{TECTONIC_VERSION}.zip"
        with urllib.request.urlopen(urllib.request.Request(TECTONIC_URL, method="HEAD"), timeout=60) as head:
            size = int(head.headers.get("Content-Length") or 0)
        if size > MAX_DOWNLOAD:
            return {"ok": False, "binary": str(binary), "reason": f"release archive is {size} bytes, over the 200 MB stop line"}
        urllib.request.urlretrieve(TECTONIC_URL, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(binary.name, binary.parent)
    version = ""
    if binary.is_file():
        run = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
        version = run.stdout.strip()
    fonts = sorted(path.name for path in (TEMPLATE / "fonts").glob("Inter-*.otf"))
    return {"ok": binary.is_file() and len(fonts) == 4, "binary": str(binary), "version": version,
            "cache": str(TECTONIC_HOME / "cache"), "class": str(TEMPLATE / "neyvia-study.cls"), "fonts": fonts}


# --------------------------------------------------------------------------- create

def _tex_escape(text: str) -> str:
    return re.sub(r"([&%#_$])", r"\\\1", text.strip())


def create(path, variant: str, title: str, chapters: list[str], subtitle: str | None = None,
           source_prefix: str = "", overwrite: bool = False) -> dict:
    """Write a new document on the class: one chapter per title, one concept skeleton each."""
    if variant not in VARIANTS:
        raise ValueError("variant must be course or sheet")
    if not title.strip() or not chapters or any(not name.strip() for name in chapters):
        raise ValueError("a title and at least one nonempty chapter title are required")
    path = Path(path)
    if path.suffix != ".tex":
        raise ValueError("documents are .tex files")
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; pass overwrite to replace it")
    lines = [f"\\documentclass[{variant}]{{neyvia-study}}",
             f"\\studytitle{{{_tex_escape(title)}}}"]
    if subtitle:
        lines.append(f"\\studysubtitle{{{_tex_escape(subtitle)}}}")
    if source_prefix:
        lines.append(f"\\studysourceprefix{{{_tex_escape(source_prefix)} }}")
    lines += ["\\begin{document}", "\\maketitle", ""]
    for chapter in chapters:
        lines += [f"\\studychapter{{{_tex_escape(chapter)}}}",
                  "\\studypart{I}{First part}",
                  "",
                  "% One concept = the six blocks in this order. Traps and practice are optional.",
                  "% The tag is where the concept comes from in your source (page, column).",
                  "\\begin{concept}{First concept}{p1}",
                  "\\begin{definition}",
                  "Let $E$ be a set. State the definition or formula exactly.",
                  "\\dline{\\forall x\\in E,\\ \\exists y\\in E,\\ x=y}",
                  "\\end{definition}",
                  "\\begin{method}{What the method proves}",
                  "\\step{Let $x\\in E$.}",
                  "\\step{Then $x=x$.}",
                  "\\step{$\\therefore$ the claim holds.}",
                  "\\end{method}",
                  "\\begin{reflex}",
                  "Cue in the exercise \\ra{} first line to write.",
                  "\\end{reflex}",
                  "\\begin{worked}{A small solved example}",
                  "\\step{Let $x=2$.}",
                  "\\result{x=2}",
                  "\\end{worked}",
                  "\\begin{traps}",
                  "\\trap{The mistake people make, said plainly.}",
                  "\\end{traps}",
                  "\\begin{practice}",
                  "\\try{The same example with one number changed.}",
                  "\\answer{Its answer.}",
                  "\\end{practice}",
                  "\\end{concept}",
                  ""]
    lines.append("\\end{document}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    sidecar = path.with_suffix(".study.json")
    sidecar.write_text(json.dumps({"schema": "neyvia.study-doc.v1", "variant": variant, "title": title,
                                   "chapters": chapters, "maxPages": PAGE_LIMITS[variant] * len(chapters)}, indent=2) + "\n",
                       encoding="utf-8")
    return {"ok": True, "tex": str(path), "sidecar": str(sidecar), "variant": variant, "chapters": len(chapters)}


# --------------------------------------------------------------------------- build

def default_outdir(tex: Path) -> Path:
    return RUNS / Path(tex).stem


def build(tex, outdir=None, timeout: int = 600) -> dict:
    """Compile with Tectonic. Keeps log and aux next to the PDF for the checks."""
    tex = Path(tex).resolve()
    if not tex.is_file():
        raise FileNotFoundError(str(tex))
    outdir = Path(outdir) if outdir else default_outdir(tex)
    outdir.mkdir(parents=True, exist_ok=True)
    binary = tectonic_path()
    if not binary.is_file():
        return {"ok": False, "tex": str(tex), "reason": "Tectonic is not installed; run study_docs.py setup"}
    # Tectonic gets its own profile on D: (it refuses to start when the profile
    # has no AppData folders, as in disposable proof homes) and a fixed cache.
    profile = TECTONIC_HOME / "profile"
    for folder in (profile / "AppData" / "Roaming", profile / "AppData" / "Local"):
        folder.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TECTONIC_CACHE_DIR=str(TECTONIC_HOME / "cache"), USERPROFILE=str(profile),
               APPDATA=str(profile / "AppData" / "Roaming"), LOCALAPPDATA=str(profile / "AppData" / "Local"))
    command = [str(binary), "-Z", f"search-path={TEMPLATE}", "-Z", f"search-path={TEMPLATE / 'fonts'}",
               "--keep-logs", "--keep-intermediates", "--chatter", "minimal", "-o", str(outdir), str(tex)]
    for stale in (outdir / (tex.stem + ".pdf"), outdir / (tex.stem + ".log")):
        if stale.exists():
            stale.unlink()
    started = time.perf_counter()

    def compile_once(offline):
        return subprocess.run([command[0], *(["--only-cached"] if offline else []), *command[1:]], cwd=str(tex.parent), env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=_NO_WINDOW)
    # An isolated no-auto-update proof must report a cache miss without fetching
    # dependencies. Normal authorized builds may retry online once.
    run = compile_once(True)
    online = False
    if run.returncode != 0 and os.environ.get('NEYVIA_TOOL_AUTO_UPDATE', '1') != '0':
        run, online = compile_once(False), True
    seconds = round(time.perf_counter() - started, 2)
    pdf, log, aux = (outdir / (tex.stem + suffix) for suffix in (".pdf", ".log", ".aux"))
    (outdir / (tex.stem + ".tectonic.txt")).write_text(run.stdout + run.stderr, encoding="utf-8")
    pages = 0
    if pdf.is_file():
        from .pdf_compat import page_count
        pages = page_count(pdf)
    errors = [line for line in (run.stdout + run.stderr).splitlines() if line.startswith("error")][:20]
    return {"ok": run.returncode == 0 and pdf.is_file(), "exitCode": run.returncode, "tex": str(tex),
            "pdf": str(pdf), "log": str(log), "aux": str(aux), "seconds": seconds, "pages": pages, "fetchedPackages": online,
            "errors": errors, "tectonic": str(outdir / (tex.stem + ".tectonic.txt"))}


# --------------------------------------------------------------------------- render

def _pages(spec, count: int) -> list[int]:
    if spec in (None, "", "all"):
        return list(range(1, count + 1))
    chosen = []
    for part in str(spec).split(","):
        if "-" in part:
            low, high = part.split("-", 1)
            chosen += list(range(int(low), min(int(high), count) + 1))
        else:
            chosen.append(int(part))
    return [page for page in chosen if 1 <= page <= count]


def render(pdf, out_dir=None, pages="1-3", dpi: int = 110) -> dict:
    """Render PDF pages to PNG files (pypdfium2, no window)."""
    from .pdf_compat import page_count, render as render_page
    pdf = Path(pdf)
    out_dir = Path(out_dir) if out_dir else pdf.parent / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for page in _pages(pages, page_count(pdf)):
        target = out_dir / f"{pdf.stem}-p{page:03d}.png"
        render_page(pdf, page - 1, dpi=dpi).save(target)
        written.append(str(target))
    return {"ok": bool(written), "pdf": str(pdf), "pngs": written, "dpi": dpi}


# --------------------------------------------------------------------------- checks

OVERFULL = re.compile(r"Overfull \\hbox \((\d+(?:\.\d+)?)pt too wide\)[^\n]*?lines? (\d+)")
UNDEFINED = re.compile(r"(?:Reference|Citation) `([^']+)' on page \d+ undefined|There were undefined (?:references|citations)")
TEX_ERROR = re.compile(r"^! (.+)$", re.M)
CONCEPT = re.compile(r"^\\nstudyconcept\{([^}]*)\}\{([0-9]*)\}\{(.*)\}\s*$", re.M)


def concepts(aux) -> list[dict]:
    """Concepts recorded by the class: number, block sequence and source tag."""
    aux = Path(aux)
    if not aux.is_file():
        return []
    return [{"concept": number, "blocks": blocks, "tag": tag.strip()}
            for number, blocks, tag in CONCEPT.findall(aux.read_text(encoding="utf-8", errors="replace"))]


def _variant(tex: Path) -> str:
    head = tex.read_text(encoding="utf-8", errors="replace")[:2000]
    match = re.search(r"\\documentclass\[([^\]]*)\]\{neyvia-study\}", head)
    return "sheet" if match and "sheet" in [part.strip() for part in match.group(1).split(",")] else "course"


def check(tex, outdir=None, max_pages: int | None = None, require: str = "13") -> dict:
    """Outcome checks on a built document; each reads the produced files, never fixtures."""
    tex = Path(tex).resolve()
    outdir = Path(outdir) if outdir else default_outdir(tex)
    pdf, log, aux = (outdir / (tex.stem + suffix) for suffix in (".pdf", ".log", ".aux"))
    variant = _variant(tex)
    results = []

    def record(name, ok, detail, **extra):
        results.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    log_text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    tectonic_text = (outdir / (tex.stem + ".tectonic.txt"))
    tectonic_text = tectonic_text.read_text(encoding="utf-8", errors="replace") if tectonic_text.is_file() else ""
    tex_errors = TEX_ERROR.findall(log_text)
    engine_errors = [line for line in tectonic_text.splitlines() if line.startswith("error:")]
    record("compiles", pdf.is_file() and log.is_file() and not tex_errors and not engine_errors,
           "no TeX errors" if not (tex_errors or engine_errors) else "; ".join((tex_errors + engine_errors)[:3]), errors=(tex_errors + engine_errors)[:10])

    undefined = sorted({match.group(1) or match.group(0) for match in UNDEFINED.finditer(log_text + tectonic_text)})
    record("references", log.is_file() and not undefined,
           "no undefined references or citations" if not undefined else ", ".join(undefined[:5]), undefined=undefined[:20])

    overfull = [{"pt": float(pt), "line": int(line)} for pt, line in OVERFULL.findall(log_text)]
    worst = max((row["pt"] for row in overfull), default=0.0)
    bad = [row for row in overfull if row["pt"] > OVERFULL_LIMIT_PT]
    record("overfull", log.is_file() and not bad,
           f"{len(bad)} overfull boxes over {OVERFULL_LIMIT_PT} pt (worst {worst} pt)" if bad else f"none over {OVERFULL_LIMIT_PT} pt (worst {worst} pt)",
           overfull=bad[:20])

    fonts, pages = set(), 0
    if pdf.is_file():
        from .pdf_compat import fonts as pdf_fonts, page_count
        pages = page_count(pdf)
        fonts = pdf_fonts(pdf)
    inter = sorted(name for name, embedded in fonts if name.startswith("Inter") and embedded)
    record("inter-embedded", any(name.startswith("Inter-Regular") for name in inter),
           ", ".join(inter) if inter else "Inter is not embedded", fonts=sorted(name for name, _ in fonts))

    rows = concepts(aux)
    disorder, untagged, missing = [], [], {}
    for row in rows:
        sequence = row["blocks"]
        if list(sequence) != sorted(sequence) or not sequence:
            disorder.append(row["concept"])
        if not row["tag"]:
            untagged.append(row["concept"])
        for block in require:
            if block not in sequence:
                missing.setdefault(BLOCKS[block], []).append(row["concept"])
    absent = {BLOCKS[block]: [row["concept"] for row in rows if block not in row["blocks"]]
              for block in "246" if block not in require}
    ok = bool(rows) and not disorder and not untagged and not missing
    detail = (f"{len(rows)} concepts, blocks in order 1-6 with {', '.join(BLOCKS[b] for b in require)} present and a source tag"
              if ok else f"{len(rows)} concepts; out of order {disorder[:8]}, untagged {untagged[:8]}, missing {dict((k, v[:8]) for k, v in missing.items())}")
    record("blocks", ok, detail, concepts=len(rows), outOfOrder=disorder, untagged=untagged, missing=missing,
           optionalAbsent={key: len(value) for key, value in absent.items()})

    chapters = 0
    toc = outdir / (tex.stem + ".toc")
    if toc.is_file():
        chapters = len(re.findall(r"\\contentsline \{section\}\{Chapter", toc.read_text(encoding="utf-8", errors="replace")))
    sidecar = tex.with_suffix(".study.json")
    if max_pages is None and sidecar.is_file():
        max_pages = json.loads(sidecar.read_text(encoding="utf-8")).get("maxPages")
    if max_pages is None:
        max_pages = PAGE_LIMITS[variant] * max(chapters, 1) + 3
    record("pages", 1 <= pages <= max_pages, f"{pages} pages (limit {max_pages}, {chapters} chapters, {variant})",
           pages=pages, maxPages=max_pages)
    flags = {re.sub(r"-(\w)", lambda m: m.group(1).upper(), row["name"]): row["ok"] for row in results}
    return {"ok": all(row["ok"] for row in results), "tex": str(tex), "pdf": str(pdf), "variant": variant, **flags,
            "checks": results, "passed": sum(row["ok"] for row in results), "total": len(results)}


# --------------------------------------------------------------------------- glance (pluggable)

def glance(pngs, command=None) -> dict:
    """LAYA page glance hook. Another component supplies the judge.

    The command (argument list, or NEYVIA_LAYA_GLANCE as JSON) gets a request
    file path and must print {"verdict": "looks fine"|"looks broken", "reason": ...}
    per page under "observations". Without a judge the step is reported as
    "not available", never as passed.
    """
    command = command or (json.loads(os.environ["NEYVIA_LAYA_GLANCE"]) if os.environ.get("NEYVIA_LAYA_GLANCE") else None)
    pngs = [str(path) for path in pngs]
    if not command:
        return {"ok": False, "status": "not available", "pages": pngs,
                "reason": "No LAYA page-glance judge is attached (NEYVIA_LAYA_GLANCE)"}
    request = Path(pngs[0]).parent / "laya-glance-request.json"
    request.write_text(json.dumps({"kind": "study-document", "pages": [
        {"png": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in pngs]}), encoding="utf-8")
    run = subprocess.run([*command, str(request)], capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW)
    try:
        verdict = json.loads(run.stdout)
        rows = verdict["observations"]
        fine = run.returncode == 0 and len(rows) == len(pngs) and all(row.get("verdict") == "looks fine" and row.get("reason") for row in rows)
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "status": "invalid response", "pages": pngs}
    return {"ok": fine, "status": "completed", "pages": pngs, "verdict": verdict}


# --------------------------------------------------------------------------- compare

def compare(original, port, pairs, out_dir, dpi: int = 80) -> dict:
    """Side-by-side page images (original left, port right) with a pixel difference score."""
    import numpy
    from .pdf_compat import render as render_page
    from PIL import Image, ImageDraw
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    if True:
        for left_page, right_page in pairs:
            left = render_page(original, left_page - 1, dpi=dpi)
            right = render_page(port, right_page - 1, dpi=dpi)
            if right.size != left.size:
                right = right.resize(left.size)
            a = numpy.asarray(left.convert("L"), dtype=numpy.int16)
            b = numpy.asarray(right.convert("L"), dtype=numpy.int16)
            changed = float((numpy.abs(a - b) > 48).mean())
            ink = float(((a < 200) | (b < 200)).mean()) or 1.0
            gap = 24
            sheet = Image.new("RGB", (left.width * 2 + gap, left.height + 28), "white")
            sheet.paste(left, (0, 28))
            sheet.paste(right, (left.width + gap, 28))
            draw = ImageDraw.Draw(sheet)
            draw.text((8, 8), f"original p{left_page}", fill=(90, 90, 90))
            draw.text((left.width + gap + 8, 8), f"neyvia-study port p{right_page}", fill=(90, 90, 90))
            target = out_dir / f"compare-{left_page:03d}-{right_page:03d}.png"
            sheet.save(target)
            rows.append({"original": left_page, "port": right_page, "image": str(target),
                         "changedPixels": round(changed, 5), "changedShareOfInk": round(changed / ink, 4)})
    return {"ok": True, "pairs": rows}


# --------------------------------------------------------------------------- port

def _group(text: str, start: int) -> tuple[str, int]:
    """Balanced {...} beginning at text[start] == '{'; returns (inside, index after)."""
    if text[start] != "{":
        raise ValueError(f"expected {{ at {start}: {text[start:start + 40]!r}")
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    raise ValueError("unbalanced group")


def _whole(line: str, prefix: str) -> str | None:
    """Return X when line is exactly prefix + '{' X '}'."""
    if not line.startswith(prefix + "{"):
        return None
    inside, end = _group(line, len(prefix))
    return inside if end == len(line) else None


def _port_line(line: str, block: str) -> str:
    if line.startswith("\\mline{1\\mind}"):
        inner = _whole(line, "\\mline{1\\mind}")
        if inner is not None:
            return f"\\step[1]{{{inner}}}"
    inner = _whole(line, "\\mline{0pt}")
    if inner is not None:
        if block == "traps" and inner.startswith("\\textbullet\\ "):
            return f"\\trap{{{inner[len(chr(92) + 'textbullet' + chr(92) + ' '):]}}}"
        if inner.startswith("\\textbf{Try:} "):
            return f"\\try{{{inner[len('\\textbf{Try:} '):]}}}"
        answer = _whole(inner, "\\textcolor{mute}")
        if answer is not None and answer.startswith("\\textbf{Answer:} "):
            return f"\\answer{{{answer[len('\\textbf{Answer:} '):]}}}"
        boxed = _whole(inner, "\\fcolorbox{boxc}{boxbg}")
        if boxed is not None and boxed.startswith("\\vphantom{Ag}$\\displaystyle ") and boxed.endswith("$") and boxed.count("$") == 2:
            return f"\\result{{{boxed[len('\\vphantom{Ag}$\\displaystyle '):-1]}}}"
        return f"\\step{{{inner}}}"
    for prefix in ("\\par\\vspace{1pt}\\noindent$\\displaystyle ", "\\vspace{1pt}\\noindent$\\displaystyle "):
        if line.startswith(prefix) and line.endswith("$\\par\\vspace{1pt}"):
            maths = line[len(prefix):-len("$\\par\\vspace{1pt}")]
            if "$" not in maths:
                return f"\\dline{{{maths}}}"
    bullet = "\\par\\noindent\\hangindent=1.2em\\hangafter=1\\hspace*{0.4em}\\textbullet\\ "
    if line.startswith(bullet):
        return f"\\point{{{line[len(bullet):]}}}"
    return line


def _port_body(content: str, block: str) -> str:
    content = content.strip()
    for lead in ("\\bfseries ", "\\small "):
        if content.startswith(lead):
            content = content[len(lead):]
    return "\n".join(_port_line(line, block) for line in content.split("\n"))


COURSE_CHAPTER = re.compile(r"\\clearpage\\markboth\{Chapter (\d+)\}\{Chapter \1\}\n\\phantomsection\\addcontentsline\{toc\}\{section\}(?=\{Chapter \1\\ ·\\ )")
COURSE_PART = re.compile(r"\\par\\vspace\{8pt\}\\Needspace\{12\\baselineskip\}\\phantomsection\\addcontentsline\{toc\}\{subsection\}(?=\{)")
COURSE_CONCEPT = re.compile(r"\\par\\vspace\{10pt\}\\Needspace\{9\\baselineskip\}\\phantomsection\\addcontentsline\{toc\}\{subsubsection\}(?=\{)")
COURSE_BLOCK = re.compile(r"\\par\\vspace\{5pt\}\\Needspace\{4\\baselineskip\}\\noindent\\setlength\{\\fboxsep\}\{2\.2pt\}\\setlength\{\\fboxrule\}\{0\.7pt\}"
                          r"\\fcolorbox\{\w+\}\{\w+!9\}\{\\textcolor\{\w+\}\{\\sffamily\\bfseries\\scriptsize\\ (\d)\\,\\,[A-Z /]+\\ \}\}")
COURSE_NOTE = "\\par\\vspace{2pt}{\\footnotesize\\textcolor{mute}{\\textit{Handout note:} "
SHEET_CHAPTER = re.compile(r"\\markboth\{Chapter (\d+)\}\{Chapter \1\}\\phantomsection\\addcontentsline\{toc\}\{section\}(?=\{Chapter \1\\ ·\\ )")
SHEET_PART = re.compile(r"\\par\\Needspace\{10\\baselineskip\}\\phantomsection\\addcontentsline\{toc\}\{subsection\}(?=\{)")
SHEET_CONCEPT = "\\begin{tcolorbox}[enhanced,before upper={\\raggedright},colback=white,colframe=black!18,"
SHEET_FORMULA = "\\begin{tcolorbox}[enhanced,before upper={\\raggedright},frame hidden,colback=defc!5,"
SHEET_METHOD = "\\par{\\color{methc}\\sffamily\\bfseries\\scriptsize METHOD "
SHEET_REFLEX = "\\par{\\small\\bfseries\\textcolor{reflc}{REFLEX\\ \\ }\\textcolor{ink}"


def _split_label(group: str) -> tuple[str, str]:
    label, _, title = group.partition("\\ \\ ")
    return label, title


def _box(text: str, index: int) -> tuple[str, int]:
    """Content of a \\begin{tcolorbox}[...] starting at index, up to its \\end{tcolorbox}."""
    open_at = text.index("]", text.index("\\begin{tcolorbox}[", index))
    depth, cursor = 1, open_at + 1
    while depth:
        nxt_begin = text.find("\\begin{tcolorbox}", cursor)
        nxt_end = text.find("\\end{tcolorbox}", cursor)
        if nxt_begin != -1 and nxt_begin < nxt_end:
            depth, cursor = depth + 1, nxt_begin + 1
        else:
            depth, cursor = depth - 1, nxt_end + len("\\end{tcolorbox}")
    return text[open_at + 1:cursor - len("\\end{tcolorbox}")], cursor


def _port_course(body: str) -> list[str]:
    out, index, open_concept = [], 0, False

    def close():
        nonlocal open_concept
        if open_concept:
            out.append("\\end{concept}")
            open_concept = False

    while index < len(body):
        rest = body[index:]
        if rest.startswith("\n"):
            index += 1
            continue
        match = COURSE_CHAPTER.match(body, index)
        if match:
            close()
            group, end = _group(body, match.end())
            out.append(f"\\studychapter{{{group.split(chr(92) + ' ·' + chr(92) + ' ', 1)[1]}}}")
            index = body.index("\n", end + 1)  # the heading line after it is produced by the class
            continue
        match = COURSE_PART.match(body, index)
        if match:
            close()
            group, end = _group(body, match.end())
            label, title = _split_label(group)
            out.append(f"\\studypart{{{label}}}{{{title}}}")
            index = body.index("\n", end) if "\n" in body[end:] else len(body)
            continue
        match = COURSE_CONCEPT.match(body, index)
        if match:
            close()
            group, end = _group(body, match.end())
            number_match = re.match(r"\\protect\\numberline\{([^}]*)\}", group)
            number, title = number_match.group(1), group[number_match.end():]
            line_end = body.index("\n", end + 1)
            heading = body[end + 1:line_end]
            tag = re.search(r"\\textcolor\{mute\}\{(?:handout )?([^}]*)\}\}\\par", heading).group(1)
            out.append(f"\\begin{{concept}}[{number}]{{{title}}}{{{tag}}}")
            open_concept = True
            index = line_end
            continue
        match = COURSE_BLOCK.match(body, index)
        if match:
            name = BLOCKS[match.group(1)]
            cursor = match.end()
            caption = None
            if body.startswith("\\ \\ \\textcolor{mute}", cursor):
                inner, cursor = _group(body, cursor + len("\\ \\ \\textcolor{mute}"))
                caption = inner.removeprefix("\\small ")
            assert body.startswith("\\par\\nopagebreak\\vspace{3pt}\n", cursor), body[cursor:cursor + 60]
            content, cursor = _box(body, cursor)
            head = f"\\begin{{{name}}}" + (f"{{{caption}}}" if caption is not None else "")
            out += [head, _port_body(content, name), f"\\end{{{name}}}"]
            index = cursor
            continue
        if rest.startswith(COURSE_NOTE):
            inner, end = _group(body, index + len("\\par\\vspace{2pt}"))
            note = _whole("x" + inner, "x\\footnotesize\\textcolor{mute}")
            out.append(f"\\studynote{{{note.removeprefix(chr(92) + 'textit{Handout note:} ')}}}")
            index = end
            continue
        line_end = body.find("\n", index)
        line_end = len(body) if line_end == -1 else line_end
        close()
        out.append(body[index:line_end])
        index = line_end
    close()
    return out


def _port_sheet(body: str) -> list[str]:
    out, lines, index = [], body.split("\n"), 0
    while index < len(lines):
        line = lines[index]
        match = SHEET_CHAPTER.match(line)
        if match:
            group, _ = _group(line, match.end())
            out.append(f"\\studychapter{{{group.split(chr(92) + ' ·' + chr(92) + ' ', 1)[1]}}}")
            index += 2  # the heading line that follows is produced by the class
            continue
        match = SHEET_PART.match(line)
        if match:
            group, _ = _group(line, match.end())
            label, title = _split_label(group)
            out.append(f"\\studypart{{{label}}}{{{title}}}")
            index += 1
            continue
        if line.startswith(SHEET_CONCEPT):
            heading = lines[index + 1]
            number = re.match(r"\{\\bfseries\\normalsize\\textcolor\{defc\}\{([^}]*)\}\\ \\ ", heading)
            title, end = _group(heading, 0)
            title = title[number.end() - 1:]
            tag = re.search(r"\\textcolor\{mute\}\{([^}]*)\}\}\\par\\vspace\{1pt\}$", heading).group(1)
            out.append(f"\\begin{{concept}}[{number.group(1)}]{{{title}}}{{{tag}}}")
            index += 2
            continue
        if line == "\\end{tcolorbox}":
            out.append("\\end{concept}")
            index += 1
            continue
        if line.startswith(SHEET_FORMULA) or line.startswith(SHEET_METHOD):
            caption = None
            if line.startswith(SHEET_METHOD):
                caption = _whole("x" + line[len("\\par"):], "x")[len("\\color{methc}\\sffamily\\bfseries\\scriptsize METHOD "):]
                index += 1
            chunk = "\n".join(lines[index:])
            content, end = _box(chunk, 0)
            consumed = chunk[:end].count("\n") + 1
            name = "method" if caption is not None else "definition"
            out += [f"\\begin{{{name}}}" + (f"{{{caption}}}" if caption is not None else ""), _port_body(content, name), f"\\end{{{name}}}"]
            index += consumed
            continue
        if line.startswith(SHEET_REFLEX):
            inner = _whole("x" + line[len("\\par"):], "x")
            body_text, _ = _group(inner, len("\\small\\bfseries\\textcolor{reflc}{REFLEX\\ \\ }\\textcolor{ink}"))
            out += ["\\begin{reflex}", body_text, "\\end{reflex}"]
            index += 1
            continue
        out.append(line)
        index += 1
    return out


def port(source, out, chapters=(1,), variant: str | None = None) -> dict:
    """Rewrite an expanded study document (the generator markup of Paul's
    Linear Algebra course and sheet) onto the neyvia-study class."""
    text = Path(source).read_text(encoding="utf-8")
    variant = variant or ("sheet" if "\\linespread{1.15}" in text[:8000] else "course")
    preamble, _, document = text.partition("\\begin{document}")
    document = document.rsplit("\\end{document}", 1)[0]
    marks = list(re.finditer(r"\\markboth\{Chapter (\d+)\}", document))
    starts = {int(mark.group(1)): (document.rfind("\\clearpage", 0, mark.start()) if variant == "course" and document.rfind("\\clearpage", 0, mark.start()) == mark.start() - len("\\clearpage") else mark.start()) for mark in marks}
    ordered = sorted(starts)
    selected = []
    for number in chapters:
        begin = starts[number]
        later = [starts[n] for n in ordered if n > number]
        end = min(later) if later else len(document)
        selected.append(document[begin:end])
    body = "".join(selected)
    if variant == "course":
        appendix = body.find("\\clearpage\\phantomsection\\addcontentsline{toc}{section}{Appendix")
        if appendix != -1:
            body = body[:appendix]
    lines = _port_course(body) if variant == "course" else _port_sheet(body)
    title = re.search(r"pdftitle=\{([^}]*)\}", preamble).group(1)
    main, _, subtitle = title.partition(" --- ")
    subtitle = subtitle.replace(" & ", " \\& ")
    head = [f"\\documentclass[{variant},noautoquant,noautokw]{{neyvia-study}}",
            f"% Ported from {Path(source).name} (chapters {', '.join(map(str, chapters))}) by scripts/study_docs.py port.",
            f"\\studytitle{{{main}}}", f"\\studysubtitle{{{subtitle}}}", "\\studysubject{Linear algebra course}"]
    if variant == "course":
        tagline = re.search(r"\{\\large\\color\{mute\}(.*?)\\par\}", document)
        head += [f"\\studytagline{{{tagline.group(1)}}}" if tagline else "", "\\studysourceprefix{handout }", "\\studynotelabel{Handout note:}"]
    else:
        tagline = re.search(r"\{\\small\\textcolor\{mute\}\{(.*?)\}\}\\par\\vspace\{2pt\}", document)
        if tagline:
            head.append(f"\\studytagline{{{tagline.group(1)}}}")
    text_out = "\n".join([*head, "\\begin{document}", "\\maketitle", "", *lines, "\\end{document}", ""])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text_out, encoding="utf-8", newline="\n")
    counts = {name: len(re.findall(r"\\begin\{" + name + r"\}", text_out)) for name in ("concept", *BLOCKS.values())}
    return {"ok": True, "source": str(source), "out": str(out), "variant": variant, "chapters": list(chapters),
            "lines": text_out.count("\n"), "counts": counts}
