"""Operate the user's authenticated Chrome through the DevTools Protocol.

Neyvia's previous browser automation launched a fresh headless Chromium with a
blank context (``ui_observer.ReusableBrowserRuntime``). That is fine for smoke
tests and useless for real work: every authenticated site answers with a login
page. This module provides the missing capability — driving a Chrome that holds
the user's real sessions.

Two facts about modern Chrome shape the whole design, both verified against
Chrome 150 rather than assumed:

1. Chrome refuses to open a remote-debugging port when it is running on the
   *default* user-data directory. This is a deliberate security restriction
   (Chrome 136+). Launching ``chrome.exe --remote-debugging-port=9222`` against
   the default profile starts the browser and silently never binds the port.
2. The same command against a dedicated ``--user-data-dir`` binds immediately.

So Neyvia cannot drive the user's *default* profile, and the alternative —
copying the profile to get its cookies — is credential theft wearing a helpful
hat. Instead Neyvia keeps its own Chrome user-data directory that the user signs
into once, through Chrome's own login flow. Chrome owns and encrypts those
credentials exactly as it always does; Neyvia never reads, copies, or stores
them. The user can inspect or delete the directory at any time.

Every action returns what was actually confirmed. A dispatched click that
produced no observable change is reported as unverified, not as success.
"""

from __future__ import annotations

from .chrome_environment import chrome_environment

import base64
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from contextvars import ContextVar

_OWNED_TAB_TRANSPORT = ContextVar("connected_owned_tab_transport", default=None)


@contextmanager
def owned_tab_transport(port: int, target_id: str, command):
    """Borrow one caller-owned CDP session without switching browser profiles.

    The callable sends real CDP commands on the existing connection. It stays
    in memory and is scoped to this thread and exact endpoint/target; closing
    a borrowed TabSession leaves resource cleanup to the connection owner.
    """
    if type(port) is not int or not 1024 <= port <= 65535 or port == 47881 or not target_id or not callable(command):
        raise ValueError("Explicit owned endpoint, target and CDP transport required")
    binding = _OWNED_TAB_TRANSPORT.set((port, target_id, command))
    try:
        yield
    finally:
        _OWNED_TAB_TRANSPORT.reset(binding)

from .cdp_client import Cdp, DevToolsSocket, json_get
from .subprocess_utils import hidden_windows_subprocess_kwargs

#: Port Neyvia asks its managed Chrome to expose. Chosen to sit outside the
#: 9222 default so a developer's own debugging Chrome is never hijacked.
DEFAULT_DEBUG_PORT = 9226

#: How long to wait for a freshly launched Chrome to bind its debug port.
LAUNCH_TIMEOUT_SECONDS = 25.0

#: Cap on extracted page text. Enough to reason about a page, small enough to
#: keep receipts and model context bounded.
MAX_PAGE_TEXT = 6000


class ConnectedChromeError(RuntimeError):
    """Raised when a connected-Chrome operation cannot be completed."""


# ---------------------------------------------------------------------------
# Chrome discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChromeInstallation:
    executable: Path
    version: str

    def as_dict(self) -> dict[str, Any]:
        return {"executable": str(self.executable), "version": self.version}


def _candidate_chrome_paths() -> list[Path]:
    candidates: list[Path] = []
    env_override = os.environ.get("NEYVIA_CHROME_EXECUTABLE", "").strip()
    if env_override:
        candidates.append(Path(env_override))

    if os.name == "nt":
        for base_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(base_var)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
        candidates.append(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        )

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _chrome_version(executable: Path) -> str:
    """Best-effort version string. Absence of a version never blocks use."""
    if os.name == "nt":
        # `chrome.exe --version` does not print on Windows; the versioned
        # directory beside the binary is the reliable source.
        versions = sorted(
            (
                child.name
                for child in executable.parent.iterdir()
                if child.is_dir() and child.name[:1].isdigit()
            ),
            reverse=True,
        )
        if versions:
            return versions[0]
        return "unknown"
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def find_chrome() -> ChromeInstallation | None:
    """Locate an installed Chrome, or ``None`` if there is none to drive."""
    for candidate in _candidate_chrome_paths():
        try:
            if candidate.is_file():
                return ChromeInstallation(candidate, _chrome_version(candidate))
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Managed profile
# ---------------------------------------------------------------------------


