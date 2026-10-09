"""CL-Skill check runner (docs/standard/cl-skill.md).

A CL-Skill is a skill compiled to Connected Language lines: procedures (P),
judgement points (J), executable checks (C) on the produced output, pitfalls (X),
provenance (M) and routing (V). This module reads the subset of CL a skill uses,
runs every C line against the files (and optionally the rendered page) an agent
produced, scores adherence and prints a CL receipt.

    python -m grant_agent.cl_skill describe --skill manuals/skills/design-craft.cl --level 1
    python -m grant_agent.cl_skill check --skill manuals/skills/design-craft.cl \
        --files Card.jsx card.css [--url http://127.0.0.1:1641/design-lab.html?only=card] \
        [--journal run.cl] [--out dir] [--json]

The reader here is deliberately small: it understands L T A I C P J X F M V lines
and the CL expression grammar (§3 of connected-language.md) needed by checks.
When the reference parser in grant_agent.cl lands, it replaces `_parse_skill` and
`_Expr`; the observers and the scoring stay.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SEVERITY_WEIGHT = {"block": 3.0, "warn": 1.0, "note": 0.25}
TAG_LINE = re.compile(r"^(?P<tag>CL|L|T|S|A|I|C|P|J|X|F|M|V|K|Q|R|E|D)\s+(?P<body>.*)$")
CHECK_HEAD = re.compile(r"^(?P<qname>[A-Za-z][\w.-]*)\s+(?P<name>[A-Za-z][\w-]*)(?:\((?P<params>[^)]*)\))?:\s+(?P<expr>.+)$")
JUDGE_HEAD = re.compile(r'^(?P<name>[A-Za-z][\w-]*)\s+(?P<options>[\w-]+(?:\|[\w-]+)+):\s+(?P<question>".*?")\s*$')
JOURNAL_J = re.compile(r'^J\s+(?P<name>[A-Za-z][\w-]*)=(?P<option>[\w-]+)(?:\s+(?P<why>".*?"))?(?:\s+ev:(?P<ev>\S+))?\s*$')
ROUTE_V = re.compile(r'^J\s+(?P<name>[A-Za-z][\w-]*)\s*->\s*(?P<route>human|model)(?::(?P<who>[\w-]+))?(?:\s+evidence:(?P<evidence>[\w,]+))?')


# --------------------------------------------------------------------------- reading


def _split_gloss(line: str) -> tuple[str, str]:
    """Split ' -- gloss' from a line, ignoring ' -- ' inside JSON strings."""
    quoted = False
    escaped = False
    for index, char in enumerate(line):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif line.startswith(" -- ", index):
            return line[:index].rstrip(), line[index + 4 :].strip()
    return line.rstrip(), ""


@dataclass
class Check:
    action: str
    name: str
    expr: str
    severity: str
    source: str
    rule: str
    params: str = ""


@dataclass
class Skill:
    path: Path
    layer: str = ""
    version: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    gloss: str = ""
    checks: list[Check] = field(default_factory=list)
    judges: dict[str, dict[str, Any]] = field(default_factory=dict)
    procedures: dict[str, list[str]] = field(default_factory=dict)
    pitfalls: dict[str, str] = field(default_factory=dict)
    memories: list[str] = field(default_factory=list)
    lines: list[tuple[str, str, int]] = field(default_factory=list)  # (tag, raw line, level)


LEVEL = {"L": 0, "T": 1, "S": 1, "A": 1, "I": 1, "C": 1, "P": 2, "J": 2, "X": 2, "F": 2, "M": 2, "V": 2, "Q": 2}


def _parse_skill(path: Path, text: str | None = None) -> Skill:
    skill = Skill(path=path)
    for number, raw in enumerate((path.read_text(encoding="utf-8") if text is None else text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        match = TAG_LINE.match(line)
        if not match:
            raise ValueError(f"{path}:{number}: not a CL line: {line[:80]}")
        tag, body = match["tag"], match["body"]
        if tag == "CL":
            continue
        head, gloss = _split_gloss(body)
        level = LEVEL.get(tag, 2)
        if tag == "L":
            parts = head.split()
            skill.layer, skill.version = parts[0], parts[1] if len(parts) > 1 else ""
            for part in parts[2:]:
                key, _, value = part.partition(":")
                skill.attrs[key] = value or "true"
            skill.gloss = gloss
        elif tag == "C":
            check = CHECK_HEAD.match(head)
            if not check:
                raise ValueError(f"{path}:{number}: malformed check: {head[:80]}")
            words = gloss.split(None, 2)
            severity = words[0].rstrip(":") if words and words[0].rstrip(":") in SEVERITY_WEIGHT else "warn"
            rest = gloss.split(None, 1)[1] if words and words[0].rstrip(":") in SEVERITY_WEIGHT and len(words) > 1 else gloss
            source, _, rule = rest.partition(": ")
            if not rule:
                source, rule = "", rest
            if check["params"]:
                level = 2
            skill.checks.append(Check(check["qname"], check["name"], check["expr"], severity, source.strip(), rule.strip(), check["params"] or ""))
        elif tag == "J":
            judge = JUDGE_HEAD.match(head)
            if not judge:
                raise ValueError(f"{path}:{number}: malformed judgement point: {head[:80]}")
            skill.judges[judge["name"]] = {"options": judge["options"].split("|"), "question": json.loads(judge["question"]), "constraints": gloss}
        elif tag == "V":
            route = ROUTE_V.match(head)
            if route and route["name"] in skill.judges:
                skill.judges[route["name"]]["kind"] = route["route"]
                if route["evidence"]:
                    skill.judges[route["name"]]["evidence"] = route["evidence"].split(",")
        elif tag == "P":
            proc = re.match(r"^([A-Za-z][\w-]*)\(.*?\):\s+(.*)$", head)
            if not proc:
                raise ValueError(f"{path}:{number}: malformed procedure: {head[:80]}")
            name = proc.group(1)
            steps = [step.strip() for step in proc.group(2).split(";")]
            skill.procedures[name] = steps
        elif tag == "X":
            parts = head.split(None, 2)
            if len(parts) >= 2 and "->" in head:
                skill.pitfalls[parts[1]] = head.split("->", 1)[1].strip()
        elif tag == "M":
            skill.memories.append(line)
        skill.lines.append((tag, line, level))
    if not skill.layer:
        raise ValueError(f"{path}: missing L line")
    return skill


def describe(skill: Skill, level: int) -> str:
    return "\n".join(["CL 1"] + [line for tag, line, lvl in skill.lines if lvl <= level])


# --------------------------------------------------------------------------- expressions


TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?(?![\w.]))
  | (?P<op>==|!=|<=|>=|<|>|~)
  | (?P<punct>[()\[\],:.{}])
  | (?P<name>[A-Za-z_@][\w-]*)
""", re.VERBOSE)
KEYWORDS = {"and", "or", "not", "has", "in", "true", "false", "null"}


