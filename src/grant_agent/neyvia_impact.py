"""Impact map: given changed files, list what they connect to, and what is broken in the wiring today.

Kept warm per process, with file-versioned text/parser facts refreshed when files change:
UI command strings -> backend dispatch (web_backend.py, the
command sets it delegates to) -> desktop bridge allow-list -> Tauri IPC -> tests -> manuals, plus the neyvia.*
tool definitions. Nothing is executed and no model is called.
"""
from __future__ import annotations

import ast
import os
import logging
import re
import subprocess
import time
import threading
from collections import OrderedDict, deque
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CMD = re.compile(r"\b([a-z][a-z0-9_]*_command)\b")
QUOTED_CMD = re.compile(r"""["'`]([a-z][a-z0-9_]*_command)["'`]""")  # UI code: a quoted name, not obj.some_command
JS_TOKEN = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|\"(?:\\.|[^\"\n\\])*\"|'(?:\\.|[^'\n\\])*'|`(?:\\.|[^`\\])*`|[\w$]+|[^\s]")
# Existing frontend gateway names, including its local forwarding wrappers.
COMMAND_CALLS = {"callBackend", "callBackendWithTimeout", "callBackendWithRetry", "callNx", "callNeyvia",
                 "callNeyviaBackend", "callPromptBackend", "invoke", "backend", "request", "act", "save", "snapshot"}
STATEMENT_END = re.compile(r"\n(?=[^\s)\]}])")  # next line starting at column 0 that is not a closing bracket
NAMED_SET = re.compile(r"^[A-Z][A-Z0-9_]*\s*=\s*(?:frozenset|set|\{)", re.M)
TOOL = re.compile(r"\bneyvia\.([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)")
FRONT_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs"}
# Frontend files that mention commands without calling them.
NOT_CALLERS = re.compile(r"(\.test\.|nxDevFixtures|nxBusMock|Fixtures?\.|fixtures/|mock)", re.I)
CAP = 40
# One source-owner boundary for both indexing and version checks. Prune before
# traversal: filtering files after rglob still walks large generated projects.
SOURCE_EXTENSIONS = {
    "src/grant_agent": {".py"}, "src-tauri/src": {".rs"}, "web/src": FRONT_EXT,
    "tests": {".py", ".mjs", ".js"}, "docs/manuals": {".md"},
    "scripts": {".py", ".mjs", ".js", ".ps1"}, "config": {".json"},
}
IGNORED_DIRECTORIES = {"node_modules", "dist", "build", "__pycache__", ".git", ".venv",
                       ".agent_control", ".cache", "generated", "coverage", "test-results", "playwright-report"}


