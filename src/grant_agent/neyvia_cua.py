"""PC-owned MIT Cua Driver sessions, background preview, receipts and takeover."""
from __future__ import annotations

import atexit
from contextvars import ContextVar
import base64
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cua_native import NativeWorker
from .durability import atomic_write_json
from .ui_command_bus import bus_for

TEXT = {"type": "string"}
SESSION = {"sessionId": TEXT}
TARGET = {**SESSION, "window_id": {"type": "integer"}}
ACTIONS = frozenset("click double_click right_click type_text press_key hotkey scroll drag set_value invoke_menu".split())
DEFINITIONS = [
    ("cua.state", "Read native sessions, app grants, control and shared log.", {}, []),
    ("cua.windows", "List the owner-allowed native windows.", SESSION, []),
    ("cua.inspect", "Observe a background window. diff_only=true returns typed CL-State handles then semantic diffs; UIA deadlines/missing controls automatically use T18 with explicit model provenance.", {**TARGET, "query": TEXT, "diff_only": {"type": "boolean"}, "previousHandle": TEXT, "reset": {"type": "boolean"}, "max_elements": {"type": "integer", "minimum": 1, "maximum": 2000}}, ["window_id"]),
    ("cua.action", "Use an upstream cua-driver action in an authorized session. Agent interference pauses execution; Paul's physical input is independent. Consequential actions need owner approval.", {**SESSION, "tool": {"type": "string", "enum": "click double_click right_click type_text press_key hotkey scroll drag set_value invoke_menu launch_app".split()}, "args": {"type": "object"}}, ["tool", "args"]),
    ("cua.capture", "Capture an allowed background window; return frame metadata and managed PNG path.", TARGET, ["window_id"]),
    ("cua.log", "Read the shared agent/Paul/driver log.", {**SESSION, "since_seq": {"type": "integer", "minimum": 0}}, []),
    ("cua.wait", "Wait for Paul to give back control and read his actions/note.", {**SESSION, "timeout_ms": {"type": "integer", "minimum": 0, "maximum": 600000}}, ["timeout_ms"]),
    ("cua.verify", "Check a structured postcondition on an allowed window.", {**TARGET, "expect": {"type": "array", "minItems": 1, "maxItems": 8}, "timeout_ms": {"type": "integer", "minimum": 0, "maximum": 10000}}, ["window_id", "expect"]),
]
SELECTOR = {"type": "object", "properties": {k: TEXT for k in ("role", "label", "automationId", "className")}, "minProperties": 1, "additionalProperties": False}
STEP = {"type": "object", "properties": {"selector": SELECTOR, "tool": {"enum": ["click", "type_text", "set_value", "press_key", "scroll"]}, "args": {"type": "object"}, "expect": {"type": "array", "minItems": 1, "maxItems": 8}}, "required": ["selector", "tool", "expect"], "additionalProperties": False}
DEFINITIONS += [
    ("cua.adapt", "Safely observe an allowed unseen app and quarantine a draft CL manual. Missing/slow UIA automatically uses T18 image-to-CL; no actions are dispatched.", {**TARGET, "visual": {"type": "boolean"}}, ["window_id"]),
    ("cua.flow", "Observe, resolve fresh controls, act and verify each step. Successful flows promote a scoped draft and repeated runs compile through the grounded manual runner. Stops on takeover or failed checks.", {**TARGET, "steps": {"type": "array", "items": STEP, "minItems": 1, "maxItems": 16}}, ["window_id", "steps"]),
]
OPS = "state windows open snapshot input control allow foreground approve apps end inspect action capture log wait verify driver adapt flow".split()
COMMANDS = frozenset("cua_" + op + "_command" for op in OPS)
OWNER_OPS = frozenset("open input control allow foreground approve end install_driver".split())
NATIVE_CLIENT = ContextVar("cua_native_client", default=None)
CHAT_ALIASES = {}


def bind_chat(alias, identity):
    if alias and identity:
        CHAT_ALIASES[str(alias)] = str(identity)


def canonical_client(client):
    client = dict(client)
    client["chatId"] = CHAT_ALIASES.get(str(client.get("chatId")), client.get("chatId"))
    if client.get("app") == "claude-code":
        client["app"] = "claude"
    return client
DANGEROUS = re.compile(r"\b(delete|remove|erase|uninstall|format|send|submit|pay|buy|purchase|publish|overwrite|replace|discard|empty recycle bin|don't save|do not save|supprimer|envoyer|payer|acheter)\b", re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def app_name(value):
    return str(value or "").replace("\\", "/").split("/")[-1].casefold().removesuffix(".exe")


def result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value, "isError": False}


def refusal(code, hint):
    value = {"effect": "refused", "route": "accessibility", "error": {"code": code, "hint": hint}, "summary": hint}
    return {"content": [{"type": "text", "text": hint}], "structuredContent": value, "isError": True}


