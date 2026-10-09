"""Explicit advisory HTTP provider for the browser's LAYA hook.

Page observations remain untrusted data. The hook never executes a returned
decision or silently substitutes a provider.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configured_provider():
    endpoint = os.environ.get("NEYVIA_BROWSER_LAYA_URL", "").strip()
    if not endpoint:
        return None
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port is None or parsed.port == 47881 or parsed.username or parsed.password
            or parsed.fragment or parsed.query):
        raise ValueError("NEYVIA_BROWSER_LAYA_URL requires an explicit local HTTP endpoint and port")
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def decide(observation, question):
        if len(question) > 20000:
            raise ValueError("Browser decision question exceeds 20000 characters")
        payload = json.dumps({"observation": observation, "question": question,
                              "trust": "untrusted-data", "mode": "advisory"}).encode()
        if len(payload) > 1000000:
            raise ValueError("Browser decision observation exceeds 1 MB")
        request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=15) as response:
                raw = response.read(100001)
                if len(raw) > 100000:
                    raise ValueError("Browser decision provider response exceeds 100 KB")
                result = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise ValueError("Configured browser decision provider did not return a valid response") from exc
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("decision"), (str, dict)):
            raise ValueError("Configured browser decision provider must return ok:true and an advisory decision")
        return result["decision"]

    return decide
