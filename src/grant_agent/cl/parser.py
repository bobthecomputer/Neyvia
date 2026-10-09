"""Connected Language 1 lexical/document and action parser; no eval or imports."""
from __future__ import annotations

from dataclasses import dataclass, field
import ast
import json
import re
from typing import Any

TAGS = frozenset("L T S E D A I C P J X F K Q R M V".split())
LEVELS = {"L": 0, "T": 1, "S": 1, "A": 1, "I": 1, "C": 1,
          "P": 2, "J": 2, "X": 2, "F": 2, "Q": 2, "M": 2, "V": 2}
NAME = r"[A-Za-z_][A-Za-z0-9_-]*(?:\.(?:[A-Za-z_][A-Za-z0-9_-]*|[0-9]+))*"


class CLParseError(ValueError):
    pass


class BareWord(str):
    """Distinguish enum/path/id words from quoted str values for type checking."""


class Handle(str):
    pass


@dataclass(frozen=True)
class Quantity:
    value: int | float
    unit: str


@dataclass(frozen=True)
class Range:
    start: int | float | None
    end: int | float | None


@dataclass
class Action:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    positional: list[Any] = field(default_factory=list)
    checks: list[tuple[str, dict]] = field(default_factory=list)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


@dataclass
class Line:
    tag: str
    body: str
    gloss: str = ""
    indent: int = 0

    @property
    def level(self):
        if self.tag == "C" and re.match(NAME + r"\s+" + NAME + r"\(", self.body):
            return 2
        return LEVELS.get(self.tag, 1)


@dataclass
class Document:
    lines: list[Line]
    version: int = 1
    pragma: bool = True


_LEX = re.compile(
    r'(?P<time>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d))'
    r'|(?P<range>(?:-?\d+(?:\.\d+)?)?\.\.(?:-?\d+(?:\.\d+)?)?)'
    r'|(?P<quantity>-?(?:\d+(?:\.\d+)?)(?:KiB|MiB|GiB|ms|px|B|s|m|h|d|%))(?![A-Za-z0-9_])'
    r'|(?P<number>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|(?P<handle>@[A-Za-z0-9]+)'
    r'|(?P<word>[A-Za-z_./][A-Za-z0-9_./-]*)'
    r'|(?P<operator>->|==|!=|<=|>=|[()\[\]{}:,;?^#|=+!~<>*-])'
)


def tokenize(text: str, *, raw=False) -> list[Token]:
    result, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text.startswith(('"""', "'''"), pos):
            if not raw:
                raise CLParseError("Raw strings are allowed only in do lines")
            end = text.find(text[pos:pos+3], pos + 3)
            if end < 0:
                raise CLParseError("Unterminated raw string")
            end += 3
            result.append(Token("raw", text[pos:end], pos, end))
            pos = end
            continue
        if text[pos] == "'":
            end = pos + 1
            while end < len(text):
                if text[end] == '\\': end += 2
                elif text[end] == "'": break
                elif text[end] in '\r\n': raise CLParseError('Unterminated quoted string')
                else: end += 1
            if end >= len(text): raise CLParseError('Unterminated quoted string')
            end += 1
            try: ast.literal_eval(text[pos:end])
            except (ValueError,SyntaxError) as exc: raise CLParseError('Invalid quoted string') from exc
            result.append(Token('pystring',text[pos:end],pos,end))
            pos = end
            continue
        if text[pos] == '"':
            try:
                _, used = json.JSONDecoder().raw_decode(text[pos:])
            except ValueError as exc:
                raise CLParseError("Invalid JSON string") from exc
            end = pos + used
            result.append(Token("string", text[pos:end], pos, end))
            pos = end
            continue
        match = _LEX.match(text, pos)
        if not match:
            raise CLParseError(f"Invalid CL token at column {pos + 1}: {text[pos:pos + 20]!r}")
        result.append(Token(match.lastgroup, match.group(), pos, match.end()))
        pos = match.end()
    return result


def _number(text):
    return float(text) if any(x in text for x in ".eE") else int(text)