def _tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            raise ValueError(f"cannot read expression at: {text[position:position + 30]!r}")
        position = match.end()
        kind = match.lastgroup
        if kind == "ws":
            continue
        out.append((kind, match.group(kind)))
    out.append(("end", ""))
    return out


class _Expr:
    """Recursive-descent evaluator for CL check expressions."""

    def __init__(self, text: str, scope: dict[str, Any], calls: dict[str, Callable[..., Any]]) -> None:
        self.tokens = _tokens(text)
        self.index = 0
        self.scope = scope
        self.calls = calls

    def peek(self, offset: int = 0) -> tuple[str, str]:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if value is not None and token[1] != value:
            raise ValueError(f"expected {value!r}, found {token[1]!r}")
        self.index += 1
        return token

    def run(self) -> Any:
        value = self.expr()
        if self.peek()[0] != "end":
            raise ValueError(f"unexpected {self.peek()[1]!r}")
        return value

    def expr(self) -> Any:
        value = self.conj()
        while self.peek() == ("name", "or"):
            self.take()
            right = self.conj()
            value = bool(value) or bool(right)
        return value

    def conj(self) -> Any:
        value = self.neg()
        while self.peek() == ("name", "and"):
            self.take()
            right = self.neg()
            value = bool(value) and bool(right)
        return value

    def neg(self) -> Any:
        if self.peek() == ("name", "not"):
            self.take()
            return not bool(self.neg())
        return self.cmp()

    def cmp(self) -> Any:
        left = self.term()
        token = self.peek()
        if token[0] == "op" or token in {("name", "has"), ("name", "in")}:
            self.take()
            right = self.term()
            op = token[1]
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "<=":
                return left <= right
            if op == ">=":
                return left >= right
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            if op == "has":
                return right in left if left is not None else False
            if op == "in":
                return left in right
            if op == "~":
                return re.search(str(right), str(left)) is not None
        return left

    def term(self) -> Any:
        value = self.primary()
        while self.peek() == ("punct", "."):
            self.take()
            key = self.take()[1]
            value = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
        return value

    def primary(self) -> Any:
        kind, text = self.peek()
        if kind == "number":
            self.take()
            return float(text) if "." in text else int(text)
        if kind == "string":
            self.take()
            return json.loads(text)
        if text == "[":
            return self.list_value()
        if text == "(":
            self.take()
            value = self.expr()
            self.take(")")
            return value
        if kind == "name":
            self.take()
            name = text
            while self.peek() == ("punct", ".") and self.peek(1)[0] == "name" and self.peek(2) == ("punct", "("):
                self.take()
                name += "." + self.take()[1]
            if self.peek() == ("punct", "(") and (name in self.calls or name == "len"):
                return self.call(name)
            if name == "true":
                return True
            if name == "false":
                return False
            if name == "null":
                return None
            if name in self.scope:
                return self.scope[name]
            return name  # bareword
        raise ValueError(f"unexpected {text!r}")

    def list_value(self) -> list[Any]:
        self.take("[")
        items: list[Any] = []
        while self.peek()[1] != "]":
            items.append(self.term())
            if self.peek()[1] == ",":
                self.take()
        self.take("]")
        return items

    def call(self, name: str) -> Any:
        self.take("(")
        positional: list[Any] = []
        named: dict[str, Any] = {}
        while self.peek()[1] != ")":
            if self.peek()[0] == "name" and self.peek(1) == ("punct", ":"):
                key = self.take()[1]
                self.take(":")
                named[key] = self.term()
            else:
                positional.append(self.expr())
            if self.peek()[1] == ",":
                self.take()
        self.take(")")
        if name == "len":
            return len(positional[0]) if positional and positional[0] is not None else 0
        return self.calls[name](*positional, **named)