def managed_profile_dir(root: str | Path) -> Path:
    """Directory holding the Chrome profile Neyvia drives.

    Kept under the workspace's control directory so it is discoverable and
    deletable by the user. This is a *separate* Chrome identity from their
    everyday browsing, which is what makes remote debugging possible at all.
    """
    return Path(root) / ".agent_control" / "connected_chrome" / "profile"


def managed_profile_state(root: str | Path) -> dict[str, Any]:
    """Report whether the managed profile has been established and signed into.

    "Signed in" is inferred from Chrome's own profile metadata; Neyvia does not
    read cookies or credential stores to determine it.
    """
    profile_dir = managed_profile_dir(root)
    local_state = profile_dir / "Local State"
    if not local_state.exists():
        return {
            "exists": False,
            "path": str(profile_dir),
            "signedInAccounts": [],
            "detail": "Neyvia has no Chrome profile yet. One will be created the first time you connect.",
        }

    accounts: list[str] = []
    try:
        payload = json.loads(local_state.read_text(encoding="utf-8"))
        info_cache = payload.get("profile", {}).get("info_cache", {})
        for entry in info_cache.values():
            user_name = str(entry.get("user_name") or "").strip()
            if user_name:
                accounts.append(user_name)
    except (OSError, ValueError, AttributeError):
        # A profile we cannot parse is still a profile; report it honestly
        # rather than claiming it is absent.
        return {
            "exists": True,
            "path": str(profile_dir),
            "signedInAccounts": [],
            "detail": "Profile exists but its metadata could not be read.",
        }

    return {
        "exists": True,
        "path": str(profile_dir),
        "signedInAccounts": accounts,
        "detail": (
            f"Signed in as {', '.join(accounts)}."
            if accounts
            else "Profile exists but no account is signed in. Sign in once in the Chrome window Neyvia opens."
        ),
    }


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChromeEndpoint:
    port: int
    browser: str
    websocket_url: str

    def as_dict(self) -> dict[str, Any]:
        return {"port": self.port, "browser": self.browser}


def probe_endpoint(port: int, *, timeout: float = 2.0) -> ChromeEndpoint | None:
    """Return the CDP endpoint on ``port``, or ``None`` if nothing answers."""
    try:
        payload = json_get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if not isinstance(payload, dict):
        return None
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        return None
    return ChromeEndpoint(
        port=port,
        browser=str(payload.get("Browser") or "unknown"),
        websocket_url=websocket_url,
    )


