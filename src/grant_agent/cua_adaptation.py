"""First-use UIA exploration and evidence-grounded, workspace-only flow learning.

Learned procedures are data executed by the existing manual runner/compiler.
App labels and images never become code or authority. Every replay resolves a
fresh unique selector and retains the session's grants, takeover and approvals.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import secrets
import time
from pathlib import Path
from types import SimpleNamespace

from .durability import atomic_write_json, atomic_write_text


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


class Adaptation:
    def __init__(self, service):
        self.service = service
        self.directory = service.directory / "adaptation"
        self.drafts = {}
        self.registry = None
        self.visual_failures = {}
        # Static authored manual preparation belongs to service startup, not a
        # first observation of a previously unseen application.
        from .neyvia_manuals import get_manual
        get_manual("computer-use", service.root / ".neyvia")

    def snapshot(self, window, image, elements, maximum):
        from .neyvia_cua import result
        native = self.service.native
        identity = secrets.token_hex(16)
        data = {"snapshot_id": identity, "capture_id": identity,
                "window_id": int(window["windowId"]), "elements": [], "source": "Windows UI Automation"}
        if elements:
            observed = native.request("inspect", {"windowId": str(window["windowId"]),
                "maxDepth": 12, "maxNodes": max(1, min(2000, int(maximum))) })
            data.update(source=observed.get("source", "Windows UI Automation"),
                        nativeRevision=observed.get("revision"), nativeDiff=observed.get("diff"),
                        degradedReason=observed.get("degradedReason"), nativeElapsedMs=observed.get("elapsedMs"))
            # HWND reuse is never a license to inspect another process.
            if any(observed["window"].get(k) != window.get(k) for k in ("pid", "processStartTime")):
                raise ValueError("window_target_not_found")
            for index, node in enumerate(observed["tree"]):
                patterns = node.get("patterns", [])
                actions = []
                if any(p in patterns for p in ("invoke", "toggle", "selectionItem")) or node.get("nativeWindowHandle"):
                    actions.append("click")
                if "value" in patterns and not node.get("isPassword") and not node.get("readOnly"):
                    actions += ["type_text", "set_value"]
                if "scroll" in patterns:
                    actions.append("scroll")
                data["elements"].append({"element_index": index,
                    "element_token": identity + ":" + node["id"], "nativeId": node["id"],
                    "parentId": node.get("parentId"), "depth": node["depth"],
                    "label": node.get("name", ""), "role": node["role"],
                    "automationId": node.get("automationId", ""), "className": node.get("className", ""),
                    "nativeHandle": node.get("nativeWindowHandle"),
                    "enabled": node["enabled"], "offscreen": node["offscreen"],
                    "protected": node.get("isPassword", False), "patterns": patterns,
                    "readOnly": node.get("readOnly", False),
                    "frame": node["bounds"], "actions": actions,
                    **{key: node[key] for key in ("value", "selected", "toggleState", "expandState") if key in node}})
            data.update(truncated=observed["truncated"], elements_complete=not observed["truncated"])
        chrome_ids = {e["nativeId"] for e in data["elements"] if e["role"] in {"TitleBar", "MenuBar"}}
        useful = [e for e in data["elements"] if e["enabled"] and not e["offscreen"] and e["actions"]
                  and e["role"] not in {"Window", "Pane", "Custom", "TitleBar", "MenuBar"}
                  and e.get("parentId") not in chrome_ids]
        # A bounded Win32/MSAA projection can still expose useful controls.
        # Perception is needed only when semantic actions are unavailable.
        fallback = elements and not useful
        value = result(data)
        if image or fallback:
            native.request("remoteGuard", {"windowId": str(window["windowId"])})
            capture = native.request("capture", {"windowId": str(window["windowId"])})
            raw = base64.b64decode(capture["pngBase64"], validate=True)
            from PIL import Image
            picture = Image.open(io.BytesIO(raw))
            width, height = picture.size
            scale = min(1, 1600 / max(width, height))
            if scale < 1:
                picture.thumbnail((1600, 1600))
                out = io.BytesIO(); picture.save(out, format="PNG"); raw = out.getvalue()
            data["screenshot_scale"] = scale
            for node in data["elements"]:
                bounds = node["frame"]
                node["screenshot_frame"] = {"x": (bounds["x"] - window["bounds"]["x"]) * scale,
                    "y": (bounds["y"] - window["bounds"]["y"]) * scale,
                    "w": bounds["width"] * scale, "h": bounds["height"] * scale}
            value["content"].append({"type": "image", "data": base64.b64encode(raw).decode(), "mimeType": "image/png"})
            if fallback:
                data["fallback"] = self.visual_projection(window, data, raw, scale)
        # The text content must describe the final structured observation too.
        value["content"][0]["text"] = json.dumps(data, ensure_ascii=False)
        return value

    def visual_projection(self, window, data, raw, scale):
        """Automatic T18 on bounded/degraded UIA, with exact pixel admission."""
        from .neyvia_perception import image_projection
        from .perception_visual import MODEL, VisualExtractionError
        sha = hashlib.sha256(raw).hexdigest()
        failure = self.visual_failures.get(sha)
        if failure and time.monotonic() - failure[0] < 30:
            return {**failure[1], "retryAfterMs": round((30 - time.monotonic() + failure[0]) * 1000)}
        path = self.directory / "visual-input" / (str(window["windowId"]) + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        try:
            visual = image_projection(path, self.directory / "visual", 0)
            latest = self.service.native.request("capture", {"windowId": str(window["windowId"])})
            from PIL import Image
            picture = Image.open(io.BytesIO(base64.b64decode(latest["pngBase64"], validate=True)))
            out = io.BytesIO()
            if max(picture.size) > 1600:
                picture.thumbnail((1600, 1600)); picture.save(out, format="PNG"); current_raw = out.getvalue()
            else:
                current_raw = base64.b64decode(latest["pngBase64"], validate=True)
            stable = hashlib.sha256(current_raw).hexdigest() == sha
            summary = {"status": "observed" if stable else "stale", "source": "T18 image-to-CL",
                "reason": data.get("degradedReason") or "No actionable semantic controls", "frameSha256": sha,
                "stable": stable, "provenance": visual["provenance"], "visual": {k: v for k, v in visual.items() if k != "provenance"}}
            if stable:
                root = next((e for e in data["elements"] if e["depth"] == 0), None)
                for index, obj in enumerate(visual["objects"]):
                    bounds = obj.get("bounds")
                    if not root or obj["certainty"] != "observed" or not bounds or not bounds["width"] or not bounds["height"]:
                        continue
                    node = {"element_index": len(data["elements"]), "element_token": data["snapshot_id"] + ":visual:" + str(index),
                        "nativeId": root["nativeId"], "visualId": "visual:" + str(index), "depth": 1, "parentId": root["nativeId"],
                        "label": obj["name"], "role": "Custom", "automationId": "", "className": root["className"],
                        "nativeHandle": root["nativeHandle"], "enabled": True, "offscreen": False, "protected": False,
                        "patterns": [], "actions": ["click"], "frame": {"x": window["bounds"]["x"] + bounds["x"] / scale,
                            "y": window["bounds"]["y"] + bounds["y"] / scale, "width": bounds["width"] / scale, "height": bounds["height"] / scale},
                        "screenshot_frame": {"x": bounds["x"], "y": bounds["y"], "w": bounds["width"], "h": bounds["height"]},
                        "captureSha256": sha, "_nativeExpected": {k: root[k] for k in ("label", "role", "className")}}
                    data["elements"].append(node)
            return summary
        except (VisualExtractionError, RuntimeError, ValueError, OSError) as exc:
            failure = {"status": "unavailable", "source": "T18 image-to-CL", "model": MODEL,
                "frameSha256": sha, "reason": type(exc).__name__ + ": " + str(exc)[:200], "stable": False}
            self.visual_failures[sha] = (time.monotonic(), failure)
            return failure
        finally:
            path.unlink(missing_ok=True)

    def cl_state(self, session, window, data, args):
        from . import manual_state
        # Snapshot-scoped tokens and timings are transport data, not semantic
        # changes. Stable native ids identify typed controls in the CL state.
        fields = ("role", "label", "value", "selected", "toggleState", "expandState", "enabled", "offscreen", "protected", "actions", "frame", "automationId", "className")
        controls = {(e.get("visualId") or e.get("nativeId") or str(e["element_index"])):
                    {k: e[k] for k in fields if k in e} for e in data["elements"]}
        fallback = data.get("fallback", {})
        state = {"window": {k: window.get(k) for k in ("windowId", "pid", "processStartTime", "processName", "title", "bounds")},
            "controls": controls, "source": data["source"], "complete": data.get("elements_complete", False),
            "trust": "untrusted-data", "fallback": {k: fallback[k] for k in ("status", "source", "stable", "frameSha256") if k in fallback}}
        observed = manual_state.observe(self.service.root / ".neyvia/cua-state",
            {"observer": "cua.window", "notation": "neyvia.window.cl-state.v1"}, state,
            {"inputs": {"sessionId": session["id"], "window_id": int(window["windowId"]), "processStartTime": window["processStartTime"]},
             **{k: args[k] for k in ("previousHandle", "reset") if k in args}})
        return {**observed, "snapshot_id": data["snapshot_id"], "window_id": int(window["windowId"]),
            "handles": {key: e["element_token"] for key, e in zip(controls, data["elements"])},
            "manual": data.get("manual"), **({"extraction": fallback.get("provenance"), "fallbackStatus": fallback["status"]} if fallback else {})}

    def key(self, window):
        path = Path(window.get("exe") or "")
        version = path.stat().st_mtime_ns if path.is_file() else None
        return digest({"exe": window.get("exe"), "app": window["processName"], "version": version})[:24]

    def draft(self, window, data):
        key = self.key(window)
        if key not in self.drafts:
            saved = self.directory / (key + ".json")
            if saved.is_file():
                self.drafts[key] = json.loads(saved.read_text(encoding="utf-8"))
                return {k: self.drafts[key][k] for k in ("appKey", "patchId", "status", "chapter", "tokens")}
            from .neyvia_manuals import get_manual, render
            from .manual_versions import quarantine
            _, sha, _ = get_manual("computer-use", self.service.root / ".neyvia")
            safe = [{k: e.get(k) for k in ("role", "label", "automationId", "className", "actions", "protected")}
                    for e in data["elements"] if not e.get("protected")]
            chapter = self.chapter(window, safe)
            patch = quarantine(self.service.root / ".neyvia", "computer-use", sha,
                "Read-only first-use UIA exploration; actions are candidates until independently checked",
                {"appKey": key, "controls": safe, "source": data["source"]},
                [{"op": "add", "path": "/chapters/app-" + key, "value": chapter}])
            record = {"appKey": key, "patchId": patch["patchId"], "status": "quarantined",
                      "chapter": "app-" + key, "baseSha256": sha, "controls": safe,
                      "manual": chapter, "exploration": "read-only UIA", "tokens": 0}
            self.directory.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.directory / (key + ".json"), record)
            atomic_write_text(self.directory / (key + ".cl"), render(chapter, {}, layer="computer-use"))
            self.drafts[key] = record
        row = self.drafts[key]
        return {k: row[k] for k in ("appKey", "patchId", "status", "chapter", "tokens")}

    def chapter(self, window, controls):
        inputs = {"type": "object", "properties": {"sessionId": {"type": "string"},
                  "window_id": {"type": "integer"}}, "required": ["sessionId", "window_id"], "additionalProperties": False}
        return {"title": "Observed " + window["processName"],
            "state": {"window": {"tool": "neyvia.cua.inspect", "inputs": inputs,
                "args": {"sessionId": {"$input": "sessionId"}, "window_id": {"$input": "window_id"}},
                "shape": {"type": "object"}}},
            "actions": {}, "checks": {}, "procedures": {}, "judge": {},
            "pitfalls": [{"failure": "A selector is stale, missing or ambiguous", "recovery": "Observe again; never guess or replay an uncertain action"}],
            "frontier": ["Unobserved controls and effects remain unproven"],
            "guidance": ["Read-only exploration; grants and irreversible-action approval stay active",
                         "Observed controls: " + json.dumps(controls, ensure_ascii=False)]}

    def action(self, window, tool, args, element):
        from .neyvia_cua import result, refusal
        native = self.service.native
        cls = element.get("className", "")
        classic_edit = cls == "Edit" or cls.startswith("WindowsForms10.EDIT")
        action = None
        if element.get("visualId"):
            if tool != "click" or args.get("count", 1) != 1 or args.get("button", "left") != "left" or args.get("modifier"):
                return refusal("background_unavailable", "Visual controls admit a verified single point click only")
            action = "pointClick"
            bounds = element["screenshot_frame"]
            args = {**args, "x": bounds["x"] + bounds["w"] / 2, "y": bounds["y"] + bounds["h"] / 2}
            frame = next((f for (_, wid), f in self.service.frames.items() if wid == str(window["windowId"])
                          and f["sha256"] == element["captureSha256"]), None)
            if not frame:
                return refusal("stale_element_token", "Visual target pixels are no longer captured")
            args["capture_id"] = frame["metadata"]["captureId"]
        elif tool in {"set_value", "type_text"} and "value" in element.get("patterns", []):
            action = ("editSetValue" if classic_edit else "value") if tool == "set_value" else ("editAppend" if classic_edit else "valueAppend")
        elif tool == "click" and not args.get("modifier") and args.get("count", 1) == 1 and args.get("button", "left") == "left":
            if cls.startswith("WindowsForms10.BUTTON") or (cls == "Button" and element.get("nativeHandle")):
                action = "buttonClick"
            elif cls == "Button":
                return refusal("background_unavailable", "This provider may focus its window; no dispatch occurred")
            else:
                action = "toggle" if "toggle" in element.get("patterns", []) else "select" if "selectionItem" in element.get("patterns", []) else "click"
        elif tool in {"press_key", "hotkey"}:
            action = "key"
        elif tool == "scroll" and "scroll" in element.get("patterns", []):
            action = "scroll"
        if not action:
            return refusal("background_unavailable", "No supported background action for this current control")
        status = native.request("status")
        x, y = args.get("x"), args.get("y")
        if x is not None or y is not None:
            # Opaque targets use the exact admitted captured pixels. Never move
            # the global cursor, inject a foreground key or guess coordinates.
            frames = [f for (sid, wid), f in self.service.frames.items()
                      if wid == str(window["windowId"]) and f["metadata"].get("captureId") == args.get("capture_id")]
            if len(frames) != 1 or x is None or y is None:
                return refusal("stale_element_token", "Coordinate actions require the current captured frame")
            frame = frames[0]
            meta = frame["metadata"]
            if not 0 <= float(x) < meta["width"] or not 0 <= float(y) < meta["height"]:
                return refusal("invalid_coordinates", "Point is outside captured window")
            capture = native.request("capture", {"windowId": str(window["windowId"])})
            raw_image = base64.b64decode(capture["pngBase64"], validate=True)
            from PIL import Image
            picture = Image.open(io.BytesIO(raw_image))
            if max(picture.size) > 1600:
                picture.thumbnail((1600, 1600)); out = io.BytesIO(); picture.save(out, format="PNG"); raw_image = out.getvalue()
            if hashlib.sha256(raw_image).hexdigest() != frame["sha256"]:
                return refusal("stale_element_token", "Pixels changed before coordinate dispatch")
            scale = meta.get("scale") or 1
            x = round(window["bounds"]["x"] + float(x) / scale)
            y = round(window["bounds"]["y"] + float(y) / scale)
        raw = native.request("remoteAction", {"windowId": str(window["windowId"]),
            "elementId": element["nativeId"], "action": action,
            "text": str(args.get("text", "") if tool == "type_text" else args.get("value", "")),
            "key": args.get("key") or "+".join(args.get("keys", [])), "x": x, "y": y,
            "horizontal": args.get("horizontal", "NoAmount"), "vertical": args.get("vertical", "SmallIncrement"),
            "expectedName": element.get("_nativeExpected", element)["label"], "expectedRole": element.get("_nativeExpected", element)["role"],
            "expectedClass": element.get("_nativeExpected", element)["className"],
            "inputGeneration": status["inputGeneration"],
            "allowForeground": bool(args.get("_ownerForegroundAllowed", False))})
        value = result({"effect": "unverifiable" if raw["effect"] == "uncertain" else raw["effect"],
            "route": "accessibility" if raw["mechanism"].startswith(("uia", "MSAA")) else "synthetic_events",
            "delivery": {"mode": raw.get("delivery") or "background", **({"delivered_count": 1} if raw["effect"] != "uncertain" else {})},
            "summary": "Action delivered through " + raw["mechanism"] + "; check the requested postcondition"})
        if raw.get("noRetry") or raw["effect"] == "uncertain":
            value.update(isError=True)
            value["structuredContent"]["summary"] = "Dispatch uncertain; inspect before retrying"
        value["_meta"] = {"neyvia/nativeRoute": raw}
        return value

    def adapt(self, session, window, args):
        started = time.perf_counter()
        value = self.service.snapshot(session, window, image=False)
        data = value["structuredContent"]
        actionable = [e for e in data["elements"] if e["enabled"] and e["actions"] and e["role"] not in {"Window", "Pane", "Custom"}]
        outcome = {"ok": True, **data["manual"], "observation": data,
                   "poorUIA": not actionable, "elapsed_ms": (time.perf_counter() - started) * 1000}
        if data.get("fallback"):
            outcome.update(visual=data["fallback"], capture_id=data["capture_id"])
        elif not actionable and args.get("visual"):
            self.service.snapshot(session, window, image=True)
            frame = self.service.frames[(session["id"], str(window["windowId"]))]
            from .neyvia_perception import image_projection
            if "path" not in frame:
                raise ValueError("Visual adaptation requires a recording-enabled local session")
            visual = image_projection(Path(frame["path"]), self.directory / "visual", 0)
            outcome.update(visual=visual, capture_id=frame["metadata"]["captureId"], frameSha256=frame["sha256"])
        return outcome

    def resolve(self, session, window, selector, observation_timeout_ms=500):
        # Slow provider initialization may yield a partial tree. Retry reads
        # before dispatch only; ambiguity and protected fields never authorize
        # an action. The caller can override this first-observation budget.
        if type(observation_timeout_ms) is not int or not 0 <= observation_timeout_ms <= 10000:
            raise ValueError("Invalid observation_timeout_ms")
        deadline = time.monotonic() + observation_timeout_ms / 1000
        attempts = 0
        while True:
            attempts += 1
            data = self.service.snapshot(session, window, image=False)["structuredContent"]
            matches = [e for e in data["elements"] if e["enabled"] and not e["protected"] and not e["offscreen"]
                       and all(str(e.get(k, "")) == v for k, v in selector.items())]
            if len(matches) > 1:
                raise ValueError("selector_ambiguous")
            if matches:
                element = matches[0]
                if element.get("visualId"):
                    return element
                fresh = self.service.native.request("inspectElements", {"windowId": str(window["windowId"]), "elementIds": [element["nativeId"]]})["tree"][0]
                if not fresh.get("isPassword") and fresh["enabled"] and not fresh["offscreen"] and all(
                        str(fresh.get("name" if k == "label" else k, "")) == v for k, v in selector.items()):
                    return {**element, "observationAttempts": attempts}
            if time.monotonic() >= deadline:
                raise ValueError("selector_missing" if not matches else "stale_element_token")
            time.sleep(min(.02, max(0, deadline - time.monotonic())))

    def perform(self, session, window, step, action_id=None):
        from .neyvia_cua import STEP
        from jsonschema import Draft202012Validator
        Draft202012Validator(STEP).validate(step)
        self.validate_expectations(step["expect"])
        action_args = dict(step.get("args", {}))
        observation_timeout_ms = action_args.pop("observation_timeout_ms", 500)
        element = self.resolve(session, window, step["selector"], observation_timeout_ms)
        arguments = {**action_args, "window_id": int(window["windowId"]),
                     "element_token": element["element_token"]}
        envelope = {"tool": step["tool"], "arguments": arguments, "sessionId": session["id"], "client": session["owner"]}
        if action_id:
            envelope.update(connectionId="grounded-flow", requestId=action_id)
        value = self.service.driver(envelope)
        preservation = value.get("_meta", {}).get("neyvia/preservation", {})
        focus_ok = preservation.get("foregroundPreserved") or (session.get("foreground") and preservation.get("focusRestored"))
        if value.get("isError") or not focus_ok or not preservation.get("cursorPreserved"):
            raise RuntimeError("Action refused or preservation failed: " + json.dumps(value.get("structuredContent", {})))
        check = self.verify(session, window, step["expect"], observation_timeout_ms)
        if check["status"] != "satisfied":
            raise RuntimeError("Flow postcondition failed: " + json.dumps(check))
        return {"ok": True, "action": value.get("structuredContent"), "check": check, "preservation": preservation,
                "observationAttempts": element.get("observationAttempts", 1)}

    @staticmethod
    def validate_expectations(expectations):
        if not isinstance(expectations, list) or not 1 <= len(expectations) <= 8:
            raise ValueError("Require 1..8 explicit postconditions")
        if not all(isinstance(rule, dict) for rule in expectations):
            raise ValueError("Postconditions must be objects")
        if any("visual" in rule for rule in expectations):
            if not all(set(rule) == {"visual"} and isinstance(rule["visual"], dict) and set(rule["visual"]) == {"text_contains"}
                       and isinstance(rule["visual"]["text_contains"], str) and rule["visual"]["text_contains"] for rule in expectations):
                raise ValueError("Visual checks require explicit nonempty visible text; mixed or guessed checks are refused")
            return
        for rule in expectations:
            item = rule.get("element")
            if set(rule) != {"element"} or not isinstance(item, dict):
                raise ValueError("Require an explicit element postcondition")
            selector = item.get("selector")
            if not isinstance(selector, dict) or not selector or set(selector) - {"role", "label", "label_contains", "automationId", "className"} or not all(isinstance(v, str) for v in selector.values()):
                raise ValueError("Unsupported postcondition selector")
            requested = set(item) - {"selector"}
            if len(requested) != 1 or not requested <= {"value_equals", "label_equals", "enabled_equals", "exists", "selected_equals", "toggle_equals", "expand_equals"}:
                raise ValueError("Unsupported postcondition; no guessed success")
            key = next(iter(requested))
            expected_type = bool if key in {"enabled_equals", "exists", "selected_equals"} else int if key in {"toggle_equals", "expand_equals"} else str
            if type(item[key]) is not expected_type or (expected_type is int and item[key] not in range(3 if key == "toggle_equals" else 4)):
                raise ValueError("Invalid postcondition value type")

    def verify(self, session, window, expectations, timeout_ms=500):
        self.validate_expectations(expectations)
        if type(timeout_ms) is not int or not 0 <= timeout_ms <= 10000:
            raise ValueError("Invalid verification timeout_ms")
        if any("visual" in rule for rule in expectations):
            self.service.snapshot(session, window, image=True)
            frame = self.service.frames[(session["id"], str(window["windowId"]))]
            if "path" not in frame:
                raise ValueError("Visual verification requires a local recorded window")
            from .neyvia_perception import image_projection
            visual = image_projection(Path(frame["path"]), self.directory / "visual", 0)
            text = "\n".join(row["text"] for row in visual["text"] if row["certainty"] == "observed")
            passed = all(rule["visual"]["text_contains"] in text for rule in expectations)
            # Hold the exact frame across extraction; slow model output cannot
            # verify pixels that have already changed underneath it.
            self.service.snapshot(session, window, image=True)
            latest = self.service.frames[(session["id"], str(window["windowId"]))]
            stable = frame["sha256"] == latest["sha256"]
            return {"status": "satisfied" if passed and stable else "unsatisfied", "stable": stable,
                    "source": "T18 image-to-CL", "frameSha256": frame["sha256"], "provenance": visual["provenance"]}
        before = None
        started = time.perf_counter()
        deadline = time.monotonic() + timeout_ms / 1000
        samples = 0
        while True:
            samples += 1
            current = self.service.target(session, {"window_id": int(window["windowId"]), "pid": window["pid"]})
            data = self.service.snapshot(session, current, image=False)["structuredContent"]
            checks = []
            for rule in expectations:
                item = rule.get("element", {})
                selector = item.get("selector", {})
                if not selector or set(selector) - {"role", "label", "label_contains", "automationId", "className"}:
                    raise ValueError("Unsupported postcondition selector")
                matches = [e for e in data["elements"] if not e["protected"] and all(
                    str(v).casefold() in str(e.get("label", "")).casefold() if k == "label_contains" else e.get(k) == v for k, v in selector.items())]
                predicates = {"value_equals": "value", "label_equals": "label", "enabled_equals": "enabled",
                              "selected_equals": "selected", "toggle_equals": "toggleState", "expand_equals": "expandState"}
                requested = set(item) - {"selector"}
                if len(requested) != 1 or not requested <= (set(predicates) | {"exists"}):
                    raise ValueError("Unsupported postcondition; no guessed success")
                key = next(iter(requested))
                if key == "exists":
                    observed, expected = bool(matches), item[key]
                else:
                    if len(matches) == 1:
                        fresh = self.service.native.request("inspectElements", {"windowId": str(window["windowId"]),
                            "elementIds": [matches[0]["nativeId"]]})["tree"][0]
                        observed_fields = ("value", "enabled", "selected", "toggleState", "expandState")
                        matches[0] = {**{field: value for field, value in matches[0].items() if field not in observed_fields},
                                      "label": fresh.get("name"),
                                      **{field: fresh[field] for field in observed_fields if field in fresh}}
                    observed = matches[0].get(predicates[key]) if len(matches) == 1 else None
                    expected = item[key]
                valid = key == "exists" or len(matches) == 1 and predicates[key] in matches[0]
                checks.append({"status": "satisfied" if valid and observed == expected else "unsatisfied" if valid else "unknown",
                               "observed": observed, "matches": len(matches)})
            satisfied = all(c["status"] == "satisfied" for c in checks)
            stable = checks == before
            if stable and satisfied or samples >= 2 and time.monotonic() >= deadline:
                break
            before = checks
            time.sleep(min(.01, max(0, deadline - time.monotonic())))
        return {"status": "satisfied" if stable and all(c["status"] == "satisfied" for c in checks) else "unsatisfied",
                "stable": stable, "samples": samples, "predicates": checks, "elapsed_ms": (time.perf_counter() - started) * 1000}

    def flow(self, session, window, steps):
        from .neyvia_cua import STEP
        from jsonschema import Draft202012Validator
        Draft202012Validator({"type": "array", "items": STEP, "minItems": 1, "maxItems": 16}).validate(steps)
        for step in steps:
            self.validate_expectations(step["expect"])
        from . import neyvia_manuals as manuals
        from .manual_versions import quarantine, promote
        from .manual_compiler import compile_procedure, run_compiled, compiled_index
        started = time.perf_counter()
        root = self.service.root / ".neyvia"
        appkey = self.key(window)
        chapter_name = "app-" + appkey
        flow_name = "flow-" + digest(steps)[:20]
        _, sha, manual = manuals.get_manual("computer-use", root)
        wrapper = SimpleNamespace(bus=SimpleNamespace(root=self.service.root))
        if self.registry is None:
            from .native_tools import NativeToolRegistry
            self.registry = NativeToolRegistry(self.service.root, nas_root=self.service.root / ".c1-local")
        inputs = {"sessionId": session["id"], "window_id": int(window["windowId"])}

        def dispatch(tool, arguments, action_id=""):
            if arguments.get("sessionId") != session["id"]:
                raise PermissionError("Learned flow cannot change session authority")
            if tool == "neyvia.cua.action":
                spec = copy.deepcopy(arguments["args"])
                spec.pop("window_id", None)
                selector = spec.pop("_selector")
                expect = spec.pop("_expect")
                return self.perform(session, self.service.target(session, inputs),
                    {"tool": arguments["tool"], "selector": selector, "args": spec, "expect": expect}, action_id)
            if tool == "neyvia.cua.verify":
                return self.verify(session, self.service.target(session, inputs), arguments["expect"])
            raise PermissionError("Learned flow is restricted to CUA action and verifier")

        chapter = manual["chapters"].get(chapter_name)
        if not chapter or flow_name not in chapter["procedures"]:
            # Only independently verified effects can turn the read-only draft
            # into a workspace revision. No extra training/replay actions here.
            outcomes = [self.perform(session, window, step) for step in steps]
            chapter = copy.deepcopy(chapter or self.chapter(window, self.drafts.get(appkey, {}).get("controls", [])))
            procedure = {"goal": "Replay the verified background flow", "inputs": chapter["state"]["window"]["inputs"], "steps": []}
            for index, step in enumerate(steps):
                name = flow_name + "-" + str(index)
                chapter["actions"][name] = {"tool": "neyvia.cua.action", "schema": "neyvia.cua.action",
                    "returns": {"type": "object"}, "pre": "Owner grant and fresh unique selector", "effect": "Verified background action", "reversible": step["tool"] in {"set_value", "type_text"}}
                checkargs = {**{k: {"$input": k} for k in inputs}, "expect": step["expect"]}
                chapter["checks"][name] = {"tool": "neyvia.cua.verify", "args": checkargs,
                                          "expect": {"path": "status", "op": "eq", "value": "satisfied"}}
                procedure["steps"].append({"action": name, "args": {"sessionId": {"$input": "sessionId"},
                    "tool": step["tool"], "args": {**step.get("args", {}), "window_id": {"$input": "window_id"},
                        "_selector": step["selector"], "_expect": step["expect"]}}, "save": "step" + str(index), "check": name})
            chapter["procedures"][flow_name] = procedure
            patch = quarantine(root, "computer-use", sha, "Verified first use of " + flow_name,
                {"appKey": appkey, "outcomes": outcomes}, [{"op": "add", "path": "/chapters/" + chapter_name, "value": chapter}])
            original = self.drafts.get(appkey, {})
            if original.get("status") == "quarantined" and original.get("baseSha256") == sha:
                original_path = root / "manual-patches" / (original["patchId"] + ".json")
                original_patch = json.loads(original_path.read_text(encoding="utf-8"))
                original_patch.update(operations=patch["operations"], observed=patch["observed"], note=patch["note"])
                atomic_write_json(original_path, original_patch)
                patch = original_patch
            evidence = self.directory / (flow_name + "-" + secrets.token_hex(8) + ".json")
            atomic_write_json(evidence, {"steps": steps, "outcomes": outcomes, "window": window})
            with manuals._LOCK, manuals.execution_lock(root):
                if manuals.get_manual("computer-use", root)[1] != sha:
                    raise ValueError("Manual changed during successful use; review the quarantined patch before promotion")
                promotion = promote(root, {"id": "computer-use", "patchId": patch["patchId"], "expectedSha256": sha,
                    "approved": True, "reviewer": "C1 host: unique selectors, independent checks, grants and preservation",
                    "evidence": [str(evidence)]}, sha, manual, self.registry)
            if appkey in self.drafts:
                self.drafts[appkey].update(status="promoted", promotedSha256=promotion["sha256"], manual=chapter)
                atomic_write_json(self.directory / (appkey + ".json"), self.drafts[appkey])
                atomic_write_text(self.directory / (appkey + ".cl"), manuals.render(chapter, manual["schemas"], layer="computer-use"))
            return {"ok": True, "status": "completed", "promotion": promotion, "outcomes": outcomes,
                    "flow": flow_name, "chapter": chapter_name, "compiled": False, "tokens": 0,
                    "elapsed_ms": (time.perf_counter() - started) * 1000}
        runargs = {"id": "computer-use", "chapter": chapter_name, "procedure": flow_name, "inputs": inputs}
        plans = [p for p in compiled_index(wrapper, {"id": "computer-use"})["scripts"]
                 if not p["stale"] and p["chapter"] == chapter_name and p["procedure"] == flow_name and p["inputSha256"] == digest(inputs)]
        output = run_compiled(wrapper, {"scriptId": plans[-1]["scriptId"], "inputs": inputs}, self.registry, dispatch) if plans else manuals.run(wrapper, runargs, self.registry, dispatch)
        compilation = None
        if output.get("ok") and not plans:
            try:
                compilation = compile_procedure(wrapper, {**runargs, "minRuns": 3}, self.registry)
            except ValueError as exc:
                if not str(exc).startswith("Compilation needs"):
                    raise
        return {**output, "compiled": bool(plans), "compilation": compilation, "flow": flow_name,
                "tokens": 0, "elapsed_ms": (time.perf_counter() - started) * 1000}
