"""No-slop language checks for UI strings and reports (plan 20, C5).

The rules live in the CL-Skill ``manuals/skills/no-slop.cl``; this module supplies the
``text.*`` observers its checks call, runs them through ``cl_skill.run_checks`` and exposes
``neyvia.language.check``. The CL host runs the same check on an agent's text deliverables
before it accepts ``done()``.

    python -m grant_agent.neyvia_language check answer.md index.html [--json]

Observers see words a person reads: Markdown prose (code blocks, inline code, URLs, quotes
and one-character table cells removed), visible HTML text and labels, JSX copy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "manuals" / "skills" / "no-slop.cl"
PROSE = {".md", ".markdown", ".txt", ".rst"}
UI = {".html", ".htm", ".jsx", ".tsx", ".svelte", ".vue"}
TEXT_SUFFIXES = PROSE | UI
CODE = "⟨code⟩"  # stands in for inline code, math and URLs: concrete, never prose
DASHES = "—–"

TEXT = {"type": "string"}
DEFINITIONS = [
    ("language.check", "Check report text or UI strings for slop: decorative em/en dashes, hype and filler words, noise "
                       "words in UI labels, padded openings and closings, vague size words where a number belongs, "
                       "stacked hedges and long sentences. Pass path, paths or text. Read-only; returns each hit with "
                       "file, line and the fix.",
     {"path": TEXT, "paths": {"type": "array", "items": TEXT, "maxItems": 40}, "text": TEXT,
      "kind": {"type": "string", "enum": ["report", "ui"]}}, []),
]


# --------------------------------------------------------------------------- segments


def _clean_inline(text: str) -> str:
    text = re.sub(r"`[^`]*`", CODE, text)
    text = re.sub(r"\$\$.+?\$\$|\$[^$\n]+\$|\\\(.+?\\\)", CODE, text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<https?://[^>]+>|https?://\S+", CODE, text)
    text = re.sub(r"<!--.*?-->", " ", text)
    text = re.sub(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    return text.strip()


def _markdown(name: str, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fence = ""
    paragraph: list[str] = []
    start = 0

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            out.append({"file": name, "line": start, "text": " ".join(paragraph), "role": "prose"})
        paragraph = []

    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.rstrip()
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            if marker and marker.group(1)[0] == fence[0]:
                fence = ""
            continue
        if marker:
            flush()
            fence = marker.group(1)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(">") or re.fullmatch(r"[-*_=\s]{3,}", stripped):
            flush()
            continue
        if stripped.startswith("|") or stripped.count("|") >= 2:
            flush()
            if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", stripped):
                continue
            for cell in stripped.strip("|").split("|"):
                cell = _clean_inline(cell)
                if cell and not re.fullmatch(r"[\s" + DASHES + r"\-?n/a]*", cell, re.I):
                    out.append({"file": name, "line": number, "text": cell, "role": "table"})
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", stripped)
        if heading:
            flush()
            out.append({"file": name, "line": number, "text": _clean_inline(heading.group(1)), "role": "heading"})
            continue
        item = re.match(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$", stripped)
        if item:
            flush()
            text = _clean_inline(item.group(1))
            if text:
                out.append({"file": name, "line": number, "text": text, "role": "prose"})
            continue
        # One segment per source line: hits name the exact line to rewrite (logs and soft-wrapped text alike).
        flush()
        start = number
        paragraph.append(_clean_inline(stripped))
    flush()
    return [row for row in out if re.search(r"[A-Za-zÀ-ɏ]", row["text"])]


class _Visible(HTMLParser):
    SKIP = {"script", "style", "title", "head", "noscript", "template", "svg", "code", "pre"}
    LABELS = ("aria-label", "title", "placeholder", "alt")

    def __init__(self, name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.name = name
        self.stack: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.scripts: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}:
            self._attrs(attrs)
            return
        self.stack.append(tag)
        if not (set(self.stack) & self.SKIP):
            self._attrs(attrs)

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        for key, value in attrs:
            if key in self.LABELS and value and re.search(r"[A-Za-z]", value):
                self.rows.append({"file": self.name, "line": line, "text": value.strip(), "role": "ui", "source": "attr"})

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        line = self.getpos()[0]
        if self.stack and self.stack[-1] == "script":
            self.scripts.append((line, data))
            return
        if set(self.stack) & self.SKIP:
            return
        text = " ".join(data.split())
        if re.search(r"[A-Za-zÀ-ɏ]", text):
            self.rows.append({"file": self.name, "line": line, "text": text, "role": "ui"})


def _script_strings(name: str, start: int, source: str) -> list[dict[str, Any]]:
    """Sentences a script puts on screen: string literals with two or more words and no code characters."""
    rows = []
    for match in re.finditer(r"(['\"`])((?:(?!\1)[^\\\n]|\\.){3,240})\1", source):
        value = match.group(2)
        if "${" in value:
            value = re.sub(r"\$\{[^}]*\}", "0", value)
        if (len(re.findall(r"[A-Za-zÀ-ɏ]{2,}", value)) >= 2 and " " in value
                and not re.search(r"[{};=<>]|=>|\b(px|rem|var|rgba?|hsl)\(|^\s*[.#\[]|\b(function|return|const|let)\b", value)):
            rows.append({"file": name, "line": start + source.count("\n", 0, match.start()), "text": value.strip(), "role": "ui", "source": "script"})
    return rows


def _html(name: str, source: str) -> list[dict[str, Any]]:
    parser = _Visible(name)
    parser.feed(source)
    parser.close()
    rows = parser.rows
    for line, script in parser.scripts:
        rows += _script_strings(name, line, script)
    return rows


def _jsx(path: Path) -> list[dict[str, Any]]:
    from .cl_skill import Output
    return [{"file": row["file"], "line": row["line"], "text": row["text"], "role": "ui"} for row in Output([path]).strings()]


CHUNK_BYTES = 200_000


def _chunks(source: str, size: int = CHUNK_BYTES) -> list[tuple[int, str]]:
    """(line offset, text) pieces cut at line boundaries, preferably blank lines, so no file is skipped for size."""
    if len(source) <= size:
        return [(0, source)]
    pieces, current, used, offset = [], [], 0, 0
    for line in source.splitlines(keepends=True):
        current.append(line)
        used += len(line)
        if used >= size and (not line.strip() or used >= size * 1.5):
            pieces.append((offset, "".join(current)))
            offset += len(current)
            current, used = [], 0
    if current:
        pieces.append((offset, "".join(current)))
    return pieces


def _parse(path: Path, name: str, suffix: str, source: str) -> list[dict[str, Any]]:
    if suffix in {".html", ".htm"}:
        return _html(name, source)
    return _markdown(name, source)


def segments_for(path: Path | None = None, text: str | None = None, name: str = "text", kind: str = "") -> list[dict[str, Any]]:
    if path is not None:
        suffix = path.suffix.lower()
        source = path.read_text(encoding="utf-8", errors="replace")
        name = path.name
        if suffix in {".jsx", ".tsx", ".svelte", ".vue"}:
            return _jsx(path)
        rows = []
        for offset, piece in _chunks(source):
            part = _parse(path, name, suffix, piece)
            for row in part:
                row["line"] += offset
            rows += part
        return rows
    rows = _markdown(name, text or "")
    if kind == "ui":
        for row in rows:
            row["role"] = "ui"
    return rows


# --------------------------------------------------------------------------- observers


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Þ\"'(\[])|;\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ɏ0-9][\w'’./%$-]*", text))


def _concrete(text: str) -> bool:
    return bool(re.search(r"\d", text) or CODE in text)


class TextOutput:
    """Produced text (files and/or inline strings) seen through the no-slop observers."""

    def __init__(self, files: list[Path] | None = None, texts: dict[str, str] | None = None, kind: str = "") -> None:
        self.files = list(files or [])
        self.url = ""
        self.segments: list[dict[str, Any]] = []
        for path in self.files:
            self.segments += segments_for(path)
        for name, text in (texts or {}).items():
            self.segments += segments_for(text=text, name=name, kind=kind)

    def _pick(self, scope: str) -> list[dict[str, Any]]:
        if scope in {"all", "any"}:
            return self.segments
        if scope == "prose":
            return [row for row in self.segments if row["role"] in {"prose", "table"}]
        if scope == "ui":
            return [row for row in self.segments if row["role"] == "ui"]
        if scope == "heading":
            return [row for row in self.segments if row["role"] in {"heading", "ui"}]
        return [row for row in self.segments if row["role"] == scope]

    @staticmethod
    def _hit(row: dict[str, Any], match: str, text: str | None = None) -> dict[str, Any]:
        return {"file": row["file"], "line": row["line"], "text": (text or row["text"])[:160], "match": match[:60]}

    def match(self, pattern: str, **kw: Any) -> list[dict[str, Any]]:
        regex = re.compile(pattern)
        maximum = kw.get("words")
        hits = []
        for row in self._pick(str(kw.get("in", "all"))):
            if maximum is not None and _words(row["text"]) > int(maximum):
                continue
            from .cl_skill import _quoted
            hits += [{**self._hit(row, found.group(0)), "quoted": _quoted(row["text"], found.start())}
                     for found in regex.finditer(row["text"])]
        return hits

    def dashes(self, **kw: Any) -> list[dict[str, Any]]:
        """Em/en dashes and spaced hyphens used as punctuation. Ranges (3–5, Mon–Fri) are data."""
        hits = []
        for row in self._pick(str(kw.get("in", "all"))):
            text = row["text"]
            if re.fullmatch(r"[\s" + DASHES + r"-]*", text):
                continue
            for found in re.finditer(r"\s*[—–]\s*|\s+--?\s+|(?<=\w)--(?=\w)", text):
                token = found.group(0)
                left, right = text[:found.start()], text[found.end():]
                if "–" in token and token.strip() == token and re.search(r"[\w)]$", left) and re.match(r"^[\w(]", right):
                    continue  # tight en dash between two terms: a range
                if token.strip() in {"-", "--"} and not left.strip():
                    continue
                hits.append(self._hit(row, token.strip() or token, text[max(0, found.start() - 40):found.end() + 40]))
        return hits

    def vague(self, pattern: str, **kw: Any) -> list[dict[str, Any]]:
        """Size and speed words in a sentence that has no number and no code to back them."""
        regex = re.compile(pattern)
        hits = []
        for row in self._pick(str(kw.get("in", "all"))):
            for sentence in _sentences(row["text"]):
                if _concrete(sentence):
                    continue
                hits += [self._hit(row, found.group(0), sentence) for found in regex.finditer(sentence)]
        return hits

    def stacked(self, pattern: str, min: int = 2, **kw: Any) -> list[dict[str, Any]]:  # noqa: A002 - CL argument name
        regex = re.compile(pattern)
        hits = []
        for row in self._pick(str(kw.get("in", "all"))):
            for sentence in _sentences(row["text"]):
                found = [item.group(0) for item in regex.finditer(sentence)]
                if len(found) >= int(min):
                    hits.append(self._hit(row, ", ".join(found), sentence))
        return hits

    def edges(self, opening: str, closing: str) -> list[dict[str, Any]]:
        """Padding: a preamble as the first prose sentence of a file, or a sign-off as its last."""
        hits = []
        files = sorted({row["file"] for row in self.segments})
        for name in files:
            rows = [row for row in self.segments if row["file"] == name and row["role"] in {"prose", "ui"}]
            if not rows:
                continue
            first = _sentences(rows[0]["text"])[:1]
            last = _sentences(rows[-1]["text"])[-1:]
            if first and re.search(opening, first[0]):
                hits.append(self._hit(rows[0], "opening", first[0]))
            for row in rows:
                for sentence in _sentences(row["text"]):
                    if re.search(closing, sentence):
                        hits.append(self._hit(row, "closing", sentence))
            if last and re.search(opening, last[0]) and rows[-1] is not rows[0]:
                hits.append(self._hit(rows[-1], "closing", last[0]))
        return hits

    def long(self, max: int = 30, **kw: Any) -> list[dict[str, Any]]:  # noqa: A002 - CL argument name
        hits = []
        for row in self._pick(str(kw.get("in", "prose"))):
            for sentence in _sentences(row["text"]):
                count = _words(sentence)
                if count > int(max):
                    hits.append(self._hit(row, f"{count} words", sentence))
        return hits

    def repeats(self, **kw: Any) -> list[dict[str, Any]]:
        """The same visible UI words twice (a heading echoed by an eyebrow or a label)."""
        seen: dict[str, dict[str, Any]] = {}
        hits = []
        for row in self._pick(str(kw.get("in", "ui"))):
            key = re.sub(r"\W+", " ", row["text"].lower()).strip()
            if row.get("source") in {"script", "attr"} or len(key.split()) < 2 or re.fullmatch(r"[\d\s%]+", key):
                continue
            if key in seen and seen[key]["line"] != row["line"]:
                hits.append(self._hit(row, "repeats line " + str(seen[key]["line"])))
            seen.setdefault(key, row)
        return hits

    def calls(self) -> dict[str, Callable[..., Any]]:
        return {"text.match": self.match, "text.dashes": self.dashes, "text.vague": self.vague, "text.stacked": self.stacked,
                "text.edges": self.edges, "text.long": self.long, "text.repeats": self.repeats}


# --------------------------------------------------------------------------- running


_SKILL_CACHE: dict[str, Any] = {}


def load_skill(path: Path = SKILL):
    from .cl_skill import _parse_skill
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key not in _SKILL_CACHE:
        _SKILL_CACHE.clear()
        _SKILL_CACHE[key] = _parse_skill(path)
    return _SKILL_CACHE[key]


def _all_hits(expr: str, output: TextOutput) -> list[dict[str, Any]]:
    from .cl_skill import _Expr
    match = re.search(r"len\(((?:text|ui)\.\w+\(.*\))\)\s*(==|<=)\s*0", expr)
    if not match:
        return []
    try:
        value = _Expr(match.group(1), {}, output.calls()).run()
    except Exception:
        return []
    return value if isinstance(value, list) else []


def check(files: list[Path] | None = None, texts: dict[str, str] | None = None, kind: str = "", skill_path: Path = SKILL) -> dict[str, Any]:
    from .cl_skill import run_checks
    skill = load_skill(skill_path)
    output = TextOutput(files, texts, kind)
    report = run_checks(skill, output)
    rows = []
    for row in report["results"]:
        if row["status"] == "fail":
            check_def = next(item for item in skill.checks if item.name == row["name"])
            row = {**row, "evidence": _all_hits(check_def.expr, output)}
        rows.append(row)
    report["results"] = rows
    report["blockingHits"] = sum(len(row["evidence"]) for row in rows if row["status"] == "fail" and row["severity"] == "block")
    report["warningHits"] = sum(len(row["evidence"]) for row in rows if row["status"] == "fail" and row["severity"] == "warn")
    report["segments"] = len(output.segments)
    report["words"] = sum(_words(row["text"]) for row in output.segments)
    return report


def receipt(report: dict[str, Any], limit: int = 8) -> str:
    """CL lines: R summary, then one X line per hit (block first), each with the fix."""
    marks = " ".join(("+" if row["status"] == "pass" else "-" if row["status"] == "fail" else "?") + row["name"] for row in report["results"])
    lines = [f"R language.check {report['status']} block:{report['blockingHits']} warn:{report['warningHits']} {marks}"]
    shown = 0
    for severity in ("block", "warn"):
        for row in report["results"]:
            if row["status"] != "fail" or row["severity"] != severity:
                continue
            for index, hit in enumerate(row["evidence"]):
                if shown >= limit:
                    break
                fix = (" -> " + (row["fix"] or row["rule"])) if index == 0 else ""
                lines.append(f"X language {row['name']} {severity} {hit['file']}:{hit['line']} {json.dumps(hit.get('match', ''), ensure_ascii=False)} "
                             f"in {json.dumps(hit['text'][:90], ensure_ascii=False)}{fix}")
                shown += 1
    total = report["blockingHits"] + report["warningHits"]
    if total > shown:
        lines.append(f"Q language {total - shown} more hits -> language.check(path=...) per file")
    return "\n".join(lines) + "\n"


def tool(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    files: list[Path] = []
    for item in ([args["path"]] if args.get("path") else []) + list(args.get("paths") or []):
        path = Path(item)
        path = path if path.is_absolute() else Path(root) / path
        if not path.is_file():
            raise ValueError(f"Not a file: {item}")
        files.append(path)
    texts = {"text": args["text"]} if args.get("text") else {}
    if not files and not texts:
        raise ValueError("Pass path, paths or text")
    report = check(files, texts, kind=str(args.get("kind") or ""))
    # Hits, lines and fixes travel once, in the CL receipt; the list only names what failed.
    compact = [{"name": row["name"], "severity": row["severity"], "count": len(row["evidence"])}
               for row in report["results"] if row["status"] == "fail"]
    # ok means the check ran; "clean" and "blocking" carry the verdict (a procedure's first look must not stop it).
    return {"ok": True, "clean": report["blockingHits"] == 0, "verdict": "clean" if not compact else "fix" if report["blockingHits"] else "warn",
            "blocking": report["blockingHits"], "warnings": report["warningHits"], "words": report["words"],
            "failed": compact, "cl": receipt(report)}


def call(workspace, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "language.check":
        return tool(Path(workspace.bus.root), args)
    raise ValueError("Unknown language action")


# --------------------------------------------------------------------------- host gate


SKIP_DIRS = {".agent_control", ".neyvia", ".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


def task_artifacts(root: Path, since: float, budget: int = 200_000, *, suffixes=None) -> tuple[list[Path], bool]:
    """Every text deliverable the task created or modified under root since `since` (epoch seconds).

    No file-count cap and no size cap (large files are scanned in chunks). Hidden, dependency and build
    folders are not entered. Returns (files newest first, complete); complete is False only if the walk
    budget ran out, so callers can say the scan was partial instead of silently passing."""
    import os
    found = []
    root = Path(root)
    if not root.is_dir():
        return [], True
    seen, complete = 0, True
    wanted = TEXT_SUFFIXES if suffixes is None else suffixes
    for folder, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        seen += len(names) + len(dirs)
        for name in names:
            if Path(name).suffix.lower() not in wanted:
                continue
            path = Path(folder) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= since:
                found.append((stat.st_mtime, path))
        if seen > budget:
            complete = False
            break
    return [path for _, path in sorted(found, key=lambda row: (-row[0], str(row[1])))], complete


def recent_text_files(root: Path, since: float, limit: int | None = None, budget: int = 200_000, *, suffixes=None) -> list[Path]:
    """Compatibility wrapper over task_artifacts; `limit` is optional and off by default."""
    files, _ = task_artifacts(root, since, budget, suffixes=suffixes)
    return files if limit is None else files[:limit]


def gate(root: Path | None, since: float, summary: str = "") -> dict[str, Any]:
    files = recent_text_files(root, since) if root else []
    report = check(files, {"done summary": summary} if summary.strip() else {})
    signature = sorted(f"{row['name']}|{hit['file']}|{hit['text'][:60]}" for row in report["results"]
                       if row["status"] == "fail" and row["severity"] == "block" for hit in row["evidence"])
    return {"files": [str(path) for path in files], "blocking": report["blockingHits"], "warnings": report["warningHits"],
            "signature": signature, "cl": receipt(report), "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m grant_agent.neyvia_language", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="check files for slop")
    c.add_argument("files", type=Path, nargs="+")
    c.add_argument("--json", action="store_true")
    c.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    report = check(args.files)
    if args.json:
        print(json.dumps({key: value for key, value in report.items()}, indent=1, ensure_ascii=False))
    else:
        print(receipt(report, args.limit), end="")
    return 0 if report["blockingHits"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