def _rel(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def _files(repo: Path, folder: str, exts) -> list[Path]:
    base = repo / folder
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return []
    found = []
    for directory, children, names in os.walk(base, followlinks=False):
        current = Path(directory)
        children[:] = [name for name in children if name not in IGNORED_DIRECTORIES
                       and not (folder == "scripts" and current == base and name == "evidence")
                       and not (current / name).is_symlink() and not (current / name).is_junction()]
        for name in names:
            path = current / name
            if path.suffix in exts and not path.is_symlink():
                found.append(path)
    return sorted(found)


def _read(path: Path) -> str:
    try:
        stat = path.stat()
        return _read_version(str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ""


@lru_cache(maxsize=4096)
def _read_version(path: str, modified: int, size: int) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


@lru_cache(maxsize=1024)
def _tree(text: str, full: bool):
    return ast.parse(text) if full else _top_level(text)


def _literal_strings(node) -> set[str] | None:
    """Strings of a literal str / set / tuple / list / frozenset({...}); None when not literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        values = set()
        for item in node.elts:
            found = _literal_strings(item)
            if found is None:
                return None
            values |= found
        return values
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"frozenset", "set"} and len(node.args) == 1:
        return _literal_strings(node.args[0])
    return None


def _top_level(text: str) -> ast.Module:
    """Only the module-level CONSTANT = ... statements; parsing whole giant modules costs seconds."""
    body = []
    for match in re.finditer(r"^[A-Z][A-Z0-9_]*\s*=", text, re.M):
        end = STATEMENT_END.search(text, match.end())
        try:
            body.extend(ast.parse(text[match.start():end.start() if end else len(text)]).body)
        except SyntaxError:
            continue
    return ast.Module(body=body, type_ignores=[])


def _named_sets(trees: dict) -> dict[str, set[str]]:
    """Module-level NAME = literal set of *_command strings, across the backend (CONNECTED_COMMANDS, ...)."""
    named: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                values = _literal_strings(node.value)
                if values and any(value.endswith("_command") for value in values):
                    named.setdefault(node.targets[0].id, set()).update(values)
    return named


def _resolve(node, named) -> set[str]:
    found = _literal_strings(node)
    if found is not None:
        return found
    if isinstance(node, ast.Name):
        return set(named.get(node.id, set()))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _resolve(node.left, named) | _resolve(node.right, named)
    return set()


def _imported_sets(tree, trees, repo: Path) -> dict[str, set[str]]:
    """Resolve registry imports and aliases without merging unrelated modules' COMMANDS sets."""
    named = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module = node.module.removeprefix("grant_agent.")
        source = repo / "src/grant_agent" / (module.replace(".", "/") + ".py")
        if source not in trees:
            continue
        exported = _named_sets({source: trees[source]})
        for alias in node.names:
            if alias.name in exported:
                named[alias.asname or alias.name] = exported[alias.name]
    from .proofs_e_release import check_imported_registries
    return check_imported_registries(tree, trees, repo, named)


@lru_cache(maxsize=2048)
def _ui_commands(text: str) -> set[str]:
    """Command arguments and registries, excluding comments, error codes and display aliases."""
    if "_command" not in text:
        return set()
    text = re.sub(r"(\b(?:[A-Z][A-Z0-9_]*_)?COMMANDS)\s*:\s*[^=\n]+(?=\s*=)", r"\1", text)
    tokens = [token for token in JS_TOKEN.findall(text) if not token.startswith(("//", "/*"))]
    found, scopes = set(), []
    pending_registry = False
    for number, token in enumerate(tokens):
        before = tokens[max(0, number - 4):number]
        if token == "=" and before and re.fullmatch(r"(?:[A-Z][A-Z0-9_]*_)?COMMANDS", before[-1]):
            pending_registry = True
        if token in {"{", "[", "("}:
            scopes.append(pending_registry or bool(scopes and scopes[-1]))
            pending_registry = False
        elif token in {"}", "]", ")"}:
            if scopes:
                scopes.pop()
        elif token == ";":
            pending_registry = False
        match = QUOTED_CMD.fullmatch(token)
        if not match:
            continue
        called = len(before) >= 2 and before[-1] == "(" and before[-2] in COMMAND_CALLS
        slot = len(before) >= 2 and before[-1] in {":", "="} and re.fullmatch(r"(?:\w*_)?command|\w*Command", before[-2])
        if called or slot or (scopes and scopes[-1]):
            found.add(match.group(1))
    from .proofs_e_release import check_ui_command_evidence
    return check_ui_command_evidence(tokens, COMMAND_CALLS, found)


def _compares(tree, variable: str, named) -> list[tuple[int, int, set[str], ast.AST]]:
    """Every `if variable == "x"` / `if variable in {...}`: (line, end line of its branch, commands, the if node)."""
    rows = []
    for branch in ast.walk(tree):
        if not isinstance(branch, ast.If):
            continue
        for node in ast.walk(branch.test):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == variable                     and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.In)):
                commands = {value for value in _resolve(node.comparators[0], named) if value.endswith("_command")}
                if commands:
                    rows.append((node.lineno, branch.body[-1].end_lineno, commands, branch))
    from .proofs_e_release import check_dispatch_membership
    return check_dispatch_membership(tree, variable, named, rows)


def _imports_in(branch) -> set[str]:
    modules = set()
    for node in ast.walk(branch):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[-1])
    return modules


@lru_cache(maxsize=4)
def _index_cached(repo_text: str, stamp: tuple):
    with _INDEX_LOCK:
        return _build(Path(repo_text))


SCANNED = tuple(SOURCE_EXTENSIONS)
_INDEX_LOCK = threading.RLock()
_WARM_LOCK = threading.Lock()
_WARMING: set[str] = set()


