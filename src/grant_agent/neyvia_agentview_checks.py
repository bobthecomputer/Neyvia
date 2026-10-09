"""Executable contracts of the agent view, run on a scratch workspace (neyvia.agentview.check).

Each area drives the production code (neyvia_agentview) with real pictures and files and
reports what it observed; manuals/cl/agent-view.cl binds these observations as checks and
procedures. The live journey (scripts/prove_agentview.py) proves the same paths against the
real driver, Obscura and the rendered UI.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path


def _picture(color=(240, 240, 240), box=None, size=(640, 400)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, color)
    if box:
        ImageDraw.Draw(image).rectangle(box, fill=(20, 90, 200))
    return image


class _Checks:
    def __init__(self, area):
        self.area, self.rows = area, []

    def check(self, identity, ok, **observed):
        # Observations travel in durable tool receipts: keep them plain JSON (tuples become lists).
        self.rows.append({"id": identity, "ok": bool(ok), "observed": json.loads(json.dumps(observed, default=str))})

    def result(self):
        return {"ok": all(row["ok"] for row in self.rows) and bool(self.rows), "area": self.area, "checks": self.rows}


def _stream(av, scratch, checks):
    import numpy as np
    a, b = np.asarray(_picture()), np.asarray(_picture(box=(70, 40, 129, 70)))
    grid = av.changed_tiles(a, b, 32)
    touched = sorted((int(r), int(c)) for r, c in zip(*np.nonzero(grid)))
    checks.check("tiles.only-touched", touched == [(r, c) for r in (1, 2) for c in (2, 3, 4)], tiles=touched)
    checks.check("tiles.merged", av.tile_rects(grid) == [(1, 2, 3, 5)], rects=av.tile_rects(grid))
    frames = av.SurfaceFrames()
    v1 = frames.push(_picture())
    same_pixels = frames.push(_picture())
    checks.check("frames.unchanged-adds-no-version", v1 == 1 and same_pixels is None and frames.delta(1)["kind"] == "same")
    full = frames.delta(0)
    v2 = frames.push(_picture(box=(300, 200, 340, 230)))
    delta = frames.delta(v1)
    area = sum(p["w"] * p["h"] for p in delta.get("patches", []))
    checks.check("frames.delta-is-small", delta["kind"] == "delta" and delta["base"] == v1 and delta["v"] == v2 and area < 640 * 400 * 0.05
                 and delta["bytes"] < full["bytes"], kind=delta["kind"], patchArea=area, deltaBytes=delta["bytes"], fullBytes=full["bytes"])
    checks.check("frames.unknown-version-gets-full", frames.delta(999)["kind"] == "full")
    frames.push(_picture(color=(10, 10, 10)))
    checks.check("frames.big-change-gets-full", frames.delta(v2)["kind"] == "full")
    big = av.SurfaceFrames()
    big.push(_picture(size=(2560, 1600)))
    checks.check("frames.fitted-width", big.latest.image.size == (av.MAX_FRAME_W, 800), size=list(big.latest.image.size))
    surface = av.Surface("t1", "browser", "browser", "tab-1", "Page")
    t0 = 1000.0
    surface.demand_until, surface.fps, surface.last_capture = t0 + av.DEMAND_S, 4.0, t0
    rate = [surface.capture_due(t0 + 0.2, True), surface.capture_due(t0 + 0.26, True)]
    surface.fps = 0.5
    bubble = [surface.capture_due(t0 + 1.5, True), surface.capture_due(t0 + 2.01, True)]
    hidden = [surface.capture_due(t0 + 60, False), surface.capture_due(t0 + av.IDLE_WATCH_S - 1, True), surface.capture_due(t0 + av.IDLE_WATCH_S + 0.1, True)]
    checks.check("throttle.viewer-rate", rate == [False, True] and bubble == [False, True], fourFps=rate, halfFps=bubble)
    native = av.Surface("w1", "app", "cua", ("s", 1), "Notepad")
    native.last_capture = t0
    checks.check("throttle.stops-when-unwatched", hidden == [False, False, True] and not native.capture_due(t0 + 600, True),
                 afterDemand=hidden, nativeUnwatched=native.capture_due(t0 + 600, True))
    view = av.AgentView(scratch, start=False)
    run = view.run_for({"app": "codex", "chatId": "check"})
    browser = run.surfaces["t1"] = av.Surface("t1", "browser", "browser", None, "Page")
    native = run.surfaces["w1"] = av.Surface("w1", "app", "cua", None, "App")
    browser.frames.push(_picture())
    native.frames.push(_picture())
    view.frame({"run": run.key, "surface": "t1", "fps": 50})
    view.frame({"run": run.key, "surface": "w1", "fps": 50})
    fast = (browser.fps, native.fps)
    view.frame({"run": run.key, "surface": "t1", "fps": 0.01})
    checks.check("throttle.fps-clamped", fast == (av.MAX_FPS, av.CUA_MAX_FPS) and browser.fps == av.MIN_FPS,
                 browserMax=fast[0], nativeMax=fast[1], floor=browser.fps)


def _timeline(av, scratch, checks, monkey):
    rows = [{"id": f"k{i}", "t": float(i), "bytes": 1000, "pinned": i == 137} for i in range(400)]
    drop = set(av.thin_keyframes(rows, max_count=100, max_bytes=10 ** 9))
    kept = [r for r in rows if r["id"] not in drop]
    gaps = [b["t"] - a["t"] for a, b in zip(kept, kept[1:])]
    checks.check("thin.count-and-protected", len(kept) == 100 and {"k0", "k399", "k137"} <= {r["id"] for r in kept}, kept=len(kept))
    checks.check("thin.even-coverage", max(gaps) <= 8, widestGapS=max(gaps))
    heavy = [{"id": f"k{i}", "t": float(i), "bytes": 50_000} for i in range(50)]
    dropped = av.thin_keyframes(heavy, max_count=1000, max_bytes=1_000_000)
    checks.check("thin.byte-budget", 50_000 * (50 - len(dropped)) <= 1_000_000, keptBytes=50_000 * (50 - len(dropped)))
    monkey(av, "MAX_KEYFRAMES", 12)
    view = av.AgentView(scratch, start=False)
    run = view.run_for({"app": "claude", "chatId": "bounds"})
    surface = run.surfaces["w1"] = av.Surface("w1", "app", "cua", None, "Notepad")
    for i in range(40):
        surface.frames.push(_picture(box=(i * 10, 10, i * 10 + 8, 30)))
        view.add_keyframe(run, surface, "change", pinned=(i == 5))
    files = sorted(p.name for p in run.directory.glob("k*.jpg"))
    ids = [k["id"] for k in run.keyframes]
    checks.check("disk.bounded", len(run.keyframes) == 12 and files == sorted(k["file"] for k in run.keyframes), keyframes=len(run.keyframes), files=len(files))
    checks.check("disk.protected", ids[0] == "k1" and ids[-1] == "k40" and "k6" in ids, first=ids[0], last=ids[-1])
    view.save(run, force=True)
    again = av.AgentView(scratch, start=False)
    checks.check("disk.survives-restart", [k["id"] for k in again.runs[run.key].keyframes] == ids)
    log = av.Run("x", {}, None)
    for i in range(av.MAX_ENTRIES + 300):
        log.entries.append({"n": i})
    checks.check("log.bounded", len(log.entries) == av.MAX_ENTRIES and log.entries[0]["n"] == 300, entries=len(log.entries))


class _ScratchLog:
    """The computer-use shared log's surface the view writes to (record, sessions, frames, snapshots)."""

    def __init__(self):
        self.lock, self.action_lock = threading.RLock(), threading.RLock()
        self.sequence = 10
        self.log, self.events = deque(maxlen=100), deque(maxlen=100)
        self.frames, self.snapshots = {}, {}
        self.sessions = {"s1": {"id": "s1", "owner": {"chatId": "chat-9", "app": "codex", "title": "Fix the invoice"}, "status": "active",
                                "control": "agent", "allow": [{"app": "C:/work/build/TaskApp.exe", "name": "taskapp", "exe": "C:/work/build/TaskApp.exe"}],
                                "windows": [{"window_id": 77, "app_name": "TaskApp", "title": "Task app", "bounds": {"x": 0, "y": 0, "width": 640, "height": 400}}],
                                "approvals": []}}

    def record(self, s, by, tool, args=None, outcome=None, *, text=None, **_):
        self.sequence += 1
        row = {"id": f"l-{self.sequence}", "seq": self.sequence, "sessionId": s["id"], "by": by, "tool": tool, "args": args or {}, "text": text}
        self.log.append(row)
        return row


