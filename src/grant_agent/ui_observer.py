"""Browser-first UI observation adapters (Playwright a11y preferred; CDP AX fallback)."""

from __future__ import annotations

import base64
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .proofs_e_sv import enforced

from .ui_graph import (
    Bounds,
    UiGraph,
    UiNode,
    infer_actions,
    stable_node_id,
)


INTERESTING_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "listbox",
        "option",
        "menuitem",
        "menu",
        "tab",
        "tablist",
        "heading",
        "img",
        "dialog",
        "alertdialog",
        "alert",
        "navigation",
        "main",
        "form",
        "table",
        "row",
        "cell",
        "gridcell",
        "treeitem",
        "slider",
        "spinbutton",
        "progressbar",
        "status",
        "toolbar",
        "tooltip",
    }
)


class ReusableBrowserRuntime:
    """Lightweight Playwright pool (mirrors native_tools.ReusablePlaywrightRuntime)."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._persistent_context: Any = None
        self._persistent_page: Any = None
        self.browser_starts = 0
        self.contexts_created = 0

    def _browser_is_connected(self) -> bool:
        try:
            return bool(self._browser and self._browser.is_connected())
        except Exception:
            return False

    def _ensure_browser(self) -> Any:
        if self._browser_is_connected():
            return self._browser
        self.close()
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_errors: list[str] = []
        # Prefer installed Google Chrome when the Playwright browser cache is missing
        # (common under sandboxed PLAYWRIGHT_BROWSERS_PATH). Fall back to bundled Chromium.
        for kwargs in (
            {"channel": "chrome", "headless": True},
            {"channel": "msedge", "headless": True},
            {"headless": True},
        ):
            try:
                self._browser = self._playwright.chromium.launch(**kwargs)
                self.browser_starts += 1
                return self._browser
            except Exception as exc:  # noqa: BLE001 — try next launch strategy
                launch_errors.append(f"{kwargs}: {exc}")
                self._browser = None
        detail = " | ".join(launch_errors[-3:])
        raise RuntimeError(
            "Unable to launch a Chromium browser for UI observation. "
            "Install Chrome or run `python -m playwright install chromium`. "
            f"Attempts: {detail}"
        )

    @contextmanager
    def page(self, *, width: int = 1440, height: int = 1000) -> Iterator[Any]:
        browser = self._ensure_browser()
        context = browser.new_context(viewport={"width": width, "height": height})
        self.contexts_created += 1
        try:
            yield context.new_page()
        finally:
            try:
                context.close()
            except Exception:
                pass

    def persistent_page(self, *, width: int = 1440, height: int = 1000) -> Any:
        """Return one reusable page for model-facing observe → act sequences."""
        page = self._persistent_page
        if page is not None:
            try:
                if not page.is_closed():
                    return page
            except Exception:
                self._persistent_page = None
        context = self._persistent_context
        self._persistent_context = None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        browser = self._ensure_browser()
        self._persistent_context = browser.new_context(viewport={"width": width, "height": height})
        self.contexts_created += 1
        self._persistent_page = self._persistent_context.new_page()
        return self._persistent_page

    def close(self) -> None:
        context, browser, playwright = self._persistent_context, self._browser, self._playwright
        self._persistent_context = None
        self._persistent_page = None
        self._browser = None
        self._playwright = None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def _states_from_mapping(payload: dict[str, Any]) -> tuple[str, ...]:
    states: list[str] = []
    for key in (
        "disabled",
        "checked",
        "selected",
        "expanded",
        "pressed",
        "readonly",
        "required",
        "focused",
        "hovered",
        "busy",
        "modal",
        "multiline",
        "protected",
        "password",
    ):
        value = payload.get(key)
        if value is True or value == "true":
            states.append(key)
    return tuple(states)


def _bounds_from_mapping(payload: dict[str, Any]) -> Bounds:
    box = payload.get("bounds") or payload.get("rect") or payload.get("boundingBox") or {}
    if not isinstance(box, dict):
        return Bounds()
    return Bounds(
        x=float(box.get("x") or box.get("left") or 0),
        y=float(box.get("y") or box.get("top") or 0),
        w=float(box.get("width") or box.get("w") or 0),
        h=float(box.get("height") or box.get("h") or 0),
    )


@enforced("sv.ui.ax-normalization")
def flatten_playwright_ax(
    snapshot: dict[str, Any] | None,
    *,
    source: str = "playwright-a11y",
    interesting_only: bool = True,
) -> list[UiNode]:
    """Normalize Playwright page.accessibility.snapshot() into UiNodes."""
    if not isinstance(snapshot, dict):
        return []
    nodes: list[UiNode] = []

    def walk(node: dict[str, Any], path: str, parent_id: str) -> None:
        role = str(node.get("role") or "generic").strip() or "generic"
        name = str(node.get("name") or "").strip()
        value = str(node.get("value") or "").strip()
        states = _states_from_mapping(node)
        node_path = f"{path}/{role}:{name}"
        node_id = stable_node_id(role=role, name=name, path=node_path, source=source)
        keep = (not interesting_only) or role.lower() in INTERESTING_ROLES or bool(name)
        if keep and role.lower() not in {"none", "presentation", "inline text box"}:
            actions = infer_actions(role, states)
            nodes.append(
                UiNode(
                    id=node_id,
                    role=role,
                    name=name,
                    states=states,
                    bounds=_bounds_from_mapping(node),
                    actions=actions,
                    source=source,
                    parent_id=parent_id,
                    value=value,
                    backend_ref=str(node.get("backendDOMNodeId") or node.get("nodeId") or ""),
                )
            )
        children = node.get("children") or []
        if isinstance(children, list):
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    walk(child, f"{node_path}[{index}]", node_id if keep else parent_id)

    walk(snapshot, "root", "")
    return nodes


@enforced("sv.ui.ax-normalization")
def flatten_cdp_ax_tree(
    ax_nodes: list[dict[str, Any]],
    *,
    source: str = "cdp-ax",
    interesting_only: bool = True,
) -> list[UiNode]:
    """Normalize CDP Accessibility.getFullAXTree nodes into UiNodes."""
    by_id: dict[str, dict[str, Any]] = {}
    for raw in ax_nodes:
        node_id = str(raw.get("nodeId") or "")
        if node_id:
            by_id[node_id] = raw

    nodes: list[UiNode] = []
    for raw in ax_nodes:
        role_obj = raw.get("role") or {}
        name_obj = raw.get("name") or {}
        value_obj = raw.get("value") or {}
        role = str(role_obj.get("value") if isinstance(role_obj, dict) else role_obj or "generic")
        name = str((name_obj.get("value") if isinstance(name_obj, dict) else name_obj) or "")
        value = str((value_obj.get("value") if isinstance(value_obj, dict) else value_obj) or "")
        role = role.strip() or "generic"
        name = name.strip()
        value = value.strip()
        props = {
            str(prop.get("name")): prop.get("value")
            for prop in (raw.get("properties") or [])
            if isinstance(prop, dict)
        }
        states: list[str] = []
        for key in ("disabled", "checked", "selected", "expanded", "pressed", "readonly", "required", "focused", "modal", "protected", "password"):
            prop = props.get(key)
            if isinstance(prop, dict) and prop.get("value") in (True, "true"):
                states.append(key)
            elif prop in (True, "true"):
                states.append(key)
        if interesting_only and role.lower() not in INTERESTING_ROLES and not name:
            continue
        if role.lower() in {"none", "ignored", "generic"} and not name:
            continue
        node_id_raw = str(raw.get("nodeId") or "")
        parent_id_raw = str(raw.get("parentId") or "")
        path = f"cdp/{node_id_raw}"
        node_id = stable_node_id(role=role, name=name or node_id_raw, path=path, source=source)
        parent_stable = ""
        if parent_id_raw and parent_id_raw in by_id:
            parent = by_id[parent_id_raw]
            parent_role = parent.get("role") or {}
            parent_name = parent.get("name") or {}
            prole = str(parent_role.get("value") if isinstance(parent_role, dict) else parent_role or "generic")
            pname = str(parent_name.get("value") if isinstance(parent_name, dict) else parent_name or "")
            parent_stable = stable_node_id(
                role=prole,
                name=pname or parent_id_raw,
                path=f"cdp/{parent_id_raw}",
                source=source,
            )
        nodes.append(
            UiNode(
                id=node_id,
                role=role,
                name=name,
                states=tuple(states),
                bounds=Bounds(),  # CDP AX tree often omits boxes without DOM resolve
                actions=infer_actions(role, states),
                source=source,
                parent_id=parent_stable,
                value=value,
                backend_ref=node_id_raw,
            )
        )
    return nodes


class UiObserver:
    """Resident observer: keep a UiGraph warm from browser a11y snapshots."""

    def __init__(
        self,
        *,
        browser_runtime: ReusableBrowserRuntime | Any | None = None,
        graph: UiGraph | None = None,
    ) -> None:
        self.browser_runtime = browser_runtime or ReusableBrowserRuntime()
        self.graph = graph or UiGraph()
        self._owns_runtime = browser_runtime is None

    def close(self) -> None:
        if self._owns_runtime and hasattr(self.browser_runtime, "close"):
            self.browser_runtime.close()

    def ingest_nodes(
        self,
        nodes: list[UiNode],
        *,
        url: str = "",
        title: str = "",
        source: str = "browser",
    ) -> str:
        self.graph.replace_nodes(nodes, url=url, title=title, source=source)
        from .ui_graph import format_compact_delta

        return format_compact_delta(self.graph)

    def observe_playwright_page(self, page: Any, *, interesting_only: bool = True) -> str:
        nodes: list[UiNode] = []
        source = "playwright-a11y"
        # Playwright removed page.accessibility; prefer CDP AX, then ariaSnapshot fallback.
        accessibility = getattr(page, "accessibility", None)
        if accessibility is not None and hasattr(accessibility, "snapshot"):
            snapshot = accessibility.snapshot()
            nodes = flatten_playwright_ax(snapshot, interesting_only=interesting_only)
        else:
            ax_nodes = self._cdp_ax_nodes_from_page(page)
            if ax_nodes:
                nodes = flatten_cdp_ax_tree(ax_nodes, interesting_only=interesting_only)
                source = "cdp-ax"
            else:
                nodes = self._nodes_from_aria_snapshot(page, interesting_only=interesting_only)
                source = "aria-snapshot"
        url = ""
        title = ""
        try:
            url = str(page.url or "")
            title = str(page.title() or "")
        except Exception:
            pass
        return self.ingest_nodes(nodes, url=url, title=title, source=source)

    @staticmethod
    def _cdp_ax_nodes_from_page(page: Any) -> list[dict[str, Any]]:
        session = None
        try:
            context = page.context
            new_cdp = getattr(context, "new_cdp_session", None)
            if not callable(new_cdp):
                return []
            session = new_cdp(page)
            try:
                session.send("Accessibility.enable")
            except Exception:
                pass
            result = session.send("Accessibility.getFullAXTree")
            nodes = result.get("nodes") if isinstance(result, dict) else None
            if isinstance(nodes, list):
                return [node for node in nodes if isinstance(node, dict)]
            return []
        except Exception:
            return []
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass

    @staticmethod
    def _nodes_from_aria_snapshot(page: Any, *, interesting_only: bool = True) -> list[UiNode]:
        """Best-effort parse of page.locator('body').aria_snapshot() YAML-ish lines."""
        try:
            body = page.locator("body")
            snap = body.aria_snapshot() if hasattr(body, "aria_snapshot") else None
        except Exception:
            snap = None
        if not isinstance(snap, str) or not snap.strip():
            # Last resort: collect common interactive roles via locators.
            return UiObserver._nodes_from_role_scan(page)
        nodes: list[UiNode] = []
        for index, raw_line in enumerate(snap.splitlines()):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Typical: `- button "Sign in" [disabled]` or `- heading "N-E-Y-V-I-A" [level=2]`
            match = re.match(
                r"^-\s*(?P<role>[a-zA-Z0-9_-]+)(?:\s+\"(?P<name>[^\"]*)\")?",
                line,
            )
            if not match:
                continue
            role = match.group("role") or "generic"
            name = match.group("name") or ""
            if interesting_only and role.lower() not in INTERESTING_ROLES and not name:
                continue
            path = f"aria/{index}/{role}:{name}"
            node_id = stable_node_id(role=role, name=name, path=path, source="aria-snapshot")
            states: list[str] = []
            if "[disabled]" in line:
                states.append("disabled")
            if "[checked]" in line:
                states.append("checked")
            nodes.append(
                UiNode(
                    id=node_id,
                    role=role,
                    name=name,
                    states=tuple(states),
                    actions=infer_actions(role, states),
                    source="aria-snapshot",
                )
            )
        return nodes or UiObserver._nodes_from_role_scan(page)

    @staticmethod
    def _nodes_from_role_scan(page: Any) -> list[UiNode]:
        roles = ("button", "link", "textbox", "heading", "tab", "navigation", "main", "img")
        nodes: list[UiNode] = []
        for role in roles:
            try:
                locator = page.get_by_role(role)
                count = min(int(locator.count()), 40)
            except Exception:
                continue
            for index in range(count):
                try:
                    item = locator.nth(index)
                    name = str(item.get_attribute("aria-label") or item.inner_text(timeout=500) or "").strip()
                    name = " ".join(name.split())[:80]
                except Exception:
                    name = ""
                path = f"role-scan/{role}/{index}:{name}"
                node_id = stable_node_id(role=role, name=name, path=path, source="role-scan")
                nodes.append(
                    UiNode(
                        id=node_id,
                        role=role,
                        name=name,
                        actions=infer_actions(role, ()),
                        source="role-scan",
                    )
                )
        return nodes

    def observe_url(
        self,
        url: str,
        *,
        width: int = 1440,
        height: int = 1000,
        wait_until: str = "domcontentloaded",
        delay_ms: int = 200,
        interesting_only: bool = True,
    ) -> str:
        """Navigate with Playwright and refresh the resident graph from a11y snapshot."""
        page_cm = getattr(self.browser_runtime, "page", None)
        if page_cm is None:
            raise RuntimeError("browser_runtime does not provide a page() context manager")
        with page_cm(width=width, height=height) as page:
            page.goto(url, wait_until=wait_until, timeout=30000)
            if delay_ms:
                page.wait_for_timeout(delay_ms)
            return self.observe_playwright_page(page, interesting_only=interesting_only)

    def observe_cdp_ax(self, ax_nodes: list[dict[str, Any]], *, url: str = "", title: str = "") -> str:
        nodes = flatten_cdp_ax_tree(ax_nodes)
        return self.ingest_nodes(nodes, url=url, title=title, source="cdp-ax")

    def resolve_clip_rect(
        self,
        node: UiNode,
        *,
        page: Any | None = None,
        padding: float = 4.0,
        clip: dict[str, Any] | None = None,
    ) -> dict[str, float] | None:
        """Resolve a screenshot clip rect from explicit clip, node bounds, or Playwright box."""
        if isinstance(clip, dict):
            try:
                return {
                    "x": max(0.0, float(clip.get("x") or 0)),
                    "y": max(0.0, float(clip.get("y") or 0)),
                    "width": max(1.0, float(clip.get("width") or clip.get("w") or 1)),
                    "height": max(1.0, float(clip.get("height") or clip.get("h") or 1)),
                }
            except (TypeError, ValueError):
                return None
        if node.bounds.w > 0 and node.bounds.h > 0:
            pad = max(0.0, float(padding))
            return {
                "x": max(0.0, float(node.bounds.x) - pad),
                "y": max(0.0, float(node.bounds.y) - pad),
                "width": max(1.0, float(node.bounds.w) + (2 * pad)),
                "height": max(1.0, float(node.bounds.h) + (2 * pad)),
            }
        if page is None:
            return None
        try:
            locator = (
                page.get_by_role(node.role, name=node.name)
                if node.name
                else page.get_by_role(node.role)
            )
            box = locator.first.bounding_box(timeout=3000)
            if not isinstance(box, dict):
                return None
            pad = max(0.0, float(padding))
            return {
                "x": max(0.0, float(box.get("x") or 0) - pad),
                "y": max(0.0, float(box.get("y") or 0) - pad),
                "width": max(1.0, float(box.get("width") or 1) + (2 * pad)),
                "height": max(1.0, float(box.get("height") or 1) + (2 * pad)),
            }
        except Exception:
            return None

    def capture_node_crop(
        self,
        node: UiNode,
        *,
        page: Any | None = None,
        path: str | Path | None = None,
        padding: float = 4.0,
        clip: dict[str, Any] | None = None,
        prefer: str = "playwright",
    ) -> dict[str, Any]:
        """Capture a vision page-fault crop via Playwright clip or CDP Page.captureScreenshot.

        Fallback-only observation path — prefer ui.find/ui.get over screenshots.
        """
        rect = self.resolve_clip_rect(node, page=page, padding=padding, clip=clip)
        if rect is None:
            return {
                "ok": False,
                "status": "no_clip",
                "message": "ui.see needs bounds, explicit clip, or an attached page with a locatable node",
                "id": node.id,
            }
        if page is None:
            # Both capture methods need an attached page; fail closed without
            # creating an empty crop directory in the process working tree.
            return {
                "ok": False,
                "status": "crop_failed",
                "message": "playwright:no_page; cdp:no_session_or_empty",
                "id": node.id,
                "clip": rect,
            }
        out_path = Path(path) if path else None
        if out_path is None:
            crop_dir = Path(".agent_control") / "mission_artifacts" / "context_microkernel" / "ui_crops"
            # Prefer writing beside the process CWD; callers may override path.
            out_path = crop_dir / f"crop_{node.id[:16]}_{uuid.uuid4().hex[:8]}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        order = ["playwright", "cdp"] if prefer != "cdp" else ["cdp", "playwright"]
        errors: list[str] = []
        for method in order:
            try:
                if method == "playwright":
                    if page is None:
                        errors.append("playwright:no_page")
                        continue
                    page.screenshot(path=str(out_path), clip=rect, type="png")
                    return {
                        "ok": True,
                        "status": "cropped",
                        "id": node.id,
                        "path": str(out_path),
                        "clip": rect,
                        "method": "playwright",
                        "role": node.role,
                        "name": node.name,
                    }
                # CDP path: Playwright CDP session when available, else raw Cdp helper.
                png_bytes: bytes | None = None
                if page is not None and hasattr(page, "context") and hasattr(page.context, "new_cdp_session"):
                    session = page.context.new_cdp_session(page)
                    try:
                        result = session.send(
                            "Page.captureScreenshot",
                            {
                                "format": "png",
                                "clip": {
                                    "x": rect["x"],
                                    "y": rect["y"],
                                    "width": rect["width"],
                                    "height": rect["height"],
                                    "scale": 1,
                                },
                                "fromSurface": True,
                            },
                        )
                        data = result.get("data") if isinstance(result, dict) else None
                        if isinstance(data, str) and data:
                            png_bytes = base64.b64decode(data)
                    finally:
                        try:
                            session.detach()
                        except Exception:
                            pass
                if png_bytes is None:
                    errors.append("cdp:no_session_or_empty")
                    continue
                out_path.write_bytes(png_bytes)
                return {
                    "ok": True,
                    "status": "cropped",
                    "id": node.id,
                    "path": str(out_path),
                    "clip": rect,
                    "method": "cdp",
                    "role": node.role,
                    "name": node.name,
                }
            except Exception as exc:  # noqa: BLE001 — keep ui.see compact
                errors.append(f"{method}:{str(exc).splitlines()[0][:160]}")
        return {
            "ok": False,
            "status": "crop_failed",
            "message": "; ".join(errors)[:400] or "crop failed",
            "id": node.id,
            "clip": rect,
        }

    @staticmethod
    def _locator_for_node(node: UiNode, page: Any) -> Any:
        return page.get_by_role(node.role, name=node.name, exact=True) if node.name else page.get_by_role(node.role)

    def act_on_node(
        self,
        node: UiNode,
        *,
        action: str,
        page: Any | None = None,
        value: Any = None,
        key: str = "",
        option: Any = None,
    ) -> dict[str, Any]:
        """Perform one semantic action on an attached page without returning input values."""
        action = (action or "click").strip().lower()
        allowed = set(node.actions)
        if action == "press" and node.role.lower() in {"textbox", "searchbox", "spinbutton", "combobox"}:
            allowed.add("press")
        if action not in allowed:
            return {"ok": False, "status": "unsupported_action", "action": action, "id": node.id}
        if "disabled" in {state.lower() for state in node.states}:
            return {
                "ok": False,
                "status": "disabled",
                "message": f"target node reports disabled state; {action} skipped",
                "id": node.id,
            }
        if page is None:
            return {
                "ok": False,
                "status": "no_page",
                "message": "ui.do requires a resident attached page; call ui.observe with a URL first.",
                "id": node.id,
            }
        try:
            locator = self._locator_for_node(node, page)
            count = int(locator.count())
            if count != 1:
                return {
                    "ok": False,
                    "status": "ambiguous_target" if count > 1 else "missing_target",
                    "message": f"semantic locator resolved to {count} elements",
                    "id": node.id,
                    "matchCount": count,
                }
            target = locator.first
            try:
                if hasattr(target, "is_enabled") and not target.is_enabled():
                    return {
                        "ok": False,
                        "status": "disabled",
                        "message": "playwright reports control disabled",
                        "id": node.id,
                    }
            except Exception:
                pass
            if action == "click":
                target.click(timeout=10000)
                status = "clicked"
            elif action == "fill":
                if value is None:
                    return {"ok": False, "status": "missing_value", "action": action, "id": node.id}
                target.fill(str(value), timeout=10000)
                status = "filled"
            elif action == "press":
                if not key:
                    return {"ok": False, "status": "missing_key", "action": action, "id": node.id}
                target.press(key, timeout=10000)
                status = "pressed"
            elif action == "select":
                if option is None:
                    return {"ok": False, "status": "missing_option", "action": action, "id": node.id}
                target.select_option(option, timeout=10000)
                status = "selected"
            elif action == "toggle":
                checked = value if isinstance(value, bool) else None
                if checked is None:
                    target.click(timeout=10000)
                elif checked:
                    target.check(timeout=10000)
                else:
                    target.uncheck(timeout=10000)
                status = "toggled"
            else:
                return {"ok": False, "status": "unsupported_action", "action": action, "id": node.id}
            return {
                "ok": True,
                "status": status,
                "action": action,
                "id": node.id,
                "role": node.role,
                "name": node.name,
            }
        except Exception as exc:  # noqa: BLE001 — keep ui.do compact; never raise into model path
            return {
                "ok": False,
                "status": f"{action}_failed",
                "message": str(exc).splitlines()[0][:240],
                "id": node.id,
            }

    def click_node(self, node: UiNode, *, page: Any | None = None) -> dict[str, Any]:
        """Compatibility wrapper for older callers."""
        return self.act_on_node(node, action="click", page=page)