def _stamp(repo: Path) -> tuple:
    """Only actual indexed owners invalidate the cache; evidence writes do not."""
    versions = []
    for folder, extensions in SOURCE_EXTENSIONS.items():
        for path in _files(repo, folder, extensions):
            try:
                stat = path.stat()
                versions.append((_rel(path, repo), stat.st_mtime_ns, stat.st_size))
            except OSError:
                pass
    return tuple(sorted(versions))


def index(repo: Path = REPO) -> dict:
    from .proofs_e_release import check_impact_index
    return check_impact_index(_index_cached(str(repo), _stamp(repo)))


def warm(repo: Path = REPO) -> None:
    """Build once at broker startup without blocking startup; file versions refresh on calls."""
    key = str(repo)
    with _WARM_LOCK:
        if key in _WARMING:
            return
        _WARMING.add(key)
    def build():
        try:
            index(repo)
        except Exception:
            logging.getLogger(__name__).exception("Could not warm the impact index; the next request will retry")
        finally:
            with _WARM_LOCK:
                _WARMING.discard(key)
    threading.Thread(target=build, name="neyvia-impact-warm", daemon=True).start()


_ENRICHMENT_LIMIT = 16
_ENRICHMENT_LOCK = threading.Condition()
_ENRICHMENT_QUEUE = deque()
_ENRICHMENT_PENDING = set()
_ENRICHMENT_RESULTS = OrderedDict()
_ENRICHMENT_WORKER = None


