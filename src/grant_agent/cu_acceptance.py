"""Standalone structured Computer Use acceptance for N-E-Y-V-I-A.

Drives the live control / login surface via UiObserver + UiToolSurface compact tools.
Screenshots are not the primary observation path. Receipts are compact JSON under
``.agent_control/mission_artifacts/cu_acceptance/``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ui_tools import UiToolSurface

SCHEMA = "neyvia.cu_acceptance.v2"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1420
CONTROL_PATH = "/control"
PREVIEW_CONTROL_QUERY = "preview-control=1&fixture=live_review&mode=builder&surface=home"

# Landmark queries used against compact ui.find (not full trees).
LOGIN_LANDMARK_QUERIES = (
    'heading[name~="N-E-Y-V-I-A"]',
    'button[name~="Sign in"]',
    'textbox[name~="Username"]',
    'textbox[name~="Password"]',
    "N-E-Y-V-I-A",
)
CONTROL_LANDMARK_QUERIES = (
    "N-E-Y-V-I-A",
    "Neyvia",
    "Neyvia command composer",
    "Chat",
    "Orchestration",
    "Agent",
    "Builder",
)
PRODUCT_MODE_LANDMARK_QUERIES = (
    'button[name="Open Neyvia Chat"]',
    'button[name="New Orchestration from conversations"]',
    "Open Neyvia Chat",
    "New Orchestration from conversations",
    "Chat",
    "Orchestration",
    "New Chat",
    "New Orchestration",
    "Neyvia Chat",
)
HARNESSES_LANDMARK_QUERIES = (
    "Harnesses",
    "Harness parity matrix",
    'button[name="Open Settings from conversations"]',
    "Runtimes & Rooms",
    "Syntelos Hybrid",
    "Use Syntelos Hybrid",
    "Mission planning and resume",
    "Planner/executor/verifier lanes",
    "Phone/tablet web supervision",
)
LIBRARY_OR_PREVIEW_LANDMARK_QUERIES = (
    'button[name="Open Workflows"]',
    "Your skills",
    "User skill library editor",
    "Curated library",
    "Preview",
    "Live Preview Side Panel",
    "Interface Preview",
    "Open Workflows",
    "Workflows",
    "Skills",
)

# Surface-rail acceptance starts once and proves real clicks. Direct-loading each
# destination first would only prove fixture routing, not Computer Use.
SURFACE_NAV_STEPS: tuple[dict[str, Any], ...] = (
    {
        "label": "Orchestration",
        "click": ('button[name="New Orchestration from conversations"]',),
        "expect": (
            "New orchestration",
            "What should the team finish?",
        ),
    },
    {
        "label": "Workflows",
        "click": ('button[name="Open Workflows"]',),
        "expect": (
            "Start from a sequence that already works.",
            "Workflows",
        ),
    },
    {
        "label": "Settings",
        "click": ('button[name="Open Settings from conversations"]',),
        "expect": ("Settings categories", "Rules & Routing", "Runtimes & Rooms"),
    },
)

CANONICAL_FLOWS = (
    "login_session",
    "control_room",
    "diff_reload",
    "product_mode_switch",
    "harnesses_surface",
    "library_or_preview",
    "surface_navigation",
)

FLOW_ALIASES = {
    **{name: name for name in CANONICAL_FLOWS},
    "login_session_smoke": "login_session",
    "control_room_smoke": "control_room",
    "diff_reload_smoke": "diff_reload",
    "product_mode_switch_smoke": "product_mode_switch",
    "harnesses_surface_smoke": "harnesses_surface",
    "library_or_preview_smoke": "library_or_preview",
    "surface_nav_interaction_smoke": "surface_navigation",
}

SKIP_REASON_AUTH_REQUIRED = (
    "Post-login product chrome requires an authenticated session, but "
    "NEYVIA_CU_USERNAME/NEYVIA_CU_PASSWORD (or FLUXIO_CU_*) credentials are not set. "
    "Pre-login landmarks were still asserted. Set credentials or use preview-control=1 "
    "dev fixture to exercise Chat|Orchestration / Harnesses / Library|Preview without auth."
)

START_SERVER_HINT = (
    "Start the Neyvia control UI, then re-run CU acceptance:\n"
    "  cd <repo> && npm run frontend:dev\n"
    "  # serves http://127.0.0.1:1420 (see vite.config.mjs / src-tauri tauri.conf.json)\n"
    "  # Browser: system Chrome/Edge preferred; else `python -m playwright install chromium`\n"
    "  # If PLAYWRIGHT_BROWSERS_PATH points at a broken sandbox cache, unset it.\n"
    "  npm run verify:cu\n"
    "  # direct: python -m grant_agent.cu_acceptance\n"
    "Optional preview control URL:\n"
    f"  http://{DEFAULT_HOST}:{DEFAULT_PORT}{CONTROL_PATH}?{PREVIEW_CONTROL_QUERY}"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def receipt_dir(root: Path | None = None) -> Path:
    base = root or repo_root()
    out = base / ".agent_control" / "mission_artifacts" / "cu_acceptance"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_base_urls() -> list[str]:
    """Discover likely local control bases from env, vite/tauri defaults, and docs."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        cleaned = (url or "").strip().rstrip("/")
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        ordered.append(cleaned)

    for key in ("NEYVIA_CONTROL_BASE", "FLUXIO_CONTROL_BASE", "TAURI_DEV_URL", "VITE_DEV_SERVER_URL"):
        add(os.environ.get(key) or "")

    port = int(os.environ.get("TAURI_DEV_PORT") or os.environ.get("NEYVIA_DEV_PORT") or DEFAULT_PORT)
    host = os.environ.get("TAURI_DEV_HOST") or DEFAULT_HOST
    add(f"http://{host}:{port}")

    # package.json / LIVE_UI / tauri defaults — keep 1420 primary; also try common Vite alt.
    add(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    add(f"http://{DEFAULT_HOST}:5174")
    add(f"http://{DEFAULT_HOST}:5173")

    # Soft-read vite / tauri configs when present (no import side effects).
    root = repo_root()
    for relative in ("vite.config.mjs", "src-tauri/tauri.conf.json", "docs/LIVE_UI_DEVELOPMENT.md"):
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r"https?://127\.0\.0\.1:\d+", text):
            add(match.group(0))
        for match in re.finditer(r"""["']devUrl["']\s*:\s*["'](https?://[^"']+)["']""", text):
            add(match.group(1))
        for match in re.finditer(r"""port\s*[:=]\s*(?:Number\([^)]*["']|["'])?(\d{2,5})""", text):
            add(f"http://{DEFAULT_HOST}:{match.group(1)}")

    return ordered