class CuaService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / ".neyvia/cua"
        self.native = NativeWorker()
        self._upstream = None
        self._driver_setup = {"state": "idle"}
        self.lock, self.action_lock = threading.RLock(), threading.RLock()
        self.sessions, self.frames, self.snapshots = {}, {}, {}
        permission_file = self.directory / "app-permissions.json"
        self.app_permissions = json.loads(permission_file.read_text(encoding="utf-8")) if permission_file.is_file() else {}
        self.displayed_frames = {}
        self.replays = {}
        from .cua_adaptation import Adaptation
        self.adaptation = Adaptation(self)
        self.log, self.events = deque(maxlen=1000), deque(maxlen=2000)
        self.sequence = 0
        receipts = self.directory / "receipts.jsonl"
        if receipts.is_file():
            with receipts.open("rb") as stream:
                stream.seek(max(0, receipts.stat().st_size - 8 * 1024 * 1024))
                for line in stream.read().decode("utf-8", errors="replace").splitlines()[-1000:]:
                    try:
                        row = json.loads(line)
                        self.log.append(row)
                        self.sequence = max(self.sequence, int(row.get("seq", 0)))
                    except (ValueError, TypeError):
                        continue
        self.stopped = threading.Event()
        saved = self.directory / "sessions.json"
        if saved.is_file():
            for s in json.loads(saved.read_text(encoding="utf-8")).get("sessions", []):
                s.update(control="paul", pausedReason="backend_restarted", approvals=[], _lastUsed=time.monotonic())
                self.sessions[s["id"]] = s
        self.monitor = threading.Thread(target=self._monitor, name="cua-physical-takeover", daemon=True)
        self.monitor.start()
        atexit.register(self.shutdown)

    @property
    def upstream(self):
        with self.lock:
            if self._upstream is None:
                from .cua_upstream import UpstreamDriver
                self._upstream = UpstreamDriver(self.root)
            return self._upstream

    def shutdown(self):
        self.stopped.set()
        self.native.close()
        if self._upstream:
            self._upstream.close()

    def public(self, s):
        view = {k: v for k, v in s.items() if not k.startswith("_")}
        view["foregroundAvailable"] = False
        view["approvals"] = [{k: v for k, v in a.items() if not k.startswith("_")} for a in s["approvals"]]
        return view

    def event(self, kind, s, data):
        with self.lock:
            self.sequence += 1
            e = {"cursor": self.sequence, "type": kind, "sessionId": s["id"], "data": data}
            self.events.append(e)
            return e

    def changed(self, s):
        self.event("session", s, self.public(s))
        if not s.get("_ephemeral"):
            atomic_write_json(self.directory / "sessions.json", {"sessions": [self.public(row) for row in self.sessions.values() if not row.get("_ephemeral")]})

    def record(self, s, by, tool, args=None, outcome=None, *, status=None, text=None, element=None, window=None, started=None, preservation=None):
        with self.lock:
            row = {"id": "l-" + secrets.token_hex(8), "seq": self.sequence + 1, "sessionId": s["id"], "at": now(), "by": by,
                "who": (s.get("owner") or {}).get("app", "Agent") if by == "agent" else "Paul" if by == "paul" else "Driver",
                "tool": tool, "windowId": int(window["windowId"]) if window else None,
                "app": window.get("processName") if window else None, "element": element,
                "args": {k: v[:500] if isinstance(v, str) else v for k, v in (args or {}).items() if k != "client"},
                "result": outcome, "status": status or ("refused" if (outcome or {}).get("effect") == "refused" else "ok"),
                "ms": round((time.perf_counter() - started) * 1000, 2) if started else 0,
                "captureId": (args or {}).get("capture_id"), "text": text or (outcome or {}).get("summary") or tool.replace("_", " ")}
            if preservation:
                row["preservation"] = preservation
            if s.get("_ephemeral"):
                # Remote control is live, not a transcript. Redact before either
                # the shared log or event queue can retain supplied/read-back text.
                row.update(by="remote" if by == "paul" else by, who="Remote owner" if by == "paul" else "Driver",
                           args={}, result={"effect": (outcome or {}).get("effect"), "route": (outcome or {}).get("route")},
                           element=None, text=tool.replace("_", " "))
            self.log.append(row)
            s["logSeq"] = row["seq"]
            if by in {"agent", "paul"} and tool in ACTIONS | {"launch_app"}:
                s["counts"][by] += 1
                s["lastActionAt"], s["_lastUsed"] = now(), time.monotonic()
            self.event("log", s, row)
            if not s.get("_ephemeral"):
                self.directory.mkdir(parents=True, exist_ok=True)
                with (self.directory / "receipts.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            return row

    def pause(self, s, reason):
        with self.lock:
            if s["status"] != "ended" and (s["control"] != "paul" or s.get("pausedReason") != reason):
                s.update(control="paul", pausedReason=reason)
                self.record(s, "driver", "control", text="Agent paused: Paul has control")
                self.changed(s)
                bus_for(self.root).emit("cua.paused", {"sessionId": s["id"], "reason": reason})

    def marker(self):
        status = self.native.request("status", timeout=8)
        guard = getattr(self.native, "guard", None)
        if guard is not None and getattr(self.native, "desktop", None) is not None:
            observed = guard.check()
            if not observed.get("ok") or not observed.get("input_hooks_installed"):
                raise RuntimeError("Attributed input-desktop guard unavailable; execution is paused")
            counters = {k: observed[k] for k in ("foreground_changes", "new_visible_windows",
                "injected_mouse_events", "injected_keyboard_events")}
            status.update(preservationObservable=True, attributedGuard=counters,
                unownedActivity=observed.get("unowned_activity", {}))
            return status, [self.native.generation, *counters.values()]
        if status.get("hooksReady") is not True:
            raise RuntimeError("Physical input hooks unavailable; execution is paused")
        status["preservationObservable"] = status.get("foregroundWindowId") not in {"0", 0, None}
        return status, [self.native.generation, status.get("inputGeneration")]

    @staticmethod
    def preservation(before, after):
        observable = before.get("preservationObservable", True) and after.get("preservationObservable", True)
        row = {"foregroundBefore": before["foregroundWindowId"], "foregroundAfter": after["foregroundWindowId"],
               "foregroundGenerationBefore": before.get("foregroundGeneration"),
               "foregroundGenerationAfter": after.get("foregroundGeneration"), "preservationObservable": observable,
               "foregroundPreserved": observable and before["foregroundWindowId"] == after["foregroundWindowId"]
                    and before.get("foregroundGeneration") == after.get("foregroundGeneration"),
               "cursorPreserved": observable and before["cursor"] == after["cursor"]}
        if "attributedGuard" in before and "attributedGuard" in after:
            deltas = {k: after["attributedGuard"][k] - v for k, v in before["attributedGuard"].items()}
            intact = observable and all(v == 0 for v in deltas.values())
            row.update(foregroundPreserved=intact, cursorPreserved=intact, policy="agent-attribution",
                attributedDeltas=deltas, unownedActivity=after.get("unownedActivity", {}))
        return row

    def permission_request(self, s, policy, executable):
        key = policy.get("appKey") or Path(executable).name.casefold()
        record = self.app_permissions.get(key)
        created = record is None
        if record is None:
            record = {"app": key, "executable": executable, "status": "pending", "at": now(),
                "approvalId": "a-" + secrets.token_hex(12), "sessionId": s["id"], "reason": policy["reason"]}
            self.app_permissions[key] = record
        if record["status"] == "pending" and not any(a["id"] == record["approvalId"] for a in s["approvals"]):
            for session in self.sessions.values():
                if session["id"] != s["id"] and any(a["id"] == record["approvalId"] for a in session["approvals"]):
                    session["approvals"] = [a for a in session["approvals"] if a["id"] != record["approvalId"]]
                    self.changed(session)
            record["sessionId"] = s["id"]
            s["approvals"].append({"id": record["approvalId"], "kind": "app_visibility", "app": key,
                "summary": "Allow " + key + " to open on your desktop? Background containment is unavailable.",
                "at": record["at"], "expiresAt": None, "_expires": float("inf"), "_decision": None})
            self.changed(s)
            if created:
                self.event("permission", s, record)
                bus_for(self.root).emit("cua.approval", {"sessionId": s["id"], "approvalId": record["approvalId"],
                    "kind": "app_visibility", "summary": s["approvals"][-1]["summary"]})
        atomic_write_json(self.directory / "app-permissions.json", self.app_permissions)
        return result({"effect": "needs-permission" if record["status"] == "pending" else "blocked", "app": key,
            "permissionRequired": record["status"] == "pending",
            "permissionStatus": record["status"], "approvalId": record["approvalId"], "launchPolicy": policy,
            "summary": "Background containment is unavailable; no visible launch was attempted."})

    def check_input(self, s):
        status, marker = self.marker()
        if marker != s.get("_inputMarker"):
            self.pause(s, "real_input")
        return status

    def _monitor(self):
        while not self.stopped.wait(0.15):
            active = [s for s in list(self.sessions.values()) if s["status"] == "active" and s["control"] == "agent"]
            for s in active:
                try:
                    self.check_input(s)
                    if time.monotonic() - s.get("_lastUsed", time.monotonic()) > 1800:
                        s.update(status="ended", control="paul", pausedReason="idle_timeout")
                        self.changed(s)
                except Exception:
                    self.pause(s, "driver_unavailable")

    def windows(self):
        value = self.native.request("windows")
        return value if isinstance(value, list) else value.get("windows", [])

    def allowed(self, s, w):
        pins = s.get("_windowPins")
        if pins is not None:
            pin = pins.get(int(w["windowId"]))
            if not pin or any(w.get(k) != pin.get(k) for k in ("pid", "exe", "processStartTime")):
                return False
        grant = next((a for a in s["allow"] if app_name(a["app"]) == app_name(w["processName"])), None)
        return bool(grant and (not grant.get("exe") or str(w.get("exe", "")).casefold() == grant["exe"].casefold()))

    def grant(self, s, app):
        normalized = app_name(app)
        if not normalized or normalized in {"neyvia", "neyvia-next", "cua-driver", "cua-driver-uia"}:
            raise ValueError("Choose an explicit target app outside Neyvia and the driver")
        existing = next((w for w in self.windows() if app_name(w["processName"]) == normalized), None)
        s["allow"] = [a for a in s["allow"] if app_name(a["app"]) != normalized]
        s["allow"].append({"app": str(app), "name": normalized, "by": "paul", **({"exe": existing["exe"]} if existing and existing.get("exe") else {})})

    def refresh(self, s):
        rows = [{"window_id": int(w["windowId"]), "pid": w["pid"], "app_name": w["processName"], "process": w["processName"] + ".exe",
                 "title": w["title"], "bounds": w["bounds"], "is_on_screen": not w.get("minimized"), "minimized": bool(w.get("minimized")),
                 "allowed": True, "manual": None, "frame": self.frames.get((s["id"], str(w["windowId"])), {}).get("metadata")}
                for w in self.windows() if self.allowed(s, w)]
        if rows != s["windows"]:
            with self.lock:
                s["windows"] = rows
                s["focusWindow"] = s.get("focusWindow") or (rows[0]["window_id"] if rows else None)
                self.changed(s)
        return rows

    def new_session(self, apps, client, *, pending=False, ephemeral=False):
        with self.lock:
            if len([s for s in self.sessions.values() if s["status"] != "ended"]) >= 8:
                raise ValueError("End an existing native session first")
            s = {"id": "s-" + secrets.token_hex(12), "owner": client, "status": "pending" if pending else "active", "control": "paul" if pending else "agent",
                 "pausedReason": None, "foreground": False, "allow": [], "windows": [], "focusWindow": None, "approvals": [],
                 "counts": {"agent": 0, "paul": 0}, "startedAt": now(), "lastActionAt": None, "logSeq": 0, "_lastUsed": time.monotonic(), "_ephemeral": ephemeral}
            for app in apps:
                self.grant(s, app)
            _, s["_inputMarker"] = self.marker()
            self.sessions[s["id"]] = s
            self.refresh(s)
            self.changed(s)
            return s

    def session(self, args, client=None):
        identity = args.get("sessionId") or args.get("session")
        if isinstance(identity, dict):
            identity = identity.get("id")
        s = self.sessions.get(str(identity)) if identity else next((row for row in reversed(list(self.sessions.values())) if row["status"] != "ended"
            and (not client or (row.get("owner") or {}).get("chatId") == client.get("chatId"))), None)
        if not s:
            raise ValueError("session_pending")
        if client and any(canonical_client(s.get("owner") or {}).get(k) != client.get(k) for k in ("chatId", "app")):
            raise ValueError("session_pending")
        return s

    def target(self, s, args):
        t = args.get("target") or {}
        identity, pid, token = args.get("window_id", args.get("windowId", t.get("window_id"))), args.get("pid", t.get("pid")), args.get("element_token")
        resolver = s.get("_resolveTarget")
        if resolver and identity is not None:
            choices = [resolver(identity)]
            if pid is not None and int(choices[0]["pid"]) != int(pid):
                choices = []
        elif token and identity is None:
            choices = [v["window"] for (sid, _), v in self.snapshots.items() if sid == s["id"] and any(e.get("element_token") == token for e in v["data"].get("elements", []))]
        elif identity is not None:
            current_window = self.native.request("window", {"windowId": str(identity)})
            choices = [current_window] if pid is None or int(current_window["pid"]) == int(pid) else []
        else:
            choices = [w for w in self.windows() if (identity is None or str(w["windowId"]) == str(identity)) and (pid is None or int(w["pid"]) == int(pid))]
        if len(choices) != 1:
            raise ValueError("ambiguous_window_target" if choices else "window_target_not_found")
        w = choices[0]
        current = w if identity is not None else resolver(w["windowId"]) if resolver else self.native.request("window", {"windowId": str(w["windowId"])})
        if not current or any(current.get(k) != w.get(k) for k in ("pid", "processStartTime")):
            raise ValueError("window_target_not_found")
        if not self.allowed(s, current) or "neyvia" in (str(current.get("exe")) + str(current.get("title"))).casefold():
            raise ValueError("app_not_allowed")
        if s.get("_targetGuard"):
            s["_targetGuard"](current)
        return current

    def snapshot(self, s, w, *, image=True, elements=True, max_elements=256):
        # Hover/stream observations must not replace the admitted token while
        # preview input is resolving and dispatching its fresh target.
        with self.action_lock:
            return self._snapshot(s, w, image=image, elements=elements, max_elements=max_elements)

    def _snapshot(self, s, w, *, image=True, elements=True, max_elements=256):
        value = s["_snapshot"](w, image, elements) if s.get("_snapshot") else self.adaptation.snapshot(w, image, elements, max_elements)
        data = value.get("structuredContent") or {}
        if not value.get("isError"):
            # Both UIA and Win32 observations retain the admitted process identity.
            data.update(pid=int(w["pid"]), window_id=int(w["windowId"]))
            value["structuredContent"] = data
        if not value.get("isError") and elements:
            self.snapshots[(s["id"], str(w["windowId"]))] = {"window": w, "data": data, "at": time.monotonic()}
        for b in value.get("content", []):
            if b.get("type") == "image":
                from PIL import Image
                raw = base64.b64decode(b["data"], validate=True)
                picture = Image.open(io.BytesIO(raw)); picture.load()
                if max(picture.size) > 1600:
                    raise ValueError("Capture exceeds1600px preview bound")
                key, sha = (s["id"], str(w["windowId"])), hashlib.sha256(raw).hexdigest()
                old = self.frames.get(key)
                meta = {"seq": self.sequence + 1, "windowId": int(w["windowId"]), "captureId": data.get("capture_id") or data.get("snapshot_id"),
                        "width": picture.width, "height": picture.height, "scale": data.get("screenshot_scale", 1), "at": now(), "unavailable": None}
                frame = {"raw": raw, "metadata": meta, "sha256": sha, "mimeType": b.get("mimeType", "image/png")}
                if not s.get("_ephemeral"):
                    path = self.directory / "frames" / (s["id"] + "-" + str(w["windowId"]) + ".png")
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                    frame["path"] = str(path)
                self.frames[key] = frame
                if not old or old.get("sha256") != sha:
                    self.event("frame", s, meta)
                else:
                    meta["seq"] = old["metadata"]["seq"]
                    meta["captureId"] = old["metadata"]["captureId"]
                    data["capture_id"] = meta["captureId"]
                    if s.get("_ephemeral"):
                        # A fresh safe UIA observation may accompany identical
                        # pixels. Keep projection and displayed-frame binding
                        # coherent for T16's exact preview-coordinate admission.
                        data["capture_id"] = meta["captureId"]
                        data["snapshot_id"] = meta["captureId"]
                cached = self.snapshots.get(key, {})
                projection = data if elements else cached.get("data", {}) if all(
                    cached.get("window", {}).get(k) == w.get(k) for k in ("pid", "processStartTime", "bounds")) else {}
                projected_controls = []
                for e in projection.get("elements", []):
                    if e.get("visualId"):
                        continue
                    control = {k: e.get(k) for k in ("nativeId", "nativeHandle", "label", "role", "className", "screenshot_frame", "enabled", "protected", "actions")}
                    bounds = e.get("frame") or {}
                    if not control["screenshot_frame"] and all(k in bounds for k in ("x", "y", "width", "height")):
                        scale = meta["scale"]
                        control["screenshot_frame"] = {"x": (bounds["x"] - w["bounds"]["x"]) * scale,
                            "y": (bounds["y"] - w["bounds"]["y"]) * scale,
                            "w": bounds["width"] * scale, "h": bounds["height"] * scale}
                    projected_controls.append(control)
                admitted = {"metadata": dict(meta), "sha256": sha, "raw": raw, "mimeType": frame["mimeType"], "at": time.monotonic(),
                            "window": {k: w.get(k) for k in ("pid", "processStartTime", "bounds")},
                            "controls": projected_controls}
                history = self.displayed_frames.setdefault(key, deque(maxlen=8))
                # A deadline may produce only part of the same rendered
                # window. Retain already observed controls for identical
                # pixels and identity; the action still resolves and validates
                # the chosen native control afresh before dispatch.
                matching = [row for row in history if row["sha256"] == sha and row["window"] == admitted["window"]]
                controls = {str(e.get("nativeHandle") or e["nativeId"]): e
                            for row in matching for e in row["controls"]}
                for e in admitted["controls"]:
                    identity = str(e.get("nativeHandle") or e["nativeId"])
                    previous = controls.get(identity)
                    # An image-only observation may use a cached projection
                    # without screenshot-relative bounds. It cannot erase
                    # geometry already proved for these exact pixels and HWND.
                    if previous and not e.get("screenshot_frame"):
                        e = {**e, "screenshot_frame": previous.get("screenshot_frame")}
                    controls[identity] = e
                admitted["controls"] = list(controls.values())
                for row in matching:
                    row["controls"] = admitted["controls"]
                if not history or history[-1]["metadata"]["captureId"] != meta["captureId"]:
                    history.append(admitted)
                else:
                    # Identical rendered pixels may acquire a more complete
                    # native projection after provider warmup. Bind that fresh
                    # observation to the same displayed frame, rather than
                    # permanently retaining its first partial control list.
                    history[-1].update(admitted)
                break
        if elements and not s.get("_ephemeral") and not value.get("isError"):
            data["manual"] = self.adaptation.draft(w, data)
        if not image:
            value["content"] = [b for b in value.get("content", []) if b.get("type") != "image"]
        return value

    def state(self, args):
        for s in list(self.sessions.values()):
            if s["status"] != "ended":
                self.refresh(s)
        from .cua_upstream import runtime_status
        value = {"driver": {**runtime_status(), "name": "cua-driver (MIT Windows)", "version": "0.32.0", "platform": "windows", "install": dict(self._driver_setup)},
                 "agentDesktop": self.native.request("agentDesktop"),
                 "sessions": [self.public(s) for s in self.sessions.values() if not args.get("sessionId") or s["id"] == args["sessionId"]]}
        # The guard receipt keys process births by integer PID. A tool receipt
        # must equal its durable JSON copy, so return the JSON form itself.
        return json.loads(json.dumps(value, ensure_ascii=False))

    def approval(self, s, kind, summary, **fields):
        with self.lock:
            a = {"id": "a-" + secrets.token_hex(12), "kind": kind, "summary": summary, "tool": None, "app": None, "element": None,
                 "at": now(), "expiresAt": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
                 "_expires": time.monotonic() + 120, "_decision": None, **fields}
            s["approvals"].append(a)
            self.record(s, "driver", "approval", status="pending_approval", text=summary)
            self.changed(s)
            bus_for(self.root).emit("cua.approval", {"sessionId": s["id"], "approvalId": a["id"], "kind": kind, "summary": summary})
        while not self.stopped.wait(0.1):
            if a["_decision"] is not None:
                return a["_decision"]
            if s["status"] == "ended" or time.monotonic() >= a["_expires"]:
                with self.lock:
                    if a in s["approvals"]:
                        s["approvals"].remove(a)
                    self.record(s, "driver", "approval", status="refused", text="Approval timed out")
                    self.changed(s)
                return "timeout"
        return "timeout"

    def meta(self, value, s, client):
        cursor = s.setdefault("_clientCursor", {}).get(client.get("chatId", "native"), 0)
        paul = [r for r in self.log if r["sessionId"] == s["id"] and r["by"] == "paul" and r["seq"] > cursor]
        s["_clientCursor"][client.get("chatId", "native")] = self.sequence
        note = s.pop("_note", None) if client.get("app") != "owner" else None
        preview = {"session": s["id"], "control": s["control"], "paulActions": paul, "note": note}
        value = {**value, "_meta": {**value.get("_meta", {}), "neyvia/preview": preview}}
        if paul or note:
            value["content"] = [*value.get("content", []), {"type": "text", "text": "Paul did since your last call: " + "; ".join(r["text"] for r in paul) + (". Note: " + note if note else "")}]
        return value

    def focus(self, s, w, tool, args, by, phase):
        data = self.snapshots.get((s["id"], str(w["windowId"])), {}).get("data", {})
        e = next((e for e in data.get("elements", []) if e.get("element_token") == args.get("element_token")), None)
        element = {"token": e.get("element_token"), "role": e.get("role"), "label": e.get("label"), "frame": e.get("screenshot_frame") or e.get("frame")} if e else None
        if s.get("_ephemeral") and element:
            element = {**element, "label": None}
        # What the action will type or press, so a watcher can say it in plain words (agent view).
        say = {} if s.get("_ephemeral") else {k: (args[k][:120] if isinstance(args[k], str) else args[k])
                                              for k in ("text", "value", "key", "keys", "modifiers", "direction") if k in args}
        self.event("focus", s, {"windowId": int(w["windowId"]), "by": by, "tool": tool, "phase": phase, "element": element, "say": say,
                   "point": {"x": args["x"], "y": args["y"]} if "x" in args and "y" in args else None, "captureId": args.get("capture_id") or data.get("capture_id")})
        return element

    def native_message(self, w, tool, args, element):
        """Classic HWND controls need messages: their UIA providers call SetFocus."""
        if element and element.get("nativeId"):
            return self.adaptation.action(w, tool, args, element)
        if not element or tool not in {"click", "type_text", "set_value"}:
            return None
        tree = self.native.request("inspect", {"windowId": str(w["windowId"]), "maxDepth": 12, "maxNodes": 2000})["tree"]
        choices = [e for e in tree if e.get("name") == element.get("label") and e.get("role") == element.get("role")]
        if len(choices) != 1:
            return None
        e = choices[0]
        cls = str(e.get("className", ""))
        action = None
        if tool in {"type_text", "set_value"} and (cls.startswith("WindowsForms10.EDIT") or cls == "Edit"):
            action = "editAppend" if tool == "type_text" else "editSetValue"
        if tool == "click" and e.get("nativeWindowHandle") and not args.get("action") and not args.get("modifier") and args.get("count", 1) == 1 and args.get("button", "left") == "left" and (cls.startswith("WindowsForms10.BUTTON") or cls == "Button"):
            action = "buttonClick"
        if not action:
            # Standard WPF ButtonAutomationPeer focuses its owner on Invoke.
            if tool == "click" and cls == "Button":
                return refusal("background_unavailable", "This WPF Invoke provider changes focus; no native dispatch occurred")
            if tool == "click" and (cls.startswith("WindowsForms10.EDIT") or cls == "Edit"):
                return refusal("background_unavailable", "Native caret clicks can change focus; text goes through the background edit route")
            return None
        raw = self.native.request("action", {"windowId": str(w["windowId"]), "elementId": e["id"], "action": action,
                                  "text": args.get("text") if tool == "type_text" else str(args.get("value", ""))})
        structured = {"effect": raw["effect"], "route": "synthetic_events", "delivery": {"mode": "background", "delivered_count": 1},
                      "summary": raw["mechanism"] + " delivered to the validated native child control; inspect the app postcondition"}
        if raw["effect"] == "confirmed":
            structured["evidence"] = [{"kind": "value_readback", "detail": str(raw.get("readback", ""))[:1000]}]
        value = result(structured)
        value["_meta"] = {"neyvia/nativeRoute": {"mechanism": raw["mechanism"], "child": e.get("nativeWindowHandle")}}
        return value

    def owner_point(self, s, w, args, required_action=None):
        """Admit the exact displayed pixels, then resolve a current semantic token."""
        key = (s["id"], str(w["windowId"]))
        old = next((f for f in reversed(self.displayed_frames.get(key, []))
                    if args.get("capture_id") == f["metadata"].get("captureId")
                    and time.monotonic() - f["at"] <= 60), None)
        if not old or any(old["window"].get(k) != w.get(k) for k in ("pid", "processStartTime", "bounds")):
            raise ValueError("stale_element_token")
        x, y = float(args["x"]), float(args["y"])
        if not 0 <= x < old["metadata"]["width"] or not 0 <= y < old["metadata"]["height"]:
            raise ValueError("invalid_coordinates")
        deadline = self.observation_deadline(args)
        observations = 0
        while True:
            observations += 1
            try:
                fresh = self.snapshot(s, w)
            except TimeoutError:
                # Only observation is retried. No action has been dispatched;
                # a busy provider/capture lane may finish within this budget.
                if time.monotonic() >= deadline:
                    raise ValueError("background_unavailable")
                time.sleep(.02)
                continue
            current = self.frames.get((s["id"], str(w["windowId"])))
            if not current:
                raise ValueError("stale_element_token")
            hits = []
            for e in (fresh.get("structuredContent") or {}).get("elements", []):
                b = e.get("screenshot_frame") or {}
                semantic = e.get("role") not in {"Window", "Pane", "TitleBar", "MenuBar"}
                if required_action:
                    semantic = required_action in e.get("actions", [])
                if e.get("role") == "Custom":
                    semantic = bool(e.get("visualId") or e.get("patterns"))
                if semantic and e.get("enabled") and not e.get("protected") and b and b.get("x", 0) <= x < b.get("x", 0) + b.get("w", 0) and b.get("y", 0) <= y < b.get("y", 0) + b.get("h", 0) and e.get("actions"):
                    hits.append((b["w"] * b["h"], e))
            if hits:
                break
            if time.monotonic() >= deadline:
                args["frameAdmission"] = {"observationAttempts": observations,
                    "source": (fresh.get("structuredContent") or {}).get("source"),
                    "controls": [{k: e.get(k) for k in ("nativeId", "nativeHandle", "role", "label", "enabled", "protected", "actions", "screenshot_frame")}
                                 for e in (fresh.get("structuredContent") or {}).get("elements", [])]}
                raise ValueError("background_unavailable")
        args["observationAttempts"] = observations
        target = min(hits, key=lambda row: row[0])[1]
        if old.get("sha256") != current.get("sha256"):
            # Carets and prior typing change pixels without changing the
            # named control being clicked. Admit a native semantic target only
            # when its displayed identity, label, role and position still match.
            # Visual-only coordinates retain exact-pixel admission.
            previous = [e for e in old["controls"] if e.get("nativeId") == target.get("nativeId")
                        or (target.get("nativeHandle") and e.get("nativeHandle") == target["nativeHandle"])]
            fields = ("label", "role", "className", "screenshot_frame", "enabled", "protected", "actions")
            previous = previous[0] if len(previous) == 1 else None
            if target.get("visualId") or not previous or any(previous.get(k) != target.get(k) for k in fields):
                args["frameAdmission"] = {"previous": previous,
                    "current": {k: target.get(k) for k in ("nativeId", "nativeHandle", *fields)}}
                raise ValueError("stale_element_token")
        args["element_token"] = target["element_token"]
        selected = s.setdefault("_previewTargets", {})
        if target.get("protected"):
            selected.pop(str(w["windowId"]), None)
        else:
            selected[str(w["windowId"])] = {"id": target["nativeId"], "handle": target.get("nativeHandle"),
                "role": target["role"], "className": target["className"]}
        # Cua's element-token route rejects capture_id; our SHA admission above
        # binds the original frame before selecting this newly observed token.
        args.pop("capture_id", None)
        args.pop("x", None); args.pop("y", None)

    @staticmethod
    def observation_deadline(args):
        budget = args.get("observation_timeout_ms", 1500)
        if type(budget) is not int or not 0 <= budget <= 10000:
            raise ValueError("Invalid observation_timeout_ms")
        return time.monotonic() + budget / 1000

    def preview_target(self, s, w, tool, args):
        """Resolve fresh controls before dispatch, including provider warmup."""
        chosen = s.get("_previewTargets", {}).get(str(w["windowId"]))
        deadline = self.observation_deadline(args)
        observations = 0
        while True:
            observations += 1
            try:
                observed = self.snapshot(s, w, image=False)
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise ValueError("background_unavailable")
                time.sleep(.02)
                continue
            controls = (observed.get("structuredContent") or {}).get("elements", [])
            selected = [e for e in controls if chosen and not e.get("protected") and
                        ((e.get("nativeId") == chosen.get("id")) or
                         (chosen.get("handle") and e.get("nativeHandle") == chosen["handle"]
                          and e.get("role") == chosen["role"] and e.get("className") == chosen["className"]))]
            if tool == "type_text":
                selected = [e for e in selected if "set_value" in e.get("actions", [])]
                if not chosen:
                    selected = [e for e in controls if e.get("role") in {"Document", "Edit"}
                                and "set_value" in e.get("actions", [])]
            if len(selected) == 1 or time.monotonic() >= deadline:
                break
        args["observationAttempts"] = observations
        if len(selected) == 1:
            args["element_token"] = selected[0]["element_token"]
            args.pop("capture_id", None)

    def verify_values(self, s, w, args):
        """Stable, explicit native ValuePattern checks; unsupported checks stay unknown."""
        expected = args.get("expect")
        if isinstance(expected, list) and expected and all(isinstance(p, dict) and ("element" in p or "visual" in p) for p in expected):
            try:
                return result(self.adaptation.verify(s, w, expected, args.get("timeout_ms", 500)))
            except ValueError:
                pass
        expected = args.get("expect")
        if not isinstance(expected, list) or not 1 <= len(expected) <= 8:
            return None
        for predicate in expected:
            element = predicate.get("element") if isinstance(predicate, dict) else None
            if not isinstance(element, dict) or set(predicate) != {"element"} or set(element) != {"selector", "value_equals"} or not isinstance(element["value_equals"], str):
                return None
            selector = element["selector"]
            if not isinstance(selector, dict) or not selector or set(selector) - {"role", "label_contains"} or any(not isinstance(v, str) for v in selector.values()):
                return None
        started, previous, samples = time.monotonic(), None, 0
        timeout = max(0, min(10000, int(args.get("timeout_ms", 5000)))) / 1000
        while True:
            current = self.target(s, {"window_id": int(w["windowId"]), "pid": w["pid"]})
            if current.get("processStartTime") != w.get("processStartTime"):
                raise ValueError("window_target_not_found")
            tree = self.native.request("inspect", {"windowId": str(w["windowId"]), "maxDepth": 12, "maxNodes": 2000})["tree"]
            rows = []
            for index, predicate in enumerate(expected):
                element, selector = predicate["element"], predicate["element"]["selector"]
                matches = [e for e in tree if (not selector.get("role") or e["role"] == selector["role"])
                           and selector.get("label_contains", "").casefold() in str(e.get("name", "")).casefold()]
                reason = "target_missing" if not matches else "multi_match" if len(matches) != 1 else "unsupported_predicate" if "value" not in matches[0] else None
                observed = {"matches": len(matches), **({"value": matches[0]["value"]} if len(matches) == 1 and "value" in matches[0] else {})}
                status = "unknown" if reason else "satisfied" if observed["value"] == element["value_equals"] else "unsatisfied"
                rows.append({"index": index, "status": status, "unknown_reason": reason, "observed_json": json.dumps(observed, ensure_ascii=False)})
            samples += 1
            stable = rows == previous and all(r["status"] != "unknown" for r in rows)
            elapsed = time.monotonic() - started
            if stable or elapsed >= timeout or any(r["status"] == "unknown" for r in rows):
                status = "unknown" if any(r["status"] == "unknown" for r in rows) else "unsatisfied" if any(r["status"] == "unsatisfied" for r in rows) else "satisfied"
                if status == "satisfied" and not stable:
                    status = "unknown"
                    rows = [{**r, "status": "unknown", "unknown_reason": "stability_unproven"} for r in rows]
                value = result({"status": status, "stable": stable, "elapsed_ms": round(elapsed * 1000), "samples": samples, "predicates": rows})
                value["_meta"] = {"neyvia/nativeVerifier": {"source": "Windows UI Automation ValuePattern", "pid": w["pid"], "window_id": int(w["windowId"]), "processStartTime": w.get("processStartTime")}}
                return value
            previous = rows
            time.sleep(min(.1, max(0, timeout - elapsed)))

    def lifecycle(self, s):
        # The PC service owns grants; its ids are not upstream transport leases.
        idle = max(0, int(time.monotonic() - s.get("_lastUsed", time.monotonic())))
        return {"session": s["id"], "implicit": False, "state": "active" if s["status"] != "ended" else "ending",
                "client_kind": "mcp", "transport": "mcp_stdio", "cursor_visible": False,
                "recording_active": False, "idle_seconds": idle, "expires_in_seconds": max(0, 1800 - idle)}

    def driver(self, envelope, *, by="agent"):
        tool, args = str(envelope.get("tool") or ""), dict(envelope.get("arguments") or {})
        client = canonical_client(envelope.get("client") or {"chatId": "native", "app": "neyvia", "title": "Native model"})
        if by == "paul":
            # Owner input must not acknowledge/consume the agent's feedback cursor.
            client = {"chatId": "owner-preview", "app": "owner", "title": "Paul"}
        if tool in {"list_apps", "get_screen_size", "get_cursor_position"}:
            return self.upstream.call(tool, args)
        if tool == "list_sessions":
            rows = [self.lifecycle(s) for s in self.sessions.values() if s["status"] != "ended"
                    and all(canonical_client(s.get("owner") or {}).get(k) == client.get(k) for k in ("chatId", "app"))]
            limit = max(0, min(100, int(args.get("limit") or 50)))
            return result({"sessions": rows[:limit], "next_cursor": None})
        if tool == "list_windows" and not envelope.get("sessionId") and not any((s.get("owner") or {}).get("chatId") == client.get("chatId") for s in self.sessions.values()):
            return result({"windows": [], "isolation": "agent-desktop", "reason": "Open an app-scoped session first"})
        try:
            s = self.session({"sessionId": envelope.get("sessionId") or args.get("session")}, client if by == "agent" else None)
        except ValueError:
            if tool not in ACTIONS | {"start_session", "get_window_state", "launch_app"}:
                return refusal("session_pending", "Call start_session; Paul must authorize this chat first")
            s = self.new_session([], client, pending=True)
            app = args.get("app") or args.get("app_name") or args.get("name")
            if not app and (args.get("window_id") or (args.get("target") or {}).get("window_id")):
                window_id = args.get("window_id") or args["target"]["window_id"]
                app = next((w["processName"] for w in self.windows() if str(w["windowId"]) == str(window_id)), None)
            if not app and args.get("pid"):
                app = next((w["processName"] for w in self.windows() if int(w["pid"]) == int(args["pid"])), None)
            decision = self.approval(s, "session", "Allow " + client.get("app", "Agent") + " to use " + str(app or "a native app") + "?", app=app)
            if decision != "allow":
                return self.meta(refusal("denied_by_user" if decision == "deny" else "approval_timeout", "Session access was not granted"), s, client)
        if tool == "end_session":
            s.update(status="ended", control="paul", approvals=[]); self.changed(s)
            return self.meta(result({"session": s["id"], "active": False}), s, client)
        if s["status"] == "ended":
            return self.meta(refusal("session_ended", "Start another session with owner approval"), s, client)
        if tool == "get_session":
            return self.meta(result(self.lifecycle(s)), s, client)
        if tool == "start_session":
            if args.get("capture_scope") == "desktop":
                return self.meta(refusal("app_not_allowed", "Desktop-wide access exceeds explicit app grants"), s, client)
            return self.meta(result({"session": s["id"], "capture_scope": "window", "effective_scope": "window",
                "desktop_capture_authorized": False, "desktop_unlocked": False, "escalation_reason": None,
                "escalation_detail": None, "active": s["status"] == "active", "revived": False}), s, client)
        if tool.startswith("preview_") or tool == "request_app":
            return self.meta(result(self.preview_tool(s, tool, args)), s, client)
        if tool in {"adapt_app", "run_flow"}:
            w = self.target(s, args)
            with self.action_lock:
                output = self.adaptation.adapt(s, w, args) if tool == "adapt_app" else self.adaptation.flow(s, w, args["steps"])
            value = result(output)
            value["isError"] = output.get("ok") is False
            return self.meta(value, s, client)
        if tool == "list_windows":
            return self.meta(result({"windows": [w for w in self.refresh(s) if not args.get("pid") or int(w["pid"]) == int(args["pid"])]}), s, client)
        if tool == "get_desktop_state" or args.get("scope") == "desktop" or (args.get("target") or {}).get("kind") == "desktop":
            return self.meta(refusal("app_not_allowed", "Desktop-wide access exceeds explicit app grants"), s, client)
        if tool not in ACTIONS | {"get_window_state", "verify_state", "launch_app"}:
            return self.meta(refusal("app_not_allowed", "Tool is outside the native app surface"), s, client)
        if args.get("delivery_mode", "background") != "background":
            return self.meta(refusal("foreground_not_allowed", "T16 supports background delivery only"), s, client)
        if tool == "launch_app":
            # The manual's launch-check-handoff names the app as args.app.
            launch = args.get("path") or args.get("name") or args.get("app") or args.get("aumid") or args.get("bundle_id") or args.get("launch_path")
            if args.get("urls") or not launch or not any(app_name(a["app"]) == app_name(launch) for a in s["allow"]):
                return self.meta(refusal("app_not_allowed", "Request an explicit app grant before launching; URL launch is outside native scope"), s, client)
            grant = next(a for a in s["allow"] if app_name(a["app"]) == app_name(launch))
            if grant.get("exe") and ("/" in str(launch) or "\\" in str(launch)) and Path(str(launch)).resolve() != Path(grant["exe"]).resolve():
                return self.meta(refusal("app_not_allowed", "Launch path differs from the owner-authorized executable"), s, client)
            before = self.check_input(s)
            if by == "agent" and s["control"] != "agent":
                return self.meta(refusal("paused_by_user", "Use preview_wait until Paul gives back control"), s, client)
            with self.action_lock:
                started = time.perf_counter()
                argv = args.get("args", [])
                if not isinstance(argv, list) or any(not isinstance(a, str) for a in argv):
                    return self.meta(refusal("invalid_request", "Launch arguments must be a string array"), s, client)
                try:
                    executable = grant.get("exe") or str(launch)
                    policy = self.native.launch_policy([executable, *argv])
                    if not policy["allowed"]:
                        value = self.permission_request(s, policy, executable) if policy.get("status") == "needs-permission" else refusal("isolated_launch_unavailable", policy["reason"])
                        value["structuredContent"]["launchPolicy"] = policy
                        self.record(s, by, "launch_app", args, value["structuredContent"], status="refused", started=started)
                        return self.meta(value, s, client)
                    process = self.native.launch([executable, *argv], environment=policy['route'], disposable_target=args.get("disposable_target"))
                    # ActionResult shape (manual cua.action returns): the job-owned
                    # process started on the private route; the window is observed next.
                    value = result({"pid": process.pid, "desktop": self.native.desktop.name, "launched": True,
                                    "route": policy['route'], "delivery": {"mode": "background", "environment": policy['route']},
                                    "effect": "confirmed", "summary": "Started in its own job on " + policy['route'] + "; observe the window before acting"})
                except (ValueError, RuntimeError, OSError) as exc:
                    value = refusal("isolated_launch_unavailable", str(exc))
                after = self.check_input(s)
                preservation = self.preservation(before, after)
                if not preservation["foregroundPreserved"] or not preservation["cursorPreserved"]: self.pause(s, "focus_changed")
                self.record(s, by, "launch_app", args, value.get("structuredContent"), preservation=preservation, started=started,
                            status="failed" if value.get("isError") or not preservation["foregroundPreserved"] or not preservation["cursorPreserved"] else "ok")
                self.changed(s)
                self.refresh(s)
                value = {**value, "_meta": {**value.get("_meta", {}), "neyvia/preservation": preservation}}
            return self.meta(value, s, client)
        try:
            w = self.target(s, args)
        except (ValueError, TypeError) as exc:
            return self.meta(refusal(str(exc), "Select one currently allowed PID/window"), s, client)
        if tool == "get_window_state":
            if args.get("screenshot_out_file"):
                return self.meta(refusal("app_not_allowed", "Use cua.capture's managed output; arbitrary screenshot file writes are not allowed"), s, client)
            with self.action_lock:
                value = self.snapshot(s, w, image=args.get("include_screenshot", True), elements=args.get("include_accessibility_tree", True))
            return self.meta(value, s, client)
        if tool == "verify_state":
            args.update(pid=w["pid"], window_id=int(w["windowId"])); args.pop("session", None)
            value = self.verify_values(s, w, args)
            if value is None:
                value = result({"status": "unknown", "stable": False, "elapsed_ms": 0, "samples": 0,
                    "predicates": [{"index": i, "status": "unknown", "unknown_reason": "unsupported_predicate", "observed_json": "null"}
                                   for i, _ in enumerate(args.get("expect") or [])]})
                value["_meta"] = {"neyvia/nativeVerifier": {"source": "unsupported predicate; no upstream query dispatched",
                    "pid": w["pid"], "window_id": int(w["windowId"])}}
            return self.meta(value, s, client)
        if by == "agent":
            self.check_input(s)
            if s["control"] != "agent":
                return self.meta(refusal("paused_by_user", "Use preview_wait until Paul gives back control"), s, client)
        replay_key = (s["id"], client.get("chatId"), envelope.get("connectionId"), str(envelope.get("requestId"))) if envelope.get("requestId") is not None and by == "agent" else None
        request_hash = hashlib.sha256(json.dumps({"tool": tool, "args": args}, sort_keys=True).encode()).hexdigest()
        if replay_key in self.replays:
            old = self.replays[replay_key]
            if old["hash"] != request_hash:
                return self.meta(refusal("invalid_request", "A requestId cannot be reused for a different action"), s, client)
            return self.meta(old["result"], s, client)
        with self.action_lock:
            if s["status"] == "ended":
                return self.meta(refusal("session_ended", "The host ended this session"), s, client)
            if s.get("_dispatchGuard"):
                s["_dispatchGuard"]()
            if replay_key in self.replays:
                old = self.replays[replay_key]
                return self.meta(old["result"] if old["hash"] == request_hash else refusal("invalid_request", "A requestId cannot change its action"), s, client)
            args.update(pid=w["pid"], window_id=int(w["windowId"]), delivery_mode="background"); args.pop("session", None)
            if by == "paul" and tool in {"click", "scroll"} and not args.get("element_token") and "x" in args and "y" in args:
                try:
                    self.owner_point(s, w, args, "scroll" if tool == "scroll" else None)
                except ValueError as exc:
                    value = refusal(str(exc), "The displayed frame changed or has no supported background control; refresh it")
                    self.record(s, by, tool, args, value["structuredContent"], window=w)
                    return self.meta(value, s, client)
            if tool == "scroll" and args.get("direction"):
                direction = args.get("direction")
                amount = args.get("amount", 1)
                if direction not in {"up", "down", "left", "right"} or type(amount) is not int or not 1 <= amount <= 10:
                    return self.meta(refusal("invalid_request", "Scroll requires a direction and amount from 1 to 10"), s, client)
                magnitude = "Large" if amount >= 3 else "Small"
                change = "Increment" if direction in {"down", "right"} else "Decrement"
                args["horizontal"] = magnitude + change if direction in {"left", "right"} else "NoAmount"
                args["vertical"] = magnitude + change if direction in {"up", "down"} else "NoAmount"
            if by == "paul" and tool in {"type_text", "press_key", "hotkey"} and not args.get("element_token"):
                self.preview_target(s, w, tool, args)
            snap = self.snapshots.get((s["id"], str(w["windowId"])))
            if not snap or time.monotonic() - snap["at"] > 60:
                return self.meta(refusal("stale_element_token", "Take a fresh window snapshot before acting"), s, client)
            token = args.get("element_token")
            element = next((e for e in snap["data"].get("elements", []) if e.get("element_token") == token), None) if token else None
            if token and element is None:
                return self.meta(refusal("stale_element_token", "Element belongs to another or expired snapshot"), s, client)
            if args.get("capture_id") and args["capture_id"] not in {snap["data"].get("capture_id"), self.frames.get((s["id"], str(w["windowId"])), {}).get("metadata", {}).get("captureId")}:
                return self.meta(refusal("stale_element_token", "The preview frame changed; capture again"), s, client)
            if by == "paul" and not s.get("_ephemeral"):
                # Our isolated driver validates frame identity itself. Native
                # preview input never starts a second upstream desktop driver.
                pass
            elif s.get("_ephemeral"):
                args.pop("capture_id", None)
            keys = str(args.get("keys") or "") + str(args.get("modifier") or args.get("modifiers") or "") + str(args.get("key") or "")
            dangerous = bool(DANGEROUS.search(str((element or {}).get("label", ""))) or DANGEROUS.search(keys) or re.search(r"alt.*f4|shift.*delete|ctrl.*[sw]", keys, re.I))
            dangerous = dangerous or tool == "invoke_menu" or (tool == "press_key" and str(args.get("key", "")).casefold() in {"enter", "return"})
            dangerous = dangerous or (not element and tool in {"click", "double_click", "right_click", "invoke_menu"})
            dangerous = dangerous or (bool(element) and element.get("role") in {"Custom", "Pane", "Window"} and tool in {"click", "press_key", "type_text"})
            if dangerous:
                # The preview must keep streaming while an approval is pending.
                self.action_lock.release()
                try:
                    decision = self.approval(s, "action", tool.replace("_", " ") + " " + str((element or {}).get("label", "unmapped control")), tool=tool, app=w["processName"], element=element)
                finally:
                    self.action_lock.acquire()
                if decision != "allow":
                    value = refusal("denied_by_user" if decision == "deny" else "approval_timeout", "Action was not approved")
                    self.record(s, by, tool, args, value["structuredContent"], status="denied", window=w)
                    return self.meta(value, s, client)
            before = self.check_input(s) if by == "agent" else self.marker()[0]
            if by == "agent" and s["control"] != "agent":
                return self.meta(refusal("paused_by_user", "Paul took over before dispatch"), s, client)
            current = self.target(s, {"pid": w["pid"], "window_id": int(w["windowId"])})
            if current.get("processStartTime") != w.get("processStartTime"):
                return self.meta(refusal("window_target_not_found", "The approved process was replaced"), s, client)
            projected, started = self.focus(s, w, tool, args, by, "about"), time.perf_counter()
            try:
                if s["status"] == "ended":
                    return self.meta(refusal("session_ended", "The host ended this session"), s, client)
                if s.get("_dispatchGuard"):
                    s["_dispatchGuard"]()
                # Only the PC-owner session flag grants the final foreground
                # route; a model-supplied argument cannot grant it.
                args["_ownerForegroundAllowed"] = bool(s.get("foreground"))
                value = s["_dispatch"](w, tool, args, element) if s.get("_dispatch") else self.native_message(w, tool, args, element) or refusal("background_unavailable", "No isolated background route supports this action")
            except Exception as exc:
                # A timeout after dispatch can have an effect. Never replay it automatically.
                self.pause(s, "action_outcome_unknown")
                value = result({"effect": "unverifiable", "route": "accessibility", "delivery": {"mode": "background"},
                    "summary": "Native action outcome is unknown; inspect before retrying: " + str(exc)[:240]})
                value["isError"] = True
                value["_meta"] = {"neyvia/outcomeUnknown": True}
            after = self.check_input(s) if by == "agent" else self.marker()[0]
            preservation = self.preservation(before, after)
            native_route=value.get("_meta", {}).get("neyvia/nativeRoute", {})
            preservation["focusRestored"] = bool(s.get("foreground") and native_route.get("focusRestored")
                and before.get("inputGeneration") == after.get("inputGeneration"))
            intact = (preservation["foregroundPreserved"] or preservation["focusRestored"]) and preservation["cursorPreserved"]
            if not intact:
                self.pause(s, "focus_changed")
                value = {**value, "isError": True, "content": [*value.get("content", []), {"type": "text", "text": "Foreground/cursor preservation failed. Execution paused; inspect the target before any retry."}]}
            self.record(s, by, tool, args, value.get("structuredContent"), status="failed" if not intact or value.get("isError") else None,
                        element=projected, window=w, started=started, preservation=preservation)
            self.changed(s)
            self.focus(s, w, tool, args, by, "done")
            value = {**value, "_meta": {**value.get("_meta", {}), "neyvia/preservation": preservation}}
            if replay_key:
                self.replays[replay_key] = {"hash": request_hash, "result": value}
                if len(self.replays) > 1000: self.replays.pop(next(iter(self.replays)))
            if not s.get("_ephemeral"):
                bus_for(self.root).emit("cua.session", {"sessionId": s["id"], "owner": s.get("owner"), "app": w["processName"], "title": w["title"]})
            return self.meta(value, s, client)

    def preview_tool(self, s, tool, args):
        if tool == "preview_log":
            rows = [r for r in self.log if r["sessionId"] == s["id"] and r["seq"] > int(args.get("since_seq", 0))]
            return {"session": s["id"], "entries": rows[:max(1, min(200, int(args.get("limit", 200))))], "next_seq": self.sequence}
        if tool == "preview_wait":
            end = time.monotonic() + min(600000, max(0, int(args.get("timeout_ms", 30000)))) / 1000
            while s["control"] == "paul" and s["status"] != "ended" and time.monotonic() < end and not self.stopped.wait(0.1):
                pass
            return {"control": s["control"], "note": s.get("_note"), "timedOut": s["control"] == "paul"}
        if tool == "preview_note":
            self.record(s, "agent", "note", text=str(args.get("text", ""))[:500]); return {"recorded": True}
        if tool == "preview_show":
            bus_for(self.root).emit("pane.show", {"kind": "preview", "target": s["id"]}); return {"shown": True}
        if tool == "request_app":
            decision = self.approval(s, "app", "Allow " + str(args.get("app")) + ": " + str(args.get("reason", ""))[:200], app=args.get("app"))
            return {"allowed": decision == "allow", "code": None if decision == "allow" else "denied_by_user" if decision == "deny" else "approval_timeout"}
        raise ValueError("Unknown preview operation")

    def install_driver(self, args):
        """Owner-started, one at a time: stage the pinned, hash-checked helper in the shared
        per-user runtime (a 31 MB download, or a verified local copy) in the background."""
        from .cua_upstream import install_runtime, runtime_status
        with self.lock:
            if self._driver_setup.get("state") == "running":
                return {"install": dict(self._driver_setup)}
            if runtime_status()["available"]:
                self._driver_setup = {"state": "done", "at": time.time()}
                return {"install": dict(self._driver_setup)}
            self._driver_setup = {"state": "running", "startedAt": time.time()}
        # An offline or managed PC can point Neyvia at a verified copy instead of the 31 MB download.
        source = args.get("source") or os.environ.get("NEYVIA_CUA_DRIVER_SOURCE")

        def run():
            try:
                result = install_runtime(Path(source) if source else None)
                value = {"state": "done", "at": time.time(), "runtime": result["runtime"], "downloaded": result["downloaded"]}
            except Exception as exc:  # noqa: BLE001 - reported to the owner in plain words
                text = str(exc)
                plain = ("The download didn't finish. Check the internet connection and try again."
                         if any(word in text.lower() for word in ("urlopen", "timed out", "connection", "network", "getaddrinfo"))
                         else "The helper couldn't be set up: " + text[:200])
                value = {"state": "failed", "at": time.time(), "error": plain}
            with self.lock:
                self._driver_setup = value

        threading.Thread(target=run, name="cua-driver-setup", daemon=True).start()
        return {"install": dict(self._driver_setup)}

    def request(self, op, args=None, *, owner=False):
        args = dict(args or {})
        if op in OWNER_OPS and not owner:
            raise ValueError("Only the PC owner can grant native app access, approve or give back")
        if op == "state": return self.state(args)
        if op == "install_driver": return self.install_driver(args)
        if op == "native":
            client = canonical_client(args.get("client") or {})
            if not client.get("chatId") or client.get("app") != "neyvia":
                raise ValueError("A bound Neyvia chat identity is required")
            name, arguments = str(args.get("name") or ""), args.get("arguments") or {}
            if not name.startswith("cua.") or name.removeprefix("cua.") not in {d[0].removeprefix("cua.") for d in DEFINITIONS}:
                raise ValueError("Unknown native CUA tool")
            return native_request(self, name, arguments, client)
        if op == "apps": return self.upstream.call("list_apps", {}).get("structuredContent")
        if op == "driver": return self.driver(args)
        if op == "open":
            apps = args.get("apps", [])
            if not isinstance(apps, list) or len(apps) > 8 or any(not isinstance(a, str) for a in apps): raise ValueError("Choose up to eight explicit app names")
            client = {"chatId": args.get("chatId") or "native", "app": args.get("app") or "neyvia", "title": args.get("title") or "Computer use"}
            return self.public(self.new_session(apps, client))
        if op == "windows" and not args.get("sessionId") and not self.sessions:
            return {"windows": []}
        s = self.session(args)
        if op == "windows": return {"windows": self.refresh(s)}
        if op in OWNER_OPS:
            with self.lock:
                if op == "control":
                    if args.get("mode") == "paul": self.pause(s, "take_over")
                    elif args.get("mode") == "agent":
                        _, s["_inputMarker"] = self.marker(); s.update(control="agent", pausedReason=None, _note=str(args.get("note") or "")[:1000] or None)
                        self.record(s, "paul", "control", text="Paul gave back control" + (": " + s["_note"] if s["_note"] else ""))
                    else: raise ValueError("Control mode must be paul or agent")
                elif op == "allow":
                    if args.get("allowed") is True: self.grant(s, args["app"])
                    elif args.get("allowed") is False:
                        s["allow"] = [a for a in s["allow"] if app_name(a["app"]) != app_name(args["app"])]
                        for key in list(self.frames):
                            if key[0] == s["id"]: self.frames.pop(key)
                        s["windows"] = []
                    else: raise ValueError("allowed must be boolean")
                    self.record(s, "paul", "allow", args, text="App allow-list changed")
                elif op == "foreground":
                    if not isinstance(args.get("allowed"), bool): raise ValueError("allowed must be boolean")
                    if args["allowed"]:
                        raise ValueError("Foreground delivery is disabled; use the isolated preview")
                    s["foreground"] = args["allowed"]
                elif op == "approve":
                    a = next((a for a in s["approvals"] if a["id"] == args.get("approvalId")), None)
                    if not a or time.monotonic() >= a["_expires"]: raise ValueError("Approval missing or expired")
                    if args.get("decision") not in {"allow", "deny"}: raise ValueError("Choose allow or deny")
                    a["_decision"] = args["decision"]
                    if a["kind"] == "app_visibility":
                        record = self.app_permissions[a["app"]]
                        record.update(status="allowed" if args["decision"] == "allow" else "denied", decidedAt=now())
                        atomic_write_json(self.directory / "app-permissions.json", self.app_permissions)
                    if args["decision"] == "allow":
                        if a["kind"] in {"app", "session"} and a.get("app"): self.grant(s, a["app"])
                        if a["kind"] == "session":
                            _, s["_inputMarker"] = self.marker(); s.update(status="active", control="agent")
                    s["approvals"].remove(a)
                    self.record(s, "paul", "approval", text="Paul " + ("allowed" if args["decision"] == "allow" else "denied") + " the request")
                elif op == "end": s.update(status="ended", control="paul", approvals=[])
                self.changed(s)
            if op != "input": return self.public(s)
        client = s.get("owner") or {"chatId": "native", "app": "neyvia"}
        if op == "input":
            tool = args.get("kind")
            if tool not in ACTIONS: raise ValueError("Unsupported preview input")
            a = {k: v for k, v in args.items() if k not in {"sessionId", "kind", "windowId", "captureId"} and v is not None}
            a["window_id"] = args["windowId"]
            if args.get("captureId"): a["capture_id"] = args["captureId"]
            original_capture = a.get("capture_id")
            with self.action_lock:
                before_sequence = self.sequence
                value = self.driver({"tool": tool, "arguments": a, "sessionId": s["id"], "client": client}, by="paul")
                row = next((r for r in reversed(self.log) if r["seq"] > before_sequence and r["sessionId"] == s["id"] and r["by"] in {"paul", "remote"} and r["tool"] == tool), None)
                if row is None:
                    row = self.record(s, "paul", tool, a, value.get("structuredContent"), status="refused")
            return {**row, "captureId": original_capture}
        if op in {"adapt", "flow"}:
            w = self.target(s, args)
            with self.action_lock:
                return self.adaptation.adapt(s, w, args) if op == "adapt" else self.adaptation.flow(s, w, args["steps"])
        if op in {"capture", "snapshot", "inspect", "verify"}:
            w = self.target(s, args)
            if op == "verify":
                value = self.driver({"tool": "verify_state", "arguments": {"pid": w["pid"], "window_id": int(w["windowId"]), "expect": args["expect"], "timeout_ms": args.get("timeout_ms", 5000)}, "sessionId": s["id"], "client": client})
                return {**value.get("structuredContent", {}), "_meta": value.get("_meta", {})}
            deadline = self.observation_deadline(args)
            while True:
                try:
                    with self.action_lock:
                        value = self.snapshot(s, w, image=op != "inspect", elements=op != "capture", max_elements=args.get("max_elements", 256))
                    break
                except TimeoutError:
                    # Hover and refresh are read-only. Recover from a cold
                    # provider within the same bounded observation budget.
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)
            if value.get("isError"): raise ValueError("Background capture/inspection unavailable: " + str(value.get("content"))[:250])
            if op != "capture":
                data = value.get("structuredContent") or value
                if op == "inspect" and args.get("query"):
                    query = str(args["query"]).casefold()
                    data = {**data, "elements": [e for e in data.get("elements", [])
                            if query in str(e.get("label", "")).casefold() or query in str(e.get("role", "")).casefold()]}
                if op == "inspect" and args.get("diff_only"):
                    if s.get("_ephemeral"):
                        raise ValueError("CL-State persistence requires a local recording-enabled session")
                    return self.adaptation.cl_state(s, w, data, args)
                return data
            frame = self.frames.get((s["id"], str(w["windowId"])))
            if not frame: raise ValueError("Background capture unavailable")
            return {**frame["metadata"], **({"path": frame["path"]} if "path" in frame else {}), "sha256": frame["sha256"]}
        if op in {"action", "log", "wait"}:
            value = self.driver({"tool": args["tool"] if op == "action" else "preview_" + op, "arguments": args.get("args", {}) if op == "action" else args, "sessionId": s["id"], "client": client})
            return {**value.get("structuredContent", {}), "_meta": value.get("_meta", {})}
        raise ValueError("Unknown CUA operation")