def _enrich_worker() -> None:
    while True:
        with _ENRICHMENT_LOCK:
            while not _ENRICHMENT_QUEUE:
                _ENRICHMENT_LOCK.wait()
            key = _ENRICHMENT_QUEUE.popleft()
        repo, paths = key
        started = time.perf_counter()
        try:
            result = impact(paths, gaps=False, repo=Path(repo))
            value = {"status": "ready", "files": result["files"], "checkedAt": time.time()}
        except Exception as error:
            value = {"status": "error", "files": [], "error": str(error), "checkedAt": time.time()}
        value["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
        with _ENRICHMENT_LOCK:
            _ENRICHMENT_PENDING.discard(key)
            _ENRICHMENT_RESULTS[key] = value
            _ENRICHMENT_RESULTS.move_to_end(key)
            while len(_ENRICHMENT_RESULTS) > _ENRICHMENT_LIMIT:
                _ENRICHMENT_RESULTS.popitem(last=False)


def impact_enrichment(paths, *, repo: Path = REPO) -> dict:
    """Optional dependency context never waits for source scanning or parsing.

    Cached results identify their observation time and queue a source-version
    refresh. They are context, never a substitute for fresh action effect checks.
    A single daemon and bounded queue/cache prevent requests or process shutdown
    from being held up by repository enrichment.
    """
    global _ENRICHMENT_WORKER
    if not paths:
        return {"status": "ready", "files": [], "freshness": "empty"}
    key = (str(repo), tuple(sorted(set(str(path) for path in paths))))
    with _ENRICHMENT_LOCK:
        cached = _ENRICHMENT_RESULTS.get(key)
        if key not in _ENRICHMENT_PENDING:
            if len(_ENRICHMENT_PENDING) >= _ENRICHMENT_LIMIT:
                return {**(cached or {"files": []}), "status": "busy", "freshness": "cached" if cached else "unavailable"}
            _ENRICHMENT_PENDING.add(key)
            _ENRICHMENT_QUEUE.append(key)
            if _ENRICHMENT_WORKER is None:
                # Source indexing is advisory and can consume a full core on a
                # fresh process. Let the action's fresh effects and G finish
                # before this optional dependency graph starts building.
                _ENRICHMENT_WORKER = threading.Timer(5.0, _enrich_worker)
                _ENRICHMENT_WORKER.name = "neyvia-impact-enrichment"
                _ENRICHMENT_WORKER.daemon = True
                _ENRICHMENT_WORKER.start()
            _ENRICHMENT_LOCK.notify()
        if cached:
            _ENRICHMENT_RESULTS.move_to_end(key)
            return {**cached, "freshness": "cached", "refreshPending": True}
        return {"status": "pending", "files": [], "freshness": "unavailable"}


def _build(repo: Path) -> dict:
    backend_files = _files(repo, "src/grant_agent", {".py"})
    trees = {}
    always = {"web_backend", "desktop_bridge"}
    for path in backend_files:
        text = _read(path)
        # Parse only what can hold command sets or tool definitions; parsing all 350 modules takes seconds.
        if path.stem not in always and not ("_command" in text and NAMED_SET.search(text)) and not (path.stem.startswith("neyvia_") and "DEFINITIONS" in text):
            continue
        trees[path] = _tree(text, path.stem in always)
    named = _named_sets(trees)
    web = repo / "src/grant_agent/web_backend.py"
    bridge = repo / "src/grant_agent/desktop_bridge.py"
    handled: dict[str, str] = {}
    branches = []
    if web in trees:
        web_named = named | _imported_sets(trees[web], trees, repo)
        for line, end, commands, branch in _compares(trees[web], "command", web_named):
            branches.append({"start": line, "end": end, "commands": commands, "modules": _imports_in(branch)})
            for command in commands:
                handled.setdefault(command, f"src/grant_agent/web_backend.py:{line}")
    bridge_allowed: set[str] = set()
    bridge_fast: set[str] = set()
    if bridge in trees:
        bridge_named = named | _imported_sets(trees[bridge], trees, repo)
        for node in trees[bridge].body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ALLOWED_DESKTOP_COMMANDS" for t in node.targets):
                bridge_allowed |= _resolve(node.value, bridge_named)
        for _line, _end, commands, _branch in _compares(trees[bridge], "normalized", bridge_named):
            bridge_fast |= commands

    rust = "\n".join(_read(p) for p in _files(repo, "src-tauri/src", {".rs"}))
    declared = set(re.findall(r"#\[tauri::command[^\]]*\]\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-z0-9_]+)", rust))
    registered = set()
    for block in re.findall(r"generate_handler!\[(.*?)\]", rust, re.S):
        registered |= {name.split("::")[-1] for name in re.findall(r"[A-Za-z0-9_:]+", block)}

    def tokens(paths, pattern=CMD):
        found: dict[str, set[str]] = {}
        for path in paths:
            text = _read(path)
            for token in (_ui_commands(text) if pattern is QUOTED_CMD else set(pattern.findall(text))):
                found.setdefault(token, set()).add(_rel(path, repo))
        return found

    front_paths = [p for p in _files(repo, "web/src", FRONT_EXT)]
    callers = [p for p in front_paths if not NOT_CALLERS.search(_rel(p, repo))]
    ui = tokens(callers, QUOTED_CMD)
    next_ui = tokens([p for p in callers if "/neyvia/next/" in _rel(p, repo)], QUOTED_CMD)
    test_paths = _files(repo, "tests", {".py", ".mjs", ".js"}) + [p for p in front_paths if ".test." in p.name]
    tests = tokens(test_paths)
    manual_paths = _files(repo, "docs/manuals", {".md"})
    manuals = tokens(manual_paths)
    scripts = tokens(_files(repo, "scripts", {".py", ".mjs", ".js", ".ps1"}))

    tools: dict[str, str] = {}
    for path, tree in trees.items():
        if not path.stem.startswith("neyvia_"):
            continue
        prefix = "pdf." if path.stem == "neyvia_pdf_tools" else ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DEFINITIONS" for t in node.targets) \
                    and isinstance(node.value, ast.List):
                for item in node.value.elts:
                    if isinstance(item, ast.Tuple) and item.elts and isinstance(item.elts[0], ast.Constant):
                        tools["neyvia." + prefix + item.elts[0].value] = _rel(path, repo)
    manual_text = {_rel(p, repo): _read(p) for p in manual_paths}
    tool_tests = tokens(test_paths, TOOL)
    return {"repo": repo, "handled": handled, "branches": branches, "bridge": bridge_allowed, "bridgeFast": bridge_fast,
            "tauriDeclared": declared, "tauri": registered, "ui": ui, "nextUi": next_ui, "tests": tests,
            "manuals": manuals, "scripts": scripts, "tools": tools, "manualText": manual_text,
            "toolTests": {"neyvia." + k: v for k, v in tool_tests.items()},
            "backendFiles": [_rel(p, repo) for p in backend_files], "frontFiles": [_rel(p, repo) for p in front_paths],
            "testFiles": [_rel(p, repo) for p in test_paths]}


def _tool_in_manuals(idx, tool: str) -> list[str]:
    short = tool.removeprefix("neyvia.")
    pattern = re.compile(r"(?<![\w.])(?:neyvia\.)?" + re.escape(short) + r"(?![\w])")
    # Manuals name siblings in shorthand after the first full name: `neyvia.pdf.open(...)` · `goto(page)`.
    space, _, last = short.rpartition(".")
    sibling = re.compile(r"(?<![\w.])" + re.escape(last) + r"\(") if space else None
    family = re.compile(r"(?<![\w])" + re.escape(space) + r"\.[a-z]") if space else None

    def literal_match(text, literal, regex, prefix=""):
        # Search literal candidates in C, then let the original regex decide
        # boundaries at that exact position. Regex search over every character
        # of giant generated manuals can monopolize the interpreter.
        start = 0
        while (position := text.find(literal, start)) >= 0:
            if regex.match(text, position):
                return True
            if prefix and position >= len(prefix) and text.startswith(prefix, position - len(prefix)):
                if regex.match(text, position - len(prefix)):
                    return True
            start = position + len(literal)
        return False

    def near(text):  # the shorthand counts only within three lines after its family is named
        lines = text.splitlines()
        return any(literal_match(line, last + "(", sibling) and
                   any(literal_match(row, space + ".", family) for row in lines[max(0, number - 3):number + 1])
                   for number, line in enumerate(lines))
    return sorted(path for path, text in idx["manualText"].items()
                  if literal_match(text, short, pattern, "neyvia.") or
                  (sibling and last + "(" in text and near(text)))


def find_gaps(idx) -> dict:
    from .proofs_awareness import check_gaps
    result = _find_gaps(idx)
    check_gaps(idx, result)
    return result


def _find_gaps(idx) -> dict:
    handled = set(idx["handled"]) | idx["bridgeFast"]
    ui, tauri = idx["ui"], idx["tauri"]
    ui_no_handler = sorted(c for c in ui if c not in handled and c not in tauri and c not in idx["tauriDeclared"])
    next_no_bridge = sorted(c for c in idx["nextUi"] if c in handled and c not in idx["bridge"] and c not in tauri)
    tauri_unregistered = sorted(idx["tauriDeclared"] - tauri)
    no_ui = [c for c in idx["handled"] if c not in ui and c not in tauri]
    only_scripts = sorted(c for c in no_ui if c in idx["scripts"] or c in idx["tests"])
    orphans = sorted(c for c in no_ui if c not in idx["scripts"] and c not in idx["tests"])
    bridge_dead = sorted(c for c in idx["bridge"] if c not in handled)
    no_manual = sorted(t for t in idx["tools"] if not _tool_in_manuals(idx, t))
    return {
        "uiWithoutHandler": {"help": "The UI names a command that no backend branch or Tauri command handles", "items": ui_no_handler,
                             "where": {c: sorted(ui[c])[:3] for c in ui_no_handler}},
        "nextUiMissingFromBridge": {"help": "The new UI calls it, the web backend handles it, but the desktop bridge refuses it", "items": next_no_bridge,
                                    "where": {c: sorted(idx["nextUi"][c])[:3] for c in next_no_bridge}},
        "bridgeWithoutHandler": {"help": "The desktop bridge allows a command nothing handles", "items": bridge_dead},
        "tauriNotRegistered": {"help": "#[tauri::command] declared but missing from generate_handler!", "items": tauri_unregistered},
        "handlerWithoutCaller": {"help": "Review lead: no static UI, Tauri, script or test reference; tools/dynamic callers may exist", "items": orphans},
        "handlerOnlyScriptsOrTests": {"help": "Review lead: static references only in scripts/tests; tools/dynamic callers may exist", "items": only_scripts},
        "toolWithoutManual": {"help": "neyvia.* tool no manual mentions", "items": no_manual},
    }


def _git_changes(repo: Path) -> dict[str, list[tuple[int, int]] | None]:
    """Uncommitted changes: path -> changed line ranges (new side); None means the whole file (new/untracked)."""
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=30, **hidden_windows_subprocess_kwargs()).stdout
    changes: dict[str, list | None] = {}
    current = None
    for line in run("diff", "HEAD", "-U0", "--no-color", "--no-ext-diff").splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else line[6:]
            if current:
                changes.setdefault(current, [])
        elif line.startswith("@@") and current is not None and changes.get(current) is not None:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, count = int(match.group(1)), int(match.group(2) or 1)
            changes[current].append((start, start + max(count, 1) - 1))
    for path in run("ls-files", "--others", "--exclude-standard").splitlines():
        changes[path] = None
    return changes


