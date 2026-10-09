"""Report source files statically reachable from passing, source-bound UI journeys.

This is deliberately a different evidence class from executed line coverage. It
does not prove that a reached component rendered or that its branches ran.
Callers must supply only outcome receipts whose pass and source bindings have
already been validated; this module rechecks the bindings for the declared
entry files and binds every traversed file into its result.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import queue
import shutil
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from typing import Any


CLASSIFICATION = "statically reached by passing journey"
SCHEMA = "neyvia.static-web-reach.v1"
_CODE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
_STYLE_EXTENSIONS = (".css", ".scss", ".sass", ".less")
_RESOLVE_EXTENSIONS = _CODE_EXTENSIONS + _STYLE_EXTENSIONS
_MAX_FILES = 12000
_MAX_TEXT_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 200 * 1024 * 1024


class ReachabilityError(ValueError):
    """Input or source graph could not be safely and deterministically read."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(repo: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReachabilityError("paths must be non-empty repository-relative strings")
    raw = Path(value.replace("\\", "/"))
    if raw.is_absolute() or any(part in ("", ".", "..") for part in raw.parts):
        raise ReachabilityError(f"path is not a normalized repository-relative path: {value!r}")
    candidate = (repo / raw).resolve(strict=False)
    if not candidate.is_relative_to(repo):
        raise ReachabilityError(f"path escapes repository: {value!r}")
    return candidate