_SERVICES, _LOCK = {}, threading.Lock()


def service_for(root):
    key = str(Path(root).resolve())
    with _LOCK:
        created = key not in _SERVICES
        if created: _SERVICES[key] = CuaService(root)
        service = _SERVICES[key]
    if created:
        # Every native session is mirrored and kept as a time-lapse, watched or not.
        from .neyvia_agentview import view_for
        view_for(root)
    return service


def call(workspace, name, args):
    client = canonical_client(NATIVE_CLIENT.get() or {"chatId": "native", "app": "neyvia"})
    if getattr(workspace, "backend", None) is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
        from .neyvia_cua_mcp import CuaMCPServer
        bridge = CuaMCPServer()
        bridge._authenticate()
        return bridge._http("/api/ui/cua", {"op": "native", "args": {"name": name, "arguments": args, "client": client}}, timeout=610 if name == "cua.wait" else 130)
    return native_request(service_for(workspace.bus.root), name, args, client)


def native_request(service, name, args, client):
    op = name.removeprefix("cua.")
    if op != "state":
        session = service.session(args, client)
        if session["status"] == "ended" and op not in {"log", "wait"}:
            raise ValueError("session_ended")
    return service.request(op, args, owner=False)


def handle_command(root, command, payload, *, owner=False):
    if command not in COMMANDS: raise ValueError("Unknown CUA command")
    return service_for(root).request(command.removeprefix("cua_").removesuffix("_command"), payload, owner=owner)


