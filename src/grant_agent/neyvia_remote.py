"""Live, owner-consented remote windows on T16's background preview service.

Grants, one-use invites, relay capabilities, frames and redacted logs live only
in memory. No file/credential/desktop/launch capability is delegated. Numeric
tailnet addresses use the existing encrypted tailnet, never configure it here.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .cua_native import NativeWorker
from .neyvia_cua import DANGEROUS, now, refusal, result, service_for as cua_for

TEXT = {"type": "string"}
CONNECTION = {"connectionId": TEXT}
WINDOW = {**CONNECTION, "windowId": {"type": "integer"}}
DEFINITIONS = [
    ("remote.state", "Read owner-enabled remote sessions and connections; never reveals capabilities.", {}, []),
    ("remote.windows", "List only windows the host has explicitly allowed on an existing connection.", CONNECTION, ["connectionId"]),
    ("remote.snapshot", "Observe a remote window with protected field values omitted; credential input remains host-only.", WINDOW, ["connectionId", "windowId"]),
    ("remote.log", "Read the shared redacted T16 log; no recording or input text.", {**CONNECTION, "since_seq": {"type": "integer", "minimum": 0}}, ["connectionId"]),
]
OPS = frozenset("state targets enable kill connect disconnect windows snapshot input log".split())
COMMANDS = frozenset("remote_" + op + "_command" for op in OPS | {"frame"})
PEER_OPS = frozenset("redeem windows snapshot frame input log end".split())
INPUTS = frozenset("click type_text press_key scroll".split())
FIELDS = frozenset("windowId kind captureId element_token x y text key direction amount".split())


class RemoteError(ValueError):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def _loopback(value):
    try:
        return ipaddress.ip_address(value.split("%")[0]).is_loopback
    except ValueError:
        return False


def _network(value):
    try:
        address = ipaddress.ip_address(value.split("%")[0])
        return address in ipaddress.ip_network("100.64.0.0/10") or address in ipaddress.ip_network("fd7a:115c:a1e0::/48") or (
            address.is_loopback and os.environ.get("NEYVIA_REMOTE_PROOF_LOOPBACK") == "1")
    except ValueError:
        return False


def _proof_port_allowlist():
    path = Path(__file__).resolve().parents[2] / "config/neyvia_remote.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))["proofPorts"]
        if not isinstance(values, list) or not values or any(type(p) is not int or not 1024 <= p <= 65535 or p == 47881 for p in values):
            raise ValueError("Invalid proof ports")
        defaults = set(values)
        # An isolated proof process declares its own assigned ports explicitly
        # (proof_ports.configure_ports); those are proof services too.
        declared = os.environ.get("NEYVIA_PROOF_ALLOWED_PORTS")
        if declared is not None:
            assigned = json.loads(declared)
            if not isinstance(assigned, list) or any(type(p) is not int or not 1024 <= p <= 65535 or p == 47881 for p in assigned):
                raise ValueError("Invalid declared proof ports")
            defaults |= set(assigned)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RemoteError("proof_port_not_allowed") from exc
    return defaults


def _proof_ports():
    defaults = _proof_port_allowlist()
    configured = os.environ.get("NEYVIA_REMOTE_PROOF_PORTS", "")
    if not configured:
        return defaults
    try:
        ports = {int(value.strip()) for value in configured.split(",")}
    except ValueError as exc:
        raise RemoteError("proof_port_not_allowed") from exc
    if not ports or not ports <= defaults:
        raise RemoteError("proof_port_not_allowed")
    return ports


def _url(value):
    p = urlsplit(str(value))
    # Numeric IPs avoid DNS rebinding and redirect/proxy-based SSRF. Never accept
    # arbitrary public URLs, URL credentials, paths, query strings or fragments.
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.path not in {"", "/"} or p.query or p.fragment or not _network(p.hostname):
        raise RemoteError("tailnet_address_required")
    if _loopback(p.hostname) and p.port not in _proof_ports():
        raise RemoteError("proof_port_not_allowed")
    if p.port == 47881:
        raise RemoteError("protected_service")
    return str(value).rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RemoteError("redirect_refused")


class Indicator:
    def __init__(self, stopped):
        self.stopped, self.window_id, self.ready = stopped, None, threading.Event()
        binary = NativeWorker._compile("remote-indicator.cs", "winexe")
        self.proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        # Keep startup alive while the native driver initializes. Heartbeats
        # cannot depend on a grant already being registered after slow UIA work.
        def keep_alive():
            while not self.stopped.wait(.3): self.heartbeat()
        threading.Thread(target=keep_alive, name="remote-indicator-heartbeat", daemon=True).start()
        def read():
            try:
                for line in self.proc.stdout:
                    if line.startswith("READY "):
                        self.window_id = int(line.split()[1]); self.ready.set()
                    else:
                        self.stopped.set()
            finally:
                self.stopped.set(); self.ready.set()
        threading.Thread(target=read, name="remote-host-indicator", daemon=True).start()
        if not self.ready.wait(8) or self.stopped.is_set() or not self.window_id:
            self.close(); raise RemoteError("host_indicator_unavailable", 503)

    def heartbeat(self):
        if self.proc.poll() is not None:
            self.stopped.set(); return
        try:
            self.proc.stdin.write("live\n"); self.proc.stdin.flush()
        except (OSError, ValueError):
            self.stopped.set()

    def close(self):
        self.stopped.set()
        try:
            self.proc.stdin.close(); self.proc.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill(); self.proc.wait(timeout=3)


class RemoteService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self._cua = None
        self.grants, self.connections, self.attempts = {}, {}, {}
        self.closed = threading.Event()
        self.controller = "pc-" + secrets.token_hex(16)
        # Handlers carry no cookies or per-connection capabilities. Reuse their
        # TLS context; each open still validates the URL and builds a fresh
        # request, with redirects and environment proxies disabled.
        self.peer_http = build_opener(ProxyHandler({}), NoRedirect())
        threading.Thread(target=self._monitor, name="remote-consent-monitor", daemon=True).start()
        atexit.register(self.close)

    @property
    def cua(self):
        with self.lock:
            if self._cua is None:
                self._cua = cua_for(self.root)
            return self._cua

    def close(self):
        self.closed.set()
        for g in list(self.grants.values()):
            self.stop(g, "backend_stopped")

    def _monitor(self):
        while not self.closed.wait(.1):
            for g in list(self.grants.values()):
                if g["status"] == "stopped":
                    continue
                s = g["cua"]
                if g["stop"].is_set() or time.monotonic() >= g["expires"]:
                    self.stop(g, "host_stop" if g["stop"].is_set() else "expired")
                elif s["status"] == "ended" or s["control"] != "agent":
                    self.stop(g, "host_takeover")

    def public(self, g):
        return {"id": g["id"], "status": g["status"], "name": g["name"], "windowIds": list(g["windows"]),
                "expiresAt": g["expiresAt"], "recording": False, "reason": g.get("reason"),
                "indicator": {"visible": g["status"] != "stopped" and not g["stop"].is_set(), "windowId": g["indicator"].window_id}}

    def connection_view(self, c):
        return {k: v for k, v in c.items() if not k.startswith("_")}

    def state(self):
        return {"sessions": [self.public(g) for g in self.grants.values()],
                "connections": [self.connection_view(c) for c in self.connections.values()]}

    def stop(self, g, reason):
        # Revoke first, without waiting for the driver's action lock. Pending and
        # subsequent dispatch gates see this immediately. In-flight native work
        # cannot be undone; no retry or reconnect occurs automatically.
        g["stop"].set()
        with self.lock:
            if g["status"] == "stopped": return
            g.update(status="stopped", reason=reason, inviteHash=None, tokenHash=None)
            s = g["cua"]
            s.update(status="ended", control="paul", pausedReason=reason, approvals=[])
            for key in list(self.cua.frames):
                if key[0] == s["id"]: self.cua.frames.pop(key, None)
            for key in list(self.cua.snapshots):
                if key[0] == s["id"]: self.cua.snapshots.pop(key, None)
        self.cua.changed(s)
        # Indicator teardown may wait for a GUI thread. Consent is already
        # revoked; acknowledge Stop without waiting on native cleanup.
        threading.Thread(target=g["indicator"].close, name="remote-indicator-reap", daemon=True).start()

    def gate(self, g):
        self.dispatch_admission(g)
        self.cua.check_input(g["cua"])
        if g["cua"]["control"] != "agent" or g["cua"]["status"] == "ended":
            self.stop(g, "host_takeover"); raise RemoteError("host_takeover", 409)

    def dispatch_admission(self, g):
        # Also runs inside NativeWorker.lock after waiting for other requests.
        # It must not issue another native request recursively.
        if g["stop"].is_set() or g["status"] == "stopped" or time.monotonic() >= g["expires"]:
            raise RemoteError("session_stopped", 409)
        if g["indicator"].proc.poll() is not None:
            g["stop"].set(); raise RemoteError("host_indicator_missing", 409)
        if g["cua"]["control"] != "agent" or g["cua"]["status"] == "ended":
            raise RemoteError("host_takeover", 409)

    def target(self, g, w):
        self.gate(g)
        pinned = g["windows"].get(int(w["windowId"]))
        if not pinned or any(w.get(k) != pinned.get(k) for k in ("pid", "exe", "processStartTime")):
            raise RemoteError("window_not_allowed")
        self.cua.native.request("remoteGuard", {"windowId": str(w["windowId"])})

    def enable(self, args):
        ids = args.get("windowIds")
        minutes = args.get("minutes", 10)
        if not isinstance(ids, list) or not 1 <= len(ids) <= 8 or any(type(n) is not int or n <= 0 for n in ids) or type(minutes) is not int or not 1 <= minutes <= 60:
            raise RemoteError("choose_windows_and_expiry", 400)
        if len([g for g in self.grants.values() if g["status"] != "stopped"]) >= 4:
            raise RemoteError("end_existing_session", 409)
        windows = {int(w["windowId"]): w for w in self.cua.windows()}
        chosen = []
        for identity in dict.fromkeys(ids):
            w = windows.get(identity)
            if not w or not w.get("exe") or not w.get("processStartTime") or "neyvia" in (w["exe"] + w["title"]).casefold():
                raise RemoteError("window_not_allowed")
            self.cua.native.request("remoteGuard", {"windowId": str(identity)})
            chosen.append(w)
        stopped = threading.Event()
        indicator = Indicator(stopped)
        s = None
        try:
            identity, invite = "r-" + secrets.token_hex(12), secrets.token_urlsafe(32)
            s = self.cua.new_session([w["exe"] for w in chosen], {"chatId": identity, "app": "remote", "title": "Remote owner"}, ephemeral=True)
            g = {"id": identity, "name": str(args.get("name") or "Remote session")[:80], "status": "enabled",
                 "windows": {int(w["windowId"]): w for w in chosen}, "cua": s, "stop": stopped, "indicator": indicator,
                 "expires": time.monotonic() + minutes * 60, "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
                 "inviteHash": hashlib.sha256(invite.encode()).hexdigest(), "inviteExpires": time.monotonic() + 120, "tokenHash": None}
            s["_targetGuard"] = lambda w: self.target(g, w)
            s["_windowPins"] = g["windows"]
            s["_resolveTarget"] = lambda identity: self.cua.native.request("window", {"windowId": str(identity)})
            s["_snapshot"] = lambda w, image, elements: self.snapshot(g, w, image, elements)
            s["_dispatchGuard"] = lambda: self.gate(g)
            s["_dispatch"] = lambda w, tool, a, element: self.dispatch(g, w, tool, a, element)
            s["windows"] = [w for w in s["windows"] if w["window_id"] in g["windows"]]
            with self.lock: self.grants[identity] = g
            self.gate(g)
            return {"session": self.public(g), "invite": invite}
        except Exception:
            indicator.close()
            if s: s.update(status="ended", control="paul")
            raise

    def snapshot(self, g, w, image, elements):
        self.target(g, w)
        observed = self.cua.native.request("remoteObserve", {"windowId": str(w["windowId"]), "image": image})
        self.gate(g)
        data, capture = observed["observation"], observed.get("capture")
        scale_x = scale_y = 1
        if capture and max(capture["width"], capture["height"]) > 1600:
            import io
            from PIL import Image
            picture = Image.open(io.BytesIO(base64.b64decode(capture["pngBase64"], validate=True)))
            picture.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            encoded = io.BytesIO(); picture.save(encoded, format="PNG")
            scale_x, scale_y = picture.width / capture["width"], picture.height / capture["height"]
            capture = {**capture, "width": picture.width, "height": picture.height, "pngBase64": base64.b64encode(encoded.getvalue()).decode()}
        identity = "rc-" + secrets.token_hex(16)
        b = w["bounds"]
        rows = []
        for e in data["tree"]:
            geometry = e.get("bounds") or {}
            patterns = e.get("patterns", [])
            rows.append({"element_token": e["id"], "role": e["role"], "label": e.get("name", ""),
                         "enabled": e["enabled"], "offscreen": e["offscreen"],
                         "screenshot_frame": {"x": (geometry.get("x", 0) - b["x"]) * scale_x, "y": (geometry.get("y", 0) - b["y"]) * scale_y,
                                              "w": geometry.get("width", 0) * scale_x, "h": geometry.get("height", 0) * scale_y},
                         "protected": bool(e.get("isPassword")),
                         "actions": [] if e.get("isPassword") else [p for p in ("invoke", "toggle", "scroll", "selectionItem") if p in patterns] + (["set_value"] if "value" in patterns else []),
                         **({"value": e["value"]} if "value" in e else {}), "_native": e})
        value = result({"capture_id": identity, "snapshot_id": identity, "window_id": int(w["windowId"]), "pid": w["pid"],
                        "projectionTruncated": bool(data.get("truncated")),
                        "screenshot_scale": scale_x, "elements": rows,
                        "screenshot_width": capture["width"] if capture else b["width"],
                        "screenshot_height": capture["height"] if capture else b["height"]})
        if capture:
            value["content"].append({"type": "image", "mimeType": "image/png", "data": capture["pngBase64"]})
        return value

    def dispatch(self, g, w, tool, a, element):
        self.target(g, w)
        if not element or element.get("offscreen") or not element.get("enabled"):
            return refusal("stale_element_token", "Select a fresh visible control")
        if DANGEROUS.search(element.get("label", "")):
            return refusal("host_approval_required", "Perform this consequential action on the host")
        e = element["_native"]
        if e.get("isPassword"):
            return refusal("protected_field", "Enter credentials on the host")
        patterns, cls = e.get("patterns", []), e.get("className", "")
        classic_edit = cls.startswith("WindowsForms10.EDIT") or cls == "Edit"
        classic_button = cls.startswith("WindowsForms10.BUTTON") or cls == "Button" and bool(e.get("nativeWindowHandle"))
        if tool == "type_text" and e["role"] in {"Edit", "Document"} and "value" in patterns:
            action = "editAppend" if classic_edit else "valueAppend"
        elif tool == "click":
            if classic_button: action = "buttonClick"
            elif "toggle" in patterns: action = "toggle"
            elif "selectionItem" in patterns: action = "select"
            elif "invoke" in patterns and not cls.startswith("HwndWrapper") and cls != "Button": action = "invoke"
            else: return refusal("background_unavailable", "This control has no safe background action")
        elif tool == "press_key": action = "key"
        elif tool == "scroll" and "scroll" in patterns: action = "scroll"
        else: return refusal("background_unavailable", "This control does not support the requested background action")
        self.gate(g)
        try:
            raw = self.cua.native.request("remoteAction", {"windowId": str(w["windowId"]), "elementId": e["id"], "action": action,
                "text": a.get("text"), "key": a.get("key"), "horizontal": "NoAmount", "vertical": "SmallDecrement" if a.get("direction") == "up" else "SmallIncrement",
                "expectedName": e.get("name", ""), "expectedRole": e["role"], "expectedClass": cls,
                "inputGeneration": g["cua"]["_inputMarker"][1]}, preflight=lambda: self.dispatch_admission(g))
        except ValueError as exc:
            if str(exc) in {"protected_field", "protection_unknown"}:
                return refusal(str(exc), "Enter credentials or unclassified field input on the host")
            if str(exc) == "stale_element_token":
                return refusal("stale_element_token", "The control changed before input; refresh the snapshot")
            raise
        return result({"effect": raw["effect"], "route": "synthetic_events" if raw["mechanism"] != "uia" else "accessibility",
                       "delivery": {"mode": "background", "delivered_count": 1}, "summary": "Remote background input delivered"})

    def redeem(self, args, address):
        now_m = time.monotonic()
        recent = [t for t in self.attempts.get(address, []) if now_m - t < 60]
        if len(recent) >= 10: raise RemoteError("pairing_rate_limited", 429)
        self.attempts[address] = [*recent, now_m]
        invite, controller = args.get("invite"), args.get("controller")
        if not isinstance(invite, str) or not 20 <= len(invite) <= 128 or not isinstance(controller, str) or not 16 <= len(controller) <= 80:
            raise RemoteError("invite_invalid", 401)
        digest = hashlib.sha256(invite.encode()).hexdigest()
        with self.lock:
            g = next((g for g in self.grants.values() if g["inviteHash"] and hmac.compare_digest(g["inviteHash"], digest)), None)
            if not g or g["status"] != "enabled" or now_m > g["inviteExpires"]:
                raise RemoteError("invite_invalid", 401)
            self.gate(g)
            token = g["id"] + "." + secrets.token_urlsafe(32)
            g.update(inviteHash=None, tokenHash=hashlib.sha256(token.encode()).hexdigest(), controller=controller, address=address, status="connected")
        return {"session": self.public(g), "capability": token, "windows": self.windows(g)}

    def authorize(self, header, controller, address):
        token = str(header).removeprefix("Neyvia-Remote ")
        identity = token.partition(".")[0]
        g = self.grants.get(identity)
        if not g or not g["tokenHash"] or not hmac.compare_digest(g["tokenHash"], hashlib.sha256(token.encode()).hexdigest()) or g.get("controller") != controller or g.get("address") != address:
            raise RemoteError("capability_invalid", 401)
        self.gate(g)
        return g

    def windows(self, g):
        self.gate(g)
        rows = []
        for identity in g["windows"]:
            try:
                w = self.cua.native.request("window", {"windowId": str(identity)})
            except ValueError:
                continue
            self.target(g, w)
            rows.append({"window_id": int(w["windowId"]), "pid": w["pid"], "app_name": w["processName"], "title": w["title"],
                         "bounds": w["bounds"], "allowed": True, "minimized": w["minimized"], "is_on_screen": not w["minimized"]})
        return rows

    def peer(self, op, args, g):
        self.gate(g)
        if op == "end": self.stop(g, "remote_disconnected"); return {"stopped": True}
        if op == "windows": return {"windows": self.windows(g)}
        if op == "log":
            rows = [r for r in self.cua.log if r["sessionId"] == g["cua"]["id"] and r["seq"] > int(args.get("since_seq", 0))]
            return {"session": g["id"], "entries": rows[-200:], "next_seq": self.cua.sequence}
        if type(args.get("windowId")) is not int: raise RemoteError("window_required", 400)
        s = g["cua"]
        w = self.cua.target(s, {"windowId": args["windowId"]})
        with self.cua.action_lock:
            self.target(g, w)
            if op in {"snapshot", "frame"}:
                self.cua.snapshot(s, w, image=True, elements=True)
                self.gate(g)
                frame = self.cua.frames[(s["id"], str(w["windowId"]))]
                if op == "frame": return frame
                projection = self.cua.snapshots[(s["id"], str(w["windowId"]))]["data"]
                return {**projection, "elements": [{k: v for k, v in e.items() if k != "_native"} for e in projection["elements"]]}
            if op != "input" or set(args) - FIELDS:
                raise RemoteError("operation_not_allowed")
            tool = args.get("kind")
            if tool not in INPUTS: raise RemoteError("input_not_allowed")
            if not isinstance(args.get("text", ""), str) or len(args.get("text", "")) > 4096:
                raise RemoteError("input_too_large", 400)
            if tool == "press_key" and args.get("key", "").lower() not in {"backspace", "left", "right", "up", "down", "home", "end", "pageup", "pagedown", "escape"}:
                raise RemoteError("key_not_allowed")
            if tool == "scroll" and (args.get("direction") not in {"up", "down"} or args.get("amount", 1) != 1):
                raise RemoteError("scroll_not_allowed")
            snap = self.cua.snapshots.get((s["id"], str(w["windowId"])))
            if not snap or time.monotonic() - snap["at"] > 60: raise RemoteError("stale_element_token", 409)
            # Remote text/key/scroll must select a control explicitly; do not
            # guess the active editor or send global keys/clipboard hotkeys.
            if tool != "click" and not args.get("element_token"): raise RemoteError("select_control", 409)
            element = next((e for e in snap["data"]["elements"] if e["element_token"] == args.get("element_token")), None)
            if element and DANGEROUS.search(element.get("label", "")): raise RemoteError("host_approval_required")
            if tool == "click" and not element:
                point = {"capture_id": args.get("captureId"), "x": args.get("x"), "y": args.get("y")}
                self.cua.owner_point(s, w, point)
                args = {k: v for k, v in args.items() if k not in {"x", "y", "captureId"}}
                args["element_token"] = point["element_token"]
                snap = self.cua.snapshots[(s["id"], str(w["windowId"]))]
                element = next((e for e in snap["data"]["elements"] if e["element_token"] == point["element_token"]), None)
            if not element: raise RemoteError("stale_element_token", 409)
            if DANGEROUS.search(element.get("label", "")): raise RemoteError("host_approval_required")
            value = self.cua.request("input", {"sessionId": s["id"], **args}, owner=True)
            self.gate(g)
            if value.get("status") in {"refused", "failed", "denied"}: raise RemoteError("background_input_refused", 409)
            return value

    def remote(self, c, op, args):
        if op not in PEER_OPS: raise RemoteError("operation_not_allowed")
        body = json.dumps(args).encode()
        req = Request(_url(c["url"]) + "/api/ui/remote/peer/" + op, data=body,
                      headers={"Content-Type": "application/json", "Authorization": "Neyvia-Remote " + c.get("_capability", ""), "X-Neyvia-Controller": self.controller})
        try:
            with self.peer_http.open(req, timeout=15) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024: raise RemoteError("response_too_large", 503)
                if op == "frame": return {"raw": raw, "headers": dict(response.headers)}
                answer = json.loads(raw)
                return answer["data"]
        except HTTPError as exc:
            try: code = json.loads(exc.read(4096)).get("code", "host_refused")
            except (ValueError, OSError): code = "host_refused"
            if exc.code == 401 or code in {"session_stopped", "host_takeover", "host_indicator_missing"}: c["status"] = "stopped"
            raise RemoteError(code, exc.code) from None
        except (URLError, OSError, TimeoutError, ValueError):
            raise RemoteError("host_unavailable", 503) from None

    def request(self, op, args, *, host=False):
        if op == "state": return self.state()
        if op in {"targets", "enable", "kill"} and not host: raise RemoteError("host_owner_required")
        if op == "targets":
            rows = []
            for w in self.cua.windows():
                if not w.get("exe") or not w.get("processStartTime") or "neyvia" in (w["exe"] + w["title"]).casefold(): continue
                # Eligibility pins window identity; field protection is checked
                # only on the live target control before typing.
                try:
                    self.cua.native.request("remoteGuard", {"windowId": str(w["windowId"])})
                    reason = None
                except (ValueError, RuntimeError):
                    reason = "protected_or_unknown"
                rows.append({"windowId": int(w["windowId"]), "app": w["processName"], "title": w["title"], "eligible": reason is None, "reason": reason})
            return {"targets": rows}
        if op == "enable": return self.enable(args)
        if op == "kill":
            selected = [g for g in self.grants.values() if not args.get("sessionId") or g["id"] == args["sessionId"]]
            for g in selected: self.stop(g, "host_stop")
            return {"stopped": True, "sessions": [self.public(g) for g in selected]}
        if op == "connect":
            c = {"id": "rc-" + secrets.token_hex(12), "url": _url(args.get("url")), "status": "connected", "recording": False}
            answer = self.remote(c, "redeem", {"invite": args.get("invite"), "controller": self.controller})
            c.update(sessionId=answer["session"]["id"], windows=answer["windows"], _capability=answer["capability"])
            with self.lock: self.connections[c["id"]] = c
            return {"connection": self.connection_view(c)}
        c = self.connections.get(str(args.get("connectionId")))
        if not c: raise RemoteError("connection_missing", 404)
        if c["status"] != "connected": raise RemoteError("session_stopped", 409)
        if op == "disconnect":
            try: self.remote(c, "end", {})
            finally: c.update(status="stopped", _capability="")
            return {"stopped": True}
        if op not in PEER_OPS: raise RemoteError("operation_not_allowed")
        return self.remote(c, op, {k: v for k, v in args.items() if k != "connectionId"})


_SERVICES, _LOCK = {}, threading.Lock()


def service_for(root):
    key = str(Path(root).resolve())
    with _LOCK:
        if key not in _SERVICES: _SERVICES[key] = RemoteService(root)
        return _SERVICES[key]


def call(workspace, name, args):
    if name not in {d[0] for d in DEFINITIONS}: raise RemoteError("operation_not_allowed")
    return service_for(workspace.bus.root).request(name.removeprefix("remote."), args)


def _origin(handler):
    origin = handler.headers.get("Origin")
    if not origin: return _loopback(handler.client_address[0])
    p = urlsplit(origin)
    return p.scheme in {"http", "https"} and (p.netloc == handler.headers.get("Host") or origin == os.environ.get("NEYVIA_REMOTE_UI_ORIGIN"))


def serve_http(backend, handler, parsed, method):
    from .web_backend import _read_json_body
    # Intentionally no reflected CORS header: account cookies and capabilities
    # must never be usable by an unrelated browser origin.
    def answer(status, value):
        raw = json.dumps(value).encode(); handler.send_response(status)
        handler.send_header("Content-Type", "application/json"); handler.send_header("Content-Length", str(len(raw)))
        handler.send_header("Cache-Control", "no-store"); handler.send_header("X-Content-Type-Options", "nosniff")
        # Refusals may occur before consuming a hostile body. Close this HTTP/1
        # connection so unread bytes cannot become another request in a pool.
        handler.send_header("Connection", "close"); handler.close_connection = True
        handler.end_headers(); handler.wfile.write(raw)
    def png(frame):
        raw = frame["raw"]; headers = frame.get("headers") or {"X-Frame-Seq": str(frame["metadata"]["seq"]),
            "X-Capture-Id": frame["metadata"]["captureId"], "X-CUA-Frame-SHA256": frame["sha256"]}
        handler.send_response(200)
        for key, value in {"Content-Type": "image/png", "Content-Length": str(len(raw)), "Cache-Control": "no-store",
                           **{k: headers[k] for k in ("X-Frame-Seq", "X-Capture-Id", "X-CUA-Frame-SHA256") if k in headers}}.items(): handler.send_header(key, value)
        handler.end_headers(); handler.wfile.write(raw)
    def body():
        if handler.headers.get("Transfer-Encoding") or handler.headers.get("Content-Encoding"):
            raise RemoteError("encoded_body_refused", 400)
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536: raise RemoteError("body_too_large", 413)
        if handler.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise RemoteError("json_required", 400)
        value = _read_json_body(handler)
        if not isinstance(value, dict): raise RemoteError("invalid_request", 400)
        return value
    try:
        service = service_for(backend.root)
        suffix = parsed.path.removeprefix("/api/ui/remote").strip("/")
        if suffix.startswith("peer/"):
            op = suffix[5:]
            if method != "POST" or op not in PEER_OPS: raise RemoteError("operation_not_allowed")
            if not _network(handler.client_address[0]): raise RemoteError("tailnet_required")
            if handler.headers.get("Origin"): raise RemoteError("peer_browser_refused")
            if op == "redeem": value = service.redeem(body(), handler.client_address[0])
            else:
                g = service.authorize(handler.headers.get("Authorization", ""), handler.headers.get("X-Neyvia-Controller", ""), handler.client_address[0])
                value = service.peer(op, body(), g)
            if op == "frame": png(value); return
        else:
            session = backend.authenticated_session(handler)
            if not session: raise RemoteError("login_required", 401)
            if str(session.get("username", "")).casefold() != backend.username.casefold(): raise RemoteError("owner_required")
            if not _origin(handler): raise RemoteError("origin_not_allowed")
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if method == "POST":
                envelope = body(); op, args = envelope.get("op"), envelope.get("args") or {}
                if op not in OPS: raise RemoteError("operation_not_allowed")
            elif method == "GET" and suffix in {"state", "targets", "windows", "frame"}:
                op, args = suffix, query
                if "windowId" in args: args["windowId"] = int(args["windowId"])
            else: raise RemoteError("operation_not_allowed")
            if not isinstance(args, dict): raise RemoteError("invalid_request", 400)
            expected = args.pop("_expectedStateRoot", None)
            if expected and Path(expected).resolve() != service.root: raise RemoteError("workspace_mismatch", 409)
            value = service.request(op, args, host=_loopback(handler.client_address[0]))
            if op == "frame": png(value); return
        answer(200, {"ok": True, "data": value})
    except RemoteError as exc:
        answer(exc.status, {"ok": False, "code": exc.code, "error": exc.code.replace("_", " ")})
    except (KeyError, TypeError, ValueError) as exc:
        code = str(exc) if str(exc) in {"protected_field", "protected_window", "protection_unknown", "stale_element_token", "app_not_allowed", "window_target_not_found"} else "invalid_request"
        answer(409 if code in {"protected_window", "protection_unknown", "stale_element_token"} else 400, {"ok": False, "code": code, "error": code.replace("_", " ")})
    except (RuntimeError, OSError):
        answer(503, {"ok": False, "code": "driver_unavailable", "error": "Host driver unavailable"})


def forward_desktop(root, command, payload):
    import http.cookiejar
    base = os.environ.get("NEYVIA_UI_BACKEND_URL") or "http://127.0.0.1:" + os.environ.get("NEYVIA_SERVICE_PORT", "48271")
    p = urlsplit(base)
    if p.scheme != "http" or not _loopback(p.hostname or "") or p.port not in _proof_ports(): raise RemoteError("selected_loopback_backend_required")
    opener = build_opener(ProxyHandler({}), NoRedirect(), __import__("urllib.request", fromlist=["HTTPCookieProcessor"]).HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, body):
        with opener.open(Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=30) as response: return json.load(response)
    post("/api/auth/local-session", {})
    return post("/api/ui/remote", {"op": command.removeprefix("remote_").removesuffix("_command"), "args": {**payload, "_expectedStateRoot": str(Path(root).resolve())}})["data"]
