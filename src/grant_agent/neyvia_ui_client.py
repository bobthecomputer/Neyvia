"""Loopback bridge for native agent workers; no provider credentials are copied."""
from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.request
from urllib.parse import urlparse


def call_tool(name: str, args: dict, *, preflight=False, expected_root=None) -> dict:
    base = os.environ["NEYVIA_UI_BACKEND_URL"].rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Model UI bridge must use a loopback backend")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.open(urllib.request.Request(base + "/api/auth/local-session", data=b"{}",
                                      headers={"Content-Type": "application/json"}), timeout=30).close()
    body = json.dumps({"tool": "neyvia." + name, "arguments": args,
                       **({"_expectedStateRoot": str(expected_root)} if expected_root is not None else {})}).encode()
    with opener.open(urllib.request.Request(base + ("/api/ui/tools/preflight" if preflight else "/api/ui/tools/call"), data=body,
                                           headers={"Content-Type": "application/json"}),
                     timeout=240 if name == "perception.observe" and args.get("layer") in {"image", "video"} else 90) as response:
        receipt = json.load(response)["data"]
    if preflight:
        return receipt
    return receipt.get("result") if receipt.get("ok") else {
        "ok": False, "status": receipt.get("status", "failed"), "error": receipt.get("error"),
        **(receipt.get("result") or {}),
    }