def serve_http(backend, handler, parsed, method):
    from .web_backend import _json_response, _read_json_body, _apply_security_headers
    query, suffix = {k: v[0] for k, v in parse_qs(parsed.query).items()}, parsed.path.removeprefix("/api/ui/cua").strip("/")
    session = backend.authenticated_session(handler)
    if not session or str(session.get("username", "")).casefold() != backend.username.casefold():
        _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required for native preview"}); return
    from .neyvia_remote import _loopback, _origin
    if not _loopback(handler.client_address[0]) or not _origin(handler):
        _json_response(handler, 403, {"ok": False, "error": "Native preview is host-local; use the explicitly enabled remote route"}); return
    try:
        service = service_for(backend.root)
        if method == "GET" and suffix == "stream": stream(service, handler, query); return
        if method == "GET" and suffix == "tools":
            from .neyvia_cua_mcp import PREVIEW_TOOLS
            value = {"tools": service.upstream.list_tools() + PREVIEW_TOOLS}
        elif method == "POST":
            body = _read_json_body(handler)
            expected = (body.get("args") or {}).get("_expectedStateRoot")
            if expected and Path(expected).resolve() != Path(backend.root).resolve():
                raise ValueError("CUA desktop state root differs from the selected service")
            selected = service.sessions.get(str((body.get("args") or {}).get("sessionId")))
            if selected and selected.get("_ephemeral"):
                raise ValueError("Use the remote route for this host-consented session")
            value = service.request(str(body.get("op") or suffix), body.get("args") or {}, owner=body.get("op") != "driver")
        elif method == "GET" and suffix == "frame":
            s, w = service.session(query), service.target(service.session(query), query)
            if s.get("_ephemeral"):
                raise ValueError("Use the remote route for this host-consented session")
            key = (s["id"], str(w["windowId"]))
            # The stream publishes captures. Fetching their image must not
            # emit another frame, which cancels the pane's pending Image load
            # and causes an endless request/capture/event loop.
            with service.action_lock:
                f = service.frames.get(key)
                if not f or not f.get("raw"):
                    service.request("capture", query, owner=True)
                    f = service.frames[key]
                if f.get("metadata", {}).get("unavailable"):
                    raise ValueError("Background capture unavailable")
                if query.get("seq"):
                    wanted = int(query["seq"])
                    f = next((row for row in reversed(service.displayed_frames.get(key, []))
                              if row["metadata"]["seq"] == wanted), None)
                    if not f:
                        raise ValueError("Displayed frame expired; wait for the next live frame")
            handler.send_response(200)
            for k, v in {"Content-Type": f["mimeType"], "Content-Length": str(len(f["raw"])), "Cache-Control": "no-store", "X-Frame-Seq": str(f["metadata"]["seq"]),
                         "X-Capture-Id": str(f["metadata"]["captureId"] or ""), "X-CUA-Frame-SHA256": f["sha256"]}.items(): handler.send_header(k, v)
            _apply_security_headers(handler); handler.end_headers(); handler.wfile.write(f["raw"]); return
        elif method == "GET" and suffix in {"state", "windows", ""}: value = service.request(suffix or "state", query, owner=True)
        else: raise ValueError("Unknown CUA route")
        _json_response(handler, 200, {"ok": True, "data": value})
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError): pass
    except (ValueError, KeyError, TypeError) as exc: _json_response(handler, 400, {"ok": False, "error": str(exc)[:500], "code": "invalid_request"})
    except (RuntimeError, OSError) as exc: _json_response(handler, 503, {"ok": False, "error": str(exc)[:500], "code": "driver_unavailable"})