def probe_http(url: str, *, timeout: float = 1.5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if 200 <= status < 500:
                return True, f"http {status}"
            return False, f"http {status}"
    except urllib.error.HTTPError as exc:
        # Vite may 404 some paths but still be up; treat any HTTP response as alive.
        if exc.code:
            return True, f"http {exc.code}"
        return False, str(exc)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def find_live_base_url(*, timeout: float = 1.5, discovery_urls: list[str] | tuple[str, ...] | None = None) -> str | None:
    for base in discover_base_urls() if discovery_urls is None else discovery_urls:
        ok, _ = probe_http(base + "/", timeout=timeout)
        if ok:
            return base
        ok, _ = probe_http(base + CONTROL_PATH, timeout=timeout)
        if ok:
            return base
    return None


def skip_reason_no_server(discovery_urls: list[str] | tuple[str, ...] | None = None) -> str:
    tried = ", ".join((discover_base_urls() if discovery_urls is None else discovery_urls)[:4])
    result = (
        f"Neyvia control server not reachable (tried {tried}). "
        f"{START_SERVER_HINT}"
    )
    from .proofs_a_control import require
    require("npm run frontend:dev" in result and "npm run verify:cu" in result
            and "pytest" not in result.lower() and f"{DEFAULT_HOST}:{DEFAULT_PORT}" in result,
            "control.cu-recovery", "unavailable-server response omitted standalone recovery commands or default URL")
    return result


def login_url(base: str) -> str:
    return f"{base.rstrip('/')}{CONTROL_PATH}"


def control_preview_url(base: str, *, surface: str = "", extra_query: str = "") -> str:
    query = PREVIEW_CONTROL_QUERY
    if surface:
        # Override surface=… while keeping preview-control + fixture.
        parts = []
        for chunk in query.split("&"):
            if chunk.startswith("surface="):
                continue
            parts.append(chunk)
        parts.append(f"surface={surface}")
        query = "&".join(parts)
    if extra_query:
        query = f"{query}&{extra_query.lstrip('&')}"
    return f"{base.rstrip('/')}{CONTROL_PATH}?{query}"


def login_credentials_from_env() -> tuple[str, str] | None:
    user = (
        os.environ.get("NEYVIA_CU_USERNAME")
        or os.environ.get("FLUXIO_CU_USERNAME")
        or os.environ.get("NEYVIA_USERNAME")
        or ""
    ).strip()
    password = (
        os.environ.get("NEYVIA_CU_PASSWORD")
        or os.environ.get("FLUXIO_CU_PASSWORD")
        or os.environ.get("NEYVIA_PASSWORD")
        or ""
    ).strip()
    if user and password:
        return user, password
    return None


def compact_match_summary(surface: UiToolSurface, query: str, *, limit: int = 8) -> dict[str, Any]:
    result = surface.call("ui.find", {"query": query, "limit": limit})
    names: list[str] = []
    roles: list[str] = []
    for line in str(result.get("text") or "").splitlines():
        # compact line: id role "name" ...
        if line.startswith("rev=") or line.startswith("matches="):
            continue
        parts = line.split(" ", 2)
        if len(parts) >= 2:
            roles.append(parts[1])
        if '"' in line:
            try:
                names.append(line.split('"', 2)[1])
            except IndexError:
                pass
    return {
        "query": query,
        "ok": bool(result.get("ok", True)),
        "matchCount": _match_count_from_text(result.get("text")),
        "sampleNames": names[:5],
        "sampleRoles": roles[:5],
        "revision": result.get("revision"),
        "textHead": "\n".join(str(result.get("text") or "").splitlines()[:6]),
    }


def _match_count_from_text(text: Any) -> int:
    for line in str(text or "").splitlines():
        if line.startswith("matches="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return 0
    return 0


_RECEIPT_LOCKS = tuple(threading.RLock() for _ in range(64))


def write_receipt(flow: str, payload: dict[str, Any], *, root: Path | None = None) -> Path:
    from .harness_jobs import _exclusive_job_lock
    out_dir = receipt_dir(root)
    latest = out_dir / f"{flow}_latest.json"
    lock = _RECEIPT_LOCKS[hash(str(latest.resolve()).casefold()) % len(_RECEIPT_LOCKS)]
    with lock, _exclusive_job_lock(latest, timeout_seconds=30):
        return _write_receipt_locked(flow, payload, out_dir)


def _write_receipt_locked(flow: str, payload: dict[str, Any], out_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{flow}_{stamp}_{uuid.uuid4().hex[:12]}.json"
    body = {
        "schema": SCHEMA,
        "flow": flow,
        "writtenAt": _utc_now(),
        "treeOmitted": True,
        **payload,
    }
    # Hard guard: never persist giant trees.
    body.pop("nodes", None)
    body.pop("tree", None)
    body.pop("accessibilityTree", None)
    from .durability import atomic_write_text
    encoded = json.dumps(body, indent=2, ensure_ascii=True) + "\n"
    atomic_write_text(path, encoded)
    latest = out_dir / f"{flow}_latest.json"
    atomic_write_text(latest, encoded)
    from .proofs_a_control import require
    stored = json.loads(path.read_text(encoding="utf-8"))
    require(not {"nodes", "tree", "accessibilityTree"} & stored.keys()
            and all(stored.get(key) == value for key, value in payload.items() if key not in {"nodes", "tree", "accessibilityTree"})
            and latest.read_bytes() == path.read_bytes(), "control.cu-receipt", "compact CU receipt changed accepted fields, persisted giant tree or lost latest mirror")
    return path


@dataclass
class CuAcceptanceRunner:
    """Session helper: keep one Playwright page attached for observe/find/diff/do."""

    surface: UiToolSurface = field(default_factory=UiToolSurface)
    base_url: str = ""
    width: int = 1440
    height: int = 1000

    def close(self) -> None:
        self.surface.close()

    def run_with_page(self, fn: Any) -> Any:
        page_cm = self.surface.observer.browser_runtime.page
        with page_cm(width=self.width, height=self.height) as page:
            self.surface.attached_page = page
            try:
                return fn(page)
            finally:
                self.surface.attached_page = None

    def observe(self, page: Any, url: str, *, delay_ms: int = 400) -> dict[str, Any]:
        return self.surface.observe_page(
            page,
            url=url,
            wait_until="domcontentloaded",
            delay_ms=delay_ms,
        )

    def find_landmarks(self, queries: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
        return [compact_match_summary(self.surface, query) for query in queries]

    def any_landmark_hit(self, matches: list[dict[str, Any]]) -> bool:
        return any(int(item.get("matchCount") or 0) > 0 for item in matches)

    def landmark_hit(self, matches: list[dict[str, Any]], *needles: str) -> bool:
        lowered = {str(item.get("query") or "").lower(): int(item.get("matchCount") or 0) for item in matches}
        for needle in needles:
            key = needle.lower()
            for query, count in lowered.items():
                if key in query and count > 0:
                    return True
        return False

    def looks_like_login_wall(self, matches: list[dict[str, Any]]) -> bool:
        return self.landmark_hit(matches, "Sign in", "Username", "Password") and not self.landmark_hit(
            matches, "Open Neyvia Chat", "New Orchestration", "New Chat"
        )

    def looks_like_app_chrome(self, matches: list[dict[str, Any]]) -> bool:
        return self.landmark_hit(
            matches,
            "Open Neyvia Chat",
            "New Orchestration from conversations",
            "New Chat",
            "New Orchestration",
            "Neyvia Chat",
            "Settings",
            "Open Workflows",
        ) or (
            self.landmark_hit(matches, "Chat")
            and self.landmark_hit(matches, "Orchestration")
            and not self.landmark_hit(matches, "Sign in to")
        )

    def _click_first(self, *queries: str) -> dict[str, Any] | None:
        for query in queries:
            candidates = self.surface.graph.find(query, limit=2)
            if len(candidates) != 1:
                continue
            return self.surface.call(
                "ui.do",
                {
                    "query": query,
                    "action": "click",
                    "ifRev": self.surface.graph.revision,
                    "ifHash": self.surface.graph.semantic_hash,
                },
            )
        return None

    def _observe_pre_login(self, page: Any) -> dict[str, Any]:
        url = login_url(self.base_url)
        observe = self.observe(page, url, delay_ms=400)
        matches = self.find_landmarks(LOGIN_LANDMARK_QUERIES)
        if not self.any_landmark_hit(matches):
            matches.extend(self.find_landmarks(("Sign in", "Username", "Password", "Local account")))
        return {
            "url": url,
            "revision": observe.get("revision"),
            "matches": matches,
            "hit": self.any_landmark_hit(matches),
            "observeTextHead": "\n".join(str(observe.get("text") or "").splitlines()[:6]),
        }

    def login_session(self, page: Any) -> dict[str, Any]:
        url = login_url(self.base_url)
        observe = self.observe(page, url)
        matches = self.find_landmarks(LOGIN_LANDMARK_QUERIES)
        # Soft free-text fallbacks if structured a11y names differ.
        if not self.any_landmark_hit(matches):
            matches.extend(
                self.find_landmarks(("Sign in", "Username", "Password", "Local account"))
            )
        passed = self.any_landmark_hit(matches) and int(observe.get("revision") or 0) >= 1
        # Revision-gated ui.do against a Sign-in button when present (may be disabled).
        do_result: dict[str, Any] | None = None
        sign_in = self.surface.graph.find('button[name~="Sign in"]', limit=1)
        if sign_in:
            do_result = self.surface.call(
                "ui.do",
                {
                    "id": sign_in[0].id,
                    "action": "click",
                    "ifRev": self.surface.graph.revision,
                    "ifHash": self.surface.graph.semantic_hash,
                },
            )
        return {
            "pass": passed,
            "url": url,
            "revision": observe.get("revision"),
            "semanticHash": observe.get("semanticHash"),
            "nodeCount": observe.get("nodeCount"),
            "matches": matches,
            "observeTextHead": "\n".join(str(observe.get("text") or "").splitlines()[:8]),
            "uiDo": {
                "attempted": do_result is not None,
                "ok": bool(do_result.get("ok")) if do_result else None,
                "status": do_result.get("status") if do_result else None,
            },
            "treeOmitted": True,
        }

    def control_room(self, page: Any) -> dict[str, Any]:
        url = control_preview_url(self.base_url)
        observe = self.observe(page, url, delay_ms=700)
        matches = self.find_landmarks(CONTROL_LANDMARK_QUERIES)
        if not self.any_landmark_hit(matches):
            # Preview shell may still expose login if DEV flag missing; accept login landmarks.
            matches.extend(self.find_landmarks(LOGIN_LANDMARK_QUERIES))
        ls_result = self.surface.call("ui.ls", {"limit": 20})
        first_rev = int(self.surface.graph.revision)
        # Reload / second observe → compact diff must work.
        observe2 = self.observe(page, url, delay_ms=400)
        ready = self.surface.call(
            "ui.wait",
            {"query": 'button[name="Open Settings from conversations"]', "timeoutMs": 5000, "pollMs": 100},
        )
        diff = self.surface.call("ui.diff", {"limit": 40, "sinceRev": first_rev - 1 if first_rev else 0})
        second_rev = int(self.surface.graph.revision)
        do_result = self._click_first('button[name="Open Settings from conversations"]')
        destination_matches = self.find_landmarks(("Settings categories", "Rules & Routing"))
        passed = (
            self.any_landmark_hit(matches)
            and second_rev >= first_rev
            and bool(ls_result.get("ok", True))
            and bool(diff.get("ok", True))
            and bool(observe2.get("ok", True))
            and bool(ready.get("ok"))
            and bool(do_result and do_result.get("ok"))
            and self.any_landmark_hit(destination_matches)
        )
        return {
            "pass": passed,
            "url": url,
            "revision": second_rev,
            "semanticHash": observe2.get("semanticHash"),
            "nodeCount": observe2.get("nodeCount"),
            "matches": matches,
            "lsTextHead": "\n".join(str(ls_result.get("text") or "").splitlines()[:8]),
            "diffTextHead": "\n".join(str(diff.get("text") or "").splitlines()[:10]),
            "revisionBeforeReload": first_rev,
            "revisionAfterReload": second_rev,
            "ready": {
                "ok": bool(ready.get("ok")),
                "status": ready.get("status"),
                "textHead": "\n".join(str(ready.get("text") or "").splitlines()[:4]),
            },
            "uiDo": {
                "attempted": do_result is not None,
                "ok": bool(do_result.get("ok")) if do_result else None,
                "status": do_result.get("status") if do_result else None,
                "targetName": "Open Settings from conversations",
            },
            "destinationMatches": destination_matches,
            "treeOmitted": True,
        }

    def diff_reload(self, page: Any) -> dict[str, Any]:
        url = control_preview_url(self.base_url)
        self.observe(page, url, delay_ms=500)
        rev1 = int(self.surface.graph.revision)
        ls1 = self.surface.call("ui.ls", {"limit": 15})
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        text = self.surface.observer.observe_playwright_page(page)
        observe2 = self.surface._compact_result(text, tool="ui.observe")
        diff = self.surface.call("ui.diff", {"limit": 40})
        rev2 = int(self.surface.graph.revision)
        passed = rev2 >= rev1 and bool(ls1.get("ok", True)) and "delta" in str(diff.get("text") or "")
        return {
            "pass": passed,
            "url": url,
            "revision": rev2,
            "semanticHash": observe2.get("semanticHash"),
            "matches": [
                {
                    "query": "reload-diff",
                    "matchCount": 1 if passed else 0,
                    "sampleNames": [f"rev {rev1}->{rev2}"],
                }
            ],
            "lsTextHead": "\n".join(str(ls1.get("text") or "").splitlines()[:6]),
            "diffTextHead": "\n".join(str(diff.get("text") or "").splitlines()[:10]),
            "treeOmitted": True,
        }

    def product_mode_switch(self, page: Any) -> dict[str, Any]:
        """Switch Chat → Orchestration → Chat and prove each destination."""
        pre_login = self._observe_pre_login(page)
        url = control_preview_url(self.base_url, surface="agent")
        observe = self.observe(page, url, delay_ms=700)
        matches = self.find_landmarks(PRODUCT_MODE_LANDMARK_QUERIES)
        app_chrome = self.looks_like_app_chrome(matches) or (
            self.landmark_hit(matches, "Chat") and self.landmark_hit(matches, "Orchestration")
        )
        login_wall = self.looks_like_login_wall(matches) and not app_chrome
        do_result: dict[str, Any] | None = None
        return_result: dict[str, Any] | None = None
        after_click_matches: list[dict[str, Any]] = []
        after_return_matches: list[dict[str, Any]] = []

        if app_chrome:
            do_result = self._click_first(
                'button[name="New Orchestration from conversations"]',
            )
            after_click_matches = self.find_landmarks(
                ("New orchestration", "What should the team finish?")
            )
            return_result = self._click_first('button[name="Open Neyvia Chat"]')
            after_return_matches = self.find_landmarks(
                ("Neyvia command composer", "Command Neyvia", "Neyvia conversation")
            )

        if app_chrome:
            chat_hit = self.landmark_hit(matches, "Chat", "Open Chat", "New Chat", "Neyvia Chat")
            orch_hit = self.landmark_hit(
                matches, "Orchestration", "New Orchestration"
            )
            orchestration_proved = self.any_landmark_hit(after_click_matches)
            chat_return_proved = self.any_landmark_hit(after_return_matches)
            passed = bool(
                chat_hit
                and orch_hit
                and pre_login.get("hit")
                and do_result
                and do_result.get("ok")
                and orchestration_proved
                and return_result
                and return_result.get("ok")
                and chat_return_proved
            )
            return {
                "pass": passed,
                "skipped": False,
                "url": url,
                "revision": observe.get("revision"),
                "semanticHash": observe.get("semanticHash"),
                "nodeCount": observe.get("nodeCount"),
                "matches": matches,
                "afterClickMatches": after_click_matches,
                "afterReturnMatches": after_return_matches,
                "preLogin": pre_login,
                "sessionState": "app_chrome",
                "uiDo": {
                    "attempted": do_result is not None,
                    "ok": bool(do_result.get("ok")) if do_result else None,
                    "status": do_result.get("status") if do_result else None,
                },
                "returnUiDo": {
                    "attempted": return_result is not None,
                    "ok": bool(return_result.get("ok")) if return_result else None,
                    "status": return_result.get("status") if return_result else None,
                },
                "treeOmitted": True,
            }

        # Auth wall without preview chrome: document skip; never false-pass.
        creds = login_credentials_from_env()
        if login_wall and not creds:
            return {
                "pass": False,
                "skipped": True,
                "reason": SKIP_REASON_AUTH_REQUIRED,
                "url": url,
                "revision": observe.get("revision"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "login_wall",
                "treeOmitted": True,
            }
        if login_wall and creds:
            user, password = creds
            username_fill = self.surface.call(
                "ui.do",
                {
                    "query": 'textbox[name="Username"]',
                    "action": "fill",
                    "value": user,
                    "ifRev": self.surface.graph.revision,
                    "ifHash": self.surface.graph.semantic_hash,
                },
            )
            password_fill = self.surface.call(
                "ui.do",
                {
                    "query": 'textbox[name="Password"]',
                    "action": "fill",
                    "value": password,
                    "ifRev": self.surface.graph.revision,
                    "ifHash": self.surface.graph.semantic_hash,
                },
            )
            sign_in = self._click_first('button[name~="Sign in"]')
            page.wait_for_timeout(500)
            text = self.surface.observer.observe_playwright_page(page)
            observe2 = self.surface._compact_result(text, tool="ui.observe")
            matches = self.find_landmarks(PRODUCT_MODE_LANDMARK_QUERIES)
            chat_hit = self.landmark_hit(matches, "Chat", "Open Chat", "New Chat")
            orch_hit = self.landmark_hit(matches, "Orchestration", "New Orchestration")
            passed = bool(
                username_fill.get("ok")
                and password_fill.get("ok")
                and sign_in
                and sign_in.get("ok")
                and chat_hit
                and orch_hit
                and pre_login.get("hit")
            )
            return {
                "pass": passed,
                "skipped": False,
                "url": url,
                "revision": observe2.get("revision"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "post_login_attempt",
                "loginActions": {
                    "username": username_fill.get("status"),
                    "password": password_fill.get("status"),
                    "submit": sign_in.get("status") if sign_in else None,
                },
                "treeOmitted": True,
            }

        return {
            "pass": False,
            "skipped": False,
            "url": url,
            "revision": observe.get("revision"),
            "matches": matches,
            "preLogin": pre_login,
            "sessionState": "unknown",
            "treeOmitted": True,
        }

    def harnesses_surface(self, page: Any) -> dict[str, Any]:
        """Harnesses landmark: Settings Runtimes panel and/or seven-row parity matrix."""
        pre_login = self._observe_pre_login(page)
        url = control_preview_url(self.base_url, surface="settings")
        observe = self.observe(page, url, delay_ms=700)
        matches = self.find_landmarks(HARNESSES_LANDMARK_QUERIES)
        do_steps: list[dict[str, Any]] = []

        if not self.landmark_hit(matches, "Harnesses", "Harness parity", "Syntelos Hybrid"):
            clicked = self._click_first(
                'button[name~="Runtimes"]',
                "Runtimes & Rooms",
                "Open runtimes",
            )
            if clicked is not None:
                do_steps.append({"action": "open-runtimes", "ok": bool(clicked.get("ok")), "status": clicked.get("status")})
                page.wait_for_timeout(400)
                text = self.surface.observer.observe_playwright_page(page)
                self.surface._compact_result(text, tool="ui.observe")
                matches.extend(self.find_landmarks(HARNESSES_LANDMARK_QUERIES))

        if not self.landmark_hit(matches, "Harnesses", "Harness parity", "Syntelos Hybrid", "Mission planning"):
            # Builder surface often renders the harness parity matrix (seven capability rows).
            builder_url = control_preview_url(self.base_url, surface="builder")
            observe = self.observe(page, builder_url, delay_ms=700)
            url = builder_url
            matches.extend(self.find_landmarks(HARNESSES_LANDMARK_QUERIES))

        harness_hit = self.landmark_hit(
            matches,
            "Harnesses",
            "Harness parity",
            "Syntelos Hybrid",
            "Use Syntelos Hybrid",
            "Mission planning",
            "Phone/tablet web supervision",
        )
        settings_nav_hit = self.landmark_hit(matches, "Settings", "Runtimes")
        app_chrome = harness_hit or settings_nav_hit or self.looks_like_app_chrome(matches)
        login_wall = self.looks_like_login_wall(matches) and not app_chrome

        if harness_hit:
            return {
                "pass": bool(pre_login.get("hit")),
                "skipped": False,
                "url": url,
                "revision": observe.get("revision"),
                "semanticHash": observe.get("semanticHash"),
                "nodeCount": observe.get("nodeCount"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "app_chrome",
                "harnessLandmark": True,
                "uiDoSteps": do_steps,
                "treeOmitted": True,
            }

        if login_wall and not login_credentials_from_env():
            return {
                "pass": False,
                "skipped": True,
                "reason": SKIP_REASON_AUTH_REQUIRED,
                "url": url,
                "revision": observe.get("revision"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "login_wall",
                "harnessLandmark": False,
                "treeOmitted": True,
            }

        # Settings chrome without explicit Harnesses label still counts as a partial miss (fail, not skip).
        return {
            "pass": False,
            "skipped": False,
            "url": url,
            "revision": observe.get("revision"),
            "matches": matches,
            "preLogin": pre_login,
            "sessionState": "app_chrome" if app_chrome else "unknown",
            "harnessLandmark": False,
            "uiDoSteps": do_steps,
            "treeOmitted": True,
        }

    def surface_navigation(self, page: Any) -> dict[str, Any]:
        """Navigate primary surfaces with real ui.do clicks and destination-specific proof."""
        pre_login = self._observe_pre_login(page)
        url = control_preview_url(self.base_url, surface="home")
        # The reference shell is intentionally lazy-loaded and may need a few
        # seconds for its first development compile. Observe after the actual
        # rail can exist instead of sampling the Suspense placeholder.
        observe = self.observe(page, url, delay_ms=8_000)
        rail_matches = self.find_landmarks(
            (
                "Home",
                "Workbench",
                "Settings",
                "Orchestration",
                "Workflows",
                "New Orchestration from conversations",
                'button[name="Open Settings from conversations"]',
                'button[name~="Sign in"]',
                "N-E-Y-V-I-A",
            )
        )
        app_chrome = self.looks_like_app_chrome(rail_matches) or self.landmark_hit(
            rail_matches,
            "Home",
            "Workbench",
            "Settings",
            "Orchestration",
            "Workflows",
            "N-E-Y-V-I-A",
        )
        login_wall = self.looks_like_login_wall(rail_matches) and not app_chrome

        if login_wall and not login_credentials_from_env():
            return {
                "pass": False,
                "skipped": True,
                "reason": SKIP_REASON_AUTH_REQUIRED,
                "url": url,
                "revision": observe.get("revision"),
                "matches": rail_matches,
                "preLogin": pre_login,
                "sessionState": "login_wall",
                "steps": [],
                "treeOmitted": True,
            }

        steps: list[dict[str, Any]] = []
        for step in SURFACE_NAV_STEPS:
            label = str(step["label"])
            click_queries = tuple(step["click"])
            expect_queries = tuple(step["expect"])
            do_result = self._click_first(*click_queries)
            if do_result is not None and do_result.get("ok"):
                # Lazy surfaces briefly expose only their loading landmark.
                # Re-observe after the destination chunk has had time to mount
                # before evaluating proof or locating the next sidebar action.
                page.wait_for_timeout(650)
                text = self.surface.observer.observe_playwright_page(page)
                self.surface._compact_result(text, tool="ui.observe")
            after = self.find_landmarks(expect_queries)
            hit = self.any_landmark_hit(after)
            action_ok = bool(do_result and do_result.get("ok"))
            steps.append(
                {
                    "click": label,
                    "uiDoAttempted": do_result is not None,
                    "uiDoOk": bool(do_result.get("ok")) if do_result else None,
                    "uiDoStatus": do_result.get("status") if do_result else None,
                    "expected": list(expect_queries),
                    "matches": after,
                    "revision": self.surface.graph.revision,
                    "passed": bool(action_ok and hit),
                }
            )

        passed_steps = sum(1 for item in steps if item.get("passed"))
        passed = bool(
            pre_login.get("hit")
            and app_chrome
            and passed_steps == len(SURFACE_NAV_STEPS)
        )
        return {
            "pass": passed,
            "skipped": False,
            "url": url,
            "revision": int(self.surface.graph.revision),
            "semanticHash": self.surface.graph.semantic_hash,
            "matches": rail_matches,
            "preLogin": pre_login,
            "sessionState": "app_chrome" if app_chrome else "unknown",
            "steps": steps,
            "passedSteps": passed_steps,
            "stepCount": len(steps),
            "treeOmitted": True,
        }

    def library_or_preview(self, page: Any) -> dict[str, Any]:
        """Library (Skills) or Preview landmark when visible without deep auth walls."""
        pre_login = self._observe_pre_login(page)
        urls_tried: list[str] = []
        matches: list[dict[str, Any]] = []
        observe: dict[str, Any] = {}
        url = ""

        for surface_name in ("skills", "agent", "builder"):
            url = control_preview_url(self.base_url, surface=surface_name)
            urls_tried.append(url)
            observe = self.observe(page, url, delay_ms=650)
            batch = self.find_landmarks(LIBRARY_OR_PREVIEW_LANDMARK_QUERIES)
            matches.extend(batch)
            if self.landmark_hit(
                batch,
                "Your skills",
                "User skill library",
                "Curated library",
                "Live Preview",
                "Interface Preview",
                "Preview",
                "Open Workflows",
                "Workflows",
            ):
                break
            # Soft navigate via rail when surface query alone is thin.
            clicked = self._click_first(
                'button[name="Open Workflows"]' if surface_name == "skills" else 'button[name~="Preview"]',
                "Open Workflows" if surface_name == "skills" else "Preview",
            )
            if clicked is not None:
                page.wait_for_timeout(350)
                text = self.surface.observer.observe_playwright_page(page)
                self.surface._compact_result(text, tool="ui.observe")
                matches.extend(self.find_landmarks(LIBRARY_OR_PREVIEW_LANDMARK_QUERIES))
                if self.landmark_hit(matches, "Your skills", "Workflows", "Preview", "Live Preview", "Curated library"):
                    break

        library_hit = self.landmark_hit(
            matches, "Your skills", "User skill library", "Curated library", "Open Workflows", "Workflows", "Skills"
        )
        preview_hit = self.landmark_hit(matches, "Preview", "Live Preview", "Interface Preview")
        app_chrome = library_hit or preview_hit or self.looks_like_app_chrome(matches)
        login_wall = self.looks_like_login_wall(matches) and not app_chrome

        if library_hit or preview_hit:
            return {
                "pass": bool(pre_login.get("hit")),
                "skipped": False,
                "url": url,
                "urlsTried": urls_tried,
                "revision": observe.get("revision"),
                "semanticHash": observe.get("semanticHash"),
                "nodeCount": observe.get("nodeCount"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "app_chrome",
                "libraryHit": library_hit,
                "previewHit": preview_hit,
                "treeOmitted": True,
            }

        if login_wall and not login_credentials_from_env():
            return {
                "pass": False,
                "skipped": True,
                "reason": SKIP_REASON_AUTH_REQUIRED,
                "url": url,
                "urlsTried": urls_tried,
                "revision": observe.get("revision"),
                "matches": matches,
                "preLogin": pre_login,
                "sessionState": "login_wall",
                "libraryHit": False,
                "previewHit": False,
                "treeOmitted": True,
            }

        return {
            "pass": False,
            "skipped": False,
            "url": url,
            "urlsTried": urls_tried,
            "revision": observe.get("revision"),
            "matches": matches,
            "preLogin": pre_login,
            "sessionState": "app_chrome" if app_chrome else "unknown",
            "libraryHit": False,
            "previewHit": False,
            "treeOmitted": True,
        }


def _is_browser_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        needle in text
        for needle in (
            "executable doesn't exist",
            "browserType.launch".lower(),
            "unable to launch a chromium browser",
            "playwright install",
        )
    )


def _invoke_flow(
    runner: CuAcceptanceRunner,
    canonical: str,
    page: Any,
) -> dict[str, Any]:
    handlers = {
        "login_session": runner.login_session,
        "control_room": runner.control_room,
        "diff_reload": runner.diff_reload,
        "product_mode_switch": runner.product_mode_switch,
        "harnesses_surface": runner.harnesses_surface,
        "library_or_preview": runner.library_or_preview,
        "surface_navigation": runner.surface_navigation,
    }
    handler = handlers.get(canonical)
    if handler is None:
        raise AssertionError(f"unhandled CU acceptance flow: {canonical}")
    return handler(page)


def _flow_error(exc: BaseException) -> dict[str, Any]:
    browser_unavailable = _is_browser_unavailable(exc)
    return {
        "pass": False,
        "skipped": False,
        "status": "browser_unavailable" if browser_unavailable else "error",
        "reason": (
            (
                "Playwright browser runtime unavailable for CU acceptance. "
                "Install Chrome or run: python -m playwright install chromium. "
                f"Detail: {exc}"
            )
            if browser_unavailable
            else f"{type(exc).__name__}: {str(exc).splitlines()[0][:500]}"
        ),
        "errorType": type(exc).__name__,
        "treeOmitted": True,
    }


def run_flow(flow: str, *, base_url: str | None = None, root: Path | None = None,
             discovery_urls: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run one acceptance flow fail-closed and always leave a compact receipt."""
    monotonic_started = time.perf_counter()
    canonical = FLOW_ALIASES.get(flow)
    if canonical is None:
        raise ValueError(f"unknown CU acceptance flow: {flow}")
    from .proofs_a_control import require
    require(canonical in CANONICAL_FLOWS, "control.cu-aliases", "compatibility alias refers to an unregistered canonical flow")
    started = _utc_now()
    live = base_url or (find_live_base_url() if discovery_urls is None else find_live_base_url(discovery_urls=discovery_urls))
    if not live:
        result = {
            "flow": canonical,
            "requestedFlow": flow,
            "baseUrl": "",
            "startedAt": started,
            "finishedAt": _utc_now(),
            "durationMs": round(
                (time.perf_counter() - monotonic_started) * 1000.0,
                3,
            ),
            "pass": False,
            "skipped": False,
            "status": "server_unavailable",
            "reason": skip_reason_no_server() if discovery_urls is None else skip_reason_no_server(discovery_urls),
            "treeOmitted": True,
        }
        receipt_path = write_receipt(canonical, result, root=root)
        result["receiptPath"] = str(receipt_path)
        return result

    runner = CuAcceptanceRunner(base_url=live)
    try:
        result = runner.run_with_page(
            lambda page: _invoke_flow(runner, canonical, page)
        )
    except Exception as exc:  # noqa: BLE001 — the gate must receipt failures, including infrastructure
        result = _flow_error(exc)
    finally:
        runner.close()
    result = {
        "flow": canonical,
        "requestedFlow": flow,
        "baseUrl": live,
        "startedAt": started,
        "finishedAt": _utc_now(),
        "durationMs": round(
            (time.perf_counter() - monotonic_started) * 1000.0,
            3,
        ),
        **result,
    }
    result["skipped"] = bool(result.get("skipped"))
    result.setdefault("status", "passed" if result.get("pass") else "failed")
    receipt_path = write_receipt(canonical, result, root=root)
    result["receiptPath"] = str(receipt_path)
    return result


def run_suite(
    *,
    base_url: str | None = None,
    flows: list[str] | tuple[str, ...] | None = None,
    root: Path | None = None,
    discovery_urls: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run the standalone product gate. A skip or unavailable dependency is a failure."""
    monotonic_started = time.perf_counter()
    requested = list(flows or CANONICAL_FLOWS)
    canonical: list[str] = []
    for name in requested:
        resolved = FLOW_ALIASES.get(name)
        if resolved is None:
            raise ValueError(f"unknown CU acceptance flow: {name}")
        if resolved not in canonical:
            canonical.append(resolved)

    started = _utc_now()
    live = base_url or (find_live_base_url() if discovery_urls is None else find_live_base_url(discovery_urls=discovery_urls))
    results: list[dict[str, Any]] = []
    browser_metrics = {"browserStarts": 0, "contextsCreated": 0}
    if live:
        runner = CuAcceptanceRunner(base_url=live)
        page_cm = runner.surface.observer.browser_runtime.page
        try:
            with page_cm(width=runner.width, height=runner.height) as page:
                runner.surface.attached_page = page
                for name in canonical:
                    flow_started_at = _utc_now()
                    flow_started = time.perf_counter()
                    try:
                        item = _invoke_flow(runner, name, page)
                    except Exception as exc:  # noqa: BLE001 — every failed flow must receipt
                        item = _flow_error(exc)
                    item = {
                        "flow": name,
                        "requestedFlow": name,
                        "baseUrl": live,
                        "startedAt": flow_started_at,
                        "finishedAt": _utc_now(),
                        "durationMs": round(
                            (time.perf_counter() - flow_started) * 1000.0,
                            3,
                        ),
                        **item,
                    }
                    item["skipped"] = bool(item.get("skipped"))
                    item.setdefault(
                        "status",
                        "passed" if item.get("pass") else "failed",
                    )
                    receipt_path = write_receipt(name, item, root=root)
                    item["receiptPath"] = str(receipt_path)
                    results.append(item)
        except Exception as exc:  # noqa: BLE001 — browser startup must fail all requested flows
            error = _flow_error(exc)
            results = []
            for name in canonical:
                item = {
                    "flow": name,
                    "requestedFlow": name,
                    "baseUrl": live,
                    "startedAt": started,
                    "finishedAt": _utc_now(),
                    "durationMs": 0.0,
                    **error,
                }
                receipt_path = write_receipt(name, item, root=root)
                item["receiptPath"] = str(receipt_path)
                results.append(item)
        finally:
            runner.surface.attached_page = None
            runtime = runner.surface.observer.browser_runtime
            browser_metrics = {
                "browserStarts": int(runtime.browser_starts),
                "contextsCreated": int(runtime.contexts_created),
            }
            runner.close()
    else:
        results = [
            {
                "flow": name,
                "pass": False,
                "skipped": False,
                "status": "server_unavailable",
                "reason": skip_reason_no_server() if discovery_urls is None else skip_reason_no_server(discovery_urls),
            }
            for name in canonical
        ]
    passed = sum(1 for item in results if item.get("pass") is True and not item.get("skipped"))
    failed = len(results) - passed
    payload = {
        "flow": "suite",
        "baseUrl": live or "",
        "startedAt": started,
        "finishedAt": _utc_now(),
        "durationMs": round(
            (time.perf_counter() - monotonic_started) * 1000.0,
            3,
        ),
        "pass": failed == 0 and bool(results),
        "skipped": False,
        "status": "passed" if failed == 0 and results else "failed",
        "summary": {"passed": passed, "failed": failed, "total": len(results)},
        "results": [
            {
                "flow": item.get("flow"),
                "pass": bool(item.get("pass")),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "receiptPath": item.get("receiptPath"),
            }
            for item in results
        ],
        "treeOmitted": True,
        "observationPolicy": {
            "primary": "structured_accessibility_graph",
            "queryFlow": ["ui.observe", "ui.find", "ui.diff", "ui.do"],
            "vision": "fallback_only",
            "visionFallbackCount": 0,
            "fullScreenshotEveryTurn": False,
        },
        "runtimeEfficiency": {
            **browser_metrics,
            "sharedBrowserAcrossFlows": bool(live and len(canonical) > 1),
        },
    }
    payload["compactReceiptBytes"] = len(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    receipt_path = write_receipt("suite", payload, root=root)
    payload["receiptPath"] = str(receipt_path)
    from .proofs_a_control import require
    require(payload["pass"] is (bool(results) and all(row.get("pass") is True and not row.get("skipped") for row in results))
            and payload["summary"] == {"passed": passed, "failed": len(results) - passed, "total": len(results)},
            "control.cu-verdict", "standalone suite turned unavailable/skipped/failed evidence into pass or changed counts")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m grant_agent.cu_acceptance",
        description="Run N-E-Y-V-I-A structured Computer Use acceptance without Pytest.",
    )
    parser.add_argument("--base-url", help="Control UI base URL; auto-discovers local Vite when omitted.")
    parser.add_argument(
        "--flow",
        action="append",
        choices=sorted(FLOW_ALIASES),
        help="Run one flow (repeatable). Defaults to the full product gate.",
    )
    parser.add_argument("--json", action="store_true", help="Print the complete suite receipt payload.")
    parser.add_argument("--list", action="store_true", help="List canonical flow names and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.list:
        print("\n".join(CANONICAL_FLOWS))
        return 0
    result = run_suite(base_url=args.base_url, flows=args.flow)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        summary = result["summary"]
        print(
            f"N-E-Y-V-I-A CU acceptance: {result['status']} "
            f"({summary['passed']}/{summary['total']} passed)"
        )
        for item in result["results"]:
            detail = f" - {item['flow']}: {item['status']}"
            if item.get("reason"):
                detail += f" ({str(item['reason']).splitlines()[0][:180]})"
            print(detail)
        print(f"Receipt: {result['receiptPath']}")
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