class Reader:
    def __init__(self, text, *, raw=False):
        self.tokens = tokenize(text, raw=raw)
        self.index = 0

    def peek(self, value=None):
        token = self.tokens[self.index] if self.index < len(self.tokens) else None
        return token if value is None else bool(token and token.text == value)

    def take(self, value=None):
        token = self.peek()
        if token is None or value is not None and token.text != value:
            raise CLParseError(f"Expected {value or 'value'}, got {token.text if token else 'end'}")
        self.index += 1
        return token

    def value(self):
        token = self.take()
        if token.kind == "string":
            return json.loads(token.text)
        if token.kind == 'pystring':
            return ast.literal_eval(token.text)
        if token.kind == "raw":
            return token.text[3:-3]
        if token.kind == "number":
            return _number(token.text)
        if token.kind == "range":
            left, right = token.text.split("..")
            return Range(_number(left) if left else None, _number(right) if right else None)
        if token.kind == "quantity":
            match = re.fullmatch(r"(-?\d+(?:\.\d+)?)(.*)", token.text)
            return Quantity(_number(match[1]), match[2])
        if token.kind == "handle":
            return Handle(token.text)
        if token.kind == "time":
            return token.text
        if token.text == "[":
            values = []
            while not self.peek("]"):
                if self.peek(","):
                    self.take()
                # Pair-form rows remain records with explicit keys.
                if self.peek() and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1].text == ":":
                    key = self.take().text
                    self.take(":")
                    values.append({key: self.value()})
                else:
                    values.append(self.value())
            self.take("]")
            return values
        if token.text == "{":
            result = {}
            while not self.peek("}"):
                if self.peek(","):
                    self.take()
                key = self.take()
                name = json.loads(key.text) if key.kind == "string" else ast.literal_eval(key.text) if key.kind == 'pystring' else key.text
                if name in result:
                    raise CLParseError("Duplicate record field: " + name)
                if self.peek(":"):
                    self.take()
                    result[name] = self.value()
                else:
                    result[name] = BareWord(name)
            self.take("}")
            return result
        if token.kind == "word":
            if self.peek("("):
                return self.call(token.text)
            if token.text in {"true", "false", "null", "True", "False", "None"}:
                return {"true": True, "false": False, "null": None,
                        "True": True, "False": False, "None": None}[token.text]
            return BareWord(token.text)
        raise CLParseError("Expected CL value, got " + token.text)

    def call(self, name=None):
        name = name or self.take().text
        if not re.fullmatch(NAME, name):
            raise CLParseError("Invalid action name")
        self.take("(")
        call = Action(name)
        named = False
        while not self.peek(")"):
            if self.peek(","):
                self.take()
            if self.peek() and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1].text in {":", "="}:
                key = self.take().text
                self.take()
                if key in call.arguments:
                    raise CLParseError("Duplicate argument: " + key)
                call.arguments[key] = self.value()
                named = True
            else:
                if named:
                    raise CLParseError("Positional arguments must precede named arguments")
                call.positional.append(self.value())
        self.take(")")
        return call


def split_gloss(text):
    pos, quoted, raw = 0, None, None
    while pos < len(text):
        if raw and text.startswith(raw,pos):
            raw = None
            pos += 3
            continue
        if not raw and not quoted and text.startswith(('"""', "'''"),pos):
            raw = text[pos:pos+3]
            pos += 3
            continue
        char = text[pos]
        if not raw and char in {'"',"'"} and (quoted is None or quoted==char):
            quoted = None if quoted else char
        elif char == "\\" and quoted:
            pos += 2
            continue
        if not quoted and not raw and text.startswith(" -- ", pos):
            return text[:pos], text[pos + 4:]
        pos += 1
    return text, ""


def parse_action(text: str) -> Action:
    body, _ = split_gloss(text.strip())
    if body.startswith("do "):
        body = body[3:]
    elif body.startswith("run "):
        body = body[4:]
    reader = Reader(body, raw=True)
    action = reader.call()
    while reader.peek():
        reader.take("C")
        name = reader.take().text
        args = reader.call(name).arguments if reader.peek("(") else {}
        action.checks.append((name, args))
    return action


def logical_lines(text):
    current, raw = [], None
    for line in text.splitlines():
        current.append(line)
        # Raw strings are action-only. Quoted source and surrounding prose never
        # change the action stream, even when they contain escaped triple quotes.
        if raw or re.match(r"(?:do |run )?" + NAME + r"\(", line.lstrip()):
            index, quoted = 0, None
            while index < len(line):
                if raw and line.startswith(raw,index):
                    raw = None
                    index += 3
                elif not raw and not quoted and line.startswith(('"""', "'''"),index):
                    raw = line[index:index+3]
                    index += 3
                elif not raw and line[index] in {'"',"'"} and (quoted is None or quoted==line[index]):
                    quoted = None if quoted else line[index]
                    index += 1
                elif quoted and line[index] == "\\":
                    index += 2
                else:
                    index += 1
        if not raw:
            yield "\n".join(current)
            current = []
    if current:
        raise CLParseError("Unterminated raw string")