# --------------------------------------------------------------------------- observers


def _strip_comments(text: str, kind: str) -> str:
    """Blank out comments but keep line numbers."""
    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    if kind == "jsx":
        text = re.sub(r"(?m)^\s*//[^\n]*", blank, text)
        text = re.sub(r"\{/\*.*?\*/\}", blank, text, flags=re.S)
    return text


def _css_rules(text: str) -> list[dict[str, Any]]:
    """Flat list of rules: selector, declarations, enclosing at-rules, line."""
    rules: list[dict[str, Any]] = []
    stack: list[str] = []
    buffer = ""
    line = 1
    start_line = 1
    for char in text:
        if char == "\n":
            line += 1
        if char == "{":
            stack.append(buffer.strip())
            buffer = ""
            start_line = line
        elif char == "}":
            if stack:
                head = stack.pop()
                if buffer.strip() and not head.startswith("@"):
                    rules.append({"selector": head, "body": buffer, "context": [item for item in stack if item.startswith("@")], "line": start_line})
            buffer = ""
        elif char == ";" and stack and stack[-1].startswith("@") and not stack[-1].startswith(("@keyframes", "@font-face")):
            buffer = ""  # stray declaration directly inside an at-rule
        else:
            buffer += char
    return rules


def _decls(body: str) -> list[tuple[str, str]]:
    out = []
    for part in body.split(";"):
        if ":" in part:
            key, _, value = part.partition(":")
            if key.strip() and not key.strip().startswith("&"):
                out.append((key.strip().lower(), value.strip()))
    return out