def _feedback(av, scratch, checks):
    view = av.AgentView(scratch, start=False)
    cua = view.cua = _ScratchLog()
    s = cua.sessions["s1"]
    run = view.cua_session(s)
    checks.check("run.per-chat-and-built-app", run.key == "codex:chat-9" and run.surfaces["w77"].kind == "build", key=run.key)
    cua.frames[("s1", "77")] = {"metadata": {"width": 640, "height": 400}}
    cua.snapshots[("s1", "77")] = {"data": {"elements": [
        {"label": "Task input", "role": "Edit", "screenshot_frame": {"x": 100, "y": 80, "w": 300, "h": 30}},
        {"label": "Window", "role": "Window", "screenshot_frame": {"x": 0, "y": 0, "w": 640, "h": 400}}]}}
    surface = run.surfaces["w77"]
    v1 = surface.frames.push(_picture())
    view.cua_log(s, {"id": "l-act", "tool": "type_text", "by": "agent", "windowId": 77, "app": "TaskApp", "status": "ok", "args": {"text": "17"},
                     "element": {"label": "Task input", "role": "Edit", "frame": {"x": 100, "y": 80, "w": 300, "h": 30}},
                     "result": {"effect": "confirmed", "evidence": [{"kind": "value_readback", "detail": "17"}]}})
    action = run.entries[-1]
    checks.check("action.normalised-for-overlay", action["element"]["box"] == {"x": 0.15625, "y": 0.2, "w": 0.46875, "h": 0.075}
                 and action["readback"] == "17", box=action["element"]["box"])
    surface.frames.push(_picture(box=(100, 80, 140, 110)))
    row = view.feedback({"run": run.key, "surface": "w77", "v": v1, "action": "l-act", "point": {"x": 0.3, "y": 0.24}, "text": "Use 42, the total changed"})
    keyframe = next(k for k in run.keyframes if k["id"] == row["keyframe"])
    checks.check("feedback.bound-to-frame-seen", keyframe["v"] == v1 and keyframe["pinned"] and keyframe["reason"] == "feedback", v=keyframe["v"])
    checks.check("feedback.bound-to-action-and-element", row["action"] == "l-act" and (row["anchor"] or {}).get("label") == "Task input"
                 and 'Typed "17"' in row["message"], anchor=row["anchor"])
    queued = row["delivery"]["channel"] == "computer-use" and row["delivery"]["state"] == "queued" and cua.log[-1]["text"] == row["message"]
    s["_clientCursor"] = {"chat-9": cua.log[-1]["seq"]}
    view.check_cua_delivery(run)
    checks.check("feedback.reaches-agent-next-step", queued and row["delivery"]["state"] == "delivered", delivery=row["delivery"])
    web = view.run_for({"app": "claude", "chatId": "web-1"})
    page = web.surfaces["t1"] = av.Surface("t1", "build", "browser", None, "Shop")
    page.frames.push(_picture())
    note = view.feedback({"run": web.key, "surface": "t1", "text": "The total looks wrong"})
    other = view.take_browser_notes({"app": "codex", "chatId": "web-1"})
    mine = view.take_browser_notes({"app": "claude-code", "chatId": "web-1"})
    again = view.take_browser_notes({"app": "claude", "chatId": "web-1"})
    checks.check("feedback.browser-next-result-once", other == [] and mine == [note["message"]] and again == [] and note["delivery"]["state"] == "delivered")
    refused = []
    for bad in ({"run": run.key, "text": "  "}, {"run": run.key, "text": "hi", "point": {"x": 2, "y": 0}}):
        try:
            view.feedback(bad)
        except ValueError:
            refused.append(True)
    checks.check("feedback.refuses-empty-and-off-frame", refused == [True, True])