def _relative(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def _parser_binding(repo: Path) -> dict[str, str]:
    path = repo / "scripts" / "p22_js_imports.cjs"
    if not path.is_file():
        raise ReachabilityError("source-bound JS parser script is missing: scripts/p22_js_imports.cjs")
    return {"path": "scripts/p22_js_imports.cjs", "sha256": _sha256(path)}


def _validate_journeys(repo: Path, journeys: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(journeys, dict) or not journeys:
        raise ReachabilityError("journeys must be a non-empty mapping of outcome IDs to validated receipts")
    accepted: dict[str, dict[str, Any]] = {}
    for identity, receipt in journeys.items():
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", identity):
            raise ReachabilityError("journey IDs must be stable contract/outcome identifiers")
        if not isinstance(receipt, dict) or receipt.get("status") != "PASS":
            continue
        bindings = receipt.get("sourceBindings")
        entries = receipt.get("entries")
        if not isinstance(bindings, dict) or not bindings or not isinstance(entries, list) or not entries:
            raise ReachabilityError(f"passing journey {identity!r} needs sourceBindings and explicit entries")
        normalized_bindings: dict[str, str] = {}
        for name, expected in bindings.items():
            path = _repo_path(repo, name)
            if not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
                raise ReachabilityError(f"journey {identity!r} has an invalid source binding for {name!r}")
            if path.stat().st_size > _MAX_FILE_BYTES:
                raise ReachabilityError(f"source binding exceeds {_MAX_FILE_BYTES} byte graph limit: {name}")
            rel = _relative(repo, path)
            if _sha256(path) != expected:
                raise ReachabilityError(f"journey {identity!r} has stale source binding: {rel}")
            normalized_bindings[rel] = expected
        normalized_entries = []
        for entry in entries:
            path = _repo_path(repo, entry)
            if not path.is_file():
                raise ReachabilityError(f"journey {identity!r} entry is missing: {entry!r}")
            rel = _relative(repo, path)
            if rel not in normalized_bindings:
                raise ReachabilityError(f"journey {identity!r} entry is not bound by its receipt: {rel}")
            if path.suffix.lower() not in _RESOLVE_EXTENSIONS:
                raise ReachabilityError(f"journey {identity!r} entry must be a JS/TS or stylesheet source: {rel}")
            normalized_entries.append(rel)
        accepted[identity] = {
            "status": "PASS",
            "entries": sorted(set(normalized_entries)),
            "sourceBindings": dict(sorted(normalized_bindings.items())),
        }
    if not accepted:
        return {}
    return dict(sorted(accepted.items()))


class _JSImportParser:
    """One bounded Babel-parser session per graph, never one Node per file."""

    def __init__(self, repo: Path, *, timeout: float = 12.0):
        self.repo = repo.resolve(strict=True)
        self.script = repo / "scripts" / "p22_js_imports.cjs"
        if not self.script.is_file():
            raise ReachabilityError("source-bound JS parser script is missing: scripts/p22_js_imports.cjs")
        self.script_hash = _sha256(self.script)
        self.timeout = timeout
        node = shutil.which("node")
        parser = Path(__file__).resolve().parents[2] / "node_modules" / "@babel" / "parser"
        if not node or not parser.is_dir():
            raise ReachabilityError("static JS reach requires installed Node and @babel/parser; no fallback lexer is admitted")
        env = dict(os.environ)
        env["P22_BABEL_PARSER_PATH"] = str(parser)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                [node, str(self.script)], cwd=repo, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="strict", bufsize=1, creationflags=creationflags,
            )
        except (OSError, ValueError) as error:
            raise ReachabilityError(f"could not start the admitted JS parser: {error}") from None
        self._lines: queue.Queue[str | None] = queue.Queue(maxsize=1)
        self._reader = threading.Thread(target=self._read_stdout, name="p22-js-parser-output", daemon=True)
        self._reader.start()
        self._next_id = 0
        self._started = time.monotonic()

    def _read_stdout(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def parse(self, path: Path, source: str) -> list[dict[str, Any]]:
        if time.monotonic() - self._started > self.timeout:
            raise ReachabilityError(f"JS graph parse exceeded {self.timeout:.1f}s")
        self._next_id += 1
        request = {"id": self._next_id, "path": _relative(self.repo, path), "source": source}
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            line = self._lines.get(timeout=max(0.05, self.timeout - (time.monotonic() - self._started)))
        except (OSError, queue.Empty, UnicodeError) as error:
            raise ReachabilityError(f"JS parser did not answer within {self.timeout:.1f}s: {error}") from None
        if line is None:
            raise ReachabilityError("JS parser exited before answering a source request")
        try:
            response = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            raise ReachabilityError("JS parser returned malformed JSON") from None
        if response.get("id") != self._next_id:
            raise ReachabilityError("JS parser response id did not match its request")
        if response.get("error"):
            raise ReachabilityError(f"Babel could not parse {_relative(self.repo, path)}: {response['error']}")
        rows = response.get("specifiers")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ReachabilityError("JS parser response omitted its specifier list")
        return rows

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write('{"close":true}\n')
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=1.0)
        if self.process.stdout:
            self.process.stdout.close()

    def __enter__(self) -> "_JSImportParser":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _css_specifiers(source: str) -> list[str]:
    # Strip comments first. A quote-aware scan prevents url(...) in arbitrary
    # declaration strings from being treated as a real dependency.
    cleaned = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    results: list[str] = []
    i = 0
    while i < len(cleaned):
        if cleaned[i] in "'\"":
            quote = cleaned[i]
            i += 1
            while i < len(cleaned):
                if cleaned[i] == "\\":
                    i += 2
                elif cleaned[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        if cleaned[i] == "@" and cleaned[i:i + 7].lower() == "@import":
            i += 7
            while i < len(cleaned) and cleaned[i].isspace():
                i += 1
            if cleaned.startswith("url(", i):
                i += 4
                while i < len(cleaned) and cleaned[i].isspace():
                    i += 1
                quote = cleaned[i] if i < len(cleaned) and cleaned[i] in "'\"" else ""
                if quote:
                    i += 1
                start = i
                while i < len(cleaned) and ((cleaned[i] != quote) if quote else cleaned[i] != ")"):
                    i += 1
                value = cleaned[start:i].strip()
                if value and not value.startswith(("data:", "http:", "https:", "//", "#")):
                    results.append(value)
                continue
            if i < len(cleaned) and cleaned[i] in "'\"":
                quote = cleaned[i]
                i += 1
                start = i
                while i < len(cleaned) and cleaned[i] != quote:
                    i += 2 if cleaned[i] == "\\" else 1
                value = cleaned[start:i]
                if value and not value.startswith(("data:", "http:", "https:", "//", "#")):
                    results.append(value)
                continue
        if cleaned[i:i + 4].lower() == "url(":
            i += 4
            while i < len(cleaned) and cleaned[i].isspace():
                i += 1
            quote = cleaned[i] if i < len(cleaned) and cleaned[i] in "'\"" else ""
            if quote:
                i += 1
            start = i
            while i < len(cleaned) and ((cleaned[i] != quote) if quote else cleaned[i] != ")"):
                i += 2 if cleaned[i] == "\\" else 1
            value = cleaned[start:i].strip()
            if value and not value.startswith(("data:", "http:", "https:", "//", "#")):
                results.append(value)
            continue
        i += 1
    return results


def _alias_target(specifier: str, aliases: dict[str, str]) -> tuple[str | None, bool]:
    matches = [prefix for prefix in aliases if specifier == prefix or specifier.startswith(prefix.rstrip("/") + "/")]
    if not matches:
        return None, False
    prefix = max(matches, key=len)
    base, suffix = aliases[prefix].rstrip("/"), specifier[len(prefix):].lstrip("/")
    return base + ("/" + suffix if suffix else ""), True


def _resolve(repo: Path, importer: Path, specifier: str, aliases: dict[str, str]) -> tuple[Path | None, str | None]:
    if not specifier or specifier.startswith(("data:", "http:", "https:", "//", "#")):
        return None, None
    if "\\" in specifier or "\x00" in specifier:
        return None, "invalid-local-specifier"
    aliased, has_alias = _alias_target(specifier, aliases)
    if has_alias:
        if aliased is None:
            return None, "unmapped-alias"
        base_value = aliased
        if base_value.startswith("/"):
            base_value = base_value.lstrip("/")
            base = repo / base_value
        else:
            base = repo / base_value
    elif specifier.startswith("."):
        base = importer.parent / specifier
    elif specifier.startswith("/"):
        base = repo / specifier.lstrip("/")
    else:
        # Bare imports are external packages; only explicit alias prefixes are
        # considered local by this graph.
        return None, None
    raw = base
    candidates = [raw]
    if not raw.suffix:
        candidates.extend(Path(str(raw) + suffix) for suffix in _RESOLVE_EXTENSIONS)
        candidates.extend(raw / ("index" + suffix) for suffix in _RESOLVE_EXTENSIONS)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(repo):
            return None, "repository-escape"
        if resolved.is_file():
            return resolved, None
    return None, "unresolved-local"


def analyze(repo: str | os.PathLike[str], journeys: dict[str, dict[str, Any]], *, aliases: dict[str, str] | None = None,
            max_files: int = _MAX_FILES, _js_parser: _JSImportParser | None = None) -> dict[str, Any]:
    """Build a hash-bound static import graph from validated passing journeys.

    `journeys` is `{outcome_id: {"status":"PASS", "sourceBindings":
    {"web/src/Entry.jsx":"<sha256>"}, "entries":["web/src/Entry.jsx"]}}`.
    The receipt validation and entry selection happen upstream. Failed outcomes
    contribute no roots; stale PASS roots raise rather than receiving credit.
    `aliases` maps explicit bundler prefixes to repo-relative directories, for
    example `{"@/":"web/src"}`. No Vite config or credentials are read here.
    """
    root = Path(repo).resolve(strict=True)
    validated = _validate_journeys(root, journeys)
    parser_binding = _parser_binding(root)
    if not validated:
        payload = {"journeys": {}, "files": {}, "unresolved": [], "parserBinding": parser_binding}
        return {"schema": SCHEMA, "classification": CLASSIFICATION, **payload, "graphDigest": _digest_payload(payload)}
    aliases = aliases or {}
    if not isinstance(aliases, dict):
        raise ReachabilityError("aliases must be an explicit prefix-to-repo-directory mapping")
    normalized_aliases: dict[str, str] = {}
    for prefix, directory in aliases.items():
        if not isinstance(prefix, str) or not prefix or not isinstance(directory, str):
            raise ReachabilityError("alias entries must be non-empty string prefix/path pairs")
        target = _repo_path(root, directory)
        if not target.is_dir():
            raise ReachabilityError(f"alias target is not a repository directory: {directory!r}")
        normalized_aliases[prefix] = _relative(root, target)

    file_journeys: dict[str, set[str]] = {}
    file_kinds: dict[str, str] = {}
    source_hashes: dict[str, str] = {}
    unresolved: set[tuple[str, str, str]] = set()
    if _js_parser is not None and _js_parser.repo != root:
        raise ReachabilityError("shared JS parser is bound to a different repository root")
    parser_context = nullcontext(_js_parser) if _js_parser is not None else _JSImportParser(root)
    with parser_context as js_parser:
        for identity, journey in validated.items():
            pending = [root / name for name in journey["entries"]]
            visited: set[Path] = set()
            while pending:
                path = pending.pop().resolve(strict=True)
                if path in visited:
                    continue
                if len(visited) >= max_files:
                    raise ReachabilityError(f"journey {identity!r} exceeds graph file limit {max_files}")
                if not path.is_relative_to(root) or not path.is_file():
                    raise ReachabilityError(f"graph source is outside repository or missing: {path}")
                visited.add(path)
                rel = _relative(root, path)
                file_journeys.setdefault(rel, set()).add(identity)
                if path.stat().st_size > _MAX_FILE_BYTES:
                    raise ReachabilityError(f"file exceeds {_MAX_FILE_BYTES} byte graph limit: {rel}")
                digest = _sha256(path)
                source_hashes[rel] = digest
                suffix = path.suffix.lower()
                if suffix in _CODE_EXTENSIONS:
                    file_kinds[rel] = "code"
                elif suffix in _STYLE_EXTENSIONS:
                    file_kinds[rel] = "css"
                else:
                    file_kinds[rel] = "asset"
                if suffix not in _CODE_EXTENSIONS + _STYLE_EXTENSIONS:
                    continue
                if path.stat().st_size > _MAX_TEXT_BYTES:
                    raise ReachabilityError(f"source file exceeds {_MAX_TEXT_BYTES} byte parse limit: {rel}")
                try:
                    source = path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    raise ReachabilityError(f"text source is not UTF-8: {rel}") from None
                if suffix in _CODE_EXTENSIONS:
                    refs = js_parser.parse(path, source)
                    for ref in refs:
                        specifier = ref.get("specifier")
                        if not isinstance(specifier, str):
                            unresolved.add((rel, f"<nonliteral:{ref.get('kind', 'import')}>", "nonliteral-module-specifier"))
                            continue
                        dependency, problem = _resolve(root, path, specifier, normalized_aliases)
                        if problem:
                            unresolved.add((rel, specifier, problem))
                        elif dependency is not None:
                            pending.append(dependency)
                else:
                    for specifier in _css_specifiers(source):
                        dependency, problem = _resolve(root, path, specifier, normalized_aliases)
                        if problem:
                            unresolved.add((rel, specifier, problem))
                        elif dependency is not None:
                            pending.append(dependency)
            # Bindings on the outcome receipt are an integrity check, not extra
            # roots. Recheck all listed files so an unrelated stale bound entry
            # cannot make a cached outcome appear current.
            for name, expected in journey["sourceBindings"].items():
                bound_path = root / name
                if bound_path.stat().st_size > _MAX_FILE_BYTES or _sha256(bound_path) != expected:
                    raise ReachabilityError(f"journey {identity!r} source binding changed while analyzing: {name}")

    files = {
        name: {"sha256": source_hashes[name], "kind": file_kinds[name], "journeyIDs": sorted(file_journeys[name])}
        for name in sorted(file_journeys)
    }
    payload = {
        "journeys": validated,
        "files": files,
        "unresolved": [{"importer": a, "specifier": b, "reason": c} for a, b, c in sorted(unresolved)],
        "parserBinding": parser_binding,
    }
    return {"schema": SCHEMA, "classification": CLASSIFICATION, **payload, "graphDigest": _digest_payload(payload)}


def _digest_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def is_fresh(repo: str | os.PathLike[str], receipt: dict[str, Any], *, aliases: dict[str, str] | None = None,
             _js_parser: _JSImportParser | None = None) -> bool:
    """Rebuild and compare the graph, catching edits and newly resolvable imports."""
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA or receipt.get("classification") != CLASSIFICATION:
        return False
    journeys = receipt.get("journeys")
    if not isinstance(journeys, dict):
        return False
    try:
        current = analyze(repo, journeys, aliases=aliases, _js_parser=_js_parser)
    except (OSError, ValueError, TypeError, KeyError, ReachabilityError):
        return False
    return current.get("graphDigest") == receipt.get("graphDigest") and current.get("files") == receipt.get("files") and current.get("unresolved") == receipt.get("unresolved")
