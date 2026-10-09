"""Compact model-facing UI query tools (ui.find / ui.diff / ui.do / …).

Never returns full accessibility trees. Screenshots are fallback-only via real
ui.see crops (Playwright/CDP clip) or preview.screenshot guidance.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .proofs_e_sv import enforced

from .ui_graph import (
    UiGraph,
    format_compact_delta,
    format_compact_get,
    format_compact_listing,
)
from .ui_observer import UiObserver
from .perception_frames import PerceptionFrame


TOOL_NAMES = (
    "ui.ls",
    "ui.find",
    "ui.get",
    "ui.diff",
    "ui.wait",
    "ui.do",
    "ui.upload",
    "ui.see",
    "ui.observe",
    "ui.frame",
    "ui.inspect_frame",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class UiToolSurface:
    """In-process compact query surface over a resident UiObserver/UiGraph."""

    observer: UiObserver = field(default_factory=UiObserver)
    attached_page: Any | None = None
    last_observe_url: str = ""
    workspace_root: Path | None = None

    def __post_init__(self) -> None:
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root).expanduser().resolve()

    def close(self) -> None:
        self.attached_page = None
        self.observer.close()

    @property
    def graph(self) -> UiGraph:
        return self.observer.graph

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(args or {})
        handler = {
            "ui.ls": self.ui_ls,
            "ui.find": self.ui_find,
            "ui.get": self.ui_get,
            "ui.diff": self.ui_diff,
            "ui.wait": self.ui_wait,
            "ui.do": self.ui_do,
            "ui.upload": self.ui_upload,
            "ui.see": self.ui_see,
            "ui.observe": self.ui_observe,
            "ui.frame": self.ui_frame,
            "ui.inspect_frame": self.ui_inspect_frame,
        }.get(name)
        if handler is None:
            raise KeyError(f"Unknown UI tool: {name}")
        return handler(args)

    def observe_page(
        self,
        page: Any,
        *,
        url: str = "",
        wait_until: str = "domcontentloaded",
        delay_ms: int = 200,
        interesting_only: bool = True,
    ) -> dict[str, Any]:
        """Observe an already-open Playwright page and keep it attached for ui.do."""
        if url:
            page.goto(url, wait_until=wait_until, timeout=30000)
            if delay_ms:
                page.wait_for_timeout(delay_ms)
        text = self.observer.observe_playwright_page(page, interesting_only=interesting_only)
        self.attached_page = page
        try:
            self.last_observe_url = str(page.url or url or "")
        except Exception:
            self.last_observe_url = url or self.last_observe_url
        return self._compact_result(text, tool="ui.observe")

    def ui_observe(self, args: dict[str, Any]) -> dict[str, Any]:
        """Refresh resident graph from a URL (Playwright a11y) or injected nodes."""
        nodes = args.get("nodes")
        if isinstance(nodes, list):
            from .ui_graph import Bounds, UiNode

            parsed = []
            for raw in nodes:
                if not isinstance(raw, dict):
                    continue
                bounds_raw = raw.get("bounds") or {}
                bounds = Bounds(
                    x=float(bounds_raw.get("x") or 0),
                    y=float(bounds_raw.get("y") or 0),
                    w=float(bounds_raw.get("w") or bounds_raw.get("width") or 0),
                    h=float(bounds_raw.get("h") or bounds_raw.get("height") or 0),
                )
                parsed.append(
                    UiNode(
                        id=str(raw.get("id") or ""),
                        role=str(raw.get("role") or "generic"),
                        name=str(raw.get("name") or ""),
                        states=tuple(raw.get("states") or ()),
                        bounds=bounds,
                        actions=tuple(raw.get("actions") or ()),
                        source=str(raw.get("source") or "inject"),
                        parent_id=str(raw.get("parent_id") or ""),
                        value=str(raw.get("value") or ""),
                        backend_ref=str(raw.get("backend_ref") or ""),
                    )
                )
            text = self.observer.ingest_nodes(
                [node for node in parsed if node.id],
                url=str(args.get("url") or ""),
                title=str(args.get("title") or ""),
                source=str(args.get("source") or "inject"),
            )
            return self._compact_result(text, tool="ui.observe")

        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("ui.observe requires url or nodes")
        page = self.attached_page
        try:
            page_closed = page is None or bool(page.is_closed())
        except Exception:
            page_closed = page is None
        if page_closed:
            persistent_page = getattr(self.observer.browser_runtime, "persistent_page", None)
            if not callable(persistent_page):
                raise RuntimeError("browser_runtime does not provide persistent_page()")
            page = persistent_page(
                width=int(args.get("width") or 1440),
                height=int(args.get("height") or 1000),
            )
        result = self.observe_page(
            page,
            url=url,
            wait_until=str(args.get("waitUntil") or "domcontentloaded"),
            delay_ms=int(args.get("delayMs") if args.get("delayMs") is not None else 200),
            interesting_only=bool(args.get("interestingOnly", True)),
        )
        self.last_observe_url = url
        return result

    def ui_frame(self, args: dict[str, Any]) -> dict[str, Any]:
        result = PerceptionFrame(self.graph).build(since_revision=int(args['sinceRevision']) if args.get('sinceRevision') is not None else None, node_id=str(args.get('nodeId') or ''), expected_revision=int(args['expectedRevision']) if args.get('expectedRevision') is not None else None)
        if result.get('ok', True) and args.get('crop') and result.get('selectedNode'):
            node = self.graph.get(str(args.get('nodeId')))
            if node is not None:
                result['crop'] = self.observer.capture_node_crop(node, page=self.attached_page, padding=float(args.get('padding') or 4), prefer=str(args.get('prefer') or 'playwright'))
        return result

    def ui_inspect_frame(self, args: dict[str, Any]) -> dict[str, Any]:
        result=self.ui_frame(args)
        if not result.get('ok', True): return result
        if not result.get('selectedNode'): return {"ok":False,"status":"node_not_found","revision":result.get('revision')}
        return result

    def ui_ls(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 40)
        role = str(args.get("role") or "")
        nodes = self.graph.ls(role=role, limit=limit)
        text = format_compact_listing(self.graph, nodes, label="listed")
        return self._compact_result(text, tool="ui.ls")

    def ui_find(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or args.get("q") or "").strip()
        if not query:
            raise ValueError("ui.find requires query")
        limit = int(args.get("limit") or 20)
        nodes = self.graph.find(query, limit=limit)
        text = format_compact_listing(self.graph, nodes, label="matches")
        return self._compact_result(text, tool="ui.find", extra={"query": query})

    def ui_get(self, args: dict[str, Any]) -> dict[str, Any]:
        node_id = str(args.get("id") or args.get("nodeId") or "").strip()
        if not node_id:
            raise ValueError("ui.get requires id")
        node = self.graph.get(node_id)
        text = format_compact_get(self.graph, node, node_id)
        return self._compact_result(text, tool="ui.get", ok=node is not None)

    def ui_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 80)
        since_rev = args.get("sinceRev")
        text = format_compact_delta(self.graph, limit=limit)
        if since_rev is not None and int(since_rev) >= self.graph.revision:
            text = f"{self.graph.header_line()}\ndelta added=0 changed=0 removed=0\n(no changes since rev={since_rev})"
        return self._compact_result(text, tool="ui.diff")

    def ui_wait(self, args: dict[str, Any]) -> dict[str, Any]:
        """Poll the attached page locally until a compact query appears or disappears."""
        query = str(args.get("query") or args.get("q") or "").strip()
        if not query:
            raise ValueError("ui.wait requires query")
        if self.attached_page is None:
            return self._compact_result(
                f"{self.graph.header_line()}\nwait status=no_page query={query!r}",
                tool="ui.wait",
                ok=False,
                status="no_page",
            )
        state = str(args.get("state") or "present").strip().lower()
        if state not in {"present", "absent"}:
            raise ValueError("ui.wait state must be present or absent")
        timeout_ms = max(0, min(int(args.get("timeoutMs") or 5000), 30000))
        poll_ms = max(25, min(int(args.get("pollMs") or 100), 1000))
        started = time.monotonic()
        last_count = 0
        while True:
            self.observer.observe_playwright_page(self.attached_page)
            last_count = len(self.graph.find(query, limit=2))
            satisfied = last_count > 0 if state == "present" else last_count == 0
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if satisfied:
                return self._compact_result(
                    (
                        f"{self.graph.header_line()}\n"
                        f"wait status=satisfied state={state} query={query!r} "
                        f"matches={last_count} elapsedMs={elapsed_ms}"
                    ),
                    tool="ui.wait",
                    status="satisfied",
                    extra={"query": query, "state": state, "matchCount": last_count, "elapsedMs": elapsed_ms},
                )
            if elapsed_ms >= timeout_ms:
                return self._compact_result(
                    (
                        f"{self.graph.header_line()}\n"
                        f"wait status=timeout state={state} query={query!r} "
                        f"matches={last_count} elapsedMs={elapsed_ms}"
                    ),
                    tool="ui.wait",
                    ok=False,
                    status="timeout",
                    extra={"query": query, "state": state, "matchCount": last_count, "elapsedMs": elapsed_ms},
                )
            self.attached_page.wait_for_timeout(poll_ms)

    @enforced("sv.ui.action-gates")
    def ui_do(self, args: dict[str, Any]) -> dict[str, Any]:
        node_id = str(args.get("id") or args.get("nodeId") or "").strip()
        query = str(args.get("query") or args.get("q") or "").strip()
        action = str(args.get("action") or "click").strip().lower()
        if not node_id and not query:
            raise ValueError("ui.do requires id or query")
        if_rev = args.get("ifRev", args.get("if_rev"))
        if_hash = str(args.get("ifHash") or args.get("if_hash") or "").strip()

        if if_rev is not None and int(if_rev) != self.graph.revision:
            return self._compact_result(
                f"{self.graph.header_line()}\nstale_state expected_rev={if_rev} actual_rev={self.graph.revision}",
                tool="ui.do",
                ok=False,
                status="stale_state",
            )
        if if_hash and if_hash != self.graph.semantic_hash:
            return self._compact_result(
                f"{self.graph.header_line()}\nstale_state expected_hash={if_hash} actual_hash={self.graph.semantic_hash}",
                tool="ui.do",
                ok=False,
                status="stale_state",
            )

        node = self.graph.get(node_id) if node_id else None
        if query:
            matches = self.graph.find(query, limit=2)
            if len(matches) > 1:
                return self._compact_result(
                    f"{self.graph.header_line()}\nambiguous query={query!r} matches={len(matches)}",
                    tool="ui.do",
                    ok=False,
                    status="ambiguous_target",
                    extra={"query": query, "matchCount": len(matches)},
                )
            if len(matches) == 1:
                if node is not None and matches[0].id != node.id:
                    return self._compact_result(
                        f"{self.graph.header_line()}\ntarget_mismatch id={node.id} query={query!r}",
                        tool="ui.do",
                        ok=False,
                        status="target_mismatch",
                    )
                node = matches[0]
                node_id = node.id
        if node is None:
            return self._compact_result(
                f"{self.graph.header_line()}\nmissing target={node_id or query}",
                tool="ui.do",
                ok=False,
                status="missing_node",
            )

        before_revision = self.graph.revision
        result = self.observer.act_on_node(
            node,
            action=action,
            page=self.attached_page,
            value=args.get("value"),
            key=str(args.get("key") or ""),
            option=args.get("option"),
        )
        if not result.get("ok"):
            line = (
                f"{self.graph.header_line()}\n"
                f"action_failed action={action} id={node.id} role={node.role} "
                f"name=\"{node.name}\" status={result.get('status')}"
            )
            return self._compact_result(
                line,
                tool="ui.do",
                ok=False,
                status=str(result.get("status") or "action_failed"),
                extra=result,
            )

        try:
            delay_ms = max(0, min(int(args.get("delayMs") or 120), 5000))
            if delay_ms and self.attached_page is not None:
                self.attached_page.wait_for_timeout(delay_ms)
            delta_text = self.observer.observe_playwright_page(self.attached_page)
        except Exception as exc:  # noqa: BLE001 — mutation happened; return an explicit verification interrupt
            line = (
                f"{self.graph.header_line()}\n"
                f"did action={action} id={node.id} status=verification_failed "
                f"message={str(exc).splitlines()[0][:180]}"
            )
            return self._compact_result(
                line,
                tool="ui.do",
                ok=False,
                status="action_done_observe_failed",
                extra={**result, "actionApplied": True},
            )

        line = (
            f"{self.graph.header_line()}\n"
            f"did action={action} id={node.id} role={node.role} name=\"{node.name}\" "
            f"rev={before_revision}->{self.graph.revision}\n"
            f"{delta_text}"
        )
        return self._compact_result(
            line,
            tool="ui.do",
            status=str(result.get("status") or "acted"),
            extra={**result, "revisionBefore": before_revision, "revisionAfter": self.graph.revision},
        )

    def ui_upload(self, args: dict[str, Any]) -> dict[str, Any]:
        """Attach workspace-bounded files to one real file input and re-observe."""

        if self.attached_page is None:
            return self._compact_result(
                f"{self.graph.header_line()}\nupload status=no_page",
                tool="ui.upload",
                ok=False,
                status="no_page",
            )
        if self.workspace_root is None:
            return self._compact_result(
                f"{self.graph.header_line()}\nupload status=workspace_root_required",
                tool="ui.upload",
                ok=False,
                status="workspace_root_required",
            )
        raw_paths = args.get("paths")
        if not isinstance(raw_paths, list):
            raw_paths = [args.get("path")] if args.get("path") else []
        resolved_paths: list[Path] = []
        for raw_path in raw_paths[:20]:
            candidate = Path(str(raw_path or "")).expanduser()
            if not candidate.is_absolute():
                candidate = self.workspace_root / candidate
            resolved = candidate.resolve()
            try:
                resolved.relative_to(self.workspace_root)
            except ValueError:
                return self._compact_result(
                    f"{self.graph.header_line()}\nupload status=path_outside_workspace",
                    tool="ui.upload",
                    ok=False,
                    status="path_outside_workspace",
                )
            if not resolved.is_file():
                return self._compact_result(
                    f"{self.graph.header_line()}\nupload status=file_missing name={resolved.name!r}",
                    tool="ui.upload",
                    ok=False,
                    status="file_missing",
                )
            resolved_paths.append(resolved)
        if not resolved_paths:
            raise ValueError("ui.upload requires path or paths")

        selector = str(args.get("selector") or "").strip()
        query = str(args.get("query") or args.get("q") or "").strip()
        page = self.attached_page
        if selector:
            target = page.locator(selector)
        elif query:
            matches = self.graph.find(query, limit=2)
            if len(matches) != 1:
                status = "ambiguous_target" if len(matches) > 1 else "missing_target"
                return self._compact_result(
                    f"{self.graph.header_line()}\nupload status={status} query={query!r} matches={len(matches)}",
                    tool="ui.upload",
                    ok=False,
                    status=status,
                )
            target = self.observer._locator_for_node(matches[0], page)
        else:
            target = page.locator('input[type="file"]')
        count = int(target.count())
        if count != 1:
            status = "ambiguous_target" if count > 1 else "missing_target"
            return self._compact_result(
                f"{self.graph.header_line()}\nupload status={status} matches={count}",
                tool="ui.upload",
                ok=False,
                status=status,
            )

        target.first.set_input_files([str(path) for path in resolved_paths], timeout=10000)
        delay_ms = max(0, min(int(args.get("delayMs") or 120), 5000))
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        delta_text = self.observer.observe_playwright_page(page)
        files = [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in resolved_paths
        ]
        return self._compact_result(
            f"{self.graph.header_line()}\nupload status=attached files={len(files)}\n{delta_text}",
            tool="ui.upload",
            status="attached",
            extra={"files": files, "fileCount": len(files)},
        )

    def ui_see(self, args: dict[str, Any]) -> dict[str, Any]:
        """Vision page-fault crop (fallback only). Prefer a11y ui.find/ui.get first."""
        node_id = str(args.get("id") or args.get("nodeId") or "").strip()
        url = str(args.get("url") or self.last_observe_url or self.graph.url or "").strip()
        clip_arg = args.get("clip") if isinstance(args.get("clip"), dict) else None
        padding = float(args.get("padding") if args.get("padding") is not None else 4)
        path_arg = str(args.get("path") or args.get("output") or "").strip()
        prefer = str(args.get("prefer") or "playwright").strip().lower() or "playwright"

        if not node_id and not clip_arg:
            return self._compact_result(
                f"{self.graph.header_line()}\nui.see status=missing_target\nhint=provide id or clip",
                tool="ui.see",
                ok=False,
                status="missing_target",
            )

        from .ui_graph import Bounds, UiNode

        node = self.graph.get(node_id) if node_id else None
        if node is None and clip_arg is not None:
            node = UiNode(
                id=node_id or "clip",
                role="region",
                name="explicit-clip",
                bounds=Bounds(
                    x=float(clip_arg.get("x") or 0),
                    y=float(clip_arg.get("y") or 0),
                    w=float(clip_arg.get("width") or clip_arg.get("w") or 0),
                    h=float(clip_arg.get("height") or clip_arg.get("h") or 0),
                ),
                source="ui.see",
            )
        if node is None:
            lines = [
                self.graph.header_line(),
                "ui.see status=missing_node",
                f"target missing id={node_id}",
            ]
            if url:
                lines.append(f"fallback_url={url}")
                lines.append("hint=use preview.screenshot if a11y target is unavailable")
            return self._compact_result(
                "\n".join(lines),
                tool="ui.see",
                ok=False,
                status="missing_node",
            )

        out_path = Path(path_arg) if path_arg else None
        crop = self.observer.capture_node_crop(
            node,
            page=self.attached_page,
            path=out_path,
            padding=padding,
            clip=clip_arg,
            prefer=prefer,
        )
        if crop.get("ok"):
            line = (
                f"{self.graph.header_line()}\n"
                f"ui.see status=cropped id={node.id} role={node.role} name=\"{node.name}\" "
                f"method={crop.get('method')} path={crop.get('path')} "
                f"clip={crop.get('clip')}"
            )
            return self._compact_result(line, tool="ui.see", status="cropped", extra=crop)

        lines = [
            self.graph.header_line(),
            f"ui.see status={crop.get('status')}",
            f"target id={node.id} role={node.role} name=\"{node.name}\" bounds={node.bounds.compact()}",
            f"message={crop.get('message') or ''}",
        ]
        if url:
            lines.append(f"fallback_url={url}")
            lines.append("hint=attach page via ui.observe or use preview.screenshot")
        return self._compact_result(
            "\n".join(lines),
            tool="ui.see",
            ok=False,
            status=str(crop.get("status") or "crop_failed"),
            extra=crop,
        )

    @enforced("sv.ui.compact-result")
    def _compact_result(
        self,
        text: str,
        *,
        tool: str,
        ok: bool = True,
        status: str = "ok",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": ok,
            "status": status,
            "tool": tool,
            "text": text,
            "revision": self.graph.revision,
            "semanticHash": self.graph.semantic_hash,
            "nodeCount": len(self.graph.nodes),
            # Explicit: never attach full trees.
            "treeOmitted": True,
        }
        if extra:
            payload["detail"] = extra
        return payload


def ui_tool_specs() -> list[dict[str, Any]]:
    """Catalog entries compatible with NativeToolSpec fields (as plain dicts)."""
    return [
        {
            "name": "ui.ls",
            "description": "List a compact subset of the resident browser UI graph (role-filtered). Never dumps the full tree.",
            "category": "ui",
            "capabilities": ("ui.read", "ui.graph"),
            "mutability_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            },
        },
        {
            "name": "ui.find",
            "description": "Query the resident UI graph with compact selectors like button[name~=\"Export\"]. Returns matching lines only.",
            "category": "ui",
            "capabilities": ("ui.read", "ui.query"),
            "mutability_class": "read",
            "aliases": ("find ui", "locate control"),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
        },
        {
            "name": "ui.get",
            "description": "Fetch one UI node by id as a single compact line.",
            "category": "ui",
            "capabilities": ("ui.read",),
            "mutability_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
        {
            "name": "ui.diff",
            "description": "Emit compact added/changed/removed lines since the last observation revision.",
            "category": "ui",
            "capabilities": ("ui.read", "ui.diff"),
            "mutability_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    "sinceRev": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "name": "ui.do",
            "description": "Revision-gated semantic UI action on the resident page. Resolve one id/query, act, then return the compact post-action delta.",
            "category": "ui",
            "capabilities": ("ui.act",),
            "mutability_class": "write",
            "parallel_safe": False,
            "input_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["click", "fill", "press", "select", "toggle"],
                    },
                    "value": {},
                    "key": {"type": "string"},
                    "option": {},
                    "delayMs": {"type": "integer", "minimum": 0, "maximum": 5000},
                    "ifRev": {"type": "integer"},
                    "ifHash": {"type": "string"},
                },
                "anyOf": [{"required": ["id"]}, {"required": ["query"]}],
            },
        },
        {
            "name": "ui.upload",
            "description": "Attach one or more workspace-bounded files to a real file input in the resident page, then return the compact post-upload delta and file hashes.",
            "category": "ui",
            "capabilities": ("ui.act", "browser.upload", "artifact.hash"),
            "mutability_class": "write",
            "parallel_safe": False,
            "input_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "selector": {"type": "string"},
                    "path": {"type": "string"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                    },
                    "delayMs": {"type": "integer", "minimum": 0, "maximum": 5000},
                },
                "anyOf": [{"required": ["path"]}, {"required": ["paths"]}],
            },
        },
        {
            "name": "ui.wait",
            "description": "Poll the resident page locally until one compact UI query is present or absent; returns one result or timeout interrupt.",
            "category": "ui",
            "capabilities": ("ui.read", "ui.wait"),
            "mutability_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "state": {"type": "string", "enum": ["present", "absent"]},
                    "timeoutMs": {"type": "integer", "minimum": 0, "maximum": 30000},
                    "pollMs": {"type": "integer", "minimum": 25, "maximum": 1000},
                },
                "required": ["query"],
            },
        },
        {
            "name": "ui.see",
            "description": "Vision page-fault crop for a node/region (Playwright or CDP clip). Prefer a11y queries; screenshots are fallback-only.",
            "category": "ui",
            "capabilities": ("ui.vision", "image.region"),
            "mutability_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "url": {"type": "string"},
                    "clip": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                    },
                    "path": {"type": "string"},
                    "padding": {"type": "number"},
                    "prefer": {"type": "string", "enum": ["playwright", "cdp"]},
                },
            },
        },
        {
            "name": "ui.observe",
            "description": "Open or refresh a URL in the resident browser session and update the compact accessibility graph (not screenshots).",
            "category": "ui",
            "capabilities": ("ui.observe", "browser.navigate"),
            "mutability_class": "write",
            "parallel_safe": False,
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "delayMs": {"type": "integer"},
                    "waitUntil": {"type": "string"},
                },
            },
        },
        {
            "name": "ui.frame",
            "description": "Return a bounded resident perception frame with graph identity, revision, semantic changes, and optional selected-node crop.",
            "category": "ui", "capabilities": ("ui.frame", "ui.graph", "ui.vision"), "mutability_class": "read",
            "input_schema": {"type":"object", "properties":{"sinceRevision":{"type":"integer"},"expectedRevision":{"type":"integer"},"nodeId":{"type":"string"},"crop":{"type":"boolean"},"padding":{"type":"number"},"prefer":{"type":"string"}}},
        },
        {
            "name": "ui.inspect_frame",
            "description": "Inspect one selected node from the current perception frame and reject stale frame references.",
            "category": "ui", "capabilities": ("ui.frame", "ui.graph"), "mutability_class": "read",
            "input_schema": {"type":"object", "properties":{"nodeId":{"type":"string"},"expectedRevision":{"type":"integer"},"crop":{"type":"boolean"}}, "required":["nodeId"]},
        },
    ]


_DEFAULT_SURFACE: UiToolSurface | None = None
_ROOT_SURFACES: dict[Path, UiToolSurface] = {}


def default_ui_surface(workspace_root: str | Path | None = None) -> UiToolSurface:
    if workspace_root is not None:
        resolved_root = Path(workspace_root).expanduser().resolve()
        surface = _ROOT_SURFACES.get(resolved_root)
        if surface is None:
            surface = UiToolSurface(workspace_root=resolved_root)
            _ROOT_SURFACES[resolved_root] = surface
        return surface
    global _DEFAULT_SURFACE
    if _DEFAULT_SURFACE is None:
        _DEFAULT_SURFACE = UiToolSurface()
    return _DEFAULT_SURFACE


def _compact_handler_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "text": result.get("text", ""),
        "revision": result.get("revision"),
        "semanticHash": result.get("semanticHash"),
        "status": result.get("status"),
        "ok": result.get("ok", True),
        "treeOmitted": True,
        "tool": tool_name,
    }
    if tool_name == "ui.upload" and isinstance(result.get("detail"), dict):
        payload["fileCount"] = int(result["detail"].get("fileCount") or 0)
        payload["files"] = list(result["detail"].get("files") or [])[:20]
    return payload


@enforced("sv.ui.discovery")
def register_with_progressive_surface(surface: Any, ui: UiToolSurface | None = None) -> list[str]:
    """Attach compact ui.* tools onto a ProgressiveToolSurface (live discovery path).

    Specs stay searchable via search→describe→call; full schemas only on describe().
    """
    from .progressive_tools import ProgressiveToolSpec

    ui = ui or default_ui_surface()
    register = getattr(surface, "register", None)
    if not callable(register):
        raise TypeError("progressive surface missing register()")

    registered: list[str] = []
    for spec in ui_tool_specs():
        name = str(spec["name"])

        def _make_handler(tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
            def _handler(args: dict[str, Any]) -> dict[str, Any]:
                return _compact_handler_result(tool_name, ui.call(tool_name, args))

            return _handler

        register(
            ProgressiveToolSpec(
                name=name,
                description=str(spec["description"]),
                category=str(spec.get("category") or "ui"),
                aliases=tuple(spec.get("aliases") or ()),
                input_schema=dict(spec.get("input_schema") or {}),
                annotations={
                    "readOnlyHint": str(spec.get("mutability_class") or "read") == "read",
                    "requiresApproval": str(spec.get("mutability_class") or "read") not in {"read", "none"},
                    "compactOnly": True,
                    "treeOmitted": True,
                },
                permissions=(
                    ("browser.interact",)
                    if str(spec.get("mutability_class") or "read") not in {"read", "none"}
                    else ()
                ),
            ),
            handler=_make_handler(name),
        )
        registered.append(name)
    return registered


@enforced("sv.ui.discovery")
def register_with_native_registry(registry: Any, surface: UiToolSurface | None = None) -> list[str]:
    """Attach ui.* tools onto a NativeToolRegistry when present in the process.

    Safe shape: mutates registry._handlers / registry._specs if those attrs exist.
    Live editable tree may lack native_tools.py; NAS pulls still ship NativeToolRegistry.
    """
    surface = surface or default_ui_surface()
    handlers = getattr(registry, "_handlers", None)
    specs = getattr(registry, "_specs", None)
    if not isinstance(handlers, dict):
        raise TypeError("registry missing _handlers dict")

    NativeToolSpec = None
    try:
        from .native_tools import NativeToolSpec as _Spec  # type: ignore

        NativeToolSpec = _Spec
    except Exception:
        NativeToolSpec = None

    registered: list[str] = []
    for spec in ui_tool_specs():
        name = str(spec["name"])

        def _make_handler(tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
            def _handler(args: dict[str, Any]) -> dict[str, Any]:
                return _compact_handler_result(tool_name, surface.call(tool_name, args))

            return _handler

        handlers[name] = _make_handler(name)
        if isinstance(specs, dict) and NativeToolSpec is not None:
            specs[name] = NativeToolSpec(
                name=name,
                description=str(spec["description"]),
                category=str(spec.get("category") or "ui"),
                input_schema=dict(spec.get("input_schema") or {}),
                aliases=tuple(spec.get("aliases") or ()),
                mutability_class=str(spec.get("mutability_class") or "read"),
                capabilities=tuple(spec.get("capabilities") or ()),
                parallel_safe=bool(spec.get("parallel_safe", True)),
            )
        elif isinstance(specs, dict):
            specs[name] = spec
        registered.append(name)
    return registered


def wire_ui_tools(target: Any, surface: UiToolSurface | None = None) -> list[str]:
    """Register ui.* onto ProgressiveToolSurface or NativeToolRegistry-shaped targets."""
    if hasattr(target, "register") and hasattr(target, "search") and hasattr(target, "describe"):
        return register_with_progressive_surface(target, surface)
    if hasattr(target, "_handlers"):
        return register_with_native_registry(target, surface)
    raise TypeError(f"unsupported ui tool registration target: {type(target)!r}")


def describe_api_surface() -> dict[str, Any]:
    return {
        "schema": "neyvia.ui_graph_tools.v1",
        "tools": [spec["name"] for spec in ui_tool_specs()],
        "compactOnly": True,
        "primaryObservation": "playwright-accessibility-or-cdp-ax",
        "screenshotFallback": "ui.see crop (Playwright/CDP clip) / preview.screenshot",
        "discovery": "progressive search → describe → call (schemas deferred)",
        "specs": ui_tool_specs(),
    }
