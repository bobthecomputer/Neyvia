"""Owner-configured local control origins shared by MCP and extension workers."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

_CAPTURE_AUTHORITY = ContextVar("neyvia_browser_capture_authority", default=None)


@contextmanager
def capture_authority(root, origin, *, legacy_ports, app_factory=False):
    """Bind an observational capture to the caller's explicit browser scope."""
    token = _CAPTURE_AUTHORITY.set(lambda page: guard_browser_page(
        root, page, origin, legacy_ports=legacy_ports, app_factory=app_factory))
    try:
        yield
    finally:
        _CAPTURE_AUTHORITY.reset(token)


def current_capture_authority():
    return _CAPTURE_AUTHORITY.get()


def approved_browser_url(root, value, *, legacy_ports, app_factory=False):
    ports = set(legacy_ports)
    path = Path(root) / "config" / "neyvia_browser_authority.json"
    if path.is_file():
        configuration = json.loads(path.read_text(encoding="utf-8"))
        proof_ports = configuration.get("proofPorts", [])
        if configuration.get("schema") != "neyvia.browser-authority.v1" or not isinstance(proof_ports,list):
            raise ValueError("Browser authority config requires explicitly assigned local proof ports")
        # The owner declares the range; browser_ports applies the shared safety
        # limits (unprivileged, bounded, never the live Neyvia ports).
        from .browser_ports import parse_ports
        ports.update(parse_ports(proof_ports))
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http","https"} or parsed.username or parsed.password:
        raise ValueError("Browser interaction requires a credential-free http(s) URL")
    if parsed.hostname not in {"127.0.0.1","localhost"} or parsed.port not in ports:
        raise ValueError("Browser interaction URL is outside the approved local fixture origins")
    route = unquote(unquote(parsed.path or "/"))
    if any(part in {".",".."} for part in route.split("/")) or "\\" in route:
        raise ValueError("Browser interaction URL contains a route traversal")
    preview = app_factory and re.fullmatch(r"/api/app-factory/app-[A-Za-z0-9-]+/(?:[A-Za-z0-9._/-]*)?",route)
    if not (route == "/control" or route.startswith("/control/") or preview):
        raise ValueError("Browser interaction is limited to approved local control routes")
    return str(value).strip()


def guard_browser_page(root, page, origin, *, legacy_ports, app_factory=False):
    """Block escaped navigation before Chrome fetches it, including redirects."""
    if not callable(getattr(page,"route",None)):
        raise ValueError("Browser transport cannot enforce navigation authority")
    transport = getattr(page,"context",None)
    if not callable(getattr(transport,"route",None)):
        transport = page
    previous = getattr(page,"_neyvia_navigation_guard",None)
    if previous:
        previous[0].unroute("**/*",previous[1])
    netloc = urlparse(origin).netloc
    def guarded_route(route):
        request = route.request
        try:
            if request.is_navigation_request():
                approved_browser_url(root,request.url,legacy_ports=legacy_ports,app_factory=app_factory)
            elif urlparse(request.url).netloc != netloc:
                raise ValueError("Browser resource escaped the approved origin")
        except ValueError:
            route.abort()
        else:
            # Redirected resources also bypass a second route callback. Read
            # one approved response for every request and refuse its Location.
            response = route.fetch(max_redirects=0)
            if 300 <= response.status < 400 and response.headers.get("location"):
                response.dispose()
                route.abort()
            else:
                route.fulfill(response=response)
                response.dispose()
    transport.route("**/*",guarded_route)
    page._neyvia_navigation_guard = (transport,guarded_route)
