from __future__ import annotations

import hashlib
import copy
import html
import importlib.util
import json
import math
import ntpath
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .nas_bridge import NasBridge, configured_nas_root
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .creative_tools import CreativeToolRuntime, creative_tool_definitions
from .native_commands import execute_local_command, inspect_local_environment


_WRITE_DIFF_MAX_CHARS = 6_000


def _bounded_line_diff(before: bytes | None, after: bytes, path: str) -> dict[str, Any]:
    """Summarize a text write as line counts plus a bounded unified diff.

    The diff lets people see what an edit changed without opening the file; it
    is capped so a rewrite of a large file cannot flood the model's context.
    """
    import difflib

    after_lines = after.decode("utf-8", errors="replace").splitlines()
    if before is None:
        return {"linesAdded": len(after_lines), "linesRemoved": 0}
    before_lines = before.decode("utf-8", errors="replace").splitlines()
    added = removed = 0
    rendered: list[str] = []
    size = 0
    truncated = False
    for line in difflib.unified_diff(before_lines, after_lines, f"a/{path}", f"b/{path}", n=2, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
        if truncated:
            continue
        if size + len(line) + 1 > _WRITE_DIFF_MAX_CHARS:
            truncated = True
            continue
        rendered.append(line)
        size += len(line) + 1
    return {
        "linesAdded": added,
        "linesRemoved": removed,
        "diff": "\n".join(rendered),
        "diffTruncated": truncated,
    }


TOOL_RECEIPT_SCHEMA = "fluxio.native_tool_receipt.v1"
TOOL_CATALOG_SCHEMA = "fluxio.native_tool_catalog.v1"
TOOL_PROTOCOL_VERSION = "1.1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_relative_path(root: Path, candidate: Path, error: str) -> tuple[Path, str]:
    """Resolve a path and prove containment, tolerating Windows' extended-path spelling.

    The path returned for I/O stays in the OS-resolved form. Extended prefixes
    are removed only from the comparison copy, after resolution, so traversal
    and symlink escapes remain subject to the normal filesystem resolution.
    """
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    if os.name == "nt":
        def comparable(path: Path) -> str:
            value = str(path)
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return ntpath.normcase(ntpath.normpath(value))

        root_value = comparable(resolved_root)
        candidate_value = comparable(resolved_candidate)
        try:
            common = ntpath.commonpath((root_value, candidate_value))
            if ntpath.normcase(common) != root_value:
                raise ValueError(error)
            relative = ntpath.relpath(candidate_value, root_value)
        except ValueError as exc:
            if str(exc) == error:
                raise
            raise ValueError(error) from exc
        return resolved_candidate, relative.replace("\\", "/")

    try:
        relative = resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(error) from exc
    return resolved_candidate, relative.as_posix()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _published_receipt(path: Path, payload: dict[str, Any]) -> bytes:
    """Write, read back through the same handle, then atomically publish.

    Reading the stored bytes before the rename proves what was persisted
    without reopening the published file, which on Windows costs a fresh
    on-access scan (about 10 ms) for every tool call.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    try:
        with open(temporary, "w+b") as handle:
            handle.write(encoded)
            handle.flush()
            handle.seek(0)
            stored = handle.read()
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return stored


def _receipt_arguments(schema: dict[str, Any], value: Any) -> Any:
    """Copy admitted typed arguments with secret-bearing values removed."""
    from .folder_sync import _redact_value
    if schema.get("writeOnly") or schema.get("format") == "password" or schema.get("x-secret"):
        return "[REDACTED]"
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        result = {}
        for key, item in value.items():
            safe = _redact_value({key: item})[key]
            if key.lower() in {"env", "environment"} or safe == "[REDACTED]":
                result[key] = "[REDACTED]"
            else:
                result[key] = _receipt_arguments(properties.get(key, {}), item)
        return result
    if isinstance(value, (list, tuple)):
        return [_receipt_arguments(schema.get("items") or {}, item) for item in value]
    if isinstance(value, str):
        # Redact the whole field when the existing text policy matches. This
        # also removes trailing words in quoted shell/environment assignments.
        if _redact_value(value) != value or re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})", value):
            return "[REDACTED]"
    return value


@dataclass(frozen=True)
class NativeToolSpec:
    name: str
    description: str
    category: str
    input_schema: dict[str, Any]
    aliases: tuple[str, ...] = ()
    risk_level: str = "low"
    requires_approval: bool = False
    core: bool = True
    schema_version: str = TOOL_PROTOCOL_VERSION
    mutability_class: str = "read"
    capabilities: tuple[str, ...] = ()
    parallel_safe: bool = True

    def __post_init__(self):
        """Advertise the existing required-value rule in the public schema."""
        from jsonschema import Draft202012Validator
        schema = copy.deepcopy(self.input_schema)
        properties = schema.get("properties", {})
        constraints = {}
        for name in schema.get("required", []):
            field_schema = properties.get(name, {})
            empty_allowed = self.name == "neyvia.pane.show" and name == "target"
            rejected = [value for value in ([None] if empty_allowed else [None, ""])
                        if Draft202012Validator(field_schema).is_valid(value)]
            if rejected:
                constraints[name] = {"not": {"enum": rejected}}
        if constraints:
            schema.setdefault("allOf", []).append({"properties": constraints})
            object.__setattr__(self, "input_schema", schema)


@dataclass
class NativeToolReceipt:
    tool: str
    ok: bool
    status: str
    duration_ms: int
    result: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    error: str = ""
    failure: dict[str, Any] | None = None
    provider: str = "neyvia-native"
    schema: str = TOOL_RECEIPT_SCHEMA
    receipt_id: str = field(default_factory=lambda: f"tool_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=_utc_now)
    receipt_path: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    argument_snapshot_boundary: str = "Arguments were not admitted; no input values recorded."


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._ignored_depth:
            return
        if self._in_title:
            self.title = f"{self.title} {value}".strip()
        self.parts.append(value)

    def readable_text(self) -> str:
        text = " ".join(self.parts)
        return re.sub(r"\s+", " ", text).strip()

    def readable_blocks(self) -> str:
        """Readable text with one line per block element, so paragraphs,
        headings, list items and navigation stay separate observable units."""
        lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in " ".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)


_BLOCK_TAGS = frozenset({"p", "br", "article", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr", "table",
                         "ul", "ol", "dl", "dt", "dd", "header", "footer", "nav", "aside", "main", "blockquote", "pre",
                         "figcaption", "caption", "form", "hr"})


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._snippet_target: dict[str, str] | None = None
        self._capture = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            href = str(attributes.get("href") or "")
            parsed = urllib.parse.urlparse(href)
            redirect_query = urllib.parse.parse_qs(parsed.query)
            target = redirect_query.get("uddg", [href])[0]
            self._current = {"title": "", "url": urllib.parse.unquote(target), "snippet": ""}
            self._capture = "title"
        elif self.results and "result__snippet" in classes:
            self._snippet_target = self.results[-1]
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None and self._capture == "title":
            if self._current["title"] and self._current["url"]:
                self.results.append(self._current)
            self._current = None
            self._capture = ""
        elif self._capture == "snippet" and tag in {"a", "div", "span"}:
            self._capture = ""
            self._snippet_target = None

    def handle_data(self, data: str) -> None:
        target = self._current if self._capture == "title" else self._snippet_target
        if target is None or not self._capture:
            return
        value = " ".join(data.split())
        if value:
            target[self._capture] = f"{target[self._capture]} {value}".strip()


def _request(url: str, *, headers: dict[str, str] | None = None, timeout: float = 15.0,
             pdf_max_bytes: int | None = None, body: bytes | None = None) -> tuple[bytes, Any]:
    if pdf_max_bytes is not None and not 2 * 1024 * 1024 <= pdf_max_bytes <= 32 * 1024 * 1024:
        raise ValueError("Optional PDF response limit must be between 2 and 32 MiB")
    request_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=body, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        if pdf_max_bytes is None:
            return response.read(2 * 1024 * 1024), response
        declared = response.headers.get("Content-Length")
        pdf_header = "application/pdf" in str(response.headers.get("Content-Type") or "").lower()
        prefix = b"" if pdf_header else response.read(1024)
        pdf = pdf_header or b"%PDF-" in prefix
        limit = pdf_max_bytes if pdf else 2 * 1024 * 1024
        if pdf and int(declared or 0) > limit:
            raise ValueError(f"PDF response declares {declared} bytes; exceeds the selected {limit} byte PDF limit")
        return prefix + response.read(limit - len(prefix)), response


class ReusablePlaywrightRuntime:
    """Keep Chromium warm while isolating every capture in a fresh context."""

    def __init__(self, root: str | Path | None = None, *, transport="playwright", port=None) -> None:
        if transport not in {"playwright", "obscura"}:
            raise ValueError("Choose an explicit browser transport")
        self.transport, self.port = transport, port
        self.root = Path(root or Path.cwd()).resolve()
        self._playwright: Any = None
        self._browser: Any = None
        self._launch_context: Any = None
        self.browser_starts = 0
        self.contexts_created = 0

    def _browser_is_connected(self) -> bool:
        try:
            return bool(self._browser and self._browser.is_connected())
        except Exception:
            return False

    def _ensure_browser(self) -> tuple[Any, bool]:
        reused = self._browser_is_connected()
        if reused:
            return self._browser, True
        self.close()
        from playwright.sync_api import sync_playwright
        from .browser_preflight import build_browser_dependency_preflight

        self._playwright = sync_playwright().start()
        if self.transport == "obscura":
            from .browser_obscura import connect_owned_playwright
            try:
                self._browser, self._launch_context = connect_owned_playwright(
                    self._playwright, self.root / ".agent_control/native-browser",
                    port=self.port, local_control=True)
            except BaseException:
                self.close()
                raise
            self.browser_starts += 1
            return self._browser, False
        preflight = build_browser_dependency_preflight(self.root)
        from .chrome_environment import chrome_executable
        executable = chrome_executable(preflight)
        launch_options: dict[str, Any] = {"headless": True}
        if executable:
            launch_options["executable_path"] = executable
        from .chrome_environment import chrome_environment, fresh_chrome_profile, CHROME_AUTOMATION_ARGS
        profile = fresh_chrome_profile(self.root, "native-worker")
        launch_options.update(env=chrome_environment(profile.parent / (profile.name + "-environment")),
                              args=CHROME_AUTOMATION_ARGS)
        self._launch_context = self._playwright.chromium.launch_persistent_context(str(profile), **launch_options)
        self._browser = self._launch_context.browser
        self.browser_starts += 1
        return self._browser, False

    @contextmanager
    def page(self, *, width: int, height: int):
        # Reconcile a detached transport only before exposing a page. Never
        # repeat anything after yield, where caller actions may have occurred.
        context = None
        for attempt in range(2):
            browser, reused = self._ensure_browser()
            try:
                context = browser.new_context(viewport={"width": width, "height": height})
                self.contexts_created += 1
                page = context.new_page()
                break
            except Exception:
                if context is not None:
                    try: context.close()
                    except Exception: pass
                    context = None
                if attempt or self._browser_is_connected():
                    raise
                self.close()
        try:
            yield page, reused
        finally:
            try:
                context.close()
            except Exception:
                pass

    def snapshot(self, *, reused: bool) -> dict[str, Any]:
        return {
            "kind": "persistent-playwright",
            "engine": self.transport,
            "browserReused": reused,
            "browserStarts": self.browser_starts,
            "contextsCreated": self.contexts_created,
        }

    def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        owned = self._launch_context
        self._launch_context = None
        self._browser = None
        self._playwright = None
        if owned is not None:
            try:
                owned.close()
            except Exception:
                pass
        elif browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


class NativeToolRegistry:
    def __init__(
        self,
        root: str | Path,
        nas_root: str | Path | None = None,
        *,
        browser_runtime: Any | None = None,
        allow_local_nas_root: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.nas_root = configured_nas_root(self.root, nas_root)
        self.browser_runtime = browser_runtime
        self.allow_local_nas_root = allow_local_nas_root
        self._semantic = None
        self.receipt_root = self.root / ".agent_control" / "tool_receipts"
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "terminal.exec": lambda args: execute_local_command(args, default_cwd=self.root),
            "runtime.environment": lambda _args: inspect_local_environment(default_cwd=self.root),
            "runtime.preflight": self._runtime_preflight,
            "runtime.evidence": self._runtime_evidence,
            "runtime.completion": self._runtime_completion,
            "workspace.read": self._workspace_read,
            "workspace.write": self._workspace_write,
            "workspace.search": self._workspace_search,
            "context.search": self._context_search,
            "context.bundle": self._context_bundle,
            "context.compact": self._context_compact,
            "orchestration.compile": self._orchestration_compile,
            "codex.assets.inspect": self._codex_assets_inspect,
            "codex.assets.import": self._codex_assets_import,
            "codex.plugins.list": lambda args: self._codex_plugin_access().inventory(),
            "codex.plugins.search": lambda args: self._codex_plugin_access().search(args["server"], args.get("query", "")),
            "codex.plugins.describe": lambda args: self._codex_plugin_access().describe(args["server"], args["tool"]),
            "codex.plugins.read": lambda args: self._codex_plugin_call(args, approved=False),
            "codex.plugins.call": lambda args: self._codex_plugin_call(args, approved=True),
            "skill.live.read": self._skill_live_read,
            "skill.live.iterate": self._skill_live_iterate,
            "web.search": self._web_search,
            "web.image_search": self._web_image_search,
            "ui.inspiration.search": self._ui_inspiration_search,
            "web.fetch": self._web_fetch,
            "preview.inspect": self._preview_inspect,
            "preview.screenshot": self._preview_screenshot,
            "preview.annotate": self._preview_annotate,
            "preview.taste": self._preview_taste,
            "video.inspect": self._video_inspect,
            "video.digest": self._video_digest,
            "nas.message.send": self._nas_message_send,
            "nas.message.receive": self._nas_message_receive,
            "nas.file.send": self._nas_file_send,
            "nas.transfer": self._nas_transfer,
            "semantic.recovery.create": self._semantic_recovery_create,
            "semantic.recovery.read": self._semantic_recovery_read,
            "semantic.proof.create": self._semantic_proof_create,
            "semantic.proof.verify": self._semantic_proof_verify,
            "semantic.changeset.create": self._semantic_changeset_create,
            "semantic.changeset.verify": self._semantic_changeset_verify,
            "semantic.memory.project": self._semantic_memory_project,
            "semantic.memory.read": self._semantic_memory_read,
            "semantic.memory.find": self._semantic_memory_find,
            "semantic.memory.retrieve": self._semantic_memory_retrieve,
            "semantic.mission.create": self._semantic_mission_create,
            "semantic.application.register": self._semantic_application_register,
            "semantic.application.read": self._semantic_application_read,
            "semantic.autonomy.admit": self._semantic_autonomy_admit,
            "semantic.autonomy.revoke": self._semantic_autonomy_revoke,
            "laya.native.capabilities": self._laya_native_capabilities,
            "laya.native.neyvia_navigation": self._laya_native_neyvia_navigation,
        }
        self._creative = None
        for name, *_ in creative_tool_definitions():
            self._handlers[name] = lambda args, tool=name: self.creative.call(tool, args)
        self._specs = {spec.name: spec for spec in self._build_specs()}
        from .cua_native_procedures import hosted_native_applications
        self.native_applications = hosted_native_applications(self.root).attach(self, NativeToolSpec)
        from .workspace_patches import patch, tool_spec as patch_spec
        from .web_documents import WebDocuments, tool_specs as document_specs
        self.documents = WebDocuments(self.root)
        self._handlers["workspace.patch"] = lambda args: patch(self, args)
        self._handlers.update({"web.read": self.documents.read, "web.passages": self.documents.search,
                               "web.cite": self.documents.cite, "web.dedupe": self.documents.dedupe})
        for spec in [patch_spec(NativeToolSpec), *document_specs(NativeToolSpec)]:
            self._specs[spec.name] = spec
        from .neyvia_workspace_tools import tool_specs, workspace_for
        workspace = workspace_for(self.root)
        for spec in tool_specs(NativeToolSpec, self.root):
            self._specs[spec.name] = spec
            self._handlers[spec.name] = lambda args, name=spec.name: workspace.call(name.removeprefix("neyvia."), args)
        from .proofs_d_native import observe as observe_native, self_check as check_native
        for name, description, handler, mutability in (
            ("neyvia.native.runtime.observe", "Observe this workspace's native goals, devices and resource profile.",
             lambda args: observe_native(self.root), "read"),
            ("neyvia.native.runtime.self-check", "Run native manual contracts using unique disposable workspace state.",
             lambda args: check_native(self.root / ".agent_control/proofs/native-self-check"), "workspace_write"),
        ):
            self._specs[name] = NativeToolSpec(name=name, description=description, category="manuals",
                input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                mutability_class=mutability, parallel_safe=False)
            self._handlers[name] = handler
        from .neyvia_pdf_tools import call_pdf, tool_specs as pdf_specs
        from .workflow_manuals import call_tool as call_workflow, tool_specs as workflow_specs
        for spec in workflow_specs(NativeToolSpec):
            self._specs[spec.name] = spec
            self._handlers[spec.name] = lambda args, name=spec.name: call_workflow(self.root, name.rsplit(".", 1)[1], args)
        for spec in pdf_specs(NativeToolSpec):
            self._specs[spec.name] = spec
            self._handlers[spec.name] = lambda args, name=spec.name: call_pdf(self.root, name.removeprefix("neyvia.pdf."), args)
        from .neyvia_notes_tools import call_notes, tool_specs as notes_specs
        from .neyvia_files_tools import call_files, tool_specs as files_specs
        for spec in [*notes_specs(NativeToolSpec), *files_specs(NativeToolSpec)]:
            self._specs[spec.name] = spec
            call = call_notes if spec.name.startswith("neyvia.notes.") else call_files
            self._handlers[spec.name] = lambda args, name=spec.name, call=call: call(self.root, name.split(".", 2)[2], args)
        from .neyvia_onboarding import call_tool as call_onboarding, tool_specs as onboarding_specs
        from .neyvia_devices import call_devices, tool_specs as device_specs
        for spec in device_specs(NativeToolSpec):
            self._specs[spec.name] = spec
            self._handlers[spec.name] = lambda args, name=spec.name: call_devices(self.root, name, args)
        for spec in onboarding_specs(NativeToolSpec):
            self._specs[spec.name] = spec
            self._handlers[spec.name] = lambda args, name=spec.name: call_onboarding(self.root, name.removeprefix("neyvia.onboarding."), args)
        from .codex_skill_access import CodexSkillAccess
        assets = CodexSkillAccess(workspace_root=self.root)
        self._handlers.update({
            "codex.instructions.list": lambda args: assets.discover(),
            "codex.instructions.read": lambda args: assets.read(args["skillId"], args.get("relativePath", "SKILL.md")),
            "codex.prompts.read": lambda args: assets.read_prompt(args["promptId"]),
        })
        plugin_target = {"server": {"type": "string"}, "tool": {"type": "string"}}
        for name, description, properties, required, mutability in [
            ("codex.instructions.list", "Discover installed Codex/OpenAI skill instructions and reusable prompts for this Native model. Read selected instructions before applying them; plugin tools may require separate connections.", {}, [], "read"),
            ("codex.instructions.read", "Load an enabled installed Codex skill's actual SKILL.md or a relative reference file, with provenance and hash.", {"skillId": {"type": "string"}, "relativePath": {"type": "string"}}, ["skillId"], "read"),
            ("codex.prompts.read", "Load the actual text of a selected installed reusable Codex prompt.", {"promptId": {"type": "string"}}, ["promptId"], "read"),
            ("codex.plugins.list", "List enabled Codex plugin MCP connections available to Native, with exact unsupported host/transport reasons.", {}, [], "read"),
            ("codex.plugins.search", "Connect to one enabled Codex MCP server and discover its real callable tools.", {"server": {"type": "string"}, "query": {"type": "string"}}, ["server"], "read"),
            ("codex.plugins.describe", "Read the actual input schema and approval requirements of a Codex plugin tool.", plugin_target, ["server", "tool"], "read"),
            ("codex.plugins.read", "Execute a read-only Codex plugin MCP tool. Mutating or unknown tools are denied; use codex.plugins.call with granted permissions instead.", {**plugin_target, "arguments": {"type": "object"}}, ["server", "tool"], "read"),
            ("codex.plugins.call", "Execute a Codex plugin MCP tool with the current run's mutation grant and a durable receipt. CL mutations require an explicit workspace file byte postcondition.", {**plugin_target, "arguments": {"type": "object"}, "effect": {"type": "object", "properties": {"path": {"type": "string"}, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, "required": ["path", "sha256"], "additionalProperties": False}}, ["server", "tool"], "external_write"),
        ]:
            self._specs[name] = NativeToolSpec(name=name, description=description, category="plugins",
                mutability_class=mutability, capabilities=("codex.plugins.execute",),
                input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False})

    def _codex_plugin_access(self):
        if not hasattr(self, "_codex_plugins"):
            import atexit
            from .codex_plugin_access import CodexPluginAccess
            self._codex_plugins = CodexPluginAccess(self.root)
            atexit.register(self._codex_plugins.close)
        return self._codex_plugins

    @property
    def semantic(self):
        if self._semantic is None:
            from .semantic_tools import SemanticToolRuntime
            self._semantic = SemanticToolRuntime(self.root)
        return self._semantic

    @property
    def creative(self):
        if self._creative is None:
            self._creative = CreativeToolRuntime(self.root)
        return self._creative

    def _codex_plugin_call(self, args, *, approved):
        result = self._codex_plugin_access().call(args["server"], args["tool"], args.get("arguments") or {}, approved=approved)
        return result

    @staticmethod
    def _build_specs() -> list[NativeToolSpec]:
        specs = [
            NativeToolSpec(
                name="workspace.read",
                description=(
                    "Read one UTF-8 text file inside the active workspace with a strict "
                    "character limit and return path, content, truncation, and SHA-256 evidence. "
                    "For large files pass the returned nextOffset as offset to read the next chunk."
                ),
                category="files",
                aliases=("read file", "open file", "inspect file", "file contents"),
                capabilities=("workspace.read", "file.hash", "evidence.read"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "maxChars": {"type": "integer", "minimum": 1, "maximum": 100000},
                        "offset": {"type": "integer", "minimum": 0},
                        "startLine": {"type": "integer", "minimum": 1},
                        "endLine": {"type": "integer", "minimum": 1},
                        "expectedSha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
                    },
                    "required": ["path"],
                },
            ),
            NativeToolSpec(
                name="workspace.write",
                description=(
                    "Create a UTF-8 text or HTML artifact inside the active workspace and verify its exact bytes by SHA-256 readback. "
                    "Existing files are never overwritten unless expectedSha256 matches their current content."
                ),
                category="files",
                risk_level="medium",
                requires_approval=True,
                mutability_class="file_write",
                capabilities=("workspace.write", "file.hash", "evidence.read"),
                parallel_safe=False,
                aliases=("create file", "write file", "save artifact", "create html", "write artifact"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "content": {"type": "string"},
                        "expectedSha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
                    },
                    "required": ["path", "content"],
                },
            ),
            NativeToolSpec(
                name="workspace.search",
                description="Search repository text with a bounded regular expression and return path, line, and snippet evidence.",
                category="files",
                aliases=("grep", "repo search", "code search", "find text"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "includeGlob": {"type": "string"},
                        "maxResults": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["query"],
                },
            ),
            NativeToolSpec(
                name="context.search",
                description="Retrieve relevant active or archived mission evidence from Neyvia's durable context ledger.",
                category="context",
                capabilities=("context.retrieve", "history.search"),
                aliases=("long context", "search memory", "find prior decision", "session search"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "sessionId": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                        "maxContextTokens": {"type": "integer", "minimum": 1000, "maximum": 2000000},
                    },
                    "required": ["sessionId", "query"],
                },
            ),
            NativeToolSpec(
                name="context.bundle",
                description="Build a bounded, provenance-bearing model context from pinned facts, relevant history, and the recent tail.",
                category="context",
                capabilities=("context.retrieve", "context.assemble", "prompt.cache_key"),
                aliases=("build context", "context pack", "retrieve context", "infinite context"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "sessionId": {"type": "string"},
                        "query": {"type": "string"},
                        "tokenBudget": {"type": "integer", "minimum": 500, "maximum": 1000000},
                        "maxContextTokens": {"type": "integer", "minimum": 1000, "maximum": 2000000},
                    },
                    "required": ["sessionId"],
                },
            ),
            NativeToolSpec(
                name="context.compact",
                description="Archive older active context without deleting it, protect recent and pinned evidence, and write a compaction receipt.",
                category="context",
                mutability_class="artifact_write",
                capabilities=("context.compact", "context.archive", "receipt.write"),
                parallel_safe=False,
                aliases=("compact context", "roll over context", "context checkpoint"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "sessionId": {"type": "string"},
                        "focus": {"type": "string"},
                        "targetRatio": {"type": "number", "minimum": 0.05, "maximum": 0.8},
                        "maxContextTokens": {"type": "integer", "minimum": 1000, "maximum": 2000000},
                    },
                    "required": ["sessionId"],
                },
            ),
            NativeToolSpec(
                name="orchestration.compile",
                description="Compile a compact NEYVIA/1 program into a validated dependency graph with runtime, permission, budget, and proof contracts.",
                category="orchestration",
                mutability_class="artifact_write",
                capabilities=("plan.compile", "dag.validate", "policy.compile", "artifact.write"),
                aliases=("compile plan", "neyvia language", "orchestration ir", "mission program"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "outputPath": {"type": "string", "description": "Optional screenshot path inside the active workspace. Omit to use the managed artifact path."},
                    },
                    "required": ["source"],
                },
            ),
            NativeToolSpec(
                name="codex.assets.inspect",
                description="Inventory Codex skills, plugin manifests, enabled-state metadata, MCP names, and safe configuration without reading credentials or private session content.",
                category="import",
                capabilities=("codex.skills.read", "codex.plugins.read", "config.redact"),
                aliases=("inspect codex", "codex skills", "codex plugins", "import audit"),
                input_schema={
                    "type": "object",
                    "properties": {"codexHome": {"type": "string"}},
                },
            ),
            NativeToolSpec(
                name="codex.assets.import",
                description="Snapshot safe personal Codex skills and capability metadata into Neyvia with secret exclusion and review-required activation.",
                category="import",
                mutability_class="artifact_write",
                capabilities=("codex.skills.import", "codex.plugins.link", "config.redact", "artifact.write"),
                parallel_safe=False,
                aliases=("import codex", "sync codex skills", "import plugins", "codex migration"),
                input_schema={
                    "type": "object",
                    "properties": {"codexHome": {"type": "string"}},
                },
            ),
            NativeToolSpec(
                name="skill.live.read",
                description="Read and validate the real SKILL.md currently bound to an Agent session, returning its content and SHA-256 for conflict-safe iteration.",
                category="skills",
                capabilities=("codex.skills.read", "skill.validate", "session.skill.bind"),
                aliases=("read live skill", "reload skill", "inspect skill version"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "skillId": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            ),
            NativeToolSpec(
                name="skill.live.iterate",
                description="Validate and atomically revise a live session SKILL.md with optimistic conflict detection, an external backup, and durable version receipts.",
                category="skills",
                risk_level="medium",
                requires_approval=True,
                mutability_class="file_write",
                capabilities=("codex.skills.write", "skill.validate", "skill.version", "receipt.write"),
                parallel_safe=False,
                aliases=("iterate skill", "improve live skill", "revise skill in session"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "skillId": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "expectedSha256": {"type": "string"},
                        "sessionId": {"type": "string"},
                        "request": {"type": "string"},
                    },
                    "required": ["path", "content", "sessionId"],
                },
            ),
            NativeToolSpec(
                name="web.search",
                description="Discover current sources with no key: paced DuckDuckGo HTML for the web, OpenAlex/arXiv for scholarly work, GitHub for code, Wikipedia for encyclopedia; optional SearXNG or Brave key. Reports the provider and every transport attempt.",
                category="web",
                aliases=("internet search", "search web", "online research"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        "vertical": {"type": "string", "enum": ["web", "scholarly", "code", "encyclopedia"]},
                    },
                    "required": ["query"],
                },
            ),
            NativeToolSpec(
                name="web.image_search",
                description="Search for visual references with SearXNG image search or DDGS and return thumbnails, source pages, dimensions, and provider proof.",
                category="web",
                capabilities=("search.images", "visual.reference"),
                aliases=("image search", "find images", "visual search", "search screenshots"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                        "region": {"type": "string"},
                        "safeSearch": {"type": "string", "enum": ["on", "moderate", "off"]},
                        "timeLimit": {"type": "string", "enum": ["day", "week", "month", "year", ""]},
                        "size": {"type": "string"},
                        "color": {"type": "string"},
                        "typeImage": {"type": "string"},
                        "layout": {"type": "string"},
                        "license": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            NativeToolSpec(
                name="ui.inspiration.search",
                description="Find interface inspiration as a visual result board, enriched for product surface, platform, style, color, and layout instead of returning generic text links.",
                category="design",
                capabilities=("search.images", "ui.reference", "visual.board"),
                aliases=("ui inspiration", "design inspiration", "interface references", "find dashboard examples", "ux screenshots"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "surface": {"type": "string"},
                        "platform": {"type": "string"},
                        "style": {"type": "string"},
                        "color": {"type": "string"},
                        "layout": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 24},
                    },
                    "required": ["query"],
                },
            ),
            NativeToolSpec(
                name="web.fetch",
                description="Fetch and cache an immutable web document; returns a handle, hashes and continuation. Reuses a recent cached response unless refresh is true.",
                category="web",
                mutability_class="artifact_write",
                aliases=("open url", "read webpage", "extract page"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "maxChars": {"type": "integer", "minimum": 200, "maximum": 100000},
                        "refresh": {"type": "boolean"},
                        "maxAgeSeconds": {"type": "integer", "minimum": 0, "maximum": 86400},
                    },
                    "required": ["url"],
                },
            ),
            NativeToolSpec(
                name="preview.inspect",
                description="Inspect or search fetched preview text, or view response bytes as hexadecimal with mode=bytes. Returns bounded results and content identity; does not execute page JavaScript.",
                category="preview",
                capabilities=("browser.navigate", "page.inspect"),
                aliases=("preview", "open preview", "check page", "smoke page", "browser_preview"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "query": {"type": "string", "maxLength": 500},
                        "mode": {"type": "string", "enum": ["text", "bytes"]},
                        "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["url"],
                },
            ),
            NativeToolSpec(
                name="preview.screenshot",
                description="Capture a real PNG from a URL with Playwright or Chromium and return dimensions, SHA-256, and engine proof.",
                category="preview",
                mutability_class="artifact_write",
                capabilities=("browser.navigate", "image.capture", "artifact.write"),
                aliases=("screenshot", "capture page", "visual proof", "browser capture", "browser_screenshot"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "outputPath": {"type": "string"},
                        "fullPage": {"type": "boolean"},
                        "width": {"type": "integer", "minimum": 320, "maximum": 3840},
                        "height": {"type": "integer", "minimum": 240, "maximum": 2160},
                        "waitFor": {"type": "string"},
                        "delayMs": {"type": "integer", "minimum": 0, "maximum": 10000},
                        "waitUntil": {"type": "string", "enum": ["domcontentloaded", "load", "networkidle"]},
                    },
                    "required": ["url"],
                },
            ),
            NativeToolSpec(
                name="preview.annotate",
                description="Capture a preview, draw an operator-selected rectangle and comment, create a cropped region, and write a W3C-shaped annotation receipt with hashes.",
                category="preview",
                mutability_class="artifact_write",
                capabilities=("browser.navigate", "image.capture", "image.region", "annotation.write", "artifact.write"),
                parallel_safe=False,
                aliases=("annotate preview", "select ui region", "comment on screenshot", "capture selected region", "ui annotation"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "rectangle": {"type": "object"},
                        "comment": {"type": "string"},
                        "viewport": {"type": "object"},
                        "outputDir": {"type": "string"},
                        "delayMs": {"type": "integer", "minimum": 0, "maximum": 10000},
                    },
                    "required": ["url", "rectangle"],
                },
            ),
            NativeToolSpec(
                name="preview.taste",
                description=(
                    "See and measure your own rendered UI before calling visual work done. Renders the page at "
                    "desktop and phone widths, returns screenshots to inspect, and reports colliding text, overflow, "
                    "contrast, typeface and colour discipline, tap targets, competing primary actions and box clutter "
                    "with evidence and fixes. Optional journey: Laya exercises the controls the goal depends on and "
                    "reports what it actually tested. Use this tool for a Laya browser journey: provide the page URL, goal, "
                    "and journey actions with expected outcomes. Measurements inform judgment; they never certify beauty."
                ),
                category="preview",
                mutability_class="artifact_write",
                capabilities=("browser.navigate", "image.capture", "artifact.write", "design.measure"),
                parallel_safe=False,
                aliases=("taste", "design review", "ui review", "visual quality", "critique ui", "check design", "review page", "test preview",
                         "Laya browser journey", "browser click test", "test app controls", "browser interaction verification"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "goal": {"type": "string", "maxLength": 600},
                        "viewports": {"type": "array", "items": {"type": "string", "enum": ["desktop", "phone"]}},
                        "colorScheme": {"type": "string", "enum": ["dark", "light"]},
                        "waitFor": {"type": "string"},
                        "delayMs": {"type": "integer", "minimum": 0, "maximum": 10000},
                        "includeImageData": {"type": "boolean", "description": "Inline capped screenshots for the installed desktop Preview, which has no HTTP artifact route."},
                        "journey": {
                            "type": "object",
                            "description": "Controls to exercise through Laya: actions [{kind: click|fill|select|press, label, value?, expect?}], expect [{kind: selector_text|text_present|selector_exists|url_contains, ...}].",
                        },
                        "outputDir": {"type": "string", "description": "Optional report directory inside the active workspace. Omit to use the managed artifact directory."},
                    },
                    "required": ["url"],
                },
            ),
            NativeToolSpec(
                name="video.inspect",
                description="Inspect a local video with FFprobe and return verified duration, streams, codecs, dimensions, frame rate, audio presence, and SHA-256.",
                category="video",
                capabilities=("video.metadata", "media.probe"),
                aliases=("inspect video", "video metadata", "probe video", "ffprobe"),
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            NativeToolSpec(
                name="video.digest",
                description="Convert a video into model-readable timestamped frames, scene-change frames, a storyboard, audio, optional local Whisper transcript, and a JSON manifest.",
                category="video",
                mutability_class="artifact_write",
                capabilities=("video.frames", "video.scenes", "audio.extract", "artifact.write"),
                parallel_safe=False,
                aliases=("analyze video", "video storyboard", "video keyframes", "decode video", "video evidence"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "outputDir": {"type": "string"},
                        "maxFrames": {"type": "integer", "minimum": 1, "maximum": 36},
                        "maxSceneFrames": {"type": "integer", "minimum": 0, "maximum": 24},
                        "sceneThreshold": {"type": "number", "minimum": 0.05, "maximum": 0.95},
                        "sceneScanSeconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                        "extractAudio": {"type": "boolean"},
                        "transcribe": {"type": "string", "enum": ["auto", "none", "local"]},
                        "whisperModel": {"type": "string"},
                        "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 7200},
                    },
                    "required": ["path"],
                },
            ),
            NativeToolSpec(
                name="nas.message.send",
                description="Send an atomic NAS mailbox message with parallel, deduplicated, resumable attachments.",
                category="messaging",
                mutability_class="external_write",
                capabilities=("message.send", "file.transfer", "checksum.verify"),
                parallel_safe=False,
                aliases=("send to nas", "nas message", "upload attachments"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "recipient": {"type": "string"},
                        "message": {"type": "string"},
                        "attachments": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["recipient", "message"],
                },
            ),
            NativeToolSpec(
                name="nas.message.receive",
                description="Receive NAS mailbox messages and materialize verified attachments into a local output directory.",
                category="messaging",
                mutability_class="artifact_write",
                capabilities=("message.receive", "file.materialize", "checksum.verify"),
                parallel_safe=False,
                aliases=("receive from nas", "nas inbox", "download attachments"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "recipient": {"type": "string"},
                        "outputDir": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "acknowledge": {"type": "boolean"},
                    },
                    "required": ["recipient", "outputDir"],
                },
            ),
            NativeToolSpec(
                name="nas.file.send",
                description="Transfer one file to the NAS content-addressed store with resume, deduplication, and checksum proof.",
                category="files",
                mutability_class="external_write",
                capabilities=("file.transfer", "transfer.resume", "transfer.deduplicate", "checksum.verify"),
                parallel_safe=False,
                aliases=("content addressed file", "deduplicated file blob"),
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            NativeToolSpec(
                name="nas.transfer",
                description="Copy one file, a filtered folder, or a multi-entry manifest to the NAS in one blocking call with strict route validation, resume-safe copying, transferred-file verification, and one receipt.",
                category="files",
                mutability_class="external_write",
                capabilities=("file.transfer", "directory.transfer", "batch.transfer", "transfer.resume", "checksum.verify", "receipt.write"),
                parallel_safe=False,
                aliases=("transfer to nas", "copy folder to nas", "upload to nas", "nas fast transfer", "send files to nas"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "manifest": {"type": "string"},
                        "destination": {"type": "string"},
                        "destinationRoot": {"type": "string"},
                        "includeAll": {"type": "boolean"},
                        "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 86400},
                    },
                },
            ),
        ]
        semantic = [
            NativeToolSpec(name="semantic.recovery.create", description="Persist a recovery object with confirmed steps, uncertain effects, authority, and recovery paths.", category="semantic", mutability_class="artifact_write", capabilities=("recovery.write",), input_schema={"type":"object","properties":{"failedOperation":{"type":"object"},"operationId":{"type":"string"},"recoveryId":{"type":"string"},"confirmedSteps":{"type":"array"},"uncertainEffects":{"type":"array"},"retrySafety":{"type":"string"},"availableRecoveryPaths":{"type":"array"},"requiredAuthority":{"type":"array"}},"required":["failedOperation"]}),
            NativeToolSpec(name="semantic.recovery.read", description="Read one durable recovery object and its repair boundary.", category="semantic", capabilities=("recovery.read",), input_schema={"type":"object","properties":{"recoveryId":{"type":"string"}},"required":["recoveryId"]}),
            NativeToolSpec(name="semantic.proof.create", description="Persist a proof capsule describing a claim, real journey, artifacts, hashes, and reproduction.", category="semantic", mutability_class="artifact_write", capabilities=("proof.write",), input_schema={"type":"object","properties":{},"required":["claim","build","environment","startingState","journey","actions","artifacts","result","reproduction"]}),
            NativeToolSpec(name="semantic.proof.verify", description="Independently hash proof artifacts, evaluate the claim, and save the verified capsule; caller verified flags are ignored.", category="semantic", mutability_class="artifact_write", capabilities=("proof.verify",), input_schema={"type":"object","properties":{"proofId":{"type":"string"}},"required":["proofId"]}),
            NativeToolSpec(name="semantic.changeset.create", description="Persist a coherent Change Set with source, generated artifacts, compatibility, proof, and rollback boundary.", category="semantic", mutability_class="artifact_write", capabilities=("changeset.write",), input_schema={"type":"object","properties":{"intended_behavior":{"type":"string"},"source_modifications":{"type":"array"},"generated_artifacts":{"type":"array"},"rollback_boundary":{"type":"object"}},"required":["intended_behavior","source_modifications","rollback_boundary"]}),
            NativeToolSpec(name="semantic.changeset.verify", description="Verify generated Change Set artifact bytes and rollback declaration.", category="semantic", capabilities=("changeset.verify",), input_schema={"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}),
            NativeToolSpec(name="semantic.memory.project", description="Project bounded faithful working memory with omitted-record retrieval paths.", category="semantic", capabilities=("memory.project",), input_schema={"type":"object","properties":{"sessionId":{"type":"string"},"query":{"type":"string"},"tokenBudget":{"type":"integer"}},"required":["sessionId"]}),
            NativeToolSpec(name="semantic.memory.read", description="Read durable working memory state and integrity hash.", category="semantic", capabilities=("memory.read",), input_schema={"type":"object","properties":{"sessionId":{"type":"string"}},"required":["sessionId"]}),
            NativeToolSpec(name="semantic.memory.find", description="Find ranked working-memory record IDs without loading the complete state; use retrieve for exact detail.", category="semantic", capabilities=("memory.find",), input_schema={"type":"object","properties":{"sessionId":{"type":"string"},"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20},"offset":{"type":"integer","minimum":0}},"required":["sessionId","query"]}),
            NativeToolSpec(name="semantic.memory.retrieve", description="Recover one exact working-memory record by ID with a strict response limit and its stored hash.", category="semantic", capabilities=("memory.retrieve",), input_schema={"type":"object","properties":{"sessionId":{"type":"string"},"recordId":{"type":"string"},"maxChars":{"type":"integer","minimum":512,"maximum":20000}},"required":["sessionId","recordId"]}),
            NativeToolSpec(name="semantic.mission.create", description="Persist a durable mission agreement from an explicit desired outcome and acceptance gates.", category="semantic", mutability_class="artifact_write", capabilities=("mission.write",), input_schema={"type":"object","properties":{"missionId":{"type":"string"},"desiredOutcome":{"type":"string"},"acceptanceGates":{"type":"array"},"conversationId":{"type":"string"},"turnId":{"type":"string"}},"required":["missionId","desiredOutcome"]}),
            NativeToolSpec(name="semantic.application.register", description="Register a Living Application source/build/health/rollback record.", category="semantic", mutability_class="artifact_write", capabilities=("application.write",), input_schema={"type":"object","properties":{"applicationId":{"type":"string"},"source":{"type":"object"},"buildRecipe":{"type":"object"},"health":{"type":"object"},"rollback":{"type":"object"}},"required":["applicationId"]}),
            NativeToolSpec(name="semantic.application.read", description="Read a Living Application registry record.", category="semantic", capabilities=("application.read",), input_schema={"type":"object","properties":{"applicationId":{"type":"string"}},"required":["applicationId"]}),
            NativeToolSpec(name="semantic.autonomy.admit", description="Authorize one action against an existing trusted persisted autonomy policy, enforcing revocation, permitted actions, evidence threshold, and budget.", category="semantic", mutability_class="artifact_write", capabilities=("autonomy.authorize",), input_schema={"type":"object","properties":{"policyId":{"type":"string"},"action":{"type":"string"},"cost":{"type":"number"},"evidenceCount":{"type":"integer"}},"required":["policyId","action"]}),
            NativeToolSpec(name="semantic.autonomy.revoke", description="Revoke a supervised autonomy policy and persist the reason.", category="semantic", mutability_class="artifact_write", capabilities=("autonomy.revoke",), input_schema={"type":"object","properties":{"policyId":{"type":"string"},"reason":{"type":"string"}},"required":["policyId"]}),
            NativeToolSpec(name="laya.native.capabilities", description="Check the live Laya background computer-use provider and its exact supported named workflows. Preflight only; no UI action is proved.", category="computer_use", aliases=("Laya computer use", "native computer capabilities"), capabilities=("laya.native.capabilities",), input_schema={"type":"object","properties":{}}),
            NativeToolSpec(name="laya.native.neyvia_navigation", description="Use Laya's named background UIA workflow to navigate the installed Neyvia desktop; require its independent postcondition receipt. No generic window control or fallback.", category="computer_use", aliases=("Laya Neyvia desktop navigation", "native computer use"), risk_level="medium", requires_approval=True, mutability_class="external_action", parallel_safe=False, capabilities=("laya.native.neyvia_navigation",), input_schema={"type":"object","properties":{}}),
        ]
        creative = [NativeToolSpec(name=name, description=description, category="creative", mutability_class=mutation,
                    capabilities=(name,), input_schema={"type": "object", "properties": properties, "required": required})
                    for name, description, mutation, properties, required in creative_tool_definitions()]
        diagnostics = [
            NativeToolSpec(name="terminal.exec", description="Execute a local command in a selected shell with bounded output and timeout. This can change local files or state and requires approval.", category="runtime", aliases=("terminal", "run command", "execute command", "powershell", "python command", "local command execution"), risk_level="medium", requires_approval=True, mutability_class="external_action", capabilities=("terminal.exec",), parallel_safe=False, input_schema={"type":"object","properties":{"command":{"type":"string","minLength":1},"shell":{"type":"string","enum":["auto","powershell","python","bash","cmd"]},"cwd":{"type":"string"},"timeoutMs":{"type":"integer","minimum":1,"maximum":120000},"maxOutputChars":{"type":"integer","minimum":128,"maximum":50000}},"required":["command"]}),
            NativeToolSpec(name="runtime.environment", description="Inspect the actual operating system, workspace cwd, Python interpreter and available shell, Node and Git executables without returning environment variable values.", category="runtime", aliases=("environment", "runtime discovery", "available shells", "python", "powershell", "terminal commands", "installed commands"), capabilities=("runtime.environment",), input_schema={"type":"object","properties":{}}),
            NativeToolSpec(name="runtime.completion", description="Read the saved operational checkpoint and compare its evidence files with current hashes. Saved checks and journey claims are reported, not independently endorsed.", category="runtime", input_schema={"type":"object","properties":{}}),
            NativeToolSpec(name="runtime.preflight", description="Check named native tool configuration and preserve a timestamped capability observation. Does not claim runtime, model, browser connection or authentication success.", category="runtime", input_schema={"type":"object","properties":{"tools":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":30}},"required":["tools"]}),
            NativeToolSpec(name="runtime.evidence", description="Summarize bounded real native tool receipts, latency and failures. Tool success is not user-outcome proof; missing token/cost data remains unknown.", category="runtime", input_schema={"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":500}}}),
        ]
        return specs + semantic + creative + diagnostics

    def _availability(self, spec: NativeToolSpec) -> tuple[bool, str]:
        from .local_network_policy import LocalOnlyError
        try:
            return self._configured_availability(spec)
        except LocalOnlyError as exc:
            return False, str(exc)

    def _configured_availability(self, spec: NativeToolSpec) -> tuple[bool, str]:
        if spec.name.startswith("neyvia.pdf.") and spec.name != "neyvia.pdf.state":
            from .pdf_document import reader_python
            try:
                return True, "PDF reader: " + reader_python()
            except RuntimeError as exc:
                return False, str(exc)
        if spec.name.startswith("codex.assets") or spec.name.startswith("skill.live"):
            codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
            return (
                (True, f"Codex home detected: {codex_home}")
                if codex_home.exists()
                else (False, f"Codex home not found: {codex_home}")
            )
        if spec.name.startswith("nas."):
            if spec.name == "nas.transfer":
                from .nas_transfer import NasTransferError, discover_nas_projects_root
                try:
                    discovered, route = discover_nas_projects_root(
                        self.nas_root,
                        allow_local_root=self.allow_local_nas_root,
                    )
                except NasTransferError as exc:
                    return False, str(exc)
                if discovered is not None:
                    return True, f"NAS transfer root: {discovered} ({route})"
                return False, "Set a valid UNC or mapped-network NAS projects root."
            if self.nas_root is None:
                return False, "Set NEYVIA_NAS_ROOT or mount the configured NAS project root."
            return True, f"NAS bridge root: {self.nas_root}"
        if spec.name in {"web.image_search", "ui.inspiration.search"}:
            searxng = str(os.environ.get("NEYVIA_SEARXNG_URL") or os.environ.get("FLUXIO_SEARXNG_URL") or "").strip()
            if searxng:
                return True, "SearXNG visual search is configured."
            try:
                ddgs_available = importlib.util.find_spec("ddgs") is not None
            except ModuleNotFoundError:
                ddgs_available = False
            if ddgs_available:
                return True, "DDGS visual metasearch is available."
            return False, "Install the project dependencies with `uv sync` to enable DDGS visual search, or configure NEYVIA_SEARXNG_URL."
        if spec.name == "preview.annotate":
            try:
                playwright_available = importlib.util.find_spec("playwright.sync_api") is not None
            except ModuleNotFoundError:
                playwright_available = False
            if playwright_available:
                return True, "Playwright is available for annotated capture and region proof."
            return False, "Playwright is required for annotated preview capture."
        if spec.name == "preview.screenshot":
            try:
                playwright_available = importlib.util.find_spec("playwright.sync_api") is not None
            except ModuleNotFoundError:
                playwright_available = False
            if playwright_available:
                return True, "Playwright package is available; the browser executable is verified at call time."
            for command in ("chromium", "chromium-browser", "google-chrome", "msedge", "chrome"):
                if shutil.which(command):
                    return True, f"{command} is available; launch is verified at call time."
            for candidate in (
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            ):
                if candidate.exists():
                    return True, f"{candidate.name} is available; launch is verified at call time."
            return False, "No Playwright package or Chromium-family executable was detected."
        if spec.name.startswith("video."):
            from .video_tools import VideoEvidenceBuilder
            return VideoEvidenceBuilder(self.root).availability()
        return True, "Ready"

    def list_tools(
        self,
        *,
        include_unavailable: bool = True,
        include_schemas: bool = False,
        prefix: str = "",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for spec in self._specs.values():
            if prefix and not spec.name.startswith(prefix):
                continue
            available, detail = self._availability(spec)
            if not available and not include_unavailable:
                continue
            spec_payload = asdict(spec)
            spec_payload.pop("input_schema", None)
            row = {
                **spec_payload,
                "available": available,
                "availabilityDetail": detail,
            }
            if include_schemas:
                row["inputSchema"] = spec.input_schema
            from .proofs_d_native import check_catalog
            check_catalog(row, spec, include_schemas)
            rows.append(row)
        return rows

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        terms = {term for term in re.findall(r"[a-z0-9]+", str(query).lower()) if len(term) > 1}
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in self.list_tools(include_unavailable=True):
            haystack = " ".join(
                [row["name"], row["description"], row["category"], *row.get("aliases", [])]
            ).lower()
            score = sum(4 if term in row["name"] else 1 for term in terms if term in haystack)
            if not terms or score:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        return [row for _, row in scored[: max(1, min(int(limit), 20))]]

    def describe(self, name: str) -> dict[str, Any]:
        spec = self._specs.get(str(name or "").strip())
        if spec is None:
            raise KeyError(f"Unknown Neyvia native tool: {name}")
        available, detail = self._availability(spec)
        spec_payload = asdict(spec)
        spec_payload.pop("input_schema", None)
        row = {**spec_payload, "inputSchema": spec.input_schema, "available": available, "availabilityDetail": detail}
        from .proofs_d_native import check_catalog
        check_catalog(row, spec, True)
        return row

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        from .runtime_diagnostics import failure_record
        tool_name = str(name or "").strip()
        spec = self._specs.get(tool_name)
        if spec is None or tool_name not in self._handlers:
            raise KeyError(f"Unknown Neyvia native tool: {name}")
        started = time.perf_counter()
        receipt = NativeToolReceipt(tool=tool_name, ok=False, status="failed", duration_ms=0)
        phase = "availability"
        proof_ids = []
        try:
            available, detail = self._availability(spec)
            if not available:
                raise RuntimeError(detail)
            phase = "validation"
            payload = self.prepare_arguments(tool_name, arguments)
            # Reject malformed Unicode before effects or receipt snapshots.
            # Otherwise an unpaired surrogate can make the failure receipt's
            # own UTF-8 digest/write fail after the handler correctly refuses.
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            receipt.arguments = _receipt_arguments(spec.input_schema, payload)
            receipt.argument_snapshot_boundary = (
                "Admitted normalized arguments; schema secret/password/writeOnly fields, "
                "secret-shaped fields/text and environment values are redacted. "
                "The receipt digest binds the stored snapshot, not removed secret values."
            )
            from .proof_contracts import before_action, after_action
            phase = "contract_precondition"
            proof_rows = before_action(tool_name, payload)
            phase = "execution"
            result = self._handlers[tool_name](payload)
            phase = "contract_postcondition"
            proof_ids = after_action(proof_rows, result)
            if not isinstance(result, dict):
                raise ValueError("Native tool returned a non-object result")
            receipt.ok = result.get("ok") is not False and str(result.get("status") or "").lower() not in {
                "failed", "error", "blocked", "uncertain", "action_uncertain", "approval_required",
            }
            receipt.status = "completed" if receipt.ok else str(result.get("status") or "failed")
            if not receipt.ok and receipt.status != "approval_required":
                receipt.error = str(result.get("error") or result.get("message") or "Tool reported failure")
                receipt.failure = failure_record(None, tool=tool_name, phase=phase, mutability=spec.mutability_class)
                receipt.failure["message"] = receipt.error
            receipt.result = result
            receipt.artifacts = [str(item) for item in result.get("artifacts", []) if str(item).strip()]
        except Exception as exc:
            receipt.error = str(exc)
            receipt.failure = failure_record(exc, tool=tool_name, phase=phase, mutability=spec.mutability_class)
        receipt.duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        private_cl = tool_name in {'neyvia.cl', 'neyvia.cl.describe'} and (
            'memory' in str(arguments or {}) or '<neyvia-memory>' in str(receipt.result))
        if private_cl or tool_name.startswith(("neyvia.remote.", "neyvia.memory.")) or (tool_name.startswith("neyvia.manual.") and (arguments or {}).get("id") == "remote"):
            # T19 is a live view. Generic tool receipts must not silently turn
            # its projections into recordings, including nested manual calls.
            return {**asdict(receipt), "recording": False}
        path = self.receipt_root / f"{receipt.receipt_id}_{_slug(tool_name)}.json"
        receipt.receipt_path = str(path)
        payload = asdict(receipt)
        payload["proofs"] = {"checked": proof_ids if receipt.ok else [], "phase": phase}
        if receipt.status == "approval_required":
            payload["reviewRequired"] = True
        payload["receiptHash"] = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        stored = _published_receipt(path, payload)
        from .proofs_d_native import check_tool_receipt
        check_tool_receipt(payload, path, stored)
        return payload

    def _runtime_preflight(self, args):
        names = args.get("tools")
        if not isinstance(names, list) or not 1 <= len(names) <= 30 or any(not isinstance(name, str) for name in names):
            raise ValueError("Choose 1 to 30 native tool names")
        rows = []
        for name in dict.fromkeys(names):
            try:
                description = self.describe(name)
                rows.append({"tool": name, "configurationAvailable": description["available"],
                             "detail": description["availabilityDetail"], "runtimeVerified": False,
                             "mutability": description["mutability_class"]})
            except KeyError:
                rows.append({"tool": name, "configurationAvailable": False, "runtimeVerified": False, "detail": "Unknown native tool"})
        observed = time.time()
        value = {"schema": "neyvia.runtime_preflight.v1", "observedAt": observed, "expiresAt": observed + 60,
                 "tools": rows, "configurationReady": all(row["configurationAvailable"] for row in rows),
                 "executionReady": False, "remainingChecks": ["actual runtime operation", "applicable authority", "selected model route"],
                 "externalBrowserConnection": "not_observed"}
        path = self.root / ".agent_control" / "runtime_preflight" / "latest.json"
        _atomic_json(path, value)
        return value

    def _runtime_completion(self, args):
        from .runtime_diagnostics import completion_evidence
        return completion_evidence(self.root)

    def _runtime_evidence(self, args):
        from .runtime_diagnostics import summarize_receipts
        return summarize_receipts(self.root, limit=args.get("limit", 200))

    def prepare_arguments(self, name, arguments):
        from .native_arguments import normalize
        spec = self._specs[name]
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        payload = normalize(spec.input_schema, dict(arguments) if arguments is not None else {})
        self._validate_arguments(spec, payload)
        return payload

    def _validate_arguments(self, spec: NativeToolSpec, payload: dict[str, Any]) -> None:
        required = list(spec.input_schema.get("required") or [])
        missing = [field for field in required if payload.get(field) is None or (payload.get(field) == ""
                   and not (spec.name == "neyvia.pane.show" and field == "target"))]
        if missing:
            raise ValueError(f"Missing required tool argument(s): {', '.join(missing)}")
        self._validate_value("$", payload, spec.input_schema)

    def _validate_value(self, field_name: str, value: Any, schema: dict[str, Any]) -> None:
        from jsonschema import Draft202012Validator
        # Use the same complete JSON Schema vocabulary as grounded contracts.
        # Never echo the rejected value: it may contain private user text.
        error = next(Draft202012Validator(schema).iter_errors(value), None)
        if error is not None:
            location = ".".join(map(str, error.absolute_path))
            raise ValueError(f"Tool argument '{field_name}{'.' + location if location else ''}' violates {error.validator}.")
        def finite(item, depth=0):
            if depth > 32:
                raise ValueError("Tool arguments exceed the supported nesting depth")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError(f"Tool argument '{field_name}' must be finite.")
            if isinstance(item, dict):
                for child in item.values():
                    finite(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    finite(child, depth + 1)
        finite(value)

    def snapshot(self) -> dict[str, Any]:
        tools = self.list_tools(include_unavailable=True)
        return {
            "schema": TOOL_CATALOG_SCHEMA,
            "runtimeId": "neyvia-native-tools",
            "label": "Neyvia Native Tools",
            "ready": sum(1 for item in tools if item["available"]),
            "total": len(tools),
            "tools": tools,
            "protocolVersion": TOOL_PROTOCOL_VERSION,
            "discovery": {
                "search": "tool.search",
                "describe": "tool.describe",
                "call": "tool.call",
                "flow": ["search", "describe", "validate", "policy", "call", "receipt"],
                "schemasDeferred": True,
            },
        }

    def _workspace_search(self, args: dict[str, Any]) -> dict[str, Any]:
        from .research import search_workspace_detailed
        result = search_workspace_detailed(
            self.root,
            str(args["query"]),
            include_glob=str(args.get("includeGlob") or "**/*"),
            max_results=max(1, min(int(args.get("maxResults") or 25), 200)),
        )
        if not result["complete"]:
            result["note"] = "Search stopped at its result or time limit. Narrow includeGlob or increase maxResults."
        return {"query": args["query"], **result}

    def _workspace_read(self, args: dict[str, Any]) -> dict[str, Any]:
        requested = str(args["path"]).strip()
        if not requested:
            raise ValueError("workspace.read requires a non-empty path.")
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("workspace.read path must stay inside the workspace root.") from exc
        if not resolved.is_file():
            raise FileNotFoundError(f"Workspace file does not exist: {relative.as_posix()}")
        raw = resolved.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if args.get("expectedSha256") and args["expectedSha256"].lower() != digest:
            raise ValueError("workspace.read content changed since the previous range; read a fresh snapshot")
        if b"\x00" in raw[:8192]:
            raise ValueError("workspace.read accepts text files only.")
        content = raw.decode("utf-8", errors="replace")
        max_chars = max(1, min(int(args.get("maxChars") or 20000), 100000))
        offset = int(args.get("offset", 0))
        if offset < 0:
            raise ValueError("workspace.read offset must be nonnegative.")
        line_metadata = {}
        range_end = len(content)
        if "startLine" in args or "endLine" in args:
            if offset:
                raise ValueError("Use either line ranges or a character offset")
            lines = content.splitlines(keepends=True)
            start_line = args.get("startLine", 1)
            end_line = args.get("endLine", len(lines))
            if not 1 <= start_line <= end_line <= len(lines):
                raise ValueError("Line range must stay inside the file (inclusive, starting at 1)")
            offset = sum(map(len, lines[:start_line - 1]))
            range_end = offset + sum(map(len, lines[start_line - 1:end_line]))
            line_metadata = {"startLine": start_line, "endLine": end_line, "rangeEnd": range_end}
        end = min(offset + max_chars, range_end)
        result = {
            "path": relative.as_posix(),
            "content": content[offset:end],
            "truncated": end < range_end,
            "offset": offset,
            "nextOffset": end if end < range_end else None,
            "characters": len(content),
            "bytes": len(raw),
            "sha256": digest,
            "coordinateUnit": "unicode_character",
            **line_metadata,
        }
        from .proofs_d_native import require
        require(result["content"] == content[offset:end] and result["sha256"] == hashlib.sha256(raw).hexdigest()
                and resolved.is_relative_to(self.root), "native.tools.workspace", "workspace read differs from bounded source snapshot")
        return result

    def _workspace_write(self, args: dict[str, Any]) -> dict[str, Any]:
        # SQLite's file lock serializes cooperative writers across registry instances/processes.
        import sqlite3
        from contextlib import closing
        lock_path = self.root / ".agent_control" / "workspace-edits.sqlite3"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(lock_path, timeout=15)) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                return self._workspace_write_unlocked(args)

    def _workspace_write_unlocked(self, args: dict[str, Any]) -> dict[str, Any]:
        """Atomically save a bounded UTF-8 text artifact and verify persisted bytes."""
        import os
        import tempfile

        root = self.root.resolve()
        requested = str(args.get("path") or "").strip()
        if not requested:
            raise ValueError("workspace.write requires a non-empty path.")
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("workspace.write path must stay inside the active workspace root.") from exc
        if relative == Path(".") or not relative.name:
            raise ValueError("workspace.write requires a file path, not the workspace directory.")

        # Walk the original path before normalizing it, so `link/../file` cannot
        # hide a symlink or junction in a segment that resolve() would erase.
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError("workspace.write refuses paths containing a symlink or junction.")
            try:
                current.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise ValueError("workspace.write path must stay inside the active workspace root.") from exc
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("workspace.write path must stay inside the active workspace root.") from exc
        parent = resolved.parent
        if resolved.exists() and not resolved.is_file():
            raise IsADirectoryError("workspace.write target must be a file.")

        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("workspace.write content must be a string.")
        raw = content.encode("utf-8", errors="strict")
        if len(raw) > 1024 * 1024:
            raise ValueError("workspace.write content exceeds the 1 MiB limit.")
        if b"\x00" in raw:
            raise ValueError("workspace.write accepts UTF-8 text only; NUL bytes are not allowed.")

        expected = str(args.get("expectedSha256") or "").strip().lower()
        if expected and (len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected)):
            raise ValueError("expectedSha256 must be a 64-character SHA-256 hex digest.")
        existed = resolved.exists()
        before_bytes = resolved.read_bytes() if existed else b""
        before_hash = hashlib.sha256(before_bytes).hexdigest() if existed else ""
        if existed and not expected:
            raise FileExistsError("workspace.write will not overwrite an existing file without expectedSha256.")
        if not existed and expected:
            raise FileNotFoundError("workspace.write expectedSha256 was supplied, but the target does not exist.")
        if expected and before_hash != expected:
            raise ValueError("workspace.write content changed since it was read; expectedSha256 does not match.")

        # Admission and CAS refusal must finish before creating any directories.
        if not parent.is_dir():
            existing_parent = parent
            while not existing_parent.exists() and existing_parent != root:
                existing_parent = existing_parent.parent
            if not existing_parent.is_dir():
                raise NotADirectoryError("workspace.write parent path contains a non-directory entry.")
            parent.mkdir(parents=True, exist_ok=True)
            try:
                parent.resolve(strict=True).relative_to(root)
            except (OSError, ValueError) as exc:
                raise ValueError("workspace.write created parent path outside the active workspace root.") from exc
            current = root
            for part in relative.parts[:-1]:
                current = current / part
                if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                    raise ValueError("workspace.write refuses paths containing a symlink or junction.")

        temporary_path: Path | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=f".{resolved.name}.", suffix=".tmp", dir=str(parent))
            temporary_path = Path(temporary)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if existed:
                # Recheck immediately before the atomic replacement to catch
                # concurrent edits during staging.
                actual_now = hashlib.sha256(resolved.read_bytes()).hexdigest()
                if actual_now != expected:
                    raise ValueError("workspace.write target changed during staging; expectedSha256 no longer matches.")
                os.replace(temporary_path, resolved)
            else:
                # Hard-link creation is atomic and fails if another writer won
                # the same new path, so the create-by-default contract holds.
                os.link(temporary_path, resolved)
                temporary_path.unlink()
                temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

        readback = resolved.read_bytes()
        expected_hash = hashlib.sha256(raw).hexdigest()
        readback_hash = hashlib.sha256(readback).hexdigest()
        if readback != raw or readback_hash != expected_hash:
            raise OSError("workspace.write readback verification failed after the atomic write.")
        return {
            "ok": True,
            "status": "created" if not existed else "updated",
            "path": relative.as_posix(),
            "bytes": len(readback),
            "sha256": readback_hash,
            "readbackVerified": True,
            "filesChanged": [relative.as_posix()],
            **_bounded_line_diff(before_bytes if existed else None, readback, relative.as_posix()),
        }

    def _context_engine(self, args: dict[str, Any]) -> DurableContextEngine:
        from .context_engine import DurableContextEngine
        maximum = int(args.get("maxContextTokens") or 400000)
        reserve = min(20000, max(1000, maximum // 10))
        return DurableContextEngine(
            self.root,
            str(args["sessionId"]),
            max_context_tokens=maximum,
            reserve_tokens=reserve,
        )

    def _context_search(self, args: dict[str, Any]) -> dict[str, Any]:
        engine = self._context_engine(args)
        matches = engine.search(str(args["query"]), limit=int(args.get("limit") or 20))
        return {"query": str(args["query"]), "matches": matches, "status": engine.status()}

    def _context_bundle(self, args: dict[str, Any]) -> dict[str, Any]:
        engine = self._context_engine(args)
        return engine.build_bundle(
            str(args.get("query") or ""),
            token_budget=int(args.get("tokenBudget") or 0) or None,
        )

    def _context_compact(self, args: dict[str, Any]) -> dict[str, Any]:
        engine = self._context_engine(args)
        result = engine.compact(
            focus=str(args.get("focus") or ""),
            target_ratio=float(args.get("targetRatio") or 0.25),
        )
        receipt_path = str(result.get("receiptPath") or "")
        return {**result, "artifacts": [receipt_path] if receipt_path else []}

    def _orchestration_compile(self, args: dict[str, Any]) -> dict[str, Any]:
        from .orchestration_language import compile_neyvia_program
        plan = compile_neyvia_program(str(args["source"]))
        requested = str(args.get("outputPath") or "").strip()
        if requested:
            output = Path(requested).expanduser()
            if not output.is_absolute():
                output = self.root / output
            output = output.resolve()
            try:
                output.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("Compiled orchestration output must stay inside the workspace.") from exc
        else:
            output = self.root / ".agent_control" / "orchestration" / f"{plan['planHash']}.json"
        _atomic_json(output, plan)
        return {**plan, "artifactPath": str(output), "artifacts": [str(output)]}

    def _codex_assets_inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        from .codex_import import CodexAssetImporter
        importer = CodexAssetImporter(self.root, args.get("codexHome") or None)
        return importer.audit()

    def _codex_assets_import(self, args: dict[str, Any]) -> dict[str, Any]:
        from .codex_import import CodexAssetImporter
        importer = CodexAssetImporter(self.root, args.get("codexHome") or None)
        receipt = importer.import_assets()
        artifacts = [str(receipt["catalogPath"])]
        return {**receipt, "artifacts": artifacts}

    def _web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        from .public_web_search import search
        return search(args, request=_request, parser_type=_DuckDuckGoParser)

    @staticmethod
    def _normalize_image_result(item: dict[str, Any]) -> dict[str, Any]:
        image_url = str(item.get("image") or item.get("img_src") or item.get("content") or "").strip()
        thumbnail = str(item.get("thumbnail") or item.get("thumbnail_src") or image_url).strip()
        source_url = str(item.get("url") or item.get("source_url") or item.get("href") or image_url).strip()
        source = str(item.get("source") or item.get("engine") or "").strip()
        try:
            source_domain = urllib.parse.urlparse(source_url).netloc.lower().removeprefix("www.")
        except ValueError:
            source_domain = ""
        return {
            "title": str(item.get("title") or item.get("name") or source_domain or "Visual reference").strip(),
            "image": image_url,
            "thumbnail": thumbnail,
            "url": source_url,
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "source": source,
            "sourceDomain": source_domain,
        }

    def _web_image_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args["query"]).strip()
        limit = max(1, min(int(args.get("limit") or 12), 30))
        safe_search = str(args.get("safeSearch") or "moderate").strip().lower()
        searxng = str(os.environ.get("NEYVIA_SEARXNG_URL") or os.environ.get("FLUXIO_SEARXNG_URL") or "").rstrip("/")
        if searxng:
            params = {
                "q": query,
                "format": "json",
                "categories": "images",
                "safesearch": {"off": 0, "moderate": 1, "on": 2}.get(safe_search, 1),
            }
            time_limit = str(args.get("timeLimit") or "").strip().lower()
            if time_limit:
                params["time_range"] = {"day": "day", "week": "day", "month": "month", "year": "year"}.get(time_limit, time_limit)
            data, _ = _request(f"{searxng}/search?{urllib.parse.urlencode(params)}", headers={"Accept": "application/json"})
            payload = json.loads(data.decode("utf-8", errors="replace"))
            rows = [self._normalize_image_result(dict(item)) for item in list(payload.get("results") or [])]
            results = [row for row in rows if row["image"]][:limit]
            if results:
                return {"query": query, "provider": "searxng-images", "results": results}

        try:
            from ddgs import DDGS
        except ImportError as exc:  # pragma: no cover - covered by availability gate
            raise RuntimeError("DDGS visual search is not installed. Run `uv sync` or configure NEYVIA_SEARXNG_URL.") from exc

        ddgs_args: dict[str, Any] = {
            "query": query,
            "region": str(args.get("region") or "us-en"),
            "safesearch": safe_search,
            "max_results": limit,
        }
        option_map = {
            "timeLimit": "timelimit",
            "size": "size",
            "color": "color",
            "typeImage": "type_image",
            "layout": "layout",
            "license": "license_image",
        }
        for source_key, target_key in option_map.items():
            value = str(args.get(source_key) or "").strip()
            if value:
                ddgs_args[target_key] = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(value.lower(), value)
        with DDGS() as search:
            raw_results = list(search.images(**ddgs_args))
        results = [self._normalize_image_result(dict(item)) for item in raw_results]
        results = [row for row in results if row["image"]][:limit]
        if not results:
            raise RuntimeError("Visual search returned no normalized image results.")
        return {"query": query, "provider": "ddgs-images", "results": results}

    def _ui_inspiration_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query, facets, enriched_query, search_args = self._inspiration_request(args)
        payload = self._web_image_search(search_args)
        return self._inspiration_board(query, facets, enriched_query, payload)

    @staticmethod
    def _inspiration_request(args):
        query = str(args["query"]).strip()
        facets = {
            "surface": str(args.get("surface") or "product interface").strip(),
            "platform": str(args.get("platform") or "desktop web app").strip(),
            "style": str(args.get("style") or "").strip(),
            "color": str(args.get("color") or "").strip(),
            "layout": str(args.get("layout") or "").strip(),
        }
        enriched_query = " ".join(
            value for value in (
                query,
                facets["surface"],
                facets["platform"],
                facets["style"],
                "UI UX interface screenshot design inspiration",
            ) if value
        )
        search_args = {
            "query": enriched_query,
            "limit": max(1, min(int(args.get("limit") or 12), 24)),
            "safeSearch": "moderate",
            "color": facets["color"],
            "layout": facets["layout"],
        }
        return query, facets, enriched_query, search_args

    @staticmethod
    def _inspiration_board(query, facets, enriched_query, payload):
        board = {
            "query": query,
            "searchQuery": enriched_query,
            "provider": payload["provider"],
            "facets": facets,
            "results": payload["results"],
            "resultCount": len(payload["results"]),
            "boardType": "ui-inspiration",
        }
        from .proofs_d_native import check_inspiration
        check_inspiration(board, query, facets, enriched_query, payload)
        return board

    def _web_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args["url"]).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("web.fetch accepts only http:// or https:// URLs")
        cached = None if args.get("refresh") else self.documents.cached(url, args.get("maxAgeSeconds", 300))
        max_chars = max(200, min(int(args.get("maxChars") or 20000), 100000))
        if cached:
            cached_text, metadata = cached
            old_pdf = "application/pdf" in str(metadata.get("contentType", "")).lower() or "%PDF-" in cached_text[:1024]
            if not old_pdf or metadata.get("pdfExtraction", {}).get("engine") == "pypdf":
                return {**self.documents.read({"document": metadata["document"], "maxChars": max_chars}), "cacheHit": True}
        pdf_limit = 32 * 1024 * 1024
        # Honest agent identity. Some publishers refuse clients that claim to be
        # a desktop browser without being one; none here are refused for this.
        agent = "NeyviaAgent/1.0 (Automation; PDF fetch)" if parsed.path.lower().endswith(".pdf") else "NeyviaAgent/1.0 (Automation; public research fetch)"
        try:
            data, response = _request(url, headers={"User-Agent": agent}, pdf_max_bytes=pdf_limit)
        except urllib.error.HTTPError as exc:
            if exc.code not in {401, 403, 429, 503}:
                raise
            rendered = self._rendered_fetch(url, exc.code, max_chars)
            if rendered is None:
                raise ValueError(f"HTTP Error {exc.code}: {exc.reason}. Plain HTTP was refused; start the workspace Obscura "
                                 "runtime on an assigned port for a non-stealth browser-rendered read") from exc
            return rendered
        content_type = str(response.headers.get("Content-Type") or "")
        pdf = "application/pdf" in content_type.lower() or b"%PDF-" in data[:1024]
        extraction = {}
        if pdf:
            import io
            import pypdf
            if len(data) >= pdf_limit:
                raise ValueError(f"PDF response reached the selected {pdf_limit} byte PDF limit; completeness is unproven")
            declared = response.headers.get("Content-Length")
            if declared is not None and len(data) != int(declared):
                raise ValueError("PDF response is truncated or has inconsistent Content-Length")
            if b"%PDF-" not in data[:1024] or not data.rstrip().endswith(b"%%EOF"):
                raise ValueError("PDF response is malformed or truncated")
            reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF extraction is refused")
            page_count = len(reader.pages)
            parts, characters = [], 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                parts.append(page_text[:max(0, 2 * 1024 * 1024 - characters)])
                characters += len(page_text) + 2
                if characters >= 2 * 1024 * 1024:
                    break
            text = "\n\n".join(parts).strip()
            if not text:
                raise ValueError("PDF has no extractable text; no OCR or invented text was used")
            title = str((reader.metadata or {}).get("/Title") or "")
            extraction = {"pdfExtraction": {"engine": "pypdf", "version": pypdf.__version__,
                          "pages": page_count, "pagesExtracted": len(parts),
                          "contentSha256": hashlib.sha256(data).hexdigest(), "truncated": False,
                          "textTruncated": characters >= 2 * 1024 * 1024,
                          "receivedBytes": len(data), "responseByteLimit": pdf_limit}}
        else:
            charset = response.headers.get_content_charset() or "utf-8"
            decoded = data.decode(charset, errors="replace")
            if "html" in content_type.lower() or "<html" in decoded[:500].lower():
                parser = _ReadableHtmlParser()
                parser.feed(decoded)
                text = parser.readable_blocks()
                title = parser.title
            else:
                text = decoded.strip()
                title = ""
        metadata = {
            "url": url,
            "finalUrl": response.geturl(),
            "status": int(getattr(response, "status", 200)),
            "contentType": content_type,
            "title": html.unescape(title),
            "responseTruncated": False if pdf else len(data) >= 2 * 1024 * 1024,
            **extraction,
        }
        _, metadata = self.documents.save(url, text, metadata, data)
        return {**self.documents.read({"document": metadata["document"], "maxChars": max_chars}), "cacheHit": False}

    def _rendered_fetch(self, url: str, refused_status: int, max_chars: int) -> dict[str, Any] | None:
        """Read a page that refused plain HTTP through the workspace's running Obscura.

        Only an already running, owner-started headless runtime is borrowed; this
        never starts a browser, solves a challenge, or changes identity. The
        stored body is the rendered readable text and is labelled as such.
        """
        from . import neyvia_browser
        service = neyvia_browser._SERVICES.get(str(self.root.resolve()))
        headless = getattr(service, "headless", None)
        if service is None or headless is None or not headless.status().get("connected"):
            return None
        opened = service.request("tab.open", {"url": url, "engine": "obscura", "readerMode": True}, owner=True)
        try:
            # The open itself captured a fresh projection of the loaded page.
            observation = service.projections.get(opened["tabId"]) or service.request("observe", {"tabId": opened["tabId"], "cached": False})
        finally:
            service.request("tab.close", {"tabId": opened["tabId"]}, owner=True)
        text = str(observation.get("text") or "").strip()
        title = str(observation.get("title") or "")
        if len(text) < 40 or re.search(r"access denied|verify you are (a )?human|captcha|unusual traffic", title + " " + text[:400], re.I):
            raise ValueError(f"HTTP Error {refused_status}; the browser-rendered page is also refused or a verification page. Not bypassed")
        metadata = {"url": url, "finalUrl": str(observation.get("url") or url), "status": None, "contentType": "text/plain; rendered",
                    "title": title, "responseTruncated": bool(observation.get("truncated")),
                    "retrieval": "obscura-rendered", "plainHttpStatus": refused_status,
                    "bodyRepresentation": "Rendered readable page text from the non-stealth Obscura engine, not HTTP transport bytes",
                    "engine": headless.status().get("engine") or "obscura"}
        body = text.encode("utf-8")[:2 * 1024 * 1024]
        text = body.decode("utf-8", errors="ignore")
        _, metadata = self.documents.save(url, text, metadata, body)
        return {**self.documents.read({"document": metadata["document"], "maxChars": max_chars}), "cacheHit": False}

    def _preview_inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("mode") == "bytes":
            url = str(args["url"]).strip()
            if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
                raise ValueError("Preview inspection accepts only HTTP or HTTPS URLs")
            data, response = _request(url)
            offset = max(0, min(int(args.get("offset", 0)), 100000))
            chunk = data[offset:min(offset + 512, 100000)]
            lines = []
            for position in range(0, len(chunk), 16):
                row = chunk[position:position + 16]
                printable = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
                lines.append(f"{offset + position:08x}  {row.hex(' '):47}  {printable}")
            return {"url": url, "finalUrl": response.geturl(), "previewType": "http",
                    "observationKind": "response_bytes", "status": int(response.status),
                    "reachable": 200 <= int(response.status) < 400,
                    "contentType": str(response.headers.get("Content-Type") or ""),
                    "text": "\n".join(lines), "offset": offset, "query": "", "matches": [],
                    "indexedCharacters": len(data), "indexTruncated": len(data) >= 2 * 1024 * 1024,
                    "nextOffset": offset + len(chunk) if chunk and offset + len(chunk) < min(len(data), 100000) else None,
                    "contentSha256": hashlib.sha256(data).hexdigest()}
        result = self._web_fetch({"url": args["url"], "maxChars": 100000})
        content = result["text"]
        query = str(args.get("query") or "").strip()
        if len(query) > 500:
            raise ValueError("Search query must be at most 500 characters")
        offset = max(0, min(int(args.get("offset", 0)), 100000))
        limit = max(1, min(int(args.get("limit", 20)), 50))
        matches = []
        next_offset = offset + 4000 if not query and offset + 4000 < len(content) else None
        if query:
            # Regex escaping makes search literal and preserves original character offsets.
            for match in re.finditer(re.escape(query), content[offset:], re.IGNORECASE):
                start = offset + match.start()
                if len(matches) == limit:
                    next_offset = start
                    break
                matches.append({"offset": start, "length": match.end() - match.start(),
                                "excerpt": content[max(0, start - 100):start + len(query) + 160]})
        observed = {**result, "text": content[offset:offset + 4000],
                "reachable": 200 <= int(result["status"]) < 400, "previewType": "http",
                "observationKind": "fetched_text", "query": query, "matches": matches,
                "offset": offset, "nextOffset": next_offset,
                "indexedCharacters": len(content), "indexTruncated": result["truncated"] or result.get("responseTruncated", False),
                "truncated": len(content) > offset + 4000,
                "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        from .proofs_d_native import check_preview
        check_preview(observed, content, offset)
        return observed

    def _screenshot_output_path(self, requested: object) -> Path:
        if requested:
            candidate = Path(str(requested)).expanduser()
            if not candidate.is_absolute():
                candidate = self.root / candidate
            resolved, _ = _workspace_relative_path(
                self.root, candidate, "Screenshot output must stay inside the workspace root."
            )
            return resolved
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.root / ".agent_control" / "mission_artifacts" / "native_tools" / "screenshots" / f"preview-{stamp}-{uuid.uuid4().hex[:6]}.png"

    @staticmethod
    def _png_dimensions(path: Path) -> tuple[int, int]:
        data = path.read_bytes()[:24]
        if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return 0, 0

    def _browser_runtime_snapshot(self, *, reused: bool) -> dict[str, Any]:
        if self.browser_runtime is None:
            return {}
        snapshot = getattr(self.browser_runtime, "snapshot", None)
        if callable(snapshot):
            return snapshot(reused=reused)
        return {
            "kind": "persistent-playwright",
            "browserReused": reused,
            "browserStarts": int(
                getattr(self.browser_runtime, "browser_starts", 0) or 0
            ),
            "contextsCreated": int(
                getattr(self.browser_runtime, "contexts_created", 0) or 0
            ),
        }

    @contextmanager
    def _capture_page(self, *, width: int, height: int):
        from .browser_preflight import build_browser_dependency_preflight
        if self.browser_runtime is not None:
            starts_before = int(getattr(self.browser_runtime, "browser_starts", 0) or 0)
            with self.browser_runtime.page(width=width, height=height) as page_result:
                if isinstance(page_result, tuple) and len(page_result) == 2:
                    page, reused = page_result
                else:
                    page = page_result
                    starts_after = int(
                        getattr(self.browser_runtime, "browser_starts", 0) or 0
                    )
                    reused = starts_before > 0 and starts_after == starts_before
                yield page, reused, getattr(self.browser_runtime, 'engine', 'playwright-persistent')
            return

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            preflight = build_browser_dependency_preflight(self.root)
            from .chrome_environment import chrome_executable
            executable = chrome_executable(preflight)
            launch_options: dict[str, Any] = {"headless": True}
            if executable:
                launch_options["executable_path"] = executable
            from .chrome_environment import chrome_environment, fresh_chrome_profile, CHROME_AUTOMATION_ARGS
            profile = fresh_chrome_profile(self.root, "native-capture")
            launch_options.update(env=chrome_environment(profile.parent / (profile.name + "-environment")),
                                  args=CHROME_AUTOMATION_ARGS)
            launch_context = playwright.chromium.launch_persistent_context(str(profile), **launch_options)
            browser = launch_context.browser
            context = browser.new_context(viewport={"width": width, "height": height})
            try:
                yield context.new_page(), False, "playwright"
            finally:
                context.close()
                browser.close()

    def _preview_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        from .browser_preflight import build_browser_dependency_preflight
        url = str(args["url"]).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https", "file"}:
            raise ValueError("preview.screenshot accepts http://, https://, or file:// URLs")
        requested_output = self._screenshot_output_path(args.get("outputPath"))
        requested_output.parent.mkdir(parents=True, exist_ok=True)
        # Capture a fresh sibling. A failed attempt must never reuse an old PNG
        # already present at the caller's requested path.
        output = requested_output.with_name(f".{requested_output.stem}-{uuid.uuid4().hex}.png")
        width = max(320, min(int(args.get("width") or 1440), 3840))
        height = max(240, min(int(args.get("height") or 1000), 2160))
        full_page = bool(args.get("fullPage", True))
        wait_for = str(args.get("waitFor") or "").strip()
        delay_ms = max(0, min(int(args.get("delayMs") if args.get("delayMs") is not None else 350), 10000))
        wait_until = str(args.get("waitUntil") or "domcontentloaded").strip().lower()
        errors: list[str] = []
        engine = ""
        browser_runtime: dict[str, Any] = {}
        from .local_browser_authority import current_capture_authority
        navigation_guard = current_capture_authority()

        if self.browser_runtime is not None or (importlib.util.find_spec("playwright") is not None and importlib.util.find_spec("playwright.sync_api") is not None):
            try:
                with self._capture_page(width=width, height=height) as (page, reused, page_engine):
                    if navigation_guard is not None:
                        navigation_guard(page)
                    page.goto(url, wait_until=wait_until, timeout=30000)
                    if wait_for:
                        page.wait_for_selector(wait_for, state="visible", timeout=15000)
                    if delay_ms:
                        page.wait_for_timeout(delay_ms)
                    page.screenshot(path=str(output), full_page=full_page)
                    engine = page_engine
                    if self.browser_runtime is not None:
                        browser_runtime = self._browser_runtime_snapshot(reused=reused)
            except Exception as exc:  # pragma: no cover - environment-specific fallback
                if navigation_guard is not None or self.browser_runtime is not None:
                    raise RuntimeError("Scoped browser capture refused: " + str(exc)) from exc
                errors.append(f"Playwright: {exc}")

        if not output.is_file():
            if navigation_guard is not None or self.browser_runtime is not None:
                raise RuntimeError("Scoped browser capture requires a guarded browser transport")
            preflight = build_browser_dependency_preflight(self.root)
            executable = str(preflight.get("chromeExecutable") or "").strip()
            if not executable:
                raise RuntimeError("; ".join(errors + [str(preflight.get("error") or "No Chromium executable found")]))
            command = [
                executable,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                f"--window-size={width},{height}",
                f"--virtual-time-budget={delay_ms}",
                f"--screenshot={output}",
                url,
            ]
            completed = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not output.is_file():
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError("; ".join(errors + [detail or "Chromium screenshot failed"]))
            engine = "chromium-headless"

        image_width, image_height = self._png_dimensions(output)
        os.replace(output, requested_output)
        output = requested_output
        return {
            "url": url,
            "path": str(output),
            "sha256": _sha256(output),
            "sizeBytes": output.stat().st_size,
            "width": image_width,
            "height": image_height,
            "engine": engine,
            "fullPage": full_page if engine.startswith("playwright") else False,
            "browserRuntime": browser_runtime,
            "fallbackErrors": errors,
            "artifacts": [str(output)],
        }

    def _preview_taste(self, args: dict[str, Any]) -> dict[str, Any]:
        from .taste_lens import PROBE_SCRIPT, TASTE_LENS_SCHEMA, VIEWPORTS, evaluate, laya_journey_manifest, run_laya_journey, triage_report

        url = str(args["url"]).strip()
        if urllib.parse.urlparse(url).scheme not in {"http", "https", "file"}:
            raise ValueError("preview.taste accepts http://, https://, or file:// URLs")
        requested = [str(item) for item in (args.get("viewports") or ["desktop", "phone"]) if str(item) in VIEWPORTS] or ["desktop", "phone"]
        wait_for = str(args.get("waitFor") or "").strip()
        delay_ms = max(0, min(int(args.get("delayMs") if args.get("delayMs") is not None else 900), 10000))
        scheme = "light" if str(args.get("colorScheme") or "").strip().lower() == "light" else "dark"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self._annotation_output_dir(args.get("outputDir")) if args.get("outputDir") else (
            self.root / ".agent_control" / "mission_artifacts" / "native_tools" / "taste" / f"taste-{stamp}-{uuid.uuid4().hex[:6]}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        use_playwright = importlib.util.find_spec("playwright") is not None and importlib.util.find_spec("playwright.sync_api") is not None
        use_cdp = not use_playwright
        if os.name == "nt" and self.browser_runtime is None:
            from .chromium_review import _browser_executable
            try:
                _browser_executable()
                use_cdp = True
            except RuntimeError:
                pass
        if use_cdp:
            from .chromium_review import chromium_review_page

        measurements: dict[str, dict[str, Any]] = {}
        screenshots: dict[str, dict[str, Any]] = {}
        for viewport in requested:
            width, height = VIEWPORTS[viewport]
            shot = output_dir / f"{viewport}.png"
            try:
                context = chromium_review_page(width=width, height=height) if use_cdp else self._capture_page(width=width, height=height)
                with context as opened:
                    page, engine = (opened, "chromium-cdp") if use_cdp else (opened[0], opened[2])
                    page.emulate_media(color_scheme=scheme)
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    status = response if use_cdp else response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise RuntimeError(
                            f"HTTP {status}: the page did not load. Neyvia-served previews need a session; "
                            "review the built file:// page or the app's dev-server URL instead."
                        )
                    if wait_for:
                        page.wait_for_selector(wait_for, state="visible", timeout=15000)
                    if delay_ms:
                        page.wait_for_timeout(delay_ms)
                    page.screenshot(path=str(shot), full_page=False)
                    measurements[viewport] = page.evaluate(PROBE_SCRIPT)
                    measurements[viewport]["engine"] = engine
                screenshots[viewport] = {"path": str(shot), "sha256": _sha256(shot), "width": width, "height": height}
            except Exception as exc:  # the report must say what could not be measured
                measurements[viewport] = {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"}

        report = evaluate(measurements)
        journey_result: dict[str, Any] | None = None
        journey = args.get("journey")
        if isinstance(journey, dict) and journey:
            goal = str(args.get("goal") or journey.get("goal") or "Exercise the page's primary controls.").strip()
            manifest = laya_journey_manifest(url, goal, journey)
            journey_result = run_laya_journey(manifest, approved=True)
            journey_result["manifest"] = manifest
            if not journey_result.get("passed"):
                report["gate"] = "blocked"
                refused = str(journey_result.get("status") or "").upper() == "DENY"
                report["findings"].insert(0, {
                    "severity": "block", "rule": "journey", "viewport": "laya",
                    "title": (f"Laya refused the journey ({journey_result.get('policy')}); nothing was exercised"
                              if refused else f"Laya journey {journey_result.get('status')}: the goal was not demonstrated"),
                    "evidence": {key: journey_result.get(key) for key in ("status", "unmet", "failureCategory", "error", "policy")},
                    "fix": "Read the unmet expectations, repair the page or the journey, then run the review again.",
                })
                report["counts"]["block"] = report["counts"].get("block", 0) + 1
        triage = triage_report(self.root, report)
        result = {
            "schema": TASTE_LENS_SCHEMA,
            "triage": triage,
            "url": url,
            "goal": str(args.get("goal") or "").strip(),
            "colorScheme": scheme,
            "gate": report["gate"],
            "score": report["score"],
            "counts": report["counts"],
            "findings": report["findings"][:24],
            "firstGlance": report["firstGlance"],
            "screenshots": screenshots,
            "journey": {key: value for key, value in (journey_result or {}).items() if key != "receipt"} if journey_result else None,
            "measurements": measurements,
            "boundary": report["boundary"],
            "nextStep": (
                "Look at each screenshot with neyvia_view_image, fix blocking findings first, then review again."
                if report["gate"] == "blocked"
                else "Look at the screenshots yourself; the lens found no blocking defect, which is not a beauty verdict."
            ),
        }
        report_path = output_dir / "taste-report.json"
        report_path.write_text(json.dumps({**result, "journeyReceipt": (journey_result or {}).get("receipt")}, indent=2), encoding="utf-8")
        result["report"] = str(report_path)
        result["artifacts"] = [item["path"] for item in screenshots.values()] + [str(report_path)]
        if args.get("includeImageData") is True:
            import base64
            for shot in screenshots.values():
                image_path = Path(shot["path"])
                if image_path.stat().st_size <= 2_000_000:
                    from .image_budget import shrunk_data_url
                    shot["dataUrl"] = shrunk_data_url(image_path)  # 1024 px JPEG; the full PNG stays at shot["path"]
        return result

    def _annotation_output_dir(self, requested: object) -> Path:
        if requested:
            candidate = Path(str(requested)).expanduser()
            if not candidate.is_absolute():
                candidate = self.root / candidate
            resolved, _ = _workspace_relative_path(
                self.root, candidate, "Annotation output must stay inside the workspace root."
            )
            return resolved
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.root / ".agent_control" / "mission_artifacts" / "native_tools" / "annotations" / f"preview-{stamp}-{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _normalize_percentage_rectangle(rectangle: dict[str, Any]) -> dict[str, float]:
        x = max(0.0, min(100.0, float(rectangle.get("x") or 0)))
        y = max(0.0, min(100.0, float(rectangle.get("y") or 0)))
        width = max(0.5, min(100.0 - x, float(rectangle.get("width") or rectangle.get("w") or 0.5)))
        height = max(0.5, min(100.0 - y, float(rectangle.get("height") or rectangle.get("h") or 0.5)))
        return {"x": round(x, 3), "y": round(y, 3), "width": round(width, 3), "height": round(height, 3)}

    def _preview_annotate(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args["url"]).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https", "file"}:
            raise ValueError("preview.annotate accepts http://, https://, or file:// URLs")
        rectangle = self._normalize_percentage_rectangle(dict(args.get("rectangle") or {}))
        viewport = dict(args.get("viewport") or {})
        width = max(320, min(int(viewport.get("width") or 1440), 3840))
        height = max(240, min(int(viewport.get("height") or 1000), 2160))
        comment = str(args.get("comment") or "Selected UI region").strip() or "Selected UI region"
        delay_ms = max(0, min(int(args.get("delayMs") if args.get("delayMs") is not None else 350), 10000))
        output_dir = self._annotation_output_dir(args.get("outputDir"))
        output_dir.mkdir(parents=True, exist_ok=True)
        base_path = output_dir / "preview.png"
        annotated_path = output_dir / "annotated.png"
        crop_path = output_dir / "region.png"
        receipt_path = output_dir / "annotation.json"

        browser_runtime: dict[str, Any] = {}
        with self._capture_page(width=width, height=height) as (page, reused, engine):
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if delay_ms:
                page.wait_for_timeout(delay_ms)
            page.screenshot(path=str(base_path), full_page=False)
            clip = {
                "x": max(0.0, width * rectangle["x"] / 100),
                "y": max(0.0, height * rectangle["y"] / 100),
                "width": max(1.0, width * rectangle["width"] / 100),
                "height": max(1.0, height * rectangle["height"] / 100),
            }
            clip["width"] = min(clip["width"], width - clip["x"])
            clip["height"] = min(clip["height"], height - clip["y"])
            page.screenshot(path=str(crop_path), clip=clip)
            if hasattr(page, 'annotate'):
                page.annotate(rectangle=rectangle, comment=comment)
            else:
                page.evaluate(
                """
                ({ rectangle, comment }) => {
                  const overlay = document.createElement('div');
                  overlay.setAttribute('data-neyvia-annotation-proof', 'true');
                  Object.assign(overlay.style, {
                    position: 'fixed', zIndex: '2147483647', pointerEvents: 'none',
                    left: `${rectangle.x}%`, top: `${rectangle.y}%`,
                    width: `${rectangle.width}%`, height: `${rectangle.height}%`,
                    border: '3px solid #f2b84b', borderRadius: '8px',
                    boxShadow: '0 0 0 9999px rgba(7,16,31,.34), 0 0 24px rgba(32,102,255,.55)',
                    boxSizing: 'border-box'
                  });
                  const label = document.createElement('span');
                  label.textContent = comment.slice(0, 120);
                  Object.assign(label.style, {
                    position: 'absolute', left: '0', bottom: '100%', marginBottom: '6px',
                    maxWidth: '360px', padding: '6px 9px', borderRadius: '6px',
                    background: '#07101f', color: '#ffffff', font: '600 12px/1.35 system-ui',
                    boxShadow: '0 6px 18px rgba(0,0,0,.28)'
                  });
                  overlay.appendChild(label);
                  document.documentElement.appendChild(overlay);
                }
                """,
                {"rectangle": rectangle, "comment": comment},
            )
            page.screenshot(path=str(annotated_path), full_page=False)
            if self.browser_runtime is not None:
                browser_runtime = self._browser_runtime_snapshot(reused=reused)

        annotation = {
            "@context": "http://www.w3.org/ns/anno.jsonld",
            "id": f"urn:neyvia:annotation:{uuid.uuid4().hex}",
            "type": "Annotation",
            "created": _utc_now(),
            "body": {"type": "TextualBody", "purpose": "commenting", "value": comment},
            "target": {
                "source": url,
                "selector": {
                    "type": "FragmentSelector",
                    "conformsTo": "http://www.w3.org/TR/media-frags/",
                    "value": f"xywh=percent:{rectangle['x']},{rectangle['y']},{rectangle['width']},{rectangle['height']}",
                },
            },
            "geometry": {"type": "RECTANGLE", "unit": "percent", **rectangle},
            "viewport": {"width": width, "height": height},
            "evidence": {
                "preview": str(base_path),
                "annotated": str(annotated_path),
                "region": str(crop_path),
            },
        }
        _atomic_json(receipt_path, annotation)
        artifacts = [base_path, annotated_path, crop_path, receipt_path]
        from .proofs_d_native import check_annotation
        check_annotation(annotation, rectangle, artifacts)
        return {
            "url": url,
            "comment": comment,
            "rectangle": rectangle,
            "viewport": {"width": width, "height": height},
            "engine": engine,
            "browserRuntime": browser_runtime,
            "annotation": annotation,
            "paths": annotation["evidence"],
            "sha256": {path.name: _sha256(path) for path in artifacts},
            "artifacts": [str(path) for path in artifacts],
        }

    def _skill_live_read(self, args: dict[str, Any]) -> dict[str, Any]:
        from .skill_iteration import read_codex_skill_file
        return read_codex_skill_file(args)

    def _skill_live_iterate(self, args: dict[str, Any]) -> dict[str, Any]:
        from .skill_iteration import iterate_codex_skill_file
        result = iterate_codex_skill_file(args, self.root)
        result["artifacts"] = [
            str(path)
            for path in (result.get("receiptPath"), result.get("backupPath"))
            if str(path or "").strip()
        ]
        return result

    def _video_inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        from .video_tools import VideoEvidenceBuilder
        return VideoEvidenceBuilder(self.root).inspect(args["path"])

    def _video_digest(self, args: dict[str, Any]) -> dict[str, Any]:
        from .video_tools import VideoEvidenceBuilder
        return VideoEvidenceBuilder(self.root).digest(args)

    def _bridge(self) -> NasBridge:
        if self.nas_root is None:
            raise RuntimeError("NAS root is not configured.")
        return NasBridge(self.root, self.nas_root)

    def _nas_message_send(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._bridge().send_message(
            sender=str(args.get("sender") or "local"),
            recipient=str(args["recipient"]),
            message=str(args["message"]),
            attachments=[str(item) for item in list(args.get("attachments") or [])],
        )

    def _nas_message_receive(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._bridge().receive_messages(
            recipient=str(args["recipient"]),
            output_dir=str(args["outputDir"]),
            limit=int(args.get("limit") or 20),
            acknowledge=bool(args.get("acknowledge", False)),
        )

    def _nas_file_send(self, args: dict[str, Any]) -> dict[str, Any]:
        result = self._bridge().send_file(str(args["path"]))
        result["artifacts"] = [result["blobPath"]]
        return result

    def _nas_transfer(self, args: dict[str, Any]) -> dict[str, Any]:
        from .nas_transfer import NasTransfer
        source = str(args.get("source") or "").strip()
        manifest = str(args.get("manifest") or "").strip()
        if bool(source) == bool(manifest):
            raise ValueError("nas.transfer requires exactly one of source or manifest")
        transfer = NasTransfer(
            self.root,
            self.nas_root,
            allow_local_nas_root=self.allow_local_nas_root,
        )
        if manifest:
            return transfer.send_manifest(
                manifest,
                destination_root=str(args["destinationRoot"]) if args.get("destinationRoot") else None,
                timeout_seconds=int(args.get("timeoutSeconds") or 1800),
                include_all=bool(args.get("includeAll", False)),
            )
        return transfer.send(
            source,
            destination=str(args["destination"]) if args.get("destination") else None,
            timeout_seconds=int(args.get("timeoutSeconds") or 1800),
            include_all=bool(args.get("includeAll", False)),
        )

    def _semantic_recovery_create(self, args): return self.semantic.recovery_create(args)
    def _semantic_recovery_read(self, args): return self.semantic.recovery_read(args)
    def _semantic_proof_create(self, args): return self.semantic.proof_create(args)
    def _semantic_proof_verify(self, args): return self.semantic.proof_verify(args)
    def _semantic_changeset_create(self, args): return self.semantic.changeset_create(args)
    def _semantic_changeset_verify(self, args): return self.semantic.changeset_verify(args)
    def _semantic_memory_project(self, args): return self.semantic.memory_project(args)
    def _semantic_memory_read(self, args): return self.semantic.memory_read(args)
    def _semantic_memory_find(self, args): return self.semantic.memory_find(args)
    def _semantic_memory_retrieve(self, args): return self.semantic.memory_retrieve(args)
    def _semantic_mission_create(self, args): return self.semantic.mission_create(args)
    def _semantic_application_register(self, args): return self.semantic.application_register(args)
    def _semantic_application_read(self, args): return self.semantic.application_read(args)
    def _semantic_autonomy_admit(self, args): return self.semantic.autonomy_admit(args)
    def _semantic_autonomy_revoke(self, args): return self.semantic.autonomy_revoke(args)
    def _laya_native_capabilities(self, args):
        from .laya_computer_use import LayaComputerUse
        return LayaComputerUse(self.root).capabilities()

    def _laya_native_neyvia_navigation(self, args):
        from .laya_computer_use import LayaComputerUse
        return LayaComputerUse(self.root).run_neyvia_navigation()


def register_with_progressive_surface(surface: Any, registry: NativeToolRegistry) -> list[str]:
    """Expose native tools to the compiler without bypassing registry receipts."""

    from .progressive_tools import ProgressiveToolSpec

    registered: list[str] = []
    for row in registry.list_tools(include_unavailable=True, include_schemas=True):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        mutability = str(row.get("mutability_class") or "read")
        permissions: tuple[str, ...] = ()
        if mutability == "artifact_write":
            permissions = ("artifact.write",)
        elif name == "laya.native.neyvia_navigation":
            permissions = ("external.side_effect",)
        elif mutability not in {"read", "none"}:
            permissions = ("workspace.write",)

        def _make_handler(tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
            return lambda arguments: registry.call(tool_name, arguments)

        surface.register(
            ProgressiveToolSpec(
                name=name,
                title=name,
                description=str(row.get("description") or ""),
                category=str(row.get("category") or "native"),
                aliases=tuple(row.get("aliases") or ()),
                input_schema=dict(row.get("inputSchema") or {}),
                annotations={
                    "readOnlyHint": mutability in {"read", "none"},
                    "requiresApproval": bool(permissions),
                    "receiptBound": True,
                },
                permissions=permissions,
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": name,
                    "trustLevel": "workspace",
                },
                available=bool(row.get("available", True)),
                availability_reason=str(row.get("availabilityDetail") or ""),
            ),
            handler=_make_handler(name),
        )
        registered.append(name)
    return registered


def build_native_tool_snapshot(root: str | Path, nas_root: str | Path | None = None) -> dict[str, Any]:
    return NativeToolRegistry(root, nas_root=nas_root).snapshot()