class Output:
    """The produced artifact: files plus an optional rendered URL."""

    COPY_PROPS = r"(?:label|aria-label|title|placeholder|alt|description|text|message|confirmLabel|hint|help)"

    def __init__(self, files: list[Path], url: str = "", out_dir: Path | None = None, *, summary: str = "", task_text: str | None = None) -> None:
        self.files = files
        self.url = url
        self.out_dir = out_dir
        self.text = {path: _strip_comments(path.read_text(encoding="utf-8"), self._kind(path)) for path in files}
        self._render_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.summary, self.task_text = summary, task_text
        self._deliverables = None

    @staticmethod
    def _kind(path: Path) -> str:
        return "css" if path.suffix.lower() in {".css", ".scss"} else "jsx"

    def _pick(self, scope: str) -> list[Path]:
        return [path for path in self.files if scope in {"all", "any"} or self._kind(path) == scope]

    def _hit(self, path: Path, text: str, start: int, snippet: str) -> dict[str, Any]:
        return {"file": path.name, "line": text.count("\n", 0, start) + 1, "text": snippet.strip()[:120], "quoted": _quoted(text, start)}

    # observers -------------------------------------------------------------
    def scan(self, pattern: str, **kw: Any) -> list[dict[str, Any]]:
        scope = str(kw.get("in", "all"))
        regex = re.compile(pattern, re.M)
        hits = []
        for path in self._pick(scope):
            text = self.text[path]
            for match in regex.finditer(text):
                hit = self._hit(path, text, match.start(), match.group(0))
                # Line-level patterns: the hit is cited text when the pattern no longer matches once quotes are removed.
                hit["quoted"] = hit["quoted"] or not regex.search(_strip_quoted(match.group(0)))
                hits.append(hit)
        return hits

    def compile(self) -> list[dict[str, Any]]:
        """Syntax and module errors (esbuild transform of each file); a file that does not compile renders nothing."""
        import shutil
        import subprocess
        repo = Path(__file__).resolve().parents[2]
        candidates = [repo / "node_modules/@esbuild/win32-x64/esbuild.exe", repo / "node_modules/.bin/esbuild", Path(shutil.which("esbuild") or "")]
        binary = next((item for item in candidates if str(item) and item.is_file()), None)
        if binary is None:
            raise _Undecided("esbuild not found; compile check cannot run")
        hits = []
        for path in self.files:
            loader = "css" if self._kind(path) == "css" else "jsx"
            result = subprocess.run([str(binary), str(path), f"--loader:{path.suffix}={loader}", "--log-level=error", "--color=false"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    creationflags=0x08000000 if sys.platform == "win32" else 0)
            if result.returncode:
                lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
                first = next((line for line in lines if "ERROR" in line), lines[0] if lines else "does not compile")
                where = next((line for line in lines if line.endswith(":") and path.name in line), "")
                number = int(where.rsplit(":", 3)[-3]) if where.count(":") >= 3 and where.rsplit(":", 3)[-3].isdigit() else 1
                hits.append({"file": path.name, "line": number, "text": first.replace("X [ERROR] ", "")[:160]})
        return hits

    def durations(self) -> list[dict[str, Any]]:
        """Literal durations in transition/animation declarations (tokens are fine)."""
        hits = []
        for path in self._pick("css"):
            for rule in _css_rules(self.text[path]):
                for key, value in _decls(rule["body"]):
                    if key.startswith(("transition", "animation")):
                        cleaned = re.sub(r"var\([^)]*\)|cubic-bezier\([^)]*\)|steps\([^)]*\)", "", value)
                        for number, unit in re.findall(r"(?<![\w-])(\d*\.?\d+)(ms|s)\b", cleaned):
                            hits.append({"file": path.name, "line": rule["line"], "text": f"{key}: {value}"[:120],
                                         "ms": float(number) * (1000 if unit == "s" else 1)})
        return hits

    def offscale(self, props: list[str], scale: list[float]) -> list[dict[str, Any]]:
        allowed = {float(item) for item in scale}
        hits = []
        for path in self._pick("css"):
            for rule in _css_rules(self.text[path]):
                for key, value in _decls(rule["body"]):
                    if key in props:
                        for number, unit in re.findall(r"(?<![\w-])(-?\d*\.?\d+)(px|rem)\b", value):
                            size = abs(float(number)) * (16 if unit == "rem" else 1)
                            if size not in allowed:
                                hits.append({"file": path.name, "line": rule["line"], "text": f"{key}: {value}"[:120]})
        return hits

    def hovermotion(self) -> list[dict[str, Any]]:
        """:hover rules that move things (transform/translate/scale) outside a hover-capable media query."""
        hits = []
        for path in self._pick("css"):
            for rule in _css_rules(self.text[path]):
                if ":hover" not in rule["selector"]:
                    continue
                gated = any("hover: hover" in item.replace("hover:hover", "hover: hover") for item in rule["context"])
                moves = any(key in {"transform", "translate", "scale", "rotate"} for key, _ in _decls(rule["body"]))
                if moves and not gated:
                    hits.append({"file": path.name, "line": rule["line"], "text": rule["selector"][:120]})
        return hits

    def unscoped(self) -> list[dict[str, Any]]:
        """Selectors that escape the .nx scope (Neyvia: every rule starts with .nx)."""
        hits = []
        for path in self._pick("css"):
            for rule in _css_rules(self.text[path]):
                if any(item.startswith("@keyframes") for item in rule["context"]):
                    continue
                for selector in rule["selector"].split(","):
                    selector = selector.strip()
                    if selector and not selector.startswith((".nx", "from", "to")) and not re.match(r"^\d+%$", selector):
                        hits.append({"file": path.name, "line": rule["line"], "text": selector[:120]})
        return hits

    def strings(self) -> list[dict[str, Any]]:
        """Words a person reads: JSX text, copy props and label-like object fields."""
        out = []
        for path in self._pick("jsx"):
            text = self.text[path]
            patterns = [
                r">\s*([^<>{}\n][^<>{}]*?)\s*<",                                   # JSX text node
                rf"\b{self.COPY_PROPS}=\"([^\"]+)\"",                               # copy prop
                rf"\b{self.COPY_PROPS}=\{{\s*[\"'`]([^\"'`]+)[\"'`]\s*\}}",         # copy prop in braces
                rf"\b{self.COPY_PROPS}\s*:\s*[\"'`]([^\"'`]+)[\"'`]",               # object field
                r"\{\s*[\"'`]([^\"'`{}]*[A-Za-z][^\"'`{}]*)[\"'`]\s*\}",            # {"text"} child
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    value = match.group(1).strip()
                    if value and re.search(r"[A-Za-z]", value) and not re.fullmatch(r"[\w.-]+\.(jsx|css|js)", value):
                        out.append(self._hit(path, text, match.start(1), value) | {"text": value[:160]})
        return out

    def copy(self, pattern: str) -> list[dict[str, Any]]:
        regex = re.compile(pattern)
        return [row for row in self.strings() if regex.search(row["text"])]

    def render(self, theme: str = "dark", viewport: str = "desktop") -> dict[str, Any]:
        key = (theme, viewport)
        if key in self._render_cache:
            cached = self._render_cache[key]
            if "undecided" in cached:
                raise _Undecided(cached["undecided"])
            return cached
        if not self.url:
            raise _Undecided("no --url given; rendered checks cannot run")
        from .chromium_review import chromium_review_page
        from .taste_lens import PROBE_SCRIPT, VIEWPORTS
        width, height = VIEWPORTS[viewport]
        url = self.url
        if "design-lab" in url:
            url = re.sub(r"([?&])theme=[^&]*&?", r"\1", url).rstrip("&?")
            url += ("&" if "?" in url else "?") + "theme=" + ("light" if theme == "light" else "dark")
        try:
            with chromium_review_page(width=width, height=height) as page:
                page.emulate_media(color_scheme="light" if theme == "light" else "dark")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("[data-specimen]" if "design-lab" in url else "body", state="visible", timeout=15000)
                page.wait_for_timeout(700)
                if self.out_dir is not None:
                    self.out_dir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(self.out_dir / f"{viewport}-{theme}.png"), full_page=False)
                measured = page.evaluate(PROBE_SCRIPT)
                measured["wrappedControls"] = page.evaluate(WRAP_PROBE)
        except Exception as exc:  # report, do not guess
            reason = f"render failed: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
            if "did not appear" in reason or "Timeout" in reason:
                reason += " (the page never showed the component: fix any -compiles failure first, then any other specimen the dev server cannot build)"
            self._render_cache[key] = {"undecided": reason}
            raise _Undecided(reason) from exc
        controls = measured.get("controls") or {}
        summary = {
            "overflowPx": int(measured.get("horizontalOverflowPx") or 0),
            "contrastFails": int((measured.get("contrast") or {}).get("failing") or 0),
            "contrastWorst": (measured.get("contrast") or {}).get("worst") or [],
            "unnamed": int(controls.get("unnamedCount") or 0),
            "smallTargets": int(controls.get("smallTargetCount") or 0),
            "collisions": len(measured.get("textCollisions") or []),
            "typefaces": len([row for row in (measured.get("typefaces") or []) if row.get("count", 0) >= 2]),
            "tinyText": int((measured.get("tinyText") or {}).get("count") or 0),
            "measured": int((measured.get("contrast") or {}).get("measured") or 0),
            "wrappedControls": len(measured.get("wrappedControls") or []),
            "wrappedLabels": (measured.get("wrappedControls") or [])[:6],
        }
        if summary["measured"] == 0:
            self._render_cache[key] = {"undecided": "nothing rendered was measured (blank page?)"}
            raise _Undecided("nothing rendered was measured (blank page?)")
        self._render_cache[key] = summary
        return summary

    def calls(self) -> dict[str, Callable[..., Any]]:
        if self._deliverables is None:
            from .cl_deliverables import DeliverableOutput
            self._deliverables = DeliverableOutput(self.files, self.summary, self.task_text)
        return {**self._deliverables.calls(), "ui.scan": self.scan, "ui.compile": self.compile, "ui.durations": self.durations, "ui.offscale": self.offscale,
                "ui.hovermotion": self.hovermotion, "ui.unscoped": self.unscoped, "ui.strings": self.strings,
                "ui.copy": self.copy, "ui.render": self.render}


# Short controls whose label breaks onto two lines or whose icon sits above the label.
WRAP_PROBE = r"""(() => {
  const scope = document.querySelector('[data-specimen]') ? '[data-specimen] ' : '';
  const out = [];
  for (const b of document.querySelectorAll(scope + 'button, ' + scope + '[role=button], ' + scope + 'a.nx-btn')) {
    const box = b.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const label = (b.innerText || '').trim();
    if (!label || label.length > 28) continue;
    const rects = [];
    const walker = document.createTreeWalker(b, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) if (r.width > 0) rects.push(r);
    }
    if (!rects.length) continue;
    let wrapped = new Set(rects.map(r => Math.round(r.top / 6))).size > 1;
    const svg = b.querySelector('svg');
    if (svg) {
      const s = svg.getBoundingClientRect(), t = rects[0];
      if (s.height && Math.abs((s.top + s.height / 2) - (t.top + t.height / 2)) > 6) wrapped = true;
    }
    if (wrapped) out.push(label.replace(/\s+/g, ' ').slice(0, 40));
  }
  return out;
})()"""


class _Undecided(Exception):
    pass


# --------------------------------------------------------------------------- run


def _evidence(expr: str, output: Output) -> list[dict[str, Any]]:
    """The hits behind a len(...)==0 style check, for the receipt."""
    match = re.search(r"len\(((?:ui|text|deliverable)\.\w+\(.*\))\)\s*(==|<=)\s*0", expr)
    if not match:
        return []
    try:
        value = _Expr(match.group(1), {}, output.calls()).run()
    except Exception:
        return []
    return value[:5] if isinstance(value, list) else []


def run_checks(skill: Skill, output: Output, journal: Path | None = None, only: set[str] | None = None) -> dict[str, Any]:
    results = []
    for check in skill.checks:
        if check.params or (only and check.name not in only):
            continue
        status, detail, evidence = "pass", "", []
        try:
            value = _Expr(check.expr, {"files": [str(path) for path in output.files], "url": output.url}, output.calls()).run()
            if not value:
                status = "fail"
                evidence = _evidence(check.expr, output)
        except _Undecided as exc:
            status, detail = "undecided", str(exc)
        except Exception as exc:
            status, detail = "undecided", f"check error: {exc}"
        results.append({"name": check.name, "severity": check.severity, "status": status, "rule": check.rule,
                        "source": check.source, "detail": detail, "evidence": evidence,
                        "fix": skill.pitfalls.get(check.name, "")})
    answered: dict[str, dict[str, str]] = {}
    unbound: dict[str, str] = {}
    if journal is not None and journal.exists():
        from .judgment_evidence import verify
        for line in journal.read_text(encoding="utf-8").splitlines():
            match = JOURNAL_J.match(line.strip())
            if match and match["name"] in skill.judges and match["option"] in skill.judges[match["name"]]["options"]:
                judge = skill.judges[match["name"]]
                if judge.get("evidence"):
                    # A model judgment counts only with current evidence; the J answer alone is not evidence.
                    ok, why = verify(match["ev"], judge["evidence"], [journal.parent, *{Path(f).parent for f in output.files}], output.files)
                    if not ok:
                        unbound[match["name"]] = why
                        answered.pop(match["name"], None)
                        continue
                    unbound.pop(match["name"], None)
                answered[match["name"]] = {"option": match["option"], "why": json.loads(match["why"]) if match["why"] else "",
                                           **({"evidence": match["ev"]} if match["ev"] else {})}
    required = sorted({step.split()[1].split("=")[0] for steps in skill.procedures.values() for step in steps if step.startswith("J ")})
    decided = [row for row in results if row["status"] != "undecided"]
    weight = sum(SEVERITY_WEIGHT[row["severity"]] for row in decided)
    passed = sum(SEVERITY_WEIGHT[row["severity"]] for row in decided if row["status"] == "pass")
    output_adherence = passed / weight if weight else 0.0
    judged = [name for name in required if name in answered]
    procedure_adherence = len(judged) / len(required) if required else 1.0
    blocking = [row["name"] for row in results if row["status"] == "fail" and row["severity"] == "block"]
    return {
        "skill": skill.layer, "version": skill.version,
        "status": "fail" if blocking else ("unknown" if len(decided) < len(results) else "ok"),
        "outputAdherence": round(output_adherence, 4),
        "procedureAdherence": round(procedure_adherence, 4),
        "adherence": round(output_adherence * (0.8 + 0.2 * procedure_adherence), 4),
        "checksRun": len(results), "checksDecided": len(decided),
        "checksPassed": sum(1 for row in decided if row["status"] == "pass"),
        "blocking": blocking,
        "judgements": {"required": required, "answered": answered, "unbound": unbound,
                       "kinds": {name: skill.judges[name].get("kind", "human") for name in required if name in skill.judges}},
        "results": results,
    }


def receipt_lines(skill: Skill, report: dict[str, Any]) -> str:
    marks = " ".join(("+" if row["status"] == "pass" else "-" if row["status"] == "fail" else "?") + row["name"] for row in report["results"])
    lines = [f"R {skill.layer}.build {report['status']} adherence:{report['adherence']} output:{report['outputAdherence']} "
             f"procedure:{report['procedureAdherence']} checks:{report['checksPassed']}/{report['checksDecided']} {marks}"]
    for row in report["results"]:
        if row["status"] == "fail":
            where = "; ".join(f"{hit['file']}:{hit['line']} {json.dumps(hit['text'], ensure_ascii=False)}" for hit in row["evidence"][:3])
            lines.append(f"X {skill.layer}.build {row['name']} {row['severity']} -> {row['fix'] or row['rule']}" + (f" -- at {where}" if where else ""))
        elif row["status"] == "undecided":
            lines.append(f"Q {row['name']} {json.dumps(row['detail'])} -> observe ui.render")
    for name in report["judgements"]["required"]:
        if name in report["judgements"].get("unbound", {}):
            lines.append(f"Q {name} {json.dumps('answer not bound to current evidence: ' + report['judgements']['unbound'][name])} -> J {name}=<option> \"why\" ev:<path>#<sha256>")
        elif name not in report["judgements"]["answered"]:
            lines.append(f"Q {name} {json.dumps(next(iter([skill.judges[name]['question']])))} -> J {name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m grant_agent.cl_skill", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("describe", help="print the skill at a level (0 index, 1 act, 2 judge)")
    d.add_argument("--skill", type=Path, required=True)
    d.add_argument("--level", type=int, default=2)
    c = sub.add_parser("check", help="run the skill's checks on produced output")
    c.add_argument("--skill", type=Path, default=Path("manuals/skills/design-craft.cl"))
    c.add_argument("--files", type=Path, nargs="+")
    c.add_argument("--latest-request", type=Path, metavar="DIR",
                   help="run the newest request JSON in DIR ({files, url?, journal?, skill?}); report goes next to DIR")
    c.add_argument("--url", default="")
    c.add_argument("--summary", default="", help="done summary for deliverable.chatdump")
    c.add_argument("--task-text", help="original user request for the proportion check")
    c.add_argument("--journal", type=Path)
    c.add_argument("--out", type=Path, help="directory for screenshots and report.json")
    c.add_argument("--only", nargs="*", help="run only these checks")
    c.add_argument("--json", action="store_true", help="print the JSON report instead of CL lines")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "check" and args.latest_request:
        requests = sorted(args.latest_request.glob("*.json"), key=lambda item: item.stat().st_mtime)
        if not requests:
            print(f"R check refused -- no request JSON in {args.latest_request}")
            return 2
        request = json.loads(requests[-1].read_text(encoding="utf-8"))
        args.files = [Path(item) for item in request.get("files") or []]
        args.url = request.get("url") or args.url
        args.journal = Path(request["journal"]) if request.get("journal") else args.journal
        args.skill = Path(request["skill"]) if request.get("skill") else args.skill
        args.summary = request.get("summary", args.summary)
        args.task_text = request.get("taskText", args.task_text)
        args.out = args.out or args.latest_request.parent
    skill = _parse_skill(args.skill)
    if args.command == "describe":
        print(describe(skill, args.level))
        return 0
    if not args.files:
        print(f"R {skill.layer}.build refused -- no files (pass --files or --latest-request)")
        return 2
    missing = [str(path) for path in args.files if not path.is_file()]
    if missing:
        print(f"R {skill.layer}.check refused -- missing files: {', '.join(missing)}")
        return 2
    output = Output(args.files, args.url, args.out, summary=args.summary, task_text=args.task_text)
    report = run_checks(skill, output, args.journal, set(args.only) if args.only else None)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2) if args.json else receipt_lines(skill, report))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

def _quoted(text: str, start: int) -> bool:
    """True when the hit sits in cited text: a blockquote line, a code span or block, or inside quotation marks on its line."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    line = text[line_start:line_end if line_end >= 0 else len(text)]
    if line.lstrip().startswith(">"):
        return True
    if text.count("```", 0, start) % 2 == 1:
        return True
    before = line[:start - line_start]
    if before.count("`") % 2 == 1:
        return True
    if before.count('"') % 2 == 1:
        return True
    for open_mark, close_mark in (("“", "”"), ("«", "»")):
        if before.count(open_mark) > before.count(close_mark):
            return True
    return False


def _strip_quoted(snippet: str) -> str:
    """The snippet without text inside quotation marks or code spans."""
    return re.sub(r'"[^"]*"|“[^”]*”|«[^»]*»|`[^`]*`', ' ', snippet)