def _balanced(body, raw=False):
    stack = []
    for token in tokenize(body, raw=raw):
        if token.text in {"(", "[", "{"}:
            stack.append(token.text)
        if token.text in {")", "]", "}"}:
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[token.text]:
                raise CLParseError("Unbalanced delimiters")
    if stack:
        raise CLParseError("Unbalanced delimiters")


def parse_document(text: str, *, strict=True) -> Document:
    document = Document([], pragma=False)
    for number, original in enumerate(logical_lines(text), 1):
        if not original.strip():
            continue
        if original.startswith("CL "):
            if document.lines or document.pragma or original.strip() != "CL 1":
                raise CLParseError("Unsupported or misplaced CL version")
            document.pragma = True
            continue
        if original.startswith("--"):
            document.lines.append(Line("--", original[2:].strip()))
            continue
        indent = len(original) - len(original.lstrip(" "))
        source, gloss = split_gloss(original.strip())
        tag, separator, body = source.partition(" ")
        if not separator or not body:
            raise CLParseError(f"Line {number}: missing tag/body separator")
        if tag not in TAGS | {"do"}:
            if strict:
                raise CLParseError(f"Line {number}: unknown tag {tag}")
            document.lines.append(Line(tag, body, gloss, indent))
            continue
        if indent and tag not in {"E", "D"}:
            raise CLParseError(f"Line {number}: only E/D may be indented")
        if tag == "do":
            parse_action(source)
        elif tag in {"X", "F"}:
            if tag == "X" and " -> " not in body:
                raise CLParseError("Pitfall needs a recovery arrow")
        else:
            _balanced(body)
        if tag == "L" and not re.match(r"^" + NAME + r" v\d+(?: |$)", body):
            raise CLParseError("Layer needs a name and version")
        if tag == "R" and not re.match(NAME + r" (ok|fail|ask|stale|refused|unknown|frontier|skipped)(?: |$)", body):
            raise CLParseError("Receipt needs a valid status")
        if tag in {"A", "P"} and not re.match(NAME + r"\(", body):
            raise CLParseError("Action/procedure needs a signature")
        if tag == "C" and not re.match(NAME + r"\s+" + NAME + r"(?:\([^)]*\))?:\s*\S", body):
            raise CLParseError("Check needs action, name and expression")
        document.lines.append(Line(tag, body, gloss, indent))
    return document


def canonical_body(body, tag):
    if tag in {"X", "F", "--"}:
        return body.strip()
    tokens = tokenize(body, raw=tag == "do")
    output, previous = "", ""
    tight_after = {"(", "[", "{", ":", "#", "?", "^", "=", "|", "~", "+", "-"}
    tight_before = {")", "]", "}", ":", "?", "#", "|", "=", ";"}
    for token in tokens:
        if token.text == ",":
            previous = ","
            continue
        value = json.dumps(token.text[3:-3], ensure_ascii=False) if token.kind == "raw" else token.text
        space = bool(output and previous not in tight_after and value not in tight_before)
        if value == "=" and previous in {"!", "~"}:
            space = True
        if value == "(" and previous and re.fullmatch(NAME, previous):
            space = False
        if value == "{" and tag == "T" and len(output.split()) == 1:
            space = False
        output += (" " if space else "") + value
        previous = value
    return output


def render_document(document: Document) -> str:
    lines = ["CL " + str(document.version)] if document.pragma else []
    for line in document.lines:
        if line.tag == "--":
            lines.append("-- " + line.body)
        else:
            lines.append(" " * line.indent + line.tag + " " + canonical_body(line.body, line.tag)
                         + (" -- " + line.gloss if line.gloss else ""))
    return "\n".join(lines) + "\n"


def filter_level(text: str, level: int) -> str:
    if type(level) is not int or level not in {0, 1, 2}:
        raise ValueError("CL level must be 0, 1 or 2")
    document = parse_document(text)
    document.lines = [line for line in document.lines if line.tag != "--" and line.level <= level]
    return render_document(document)
