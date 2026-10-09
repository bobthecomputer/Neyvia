"""Small installed-desktop CDP renderer for observational Preview reviews.

The packaged runtime omits Playwright to keep the installer small. This uses an
existing Chrome or Edge binary and the already bundled websockets client. The
browser has a fresh temporary profile and is terminated after each review.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _browser_executable() -> Path:
    candidates = [
        os.environ.get("NEYVIA_REVIEW_CHROME", ""),
        shutil.which("chrome") or "",
        shutil.which("msedge") or "",
    ]
    if os.name == "nt":
        for root in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")):
            candidates.extend((str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                               str(Path(root) / "Microsoft/Edge/Application/msedge.exe")))
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise RuntimeError("Design review needs Chrome or Edge installed on this computer.")


class ChromiumReviewPage:
    def __init__(self, websocket: Any, *, width: int, height: int):
        self.websocket = websocket
        self.next_id = 0
        self.session_id = ""
        self.document_status: int | None = None
        target = self._send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session_id = self._send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self._send("Page.enable")
        self._send("Runtime.enable")
        self._send("Network.enable")
        self._send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
        })

    def _send(self, method: str, params: dict[str, Any] | None = None, timeout: float = 20) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        payload: dict[str, Any] = {"id": request_id, "method": method, "params": params or {}}
        if self.session_id:
            payload["sessionId"] = self.session_id
        self.websocket.send(json.dumps(payload))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Chrome did not answer {method}.")
            message = json.loads(self.websocket.recv(timeout=remaining))
            if message.get("method") == "Network.responseReceived":
                event = message.get("params") or {}
                if event.get("type") == "Document":
                    self.document_status = int((event.get("response") or {}).get("status") or 0)
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(f"Chrome {method}: {message['error'].get('message', 'unknown error')}")
            return message.get("result") or {}

    def emulate_media(self, *, color_scheme: str) -> None:
        self._send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": color_scheme}]})

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 30000) -> int | None:
        self.document_status = None
        result = self._send("Page.navigate", {"url": url}, timeout=timeout / 1000)
        if result.get("errorText"):
            raise RuntimeError(f"Chrome navigation: {result['errorText']}")
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") in {"interactive", "complete"}:
                return self.document_status
            time.sleep(0.08)
        raise TimeoutError("The review page did not become ready.")

    def evaluate(self, expression: str) -> Any:
        if expression.lstrip().startswith("() =>"):
            expression = f"({expression})()"
        result = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise RuntimeError("The review page could not be measured.")
        return (result.get("result") or {}).get("value")

    def wait_for_selector(self, selector: str, *, state: str = "visible", timeout: int = 15000) -> None:
        deadline = time.monotonic() + timeout / 1000
        expression = "Boolean((e => e && e.getClientRects().length)(document.querySelector(" + json.dumps(selector) + ")))"
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.1)
        raise TimeoutError(f"Review target did not appear: {selector[:80]}")

    def wait_for_timeout(self, milliseconds: int) -> None:
        time.sleep(milliseconds / 1000)

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        data = self._send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full_page}, timeout=30).get("data")
        if not data:
            raise RuntimeError("Chrome returned no screenshot.")
        Path(path).write_bytes(base64.b64decode(data))


@contextmanager
def chromium_review_page(*, width: int, height: int):
    from websockets.sync.client import connect

    executable = _browser_executable()
    # Chrome helpers can hold cache files for a moment after exit; a failed cleanup must not discard the capture.
    with tempfile.TemporaryDirectory(prefix="neyvia-review-", ignore_cleanup_errors=True) as profile:
        process = subprocess.Popen([
            str(executable), "--headless=new", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-extensions", "about:blank",
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 10
            port_info = ""
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    port_info = active_port.read_text(encoding="utf-8")
                    if len(port_info.splitlines()) >= 2:
                        break
                except (FileNotFoundError, PermissionError):
                    pass
                time.sleep(0.05)
            if len(port_info.splitlines()) < 2:
                raise RuntimeError("Chrome did not start its local review session.")
            port, socket_path = port_info.splitlines()[:2]
            with connect(f"ws://127.0.0.1:{port}{socket_path}", proxy=None, max_size=12_000_000) as socket:
                yield ChromiumReviewPage(socket, width=width, height=height)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=4)