def _text(idx, rel: str) -> str:
    """File text, read once per index (the index is rebuilt when any scanned file changes)."""
    cache = idx.setdefault("texts", {})
    if rel not in cache:
        cache[rel] = _read(idx["repo"] / rel)
    return cache[rel]


def _dependents(idx, rel: str) -> list[str]:
    cache = idx.setdefault("dependents", {})
    if rel in cache:
        return cache[rel]
    repo, stem, suffix = idx["repo"], Path(rel).stem, Path(rel).suffix
    if suffix == ".py":
        module = rel.removeprefix("src/").removesuffix(".py").replace("/", ".")
        pattern = re.compile(r"(from\s+\.+(?:[\w]+\.)*" + re.escape(stem) + r"\s+import|grant_agent\." + re.escape(stem) + r"\b"
                             r"|(?:from|import)\s+" + re.escape(module) + r"\b"
                             r"|from\s+\.+\s+import\s+[^\n]*\b" + re.escape(stem) + r"\b)")
        pool = idx["backendFiles"] + idx["testFiles"]
    elif suffix in FRONT_EXT:
        pattern = re.compile(r"""(?:from\s+|import\(\s*)["'][^"']*/""" + re.escape(stem) + r"""(?:\.[a-z]+)?["']""")
        pool = idx["frontFiles"] + idx["testFiles"]
    else:  # config, manuals, styles: whoever names the file
        pattern = re.compile(r"(?<![\w-])" + re.escape(Path(rel).name) + r"(?![\w-])")
        pool = idx["backendFiles"] + idx["frontFiles"] + idx["testFiles"] + [
            _rel(p, repo) for p in (repo / "config").glob("*.json")] + [_rel(p, repo) for p in (repo / "scripts").glob("*.py")]
    needle = stem if suffix in FRONT_EXT | {".py"} else Path(rel).name  # cheap substring test before the regex
    cache[rel] = sorted(path for path in pool if path != rel and needle in _text(idx, path) and pattern.search(_text(idx, path)))
    return cache[rel]