def connection_status(root: str | Path, *, port: int = DEFAULT_DEBUG_PORT) -> dict[str, Any]:
    """Describe the connection truthfully, including what to do next.

    States:
      ``connected``            Neyvia can drive Chrome right now.
      ``ready_to_launch``      Profile exists; Chrome is not running.
      ``setup_required``       No profile yet; a one-time sign-in is needed.
      ``chrome_missing``       No Chrome installed to drive.
    """
    installation = find_chrome()
    profile = managed_profile_state(root)
    endpoint = probe_endpoint(port)

    if endpoint is not None:
        state, detail, next_action = (
            "connected",
            f"Connected to {endpoint.browser} on port {port}.",
            None,
        )
    elif installation is None:
        state, detail, next_action = (
            "chrome_missing",
            "Google Chrome was not found on this machine.",
            "Install Google Chrome, then connect again.",
        )
    elif profile["exists"] and profile["signedInAccounts"]:
        state, detail, next_action = (
            "ready_to_launch",
            "Neyvia's Chrome profile is set up but Chrome is not running.",
            "Start the connected browser.",
        )
    else:
        state, detail, next_action = (
            "setup_required",
            "Neyvia needs its own Chrome profile, which you sign into once.",
            "Start the connected browser and sign in to the sites you want Neyvia to use.",
        )

    return {
        "schema": "neyvia.connected_chrome.status/1",
        "state": state,
        "detail": detail,
        "nextAction": next_action,
        "port": port,
        "chrome": installation.as_dict() if installation else None,
        "profile": profile,
        "endpoint": endpoint.as_dict() if endpoint else None,
        # Stated plainly in the product surface so the access model is never a
        # surprise. This is the whole reason a separate profile exists.
        "accessModel": {
            "drivesDefaultProfile": False,
            "explanation": (
                "Chrome blocks automation of your everyday profile. Neyvia therefore "
                "drives a separate Chrome profile that you sign into once. Your saved "
                "passwords and sessions are held by Chrome, not by Neyvia, and are "
                "never copied out."
            ),
            "profilePath": profile["path"],
        },
    }


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def launch(
    root: str | Path,
    *,
    port: int = DEFAULT_DEBUG_PORT,
    initial_url: str = "about:blank",
    timeout: float = LAUNCH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Start (or reuse) the Chrome that Neyvia drives.

    Returns the resulting connection status. Raises if Chrome starts but never
    exposes its debug port — the failure mode that silently defeats automation
    against the default profile.
    """
    existing = probe_endpoint(port)
    if existing is not None:
        return {
            "launched": False,
            "reused": True,
            "status": connection_status(root, port=port),
        }

    installation = find_chrome()
    if installation is None:
        raise ConnectedChromeError(
            "Google Chrome was not found on this machine, so Neyvia cannot connect to a browser."
        )

    profile_dir = managed_profile_dir(root)
    profile_dir.mkdir(parents=True, exist_ok=True)

    if not _port_is_free(port):
        raise ConnectedChromeError(
            f"Port {port} is already in use by something that is not a Chrome debug endpoint. "
            "Close whatever is using it, or choose a different port."
        )

    command = [
        str(installation.executable),
        f"--remote-debugging-port={port}",
        # The dedicated directory is what makes remote debugging permitted at
        # all; without it Chrome starts and never binds the port.
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        initial_url,
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)

    try:
        subprocess.Popen(  # noqa: S603 — fixed executable, no shell
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            env=chrome_environment(Path(root) / ".agent_control/connected_chrome/environment"),
        )
    except OSError as exc:
        raise ConnectedChromeError(f"Failed to start Chrome: {exc}") from exc

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        endpoint = probe_endpoint(port)
        if endpoint is not None:
            return {
                "launched": True,
                "reused": False,
                "status": connection_status(root, port=port),
            }
        time.sleep(0.25)

    raise ConnectedChromeError(
        f"Chrome started but never exposed its debugging port on {port} within "
        f"{timeout:.0f}s. This happens when Chrome is already running on the same "
        "user-data directory; close all Chrome windows for Neyvia's profile and retry."
    )


def shutdown(*, port: int = DEFAULT_DEBUG_PORT, timeout: float = 10.0) -> dict[str, Any]:
    """Close the connected browser.

    This is the hard stop behind the operator's Stop control. It closes Chrome
    rather than merely detaching, because leaving an automation-enabled browser
    running after the user asked it to stop is its own kind of dishonesty. The
    user's own everyday Chrome is a different process and is unaffected.
    """
    endpoint = probe_endpoint(port)
    if endpoint is None:
        return {"stopped": False, "reason": "The connected browser was not running."}

    try:
        socket_connection = DevToolsSocket(endpoint.websocket_url)
    except (OSError, RuntimeError) as exc:
        raise ConnectedChromeError(f"Could not attach in order to close Chrome: {exc}") from exc

    try:
        Cdp(socket_connection).send("Browser.close")
    except (RuntimeError, OSError):
        # Chrome frequently drops the socket as it exits; confirm by probing.
        pass
    finally:
        try:
            socket_connection.close()
        except OSError:
            pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_endpoint(port) is None:
            return {"stopped": True, "reason": "The connected browser was closed."}
        time.sleep(0.25)

    return {
        "stopped": False,
        "reason": f"Chrome was asked to close but is still answering on port {port}.",
    }


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrowserTab:
    target_id: str
    title: str
    url: str
    websocket_url: str

    def as_dict(self) -> dict[str, Any]:
        return {"targetId": self.target_id, "title": self.title, "url": self.url}


def list_tabs(*, port: int = DEFAULT_DEBUG_PORT) -> list[BrowserTab]:
    """List the real page tabs open in the connected browser."""
    owned = _OWNED_TAB_TRANSPORT.get()
    if owned is not None and owned[0] == port:
        info = owned[2]("Target.getTargetInfo", {"targetId": owned[1]})["targetInfo"]
        if info.get("targetId") != owned[1] or info.get("type") != "page":
            raise ConnectedChromeError("Owned CDP target changed; observe the current page")
        return [BrowserTab(info["targetId"], str(info.get("title") or ""), str(info.get("url") or ""),
                          f"ws://127.0.0.1:{port}/devtools/page/{info['targetId']}")]
    try:
        payload = json_get(f"http://127.0.0.1:{port}/json/list", timeout=5.0)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise ConnectedChromeError(
            f"Could not list tabs; the connected browser is not reachable on port {port}. ({exc})"
        ) from exc

    if not isinstance(payload, list):
        return []

    tabs: list[BrowserTab] = []
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("type") != "page":
            continue
        url = str(entry.get("url") or "")
        if url.startswith(("chrome-extension:", "devtools:")):
            continue
        websocket_url = str(entry.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            continue
        tabs.append(
            BrowserTab(
                target_id=str(entry.get("id") or ""),
                title=str(entry.get("title") or ""),
                url=url,
                websocket_url=websocket_url,
            )
        )
    return tabs


def find_tab(target_id: str, *, port: int = DEFAULT_DEBUG_PORT) -> BrowserTab:
    for tab in list_tabs(port=port):
        if tab.target_id == target_id:
            return tab
    raise ConnectedChromeError(
        f"Tab {target_id} is no longer open. Re-list tabs and choose the target again."
    )


def open_tab(url: str, *, port: int = DEFAULT_DEBUG_PORT) -> BrowserTab:
    """Open a new tab and return it once Chrome reports it."""
    encoded = urllib.parse.quote(url, safe="")
    try:
        with urllib.request.urlopen(  # noqa: S310 — fixed localhost endpoint
            f"http://127.0.0.1:{port}/json/new?{encoded}",
            data=b"",
            timeout=10.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise ConnectedChromeError(f"Could not open a new tab: {exc}") from exc

    target_id = str(payload.get("id") or "")
    if not target_id:
        raise ConnectedChromeError("Chrome did not return an identifier for the new tab.")
    # Re-read through /json/list so the returned tab reflects settled state.
    for _ in range(20):
        try:
            return find_tab(target_id, port=port)
        except ConnectedChromeError:
            time.sleep(0.2)
    raise ConnectedChromeError("The new tab did not appear in Chrome's target list.")


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


@dataclass
class TabSession:
    """An open CDP connection to one tab. Use as a context manager."""

    tab: BrowserTab
    socket: DevToolsSocket = field(init=False)
    cdp: Cdp = field(init=False)

    def __post_init__(self) -> None:
        owned = _OWNED_TAB_TRANSPORT.get()
        port = urllib.parse.urlsplit(self.tab.websocket_url).port
        if owned is not None and (owned[0], owned[1]) == (port, self.tab.target_id):
            self.socket = None
            self.cdp = Cdp(None, transport=owned[2])
            return
        try:
            self.socket = DevToolsSocket(self.tab.websocket_url)
        except (OSError, RuntimeError) as exc:
            raise ConnectedChromeError(
                f"Could not attach to tab '{self.tab.title}': {exc}"
            ) from exc
        self.cdp = Cdp(self.socket)

    def __enter__(self) -> "TabSession":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.socket is None:
            return
        try:
            self.socket.close()
        except OSError:
            pass


def _page_state(cdp: Cdp) -> dict[str, Any]:
    """Read a comparable snapshot of what the page currently shows."""
    expression = """
    (() => {
      const text = (document.body && document.body.innerText) || "";
      return {
        url: location.href,
        title: document.title,
        readyState: document.readyState,
        textLength: text.length,
        text: text.slice(0, %d),
      };
    })()
    """ % MAX_PAGE_TEXT
    value = cdp.eval(expression)
    if not isinstance(value, dict):
        raise ConnectedChromeError("Could not read the page state.")
    return value


def _settled_page_state(
    cdp: Cdp,
    *,
    expected_url: str | None = None,
    timeout: float = 10.0,
) -> tuple[dict[str, Any], bool]:
    """Read the page once it has actually committed, not while it is still loading.

    Chrome reports a tab's destination URL in ``/json/list`` the moment the tab is
    created, well before that document exists. Reading straight away yields a
    pristine-looking observation of ``about:blank`` — a false negative that is
    indistinguishable from a genuinely empty page. Returns the state and whether
    it settled within the timeout.
    """
    deadline = time.monotonic() + timeout
    state = _page_state(cdp)
    awaiting_navigation = bool(
        expected_url
        and expected_url != "about:blank"
        and not expected_url.startswith("chrome://")
    )

    while time.monotonic() < deadline:
        current_url = str(state.get("url") or "")
        still_blank = awaiting_navigation and current_url in ("", "about:blank")
        if not still_blank and state.get("readyState") in ("interactive", "complete"):
            return state, True
        time.sleep(0.25)
        state = _page_state(cdp)

    return state, False


def _state_signature(state: dict[str, Any]) -> str:
    """Signature used to decide whether an action changed anything."""
    return "|".join(
        [
            str(state.get("url", "")),
            str(state.get("title", "")),
            str(state.get("textLength", "")),
            str(state.get("text", ""))[:2000],
        ]
    )


def capture_screenshot(cdp: Cdp) -> bytes:
    """Full-viewport screenshot of the tab."""
    result = cdp.send("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, str) or not data:
        raise ConnectedChromeError("Chrome returned no screenshot data.")
    return base64.b64decode(data)


def observe(
    target_id: str,
    *,
    port: int = DEFAULT_DEBUG_PORT,
    with_screenshot: bool = True,
    evidence_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Report what Neyvia can currently see in a tab.

    Pure observation: nothing on the page is changed.
    """
    tab = find_tab(target_id, port=port)
    with TabSession(tab) as session:
        session.cdp.enable_page()
        state, settled = _settled_page_state(session.cdp, expected_url=tab.url)

        screenshot_path: str | None = None
        if with_screenshot and evidence_dir is not None:
            try:
                image = capture_screenshot(session.cdp)
                directory = Path(evidence_dir)
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"observe-{int(time.time() * 1000)}.png"
                path.write_bytes(image)
                screenshot_path = str(path)
            except (ConnectedChromeError, OSError):
                # An unavailable screenshot must not invalidate a good observation.
                screenshot_path = None

    return {
        "schema": "neyvia.connected_chrome.observation/1",
        "observedAt": time.time(),
        "tab": tab.as_dict(),
        "url": state.get("url"),
        "title": state.get("title"),
        "readyState": state.get("readyState"),
        "settled": settled,
        "text": state.get("text"),
        "textTruncated": int(state.get("textLength") or 0) > MAX_PAGE_TEXT,
        "screenshotPath": screenshot_path,
        # A page that never settled may still be loading; saying so lets the
        # caller re-observe instead of reasoning about a half-rendered page.
        "caveat": None if settled else "The page had not finished loading when it was read.",
    }


def find_elements(
    target_id: str,
    query: str,
    *,
    port: int = DEFAULT_DEBUG_PORT,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Find interactive elements whose visible label matches ``query``.

    Returns stable descriptors (selector plus centre point) that :func:`act` can
    operate on, so the caller never has to guess coordinates.
    """
    tab = find_tab(target_id, port=port)
    expression = """
    (() => {
      const needle = %s.toLowerCase();
      const limit = %d;
      const selector = 'a,button,input,select,textarea,[role=button],[role=link],[role=tab],[onclick]';
      const results = [];
      for (const element of document.querySelectorAll(selector)) {
        const rect = element.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(element);
        if (style.visibility === 'hidden' || style.display === 'none') continue;
        const label = (
          element.innerText || element.value || element.getAttribute('aria-label') ||
          element.getAttribute('title') || element.getAttribute('placeholder') || ''
        ).trim();
        if (needle && !label.toLowerCase().includes(needle)) continue;
        results.push({
          label: label.slice(0, 160),
          tag: element.tagName.toLowerCase(),
          role: element.getAttribute('role') || '',
          disabled: !!element.disabled,
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
          inViewport: rect.top >= 0 && rect.top < window.innerHeight,
        });
        if (results.length >= limit) break;
      }
      return results;
    })()
    """ % (json.dumps(query), limit)

    with TabSession(tab) as session:
        session.cdp.enable_page()
        value = session.cdp.eval(expression)
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Action with verification
# ---------------------------------------------------------------------------


def _dispatch_click(cdp: Cdp, x: float, y: float) -> None:
    """Real mouse input, not a synthetic DOM ``click()``.

    Sites that gate on trusted events (which includes most consequential
    controls) ignore scripted clicks, so a JS click would produce exactly the
    false success this module exists to prevent.
    """
    for event_type in ("mousePressed", "mouseReleased"):
        cdp.send(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
                "buttons": 1 if event_type == "mousePressed" else 0,
            },
        )


def _dispatch_text(cdp: Cdp, text: str) -> None:
    for character in text:
        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": character})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "text": character})


def act(
    target_id: str,
    action: dict[str, Any],
    *,
    port: int = DEFAULT_DEBUG_PORT,
    settle_seconds: float = 1.5,
    evidence_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Perform one action and report what actually changed.

    ``action`` is one of::

        {"kind": "navigate", "url": ...}
        {"kind": "click", "x": ..., "y": ...}
        {"kind": "type", "text": ...}
        {"kind": "key", "key": "Enter"}

    Approval is the caller's responsibility — see
    :mod:`grant_agent.connected_chrome_policy`. This function assumes the
    decision has already been made, and concerns itself only with performing the
    action and telling the truth about the result.
    """
    tab = find_tab(target_id, port=port)
    kind = str(action.get("kind") or "")
    started = time.time()

    with TabSession(tab) as session:
        cdp = session.cdp
        cdp.enable_page()
        before, _ = _settled_page_state(cdp, expected_url=tab.url)

        if kind == "navigate":
            url = str(action.get("url") or "").strip()
            if not url:
                raise ConnectedChromeError("A navigate action requires a url.")
            cdp.send("Page.navigate", {"url": url})
        elif kind == "click":
            _dispatch_click(cdp, float(action["x"]), float(action["y"]))
        elif kind == "type":
            _dispatch_text(cdp, str(action.get("text") or ""))
        elif kind == "key":
            key = str(action.get("key") or "")
            cdp.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": key})
            cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
        else:
            raise ConnectedChromeError(f"Unsupported action kind: {kind!r}")

        time.sleep(settle_seconds)

        try:
            expected = str(action.get("url") or "") if kind == "navigate" else None
            after, _ = _settled_page_state(cdp, expected_url=expected)
            read_back = True
        except ConnectedChromeError:
            # A navigation can tear down the execution context mid-read. That is
            # an unverified result, not a failure and not a success.
            after, read_back = {}, False

        screenshot_path: str | None = None
        if evidence_dir is not None and read_back:
            try:
                image = capture_screenshot(cdp)
                directory = Path(evidence_dir)
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"act-{int(time.time() * 1000)}.png"
                path.write_bytes(image)
                screenshot_path = str(path)
            except (ConnectedChromeError, OSError):
                screenshot_path = None

    changed = read_back and _state_signature(before) != _state_signature(after)
    expectation = str(action.get("expect") or "").strip()
    expectation_met: bool | None = None
    if expectation and read_back:
        haystack = f"{after.get('url', '')}\n{after.get('title', '')}\n{after.get('text', '')}".lower()
        expectation_met = expectation.lower() in haystack

    if not read_back:
        verdict = "unverified"
        summary = (
            "The action was sent but the page could not be read back afterwards "
            "(the tab may still be navigating). Re-observe the tab to confirm."
        )
    elif expectation_met is False:
        verdict = "unverified"
        summary = f"The page changed but did not contain the expected text {expectation!r}."
    elif expectation_met is True:
        verdict = "verified"
        summary = f"The page now contains the expected text {expectation!r}."
    elif changed:
        verdict = "verified"
        summary = "The page changed after the action."
    else:
        verdict = "unverified"
        summary = (
            "The action was dispatched but nothing observable changed. It may have "
            "had no effect — do not assume it succeeded."
        )

    return {
        "schema": "neyvia.connected_chrome.action/1",
        "action": {key: value for key, value in action.items() if key != "approvalToken"},
        "tab": tab.as_dict(),
        "verdict": verdict,
        "summary": summary,
        "changed": changed,
        "expectationMet": expectation_met,
        "before": {"url": before.get("url"), "title": before.get("title")},
        "after": {"url": after.get("url"), "title": after.get("title")} if read_back else None,
        "screenshotPath": screenshot_path,
        "startedAt": started,
        "durationSeconds": round(time.time() - started, 3),
    }
