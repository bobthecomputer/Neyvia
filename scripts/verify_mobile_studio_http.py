"""Exercise Mobile Studio's real authenticated HTTP/tool and preview boundaries.

Uses only disposable local data and port 47922; never builds, installs or downloads.
"""
from __future__ import annotations

import argparse
import gc
import http.cookiejar
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["NEYVIA_COORDINATOR_AUTOSTART"] = "0"
os.environ["FLUXIO_WATCHDOG_AUTOSTART"] = "0"
os.environ["FLUXIO_RUNTIME_AUTO_UPDATE"] = "0"

from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.web_backend import FluxioWebBackend, make_handler


def verify(root: Path):
    backend = FluxioWebBackend(root, root)
    server = ThreadingHTTPServer(("127.0.0.1", 47922), make_handler(backend))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    auth = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    anonymous = build_opener()
    origin = "http://127.0.0.1:47922"
    checks = []

    def request(path, body=None, opener=auth, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = Request(origin + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=30) as response:
                content = response.read()
                return response.status, response.headers, content if raw else json.loads(content)
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def tool(name, arguments):
        code, headers, body = request("/api/ui/tools/call", {"tool": "neyvia.mobile." + name, "arguments": arguments})
        assert code == 200, (code, body)
        return body["data"]["result"]

    try:
        assert request("/api/ui/state", opener=anonymous)[0] == 401
        assert request("/api/auth/login", {"username": backend.username, "password": backend.generated_admin_password})[0] == 200
        checks.append("authenticated HTTP boundary")
        args = {"path": str(root / "apps"), "name": "Backend Phone"}
        approval = tool("create", args)
        assert approval["status"] == "approval_required"
        request("/api/ui/approve", {"id": approval["approvalId"]})
        created = tool("create", args)
        project, url = created["created"], created["preview"]["url"]
        shown = tool("preview", {"project": project, "device": "iphone-se"})
        assert shown["device"] == "iphone-se" and shown["preview"]["url"] == url
        checks.append("native tool approval and starter creation")
        request("/api/ui/app-state", {"app": "mobile-studio", "state": {
            "project": project, "device": "pixel-9", "orientation": "landscape", "dark": True}})
        status = tool("status", {})
        assert status["device"] == "pixel-9" and status["orientation"] == "landscape" and status["dark"]
        checks.append("UI/bot shared device state")
        code, headers, page = request(url, opener=anonymous, raw=True)
        assert code == 200 and b"window.__NX_MOBILE__" in page and b'"device": "pixel-9"' in page
        assert "allow-same-origin" not in headers["Content-Security-Policy"]
        assert request(url + "app.js", opener=anonymous, raw=True)[0] == 200
        assert request(url + "__nx/helper.js", opener=anonymous, raw=True)[0] == 200
        assert request(url + "%2e%2e/app.json", opener=anonymous, raw=True)[0] == 403
        assert request(url + "missing.js", opener=anonymous, raw=True)[0] == 404
        assert request(url + "settings", opener=anonymous, raw=True)[0] == 200
        checks.append("anonymous capability preview, helper, SPA and traversal")
        request(url + "__nx/storage", {"saved": "phone"}, opener=anonymous)
        assert request(url + "__nx/storage", opener=anonymous)[2] == {"saved": "phone"}
        before = request(url + "__nx/version", opener=anonymous)[2]
        asset = Path(project) / "www/app.js"
        asset.write_text(asset.read_text(encoding="utf-8") + "\n// live edit\n", encoding="utf-8")
        after = request(url + "__nx/version", opener=anonymous)[2]
        assert before["other"] != after["other"]
        checks.append("persistent preview storage and hot reload version")
        for platform in ("android", "ios"):
            if not status[platform]["ready"]:
                result = tool("build", {"platform": platform})
                assert result["status"] == "blocked" and result["needsPaul"] and result["missing"]
                checks.append(platform + " missing-toolchain boundary")
        assert tool("setup", {"part": "ios-compiler"})["status"] == "approval_required"
        assert tool("install", {"target": "usb"})["status"] == "blocked"
        checks.append("setup approval and no-APK installation boundary")
        print(json.dumps({"ok": True, "checks": checks, "androidReady": status["android"]["ready"],
                          "iosReady": status["ios"]["ready"], "androidNotes": status["android"]["notes"]}, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        workspace_for(root).close()
        # sqlite connection context managers in the existing auth service commit
        # but release their handles on collection; Windows needs them released
        # before the disposable directory is removed.
        gc.collect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Optional disposable scratch folder to retain for inspection")
    args = parser.parse_args()
    if args.root:
        if args.root.exists() and any(args.root.iterdir()):
            parser.error("--root must be new or empty")
        args.root.mkdir(parents=True, exist_ok=True)
        verify(args.root.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="nx-mobile-http-") as scratch:
            verify(Path(scratch))
