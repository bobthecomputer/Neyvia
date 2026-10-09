"""Injection-safe CL observations, immutable projections, and context aliases."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import re
import threading

from .parser import Action, BareWord, Handle, Quantity, Range

IDENTIFIERS = frozenset({"id", "handle", "revision", "modified", "expectedModified", "element_token",
    "window_id", "windowId", "browserId", "sessionId", "capture_id", "snapshot_id", "frameId", "runId",
    "actionId", "valueSha256", "sha256", "previousHandle", "diffHandle", "pid"})


class StaleHandleError(ValueError):
    pass


class HandleStore:
    """One store per agent context. State/receipt snapshots are immutable."""
    def __init__(self):
        self.values = {}
        self.keys = {}
        self.streams = {}
        self.elements = {}
        self.counts = {}
        self.lock = threading.RLock()

    def put(self, value, kind="h", *, stable=False):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        key = (kind, raw)
        with self.lock:
            if stable and key in self.keys:
                return self.keys[key]
            self.counts[kind] = self.counts.get(kind, 0) + 1
            alias = "@" + kind + str(self.counts[kind])
            self.values[alias] = deepcopy(value)
            if stable:
                self.keys[key] = alias
            return alias

    def begin(self, layer):
        with self.lock:
            self.streams[layer] = self.streams.get(layer, 0) + 1
            self.elements[layer] = {"valid": True, "aliases": {}}

    def invalidate(self, layer):
        if layer in self.elements:
            self.elements[layer]["valid"] = False

    def element(self, layer, value):
        row = self.elements.setdefault(layer, {"valid": True, "aliases": {}})
        # Globally increasing digit aliases prevent rebinding an old @0 to a new target.
        count = self.counts.get("element", -1) + 1
        self.counts["element"] = count
        alias = "@" + str(count)
        row["aliases"][alias] = deepcopy(value)
        self.values[alias] = {"layer": layer, "generation": self.streams.get(layer, 0), "value": deepcopy(value)}
        return alias

    def resolve(self, alias):
        alias = str(alias)
        with self.lock:
            if alias not in self.values:
                raise ValueError("Unknown context handle: " + alias)
            value = self.values[alias]
            if alias[1:].isdigit():
                layer = value["layer"]
                current = self.elements.get(layer, {})
                if not current.get("valid") or value["generation"] != self.streams.get(layer, 0):
                    raise StaleHandleError("Element belongs to an older observation")
                return deepcopy(value["value"])
            return deepcopy(value)

    def project(self, alias, path="", selected=None):
        value = self.resolve(alias)
        if path:
            for part in path.split("."):
                value = value[int(part)] if isinstance(value, list) else value[part]
        if selected is not None:
            if not isinstance(selected, Range):
                raise ValueError("Projection slice must be a CL range")
            value = value[int(selected.start or 0):int(selected.end) if selected.end is not None else None]
        return value


def encode_value(value):
    if isinstance(value, (Handle, BareWord)):
        return str(value)
    if isinstance(value, Quantity):
        return str(value.value) + value.unit
    if isinstance(value, Range):
        return (str(value.start) if value.start is not None else "") + ".." + (str(value.end) if value.end is not None else "")
    if isinstance(value, Action):
        values = [encode_value(item) for item in value.positional]
        values += [key + ":" + encode_value(item) for key, item in value.arguments.items()]
        return value.name + "(" + " ".join(values) + ")"
    if isinstance(value, dict):
        return "{" + " ".join((key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) else json.dumps(key)) + ":" + encode_value(item) for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + " ".join(encode_value(item) for item in value) + "]"
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for character in ("\u0085", "\u2028", "\u2029"):
        text = text.replace(character, "\\u" + format(ord(character), "04x"))
    return text


def _aliases(value, store, layer, key=""):
    if key in IDENTIFIERS and value is not None and not isinstance(value, (dict, list)):
        if key == "element_token":
            return Handle(store.element(layer, value))
        return Handle(store.put(value, "i", stable=True))
    if isinstance(value, dict):
        return {field: _aliases(item, store, layer, field) for field, item in value.items()}
    if isinstance(value, list):
        return [_aliases(item, store, layer) for item in value]
    return value


def render_state(layer, payload, *, store=None, budget=4000, full=False):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", layer):
        raise ValueError("Invalid layer name")
    store = store or HandleStore()
    store.begin(layer)
    alias = store.put(payload)
    header = [f"L {layer} v1 untrusted", f"S {layer} {alias}"]
    visible = _aliases(payload, store, layer)
    body = encode_value(visible)
    if not full and len(body) > budget:
        size = len(payload) if isinstance(payload, (dict, list, str)) else 1
        header[-1] += " #" + str(size)
    elif isinstance(visible, list):
        header += ["E " + encode_value(item) for item in visible]
    else:
        header.append("E " + body)
    return "\n".join(header) + "\n"


def render_delta(layer, delta, *, store):
    visible = []
    for row in delta:
        item = dict(row)
        key = str(item.get("path", "")).rsplit("/", 1)[-1]
        if "value" in item:
            item["value"] = _aliases(item["value"], store, layer, key)
        visible.append(item)
    text = "D +" + layer + " " + encode_value(visible) + "\n"
    if len(text) > 4000:
        return "D +" + layer + " " + store.put(delta) + " #" + str(len(delta)) + "\n"
    return text


def render_receipt(name, status, elapsed_ms, handle, checks=()):
    marks = "".join(" " + ("+" if passed is True else "-" if passed is False else "?") + key for key, passed in checks)
    return f"R {name} {status} {elapsed_ms}ms {handle}{marks}\n"
