from __future__ import annotations

import argparse
import html
import http.server
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser

from .subprocess_utils import hidden_windows_subprocess_kwargs


class RelayHandler(http.server.BaseHTTPRequestHandler):
    relay_url = ""
    relay_token = ""
    completed = threading.Event()

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.startswith("/auth/callback?"):
            self.send_error(404, "Not found")
            return
        try:
            request = urllib.request.Request(
                self.relay_url,
                data=json.dumps({"callbackPath": self.path}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.relay_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                body = response.read().decode("utf-8", "replace")
            self._send_html(
                "Codex connected",
                "Codex connection complete. You can close this tab and return to Neyvia.",
                body,
            )
            self.completed.set()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            self._send_html("Relay failed", f"The NAS rejected the OAuth callback: HTTP {exc.code}", detail)
        except Exception as exc:  # pragma: no cover - depends on local network/browser state.
            self._send_html("Relay failed", f"The OAuth relay failed: {exc}", "")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, title: str, message: str, detail: str) -> None:
        detail_html = f"<pre>{html.escape(detail)}</pre>" if detail else ""
        body = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
  </head>
  <body style="font-family: system-ui, sans-serif; padding: 32px;">
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(message)}</p>
    {detail_html}
  </body>
</html>"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relay a Codex localhost OAuth callback back to a Neyvia NAS.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--auth-url", required=True)
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--relay-token", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    return parser.parse_args()


def open_browser(url: str) -> None:
    if webbrowser.open(url):
        return
    if sys.platform.startswith("win"):
        subprocess.Popen(["cmd", "/c", "start", "", url], close_fds=True, **hidden_windows_subprocess_kwargs())  # noqa: S603,S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], close_fds=True, **hidden_windows_subprocess_kwargs())  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", url], close_fds=True, **hidden_windows_subprocess_kwargs())  # noqa: S603,S607


def main() -> int:
    args = parse_args()
    if args.port < 1 or args.port > 65535:
        raise SystemExit(f"Invalid port: {args.port}")
    RelayHandler.relay_url = args.relay_url
    RelayHandler.relay_token = args.relay_token
    RelayHandler.completed.clear()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), RelayHandler)
    server.timeout = 1
    print(f"Listening on http://127.0.0.1:{args.port}/auth/callback", flush=True)
    open_browser(args.auth_url)
    deadline = threading.Event()
    timer = threading.Timer(args.timeout, deadline.set)
    timer.start()
    try:
        while not RelayHandler.completed.is_set() and not deadline.is_set():
            server.handle_request()
    finally:
        timer.cancel()
        server.server_close()
    if not RelayHandler.completed.is_set():
        print("Timed out waiting for the OpenAI Codex OAuth callback.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