def self_check(root, area):
    from . import neyvia_agentview as av
    if area not in {"stream", "timeline", "feedback"}:
        raise ValueError("Choose stream, timeline or feedback")
    scratch = Path(root).resolve() / ".agent_control/agentview-check" / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    checks = _Checks(area)
    saved = {}

    def monkey(module, name, value):
        saved.setdefault(name, getattr(module, name))
        setattr(module, name, value)
    started = time.perf_counter()
    try:
        if area == "stream":
            _stream(av, scratch, checks)
        elif area == "timeline":
            _timeline(av, scratch, checks, monkey)
        else:
            _feedback(av, scratch, checks)
    except Exception as exc:  # noqa: BLE001 - a broken contract is an observation, reported as a failed check
        checks.check("raised", False, error=type(exc).__name__ + ": " + str(exc)[:300])
    finally:
        for name, value in saved.items():
            setattr(av, name, value)
        shutil.rmtree(scratch, ignore_errors=True)
    return {**checks.result(), "elapsedMs": round((time.perf_counter() - started) * 1000, 1)}


def call(workspace, name, args):
    root = workspace.bus.root
    if name == "agentview.check":
        return self_check(root, args.get("area"))
    if name == "agentview.state":
        from .neyvia_agentview import view_for
        value = view_for(root).list_runs()
        return {"ok": True, **value}
    raise ValueError("Unknown agent view tool")