def stream(service, handler, query):
    from .web_backend import _apply_security_headers
    handler.send_response(200)
    for k, v in {"Content-Type": "text/event-stream", "Cache-Control": "no-store", "Connection": "keep-alive"}.items(): handler.send_header(k, v)
    _apply_security_headers(handler); handler.end_headers()
    cursor, identity = int(query.get("cursor") or handler.headers.get("Last-Event-ID") or 0), query.get("sessionId")
    def send(e):
        handler.wfile.write(("id: " + str(e["cursor"]) + "\ndata: " + json.dumps(e, ensure_ascii=False) + "\n\n").encode()); handler.wfile.flush()
    for s in list(service.sessions.values()):
        if not identity or s["id"] == identity: send({"cursor": cursor, "type": "session", "sessionId": s["id"], "data": service.public(s)})
    keepalive, capture_at = time.monotonic(), 0
    while not service.stopped.wait(0.25):
        for e in [e for e in list(service.events) if e["cursor"] > cursor]:
            if not identity or e["sessionId"] == identity: send(e)
            cursor = max(cursor, e["cursor"])
        if time.monotonic() - capture_at >= 0.5:
            capture_at = time.monotonic()
            for s in list(service.sessions.values()):
                if s["status"] != "active" or (identity and s["id"] != identity): continue
                for w in service.refresh(s)[:8]:
                    try:
                        with service.action_lock: service.request("capture", {"sessionId": s["id"], "windowId": w["window_id"]}, owner=True)
                    except (ValueError, RuntimeError) as exc:
                        key = (s["id"], str(w["window_id"]))
                        m = {"seq": service.sequence + 1, "windowId": w["window_id"], "captureId": None, "width": 0, "height": 0, "scale": 1, "at": now(), "unavailable": "minimized" if w["minimized"] else "capture_unavailable", "reason": str(exc)[:250]}
                        if service.frames.get(key, {}).get("metadata", {}).get("unavailable") != m["unavailable"]:
                            service.frames[key] = {"metadata": m}; service.event("frame", s, m)
        if time.monotonic() - keepalive >= 5:
            handler.wfile.write(b": keep-alive\n\n"); handler.wfile.flush(); keepalive = time.monotonic()


def forward_desktop(root, command, payload):
    import http.cookiejar
    import urllib.request
    base = os.environ.get("NEYVIA_UI_BACKEND_URL") or ("http://127.0.0.1:" + os.environ.get("NEYVIA_SERVICE_PORT", "48171"))
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port not in (*range(48171, 48180), *range(48701, 48710)): raise ValueError("Native CUA IPC requires the selected loopback PC backend")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, body):
        with opener.open(urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=135) as response: return json.load(response)
    post("/api/auth/local-session", {})
    answer = post("/api/ui/cua", {"op": command.removeprefix("cua_").removesuffix("_command"), "args": {**payload, "_expectedStateRoot": str(Path(root).resolve())}})
    return answer.get("data") or answer