def _commands_for(idx, rel: str, ranges) -> tuple[set[str], set[str]]:
    repo = idx["repo"]
    text = _read(repo / rel)
    lines = text.splitlines()
    if ranges:
        text = "\n".join("\n".join(lines[a - 1:b]) for a, b in ranges)
    commands, tools = set(CMD.findall(text)), {"neyvia." + t for t in TOOL.findall(text)}
    if rel == "src/grant_agent/web_backend.py":
        if ranges:
            for branch in idx["branches"]:
                if any(a <= branch["end"] and b >= branch["start"] for a, b in ranges):
                    commands |= branch["commands"]
        else:
            commands = set()  # every command: too broad to be useful without changed lines
    stem = Path(rel).stem
    if rel.startswith("src/grant_agent/") and rel.endswith(".py"):
        for branch in idx["branches"]:
            if stem in branch["modules"]:
                commands |= branch["commands"]
        tools |= {name for name, path in idx["tools"].items() if path == rel}
    known = set(idx["handled"]) | idx["bridge"] | idx["tauri"] | set(idx["ui"])
    return {c for c in commands if c in known}, {t for t in tools if t in idx["tools"]}


def _command_row(idx, command: str) -> dict:
    handled = idx["handled"].get(command) or ("desktop_bridge fastpath" if command in idx["bridgeFast"] else None)
    ui = sorted(idx["ui"].get(command, ()))
    row = {"command": command, "ui": ui, "handler": handled, "bridge": command in idx["bridge"],
           "tauri": command in idx["tauri"], "tests": sorted(idx["tests"].get(command, ())),
           "manuals": sorted(idx["manuals"].get(command, ()))}
    missing = []
    if ui and not handled and not row["tauri"]:
        missing.append("no handler")
    if handled and not ui and not row["tauri"]:
        missing.append("no UI calls it")
    if command in idx["nextUi"] and handled and not row["bridge"] and not row["tauri"]:
        missing.append("not in the desktop bridge")
    row["missing"] = missing
    from .proofs_awareness import check_command
    check_command(idx, command, row)
    return row


def _short(paths, limit=4) -> str:
    paths = list(paths)
    return ", ".join(paths[:limit]) + (f" +{len(paths) - limit} more" if len(paths) > limit else "")


def impact(paths=None, *, gaps: bool = True, repo: Path = REPO) -> dict:
    started = time.perf_counter()
    idx = index(repo)
    if paths:
        changes = {}
        for raw in paths:
            path = Path(str(raw).strip())
            path = path if path.is_absolute() else repo / path
            try:
                rel = _rel(path.resolve(), repo.resolve())
            except ValueError:
                raise ValueError(f"{raw} is outside this repository ({repo})")
            changes[rel] = None
        source = "paths"
    else:
        changes, source = _git_changes(repo), "git"
    files, lines = [], []
    for rel, ranges in sorted(changes.items()):
        if not (repo / rel).is_file():
            files.append({"path": rel, "deleted": True, "dependents": _dependents(idx, rel)})
            continue
        commands, tools = _commands_for(idx, rel, ranges)
        rows = [_command_row(idx, c) for c in sorted(commands)]
        tool_rows = [{"tool": t, "definedIn": idx["tools"][t], "manuals": _tool_in_manuals(idx, t),
                      "tests": sorted(idx["toolTests"].get(t, ()))} for t in sorted(tools)]
        stem = Path(rel).stem
        dependents = _dependents(idx, rel)
        needle = stem if Path(rel).suffix in FRONT_EXT | {".py"} else Path(rel).name
        mention_tests = sorted(set(p for p in dependents if p in idx["testFiles"]) | (
            {p for p in idx["testFiles"] if p != rel and needle in _text(idx, p)} if len(needle) > 4 else set()))
        entry = {"path": rel, "changedLines": ranges, "commands": rows[:CAP], "commandsTruncated": len(rows) > CAP,
                 "tools": tool_rows, "dependents": dependents[:CAP], "tests": mention_tests[:CAP]}
        files.append(entry)
        check = []
        for row in rows[:12]:
            ends = [part for part in (
                ("UI " + _short(row["ui"], 2)) if row["ui"] else "",
                ("handler " + row["handler"]) if row["handler"] else "",
                "bridge" if row["bridge"] else "", "Tauri" if row["tauri"] else "",
                ("tests " + _short(row["tests"], 2)) if row["tests"] else "",
                ("manual " + _short(row["manuals"], 1)) if row["manuals"] else "") if part]
            check.append(f"  - {row['command']}: " + "; ".join(ends) + (f"  MISSING: {', '.join(row['missing'])}" if row["missing"] else ""))
        if len(rows) > 12:
            check.append(f"  - and {len(rows) - 12} more commands")
        for row in tool_rows:
            check.append(f"  - {row['tool']}: manual {_short(row['manuals'], 2) or 'MISSING'}; tests {_short(row['tests'], 2) or 'none'}")
        if dependents:
            check.append(("  - imported by " if Path(rel).suffix in FRONT_EXT | {".py"} else "  - named by ") + _short(dependents, 5))
        if mention_tests:
            check.append("  - tests naming it: " + _short(mention_tests, 4))
        lines.append(f"You changed {rel}." + ("\n Also check:\n" + "\n".join(check) if check else " Nothing else names it."))
    result = {"ok": True, "source": source, "repo": str(repo), "files": files,
              "index": {"handlers": len(idx["handled"]), "bridge": len(idx["bridge"]), "tauri": len(idx["tauri"]),
                        "uiCommands": len(idx["ui"]), "tools": len(idx["tools"])}}
    if gaps:
        found = find_gaps(idx)
        result["gaps"] = {key: {**value, "count": len(value["items"]), "items": value["items"][:60]} for key, value in found.items()}
        lines.append("Static wiring gaps and review leads in the repository today:\n" + "\n".join(
            f"  - {value['help']}: {len(value['items'])}" + (f" ({_short(value['items'], 4)})" if value["items"] else "")
            for value in found.values()))
    if not files:
        lines.insert(0, "No changed files." if source == "git" else "No paths given.")
    result["text"] = "\n".join(lines)
    result["elapsedMs"] = round((time.perf_counter() - started) * 1000)
    return result
