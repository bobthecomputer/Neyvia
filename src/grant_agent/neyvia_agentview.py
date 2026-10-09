"""Agent view: watch and steer agents working on their own surfaces.

Agents drive apps on the private agent desktop (the C11 driver behind
neyvia_cua) and pages in Obscura (neyvia_browser). Paul never sees those real
windows. This module mirrors them into Neyvia as rendered frames:

* Live view: one run per agent chat, one surface per window/tab. Frames are
  captured only while someone watches (each frame request renews a short
  demand), at the rate the viewer asks for (0.2-5 fps), and only the regions
  that changed since the version the viewer holds are sent (JPEG tiles).
* Action overlay: the driver's "about to act" focus and every logged action,
  normalised to the frame (0-1) so the UI can outline the element and say it
  in plain words.
* Feedback: Paul clicks a frame or an action and writes a comment. It is
  bound to that frame version, keyframe and action, and reaches the agent
  through the existing channels: the running turn's steer when the chat has
  one, else the computer-use shared log the agent reads on its next driver
  call, else the next browser tool result.
* Time-lapse: each run keeps keyframes (after every action, on change, on
  feedback) and its action log, bounded in count and bytes. Thinning drops the
  keyframe whose loss costs the least time coverage, never a pinned one.

Routes (owner only, loopback, like /api/ui/cua):
  GET  /api/ui/agentview/runs
  GET  /api/ui/agentview/frame?run=&surface=&since=&fps=&after=
  GET  /api/ui/agentview/timeline?run=
  GET  /api/ui/agentview/keyframe?run=&id=
  POST /api/ui/agentview {op: runs|timeline|feedback, args}
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .durability import atomic_write_json

# ---- bounds -------------------------------------------------------------------------
MAX_FRAME_W = 1280          # live frames are fitted to this width
TILE = 32                   # changed-region grid, in live-frame pixels
DIFF_LEVEL = 12             # per-channel difference that counts as a change
FULL_FRACTION = 0.55        # past this share of changed tiles, send one full frame
RING = 6                    # frame versions kept per surface for deltas
MIN_FPS, MAX_FPS = 0.2, 5.0
AFTER_RETRIES = 20          # "after" keyframes wait up to ~10 s for a capture the driver admits
CUA_MAX_FPS = 1.5           # native captures share the driver's guard and capture lanes with the agent
DEMAND_S = 2.5              # a frame request keeps capture going this long
IDLE_WATCH_S = 12.0         # with nobody watching, a live run is sampled this often
LIVE_WINDOW_S = 90.0        # a run is "live" while it acted within this time
KEYFRAME_W = 960
KEYFRAME_QUALITY = 72
CHANGE_KEYFRAME_S = 8.0
MAX_KEYFRAMES = 240
MAX_KEYFRAME_BYTES = 24 * 1024 * 1024
MAX_ENTRIES = 1500
MAX_FEEDBACK_TEXT = 2000
MAX_RUNS_ON_DISK = 40
ACTION_TOOLS = frozenset("click double_click right_click type_text press_key hotkey scroll drag set_value invoke_menu launch_app".split())
AGENT_NAMES = {"codex": "Codex", "claude": "Claude Code", "claude-code": "Claude Code", "neyvia": "Neyvia", "opencode": "OpenCode"}

# The agent identity of a browser call (the CUA bridge binds its own). Callers
# that know which chat is acting set it; otherwise neyvia_cua.NATIVE_CLIENT.
AGENT_CLIENT: contextvars.ContextVar = contextvars.ContextVar("agentview_client", default=None)

TEXT = {"type": "string"}
DEFINITIONS = [
    ("agentview.state", "Read the agent runs mirrored to Paul: surfaces, last steps in plain words, his comments and their delivery, and the time-lapse bounds.", {}, []),
    ("agentview.check", "Run the agent view's executable contracts (stream, timeline or feedback) on a scratch workspace; returns each check's observation.",
     {"area": {"type": "string", "enum": ["stream", "timeline", "feedback"]}}, ["area"]),
]


class AgentViewContractError(RuntimeError):
    """A postcondition of the agent view failed (manuals/cl/agent-view.cl, proof contracts)."""


def contract(identity, ok):
    """Executable postconditions, checked on every real invocation; the id names the manual contract."""
    if not ok:
        raise AgentViewContractError("Agent view contract " + identity + " failed")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_key(key):
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key))[:60].strip("._") or "run"
    return slug + "-" + hashlib.sha256(str(key).encode()).hexdigest()[:10]


def run_key(client):
    client = client or {}
    app = str(client.get("app") or "agent")
    app = "claude" if app == "claude-code" else app
    return app + ":" + str(client.get("chatId") or "native")


# ---- pure frame helpers (tested) -------------------------------------------------------

def fit(image, max_w=MAX_FRAME_W):
    """RGB copy no wider than max_w, aspect kept."""
    from PIL import Image
    image = image.convert("RGB")
    if image.width > max_w:
        image = image.resize((max_w, max(1, round(image.height * max_w / image.width))), Image.LANCZOS)
    return image


def changed_tiles(previous, current, tile=TILE, level=DIFF_LEVEL):
    """Boolean grid (rows x cols): which tiles differ between two same-size RGB arrays."""
    import numpy as np
    if previous.shape != current.shape:
        raise ValueError("Frames differ in size")
    height, width = current.shape[:2]
    mask = (np.abs(previous.astype(np.int16) - current.astype(np.int16)) > level).any(axis=2)
    rows, cols = -(-height // tile), -(-width // tile)
    padded = np.zeros((rows * tile, cols * tile), dtype=bool)
    padded[:height, :width] = mask
    return padded.reshape(rows, tile, cols, tile).any(axis=(1, 3))


def tile_rects(grid):
    """Merge changed tiles into rectangles (tile units): horizontal runs, then equal runs stacked."""
    runs = []
    for r, row in enumerate(grid):
        c = 0
        cols = len(row)
        while c < cols:
            if row[c]:
                start = c
                while c < cols and row[c]:
                    c += 1
                runs.append([r, start, r + 1, c])
            else:
                c += 1
    merged = []
    open_by_span = {}
    for run in runs:
        r, c0, _, c1 = run
        above = open_by_span.get((c0, c1))
        if above is not None and above[2] == r:
            above[2] = r + 1
        else:
            merged.append(run)
            open_by_span[(c0, c1)] = run
    return [tuple(rect) for rect in merged]


def encode_jpeg(image, quality=82):
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buffer.getvalue()


def data_url(raw):
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


class Frame:
    __slots__ = ("v", "image", "array", "at", "t")

    def __init__(self, v, image, at):
        import numpy as np
        self.v, self.image, self.at, self.t = v, image, at, time.time()
        self.array = np.asarray(image)


class SurfaceFrames:
    """Recent versions of one surface; answers "what changed since version v"."""

    def __init__(self, ring=RING, tile=TILE):
        self.ring = deque(maxlen=ring)
        self.tile = tile
        self.v = 0
        self.lock = threading.Lock()

    @property
    def latest(self):
        return self.ring[-1] if self.ring else None

    def push(self, image, at=None):
        """Add a picture; returns the new version, or None when nothing visibly changed."""
        image = fit(image)
        with self.lock:
            last = self.latest
            if last is not None and last.image.size == image.size:
                import numpy as np
                current = np.asarray(image)
                if not changed_tiles(last.array, current, self.tile).any():
                    last.at = at or now_iso()
                    return None
            self.v += 1
            self.ring.append(Frame(self.v, image, at or now_iso()))
            return self.v

    def find(self, v):
        return next((frame for frame in self.ring if frame.v == v), None)

    def delta(self, since):
        answer = self._delta(since)
        contract("agentview.delta", delta_holds(answer, since, self.tile))
        return answer

    def _delta(self, since):
        with self.lock:
            current = self.latest
            if current is None:
                return {"kind": "none", "v": 0}
            width, height = current.image.size
            base = {"v": current.v, "w": width, "h": height, "at": current.at}
            if since and since == current.v:
                return {**base, "kind": "same", "patches": [], "bytes": 0}
            previous = self.find(since) if since else None
            if previous is not None and previous.image.size == current.image.size:
                grid = changed_tiles(previous.array, current.array, self.tile)
                share = float(grid.mean()) if grid.size else 1.0
                if share <= FULL_FRACTION:
                    patches, total = [], 0
                    for r0, c0, r1, c1 in tile_rects(grid):
                        x, y = c0 * self.tile, r0 * self.tile
                        w, h = min(width, c1 * self.tile) - x, min(height, r1 * self.tile) - y
                        raw = encode_jpeg(current.image.crop((x, y, x + w, y + h)))
                        total += len(raw)
                        patches.append({"x": x, "y": y, "w": w, "h": h, "src": data_url(raw)})
                    return {**base, "kind": "delta", "base": since, "patches": patches, "bytes": total, "changed": round(share, 4)}
            raw = encode_jpeg(current.image, 80)
            return {**base, "kind": "full", "patches": [{"x": 0, "y": 0, "w": width, "h": height, "src": data_url(raw)}], "bytes": len(raw), "changed": 1.0}


def delta_holds(answer, since, tile=TILE):
    """Same only for the version held; a delta only from that version, inside the frame and under the
    full-frame share; anything else one full frame."""
    kind = answer.get("kind")
    if kind == "none":
        return answer.get("v") == 0
    width, height, patches = answer.get("w") or 0, answer.get("h") or 0, answer.get("patches") or []
    inside = all(0 <= p["x"] and 0 <= p["y"] and p["w"] > 0 and p["h"] > 0 and p["x"] + p["w"] <= width and p["y"] + p["h"] <= height for p in patches)
    if kind == "same":
        return bool(since) and since == answer["v"] and not patches
    if kind == "delta":
        area = sum(p["w"] * p["h"] for p in patches)
        return answer.get("base") == since and since != answer["v"] and inside and area <= FULL_FRACTION * width * height + tile * tile * len(patches) * 2
    if kind == "full":
        return len(patches) == 1 and patches[0]["x"] == 0 and patches[0]["y"] == 0 and patches[0]["w"] == width and patches[0]["h"] == height
    return False


def thin_keyframes(keyframes, max_count=MAX_KEYFRAMES, max_bytes=MAX_KEYFRAME_BYTES):
    """Ids to drop so the list fits. Never the first, the last or a pinned one.

    Each step drops the keyframe whose neighbours are closest in time, i.e. the
    one whose loss leaves the smallest hole, so long runs keep even coverage.
    """
    rows = sorted(keyframes, key=lambda k: (k["t"], k["id"]))
    drop = []
    count = len(rows)
    total = sum(int(k.get("bytes", 0)) for k in rows)
    while (count > max_count or total > max_bytes) and len(rows) > 2:
        best, best_span = None, None
        for index in range(1, len(rows) - 1):
            if rows[index].get("pinned"):
                continue
            span = rows[index + 1]["t"] - rows[index - 1]["t"]
            if best_span is None or span < best_span:
                best, best_span = index, span
        if best is None:
            break
        gone = rows.pop(best)
        drop.append(gone["id"])
        count -= 1
        total -= int(gone.get("bytes", 0))
    return drop


CONTAINERS = frozenset({"window", "pane", "titlebar", "menubar", "document", "group", "main", "body", "html"})


def element_at(elements, x, y, key="screenshot_frame"):
    """Smallest element whose box holds the point (boxes as {x,y,w,h}); whole windows and panes don't name a spot."""
    best = None
    for element in elements or []:
        if str(element.get("role") or "").casefold() in CONTAINERS:
            continue
        box = element.get(key) or {}
        try:
            bx, by, bw, bh = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
        except (KeyError, TypeError, ValueError):
            continue
        if bx <= x <= bx + bw and by <= y <= by + bh and (best is None or bw * bh < best[0]):
            best = (bw * bh, element)
    return best[1] if best else None


def norm_box(box, width, height):
    if not box or not width or not height:
        return None
    try:
        return {"x": round(float(box["x"]) / width, 5), "y": round(float(box["y"]) / height, 5),
                "w": round(float(box["w"]) / width, 5), "h": round(float(box["h"]) / height, 5)}
    except (KeyError, TypeError, ValueError):
        return None


def describe(entry):
    """One plain line for the agent-facing feedback message (the UI has its own, richer one)."""
    say = entry.get("say") or {}
    label = (entry.get("element") or {}).get("label")
    target = f'"{label}"' if label else "the window"
    tool = entry.get("tool")
    if tool == "type_text":
        return f'Typed "{str(say.get("text", ""))[:60]}" into {target}'
    if tool == "set_value":
        return f'Set {target} to "{str(say.get("value", ""))[:60]}"'
    if tool in {"press_key", "hotkey"}:
        return "Pressed " + "+".join(say.get("keys") or [say.get("key") or "a key"])
    if tool == "fill":
        return f'Typed "{str(say.get("value", ""))[:60]}" into {target}'
    if tool == "navigate":
        return "Went to " + str(say.get("url") or "a page")
    return (tool or "acted").replace("_", " ").capitalize() + (" " + target if label else "")


# ---- runs ----------------------------------------------------------------------------

class Surface:
    def __init__(self, sid, kind, source, ref, label, app=None, title=None, url=None):
        self.id, self.kind, self.source, self.ref = sid, kind, source, ref
        self.label, self.app, self.title, self.url = label, app, title, url
        self.frames = SurfaceFrames()
        self.last_capture = 0.0
        self.demand_until = 0.0
        self.fps = 0.0
        self.unavailable = None
        self.capture_size = None  # (w, h) of the source capture, for normalising boxes
        self.last_sha = None
        self.last_keyframe_t = 0.0
        self.last_keyframe_v = 0

    def view(self):
        latest = self.frames.latest
        return {"id": self.id, "kind": self.kind, "source": self.source, "label": self.label, "app": self.app,
                "title": self.title, "url": self.url, "v": self.frames.v, "unavailable": self.unavailable,
                "w": latest.image.width if latest else None, "h": latest.image.height if latest else None,
                "frameAt": latest.at if latest else None}

    def capture_due(self, now, live):
        """When this surface should be captured: a viewer's rate, else a slow watch of live pages.

        Native windows are not watched without a viewer: their keyframes come after each action,
        and every extra capture would share the driver's guard with the agent."""
        if now < self.demand_until and self.fps > 0:
            return now - self.last_capture >= 1.0 / self.fps
        return live and self.source != "cua" and now - self.last_capture >= IDLE_WATCH_S


class Run:
    def __init__(self, key, agent, directory):
        self.key, self.agent = key, dict(agent)
        self.directory = directory
        self.surfaces = {}
        self.entries = deque(maxlen=MAX_ENTRIES)
        self.keyframes = []
        self.feedback = []
        self.focus = None
        self.n = 0
        self.kn = 0
        self.started_at = now_iso()
        self.last_t = time.time()
        self.status = "live"
        self.cua_session = None
        self.paused_reason = None
        self.dirty = True
        self.saved_t = 0.0
        self.pending_launch = None

    def next_n(self):
        self.n += 1
        return self.n

    def live(self, now=None):
        return self.status != "ended" and (now or time.time()) - self.last_t < LIVE_WINDOW_S

    def view(self, now=None):
        now = now or time.time()
        focus = self.focus if self.focus and now - self.focus["t"] < (8 if self.focus["phase"] == "about" else 3) else None
        status = self.status
        if status != "ended":
            status = "waiting" if self.paused_reason else "working" if now - self.last_t < 15 else "idle"
        return {"key": self.key, "agent": self.agent, "title": self.agent.get("title") or self.agent.get("name"),
                "status": status, "pausedReason": self.paused_reason, "startedAt": self.started_at,
                "lastAt": datetime.fromtimestamp(self.last_t, timezone.utc).isoformat(), "cuaSession": self.cua_session,
                "surfaces": [s.view() for s in self.surfaces.values()], "focus": focus,
                "recent": list(self.entries)[-12:],
                "counts": {"actions": sum(1 for e in self.entries if e["kind"] == "action"),
                           "keyframes": len(self.keyframes), "feedback": len(self.feedback),
                           "keyframeBytes": sum(k["bytes"] for k in self.keyframes)},
                "feedback": self.feedback[-20:],
                "lastKeyframe": self.keyframes[-1]["id"] if self.keyframes else None,
                "lastKeyframes": {k["surface"]: {"id": k["id"], "w": k["w"], "h": k["h"]} for k in self.keyframes}}

    def index(self):
        return {"key": self.key, "agent": self.agent, "startedAt": self.started_at, "lastT": self.last_t,
                "status": self.status, "n": self.n, "kn": self.kn, "entries": list(self.entries),
                "keyframes": self.keyframes, "feedback": self.feedback,
                "surfaces": [{k: v for k, v in s.view().items() if k in {"id", "kind", "source", "label", "app", "title", "url"}}
                             for s in self.surfaces.values()]}


class AgentView:
    def __init__(self, root, *, start=True):
        self.root = Path(root).resolve()
        self.directory = self.root / ".neyvia/agentview"
        self.lock = threading.RLock()
        self.runs = {}
        self.pending_keyframes = []  # (due, run key, surface id, reason, action id)
        self.browser_notes = {}      # run key -> [feedback ids] waiting for the next browser call
        self.cua = None
        self.cua_cursor = 0
        self.browser = None
        self.stopped = threading.Event()
        self.load()
        self.thread = None
        if start:
            self.thread = threading.Thread(target=self._pump, name="agentview-pump", daemon=True)
            self.thread.start()

    # -- persistence --
    def load(self):
        if not self.directory.is_dir():
            return
        for index in sorted(self.directory.glob("*/index.json")):
            try:
                data = json.loads(index.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run = Run(data["key"], data.get("agent") or {}, index.parent)
            run.started_at, run.last_t, run.status = data.get("startedAt") or run.started_at, float(data.get("lastT") or 0), "ended"
            run.n, run.kn = int(data.get("n") or 0), int(data.get("kn") or 0)
            run.entries.extend(data.get("entries") or [])
            run.keyframes = [k for k in data.get("keyframes") or [] if (index.parent / k["file"]).is_file()]
            run.feedback = data.get("feedback") or []
            for row in data.get("surfaces") or []:
                run.surfaces[row["id"]] = Surface(row["id"], row.get("kind", "app"), row.get("source", "cua"), None,
                                                  row.get("label") or row["id"], row.get("app"), row.get("title"), row.get("url"))
            run.dirty = False
            self.runs[run.key] = run

    def save(self, run, force=False):
        if not run.dirty or (not force and time.time() - run.saved_t < 2):
            return
        run.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run.directory / "index.json", run.index(), indent=None)
        run.dirty, run.saved_t = False, time.time()

    def prune_disk(self):
        ended = sorted((r for r in self.runs.values() if r.status == "ended"), key=lambda r: r.last_t)
        while len(self.runs) > MAX_RUNS_ON_DISK and ended:
            run = ended.pop(0)
            self.runs.pop(run.key, None)
            if run.directory.is_relative_to(self.directory):
                shutil.rmtree(run.directory, ignore_errors=True)

    def run_for(self, client, title=None):
        key = run_key(client)
        with self.lock:
            run = self.runs.get(key)
            if run is None:
                app = "claude" if (client or {}).get("app") == "claude-code" else str((client or {}).get("app") or "agent")
                agent = {"app": app, "name": AGENT_NAMES.get(app, app.capitalize() if app != "agent" else "Agent"),
                         "chatId": (client or {}).get("chatId"), "title": title or (client or {}).get("title")}
                run = Run(key, agent, self.directory / safe_key(key))
                self.runs[key] = run
                self.prune_disk()
            elif run.status == "ended":
                run.status = "live"
            if title and not run.agent.get("title"):
                run.agent["title"] = title
            return run

    def get_run(self, key):
        run = self.runs.get(str(key or ""))
        if run is None:
            raise ValueError("Unknown agent run")
        return run

    # -- recording --
    def add_entry(self, run, entry):
        with self.lock:
            entry = {"n": run.next_n(), "at": now_iso(), "t": time.time(), **entry}
            run.entries.append(entry)
            run.last_t = entry["t"]
            run.dirty = True
            return entry

    def schedule_keyframe(self, run, surface_id, reason, action=None, delay=0.35, attempt=0):
        with self.lock:
            self.pending_keyframes.append((time.time() + delay, run.key, surface_id, reason, action, attempt))

    def add_keyframe(self, run, surface, reason, action=None, frame=None, pinned=False):
        frame = frame or surface.frames.latest
        if frame is None:
            return None
        image = frame.image
        if image.width > KEYFRAME_W:
            from PIL import Image
            image = image.resize((KEYFRAME_W, max(1, round(image.height * KEYFRAME_W / image.width))), Image.LANCZOS)
        raw = encode_jpeg(image, KEYFRAME_QUALITY)
        with self.lock:
            run.kn += 1
            identity = "k" + str(run.kn)
            row = {"id": identity, "t": time.time(), "at": now_iso(), "surface": surface.id, "v": frame.v,
                   "w": image.width, "h": image.height, "bytes": len(raw), "reason": reason,
                   "action": action, "pinned": bool(pinned), "file": identity + ".jpg"}
            run.directory.mkdir(parents=True, exist_ok=True)
            (run.directory / row["file"]).write_bytes(raw)
            run.keyframes.append(row)
            surface.last_keyframe_t, surface.last_keyframe_v = row["t"], frame.v
            if action:
                for entry in reversed(run.entries):
                    if entry.get("id") == action:
                        entry["kf"] = identity
                        break
            self.enforce_bounds(run)
            run.dirty = True
            return row

    def enforce_bounds(self, run):
        before = sorted(run.keyframes, key=lambda k: (k["t"], k["id"]))
        drop = set(thin_keyframes(run.keyframes, MAX_KEYFRAMES, MAX_KEYFRAME_BYTES))
        if not drop:
            contract("agentview.bounds", len(run.keyframes) <= MAX_KEYFRAMES or all(k.get("pinned") for k in before[1:-1]))
            return []
        kept = []
        for row in run.keyframes:
            if row["id"] in drop:
                (run.directory / row["file"]).unlink(missing_ok=True)
            else:
                kept.append(row)
        run.keyframes = kept
        protected = {before[0]["id"], before[-1]["id"], *(k["id"] for k in before if k.get("pinned"))}
        within = len(kept) <= MAX_KEYFRAMES and sum(k["bytes"] for k in kept) <= MAX_KEYFRAME_BYTES
        contract("agentview.bounds", protected <= {k["id"] for k in kept}
                 and (within or all(k["id"] in protected for k in kept))
                 and not any((run.directory / (identity + ".jpg")).exists() for identity in drop))
        return sorted(drop)

    # -- frames --
    def accept_frame(self, run, surface, raw, size=None):
        sha = hashlib.sha256(raw).hexdigest()
        surface.last_capture = time.time()
        if sha == surface.last_sha:
            return None
        surface.last_sha = sha
        from PIL import Image
        picture = Image.open(io.BytesIO(raw))
        picture.load()
        surface.capture_size = size if size and all(size) else picture.size
        surface.unavailable = None
        version = surface.frames.push(picture)
        if version is not None:
            first = not run.keyframes or not any(k["surface"] == surface.id for k in run.keyframes)
            if first or time.time() - surface.last_keyframe_t >= CHANGE_KEYFRAME_S:
                self.add_keyframe(run, surface, "start" if first else "change")
        return version

    def capture(self, run, surface, force=False):
        """True when the surface now holds a frame taken for this request."""
        try:
            if surface.source == "cua":
                return self._capture_cua(run, surface, force)
            if surface.source == "browser":
                self._capture_browser(run, surface)
                return True
        except Exception as exc:  # noqa: BLE001 - shown as "unavailable", never raised into the agent's path
            surface.last_capture = time.time()
            surface.unavailable = str(exc)[:200] or type(exc).__name__
        return False

    def _capture_cua(self, run, surface, force=False):
        service = self.cua
        sid, wid = surface.ref
        key = (sid, str(wid))
        current = service.frames.get(key) or {}
        # A capture the agent's own step (or the preview) just made is reused; otherwise take one.
        age = time.time() - _epoch((current.get("metadata") or {}).get("at")) if current.get("raw") else None
        fresh_enough = current.get("raw") and (current.get("sha256") != surface.last_sha or age < 1.0 / max(surface.fps, MIN_FPS))
        if force or not fresh_enough:
            # The agent always goes first: a live-view capture never waits behind (or queues ahead of)
            # an action; it skips this tick when the driver is busy. Keyframes after an action wait briefly.
            if not service.action_lock.acquire(timeout=2.0 if force else 0):
                surface.last_capture = time.time()
                return False
            try:
                service.request("capture", {"sessionId": sid, "windowId": wid}, owner=True)
            finally:
                service.action_lock.release()
            current = service.frames.get(key) or {}
        if not current.get("raw"):
            raise RuntimeError(current.get("metadata", {}).get("unavailable") or "capture_unavailable")
        meta = current.get("metadata") or {}
        self.accept_frame(run, surface, current["raw"], (meta.get("width"), meta.get("height")))
        return True

    def _capture_browser(self, run, surface):
        service = self.browser
        tab_id = surface.ref
        with service.lock:
            tab = next((t for t in service.state["tabs"] if t["id"] == tab_id), None)
            if tab is None:
                raise RuntimeError("closed")
            shot = service.run_headless(tab["profileId"], "capture", tab_id)
        self.accept_frame(run, surface, shot["image"], (shot.get("width"), shot.get("height")))

    def frame(self, args):
        run = self.get_run(args.get("run"))
        surface = run.surfaces.get(str(args.get("surface") or "")) or next(iter(run.surfaces.values()), None)
        if surface is None:
            after = int(args.get("after") or 0) if str(args.get("after") or "0").isdigit() else 0
            with self.lock:
                view = run.view()
                return {"kind": "none", "v": 0, "run": {k: v for k, v in view.items() if k != "recent"},
                        "entries": [e for e in run.entries if e["n"] > after][-50:]}
        try:
            fps = float(args.get("fps") or 2)
        except (TypeError, ValueError):
            fps = 2.0
        fps = min(CUA_MAX_FPS if surface.source == "cua" else MAX_FPS, max(MIN_FPS, fps))
        now = time.time()
        surface.demand_until = now + DEMAND_S
        surface.fps = fps
        contract("agentview.demand", MIN_FPS <= surface.fps <= (CUA_MAX_FPS if surface.source == "cua" else MAX_FPS)
                 and abs(surface.demand_until - now - DEMAND_S) < 1e-6)
        if surface.frames.latest is None and surface.ref is not None and run.status != "ended":
            self.capture(run, surface)
        try:
            since = int(args.get("since") or 0)
            after = int(args.get("after") or 0)
        except (TypeError, ValueError):
            since = after = 0
        delta = surface.frames.delta(since)
        with self.lock:
            entries = [e for e in run.entries if e["n"] > after][-50:]
            view = run.view(now)
        return {**delta, "surface": surface.id, "unavailable": surface.unavailable, "run": {k: v for k, v in view.items() if k != "recent"},
                "entries": entries}

    # -- views --
    def list_runs(self):
        with self.lock:
            now = time.time()
            rows = [run.view(now) for run in self.runs.values()]
        rows.sort(key=lambda r: (r["status"] == "ended", -(datetime.fromisoformat(r["lastAt"]).timestamp())))
        return {"runs": rows, "bounds": {"keyframes": MAX_KEYFRAMES, "keyframeBytes": MAX_KEYFRAME_BYTES, "entries": MAX_ENTRIES},
                "agentDesktop": self.desktop_health()}

    def desktop_health(self):
        """The agent desktop's zero-disturbance guard, as last observed (no new sample is taken)."""
        guard = getattr(getattr(self.cua, "native", None), "guard", None)
        if guard is None:
            return None
        try:
            receipt = guard._receipt()
            contained = []
            for row in receipt.get("containment_log", [])[-6:]:
                name = None
                try:
                    import psutil
                    process = psutil.Process(int(row.get("pid")))
                    name = " ".join(process.cmdline())[:160] or process.name()
                except Exception:  # noqa: BLE001 - the process may be gone
                    pass
                contained.append({**row, "process": name})
            return {"ok": receipt["ok"], "violations": receipt["violations"], "newVisibleWindows": receipt["new_visible_windows"],
                    "foregroundChanges": receipt["foreground_changes"], "contained": contained}
        except Exception:  # noqa: BLE001
            return None

    def timeline(self, args):
        run = self.get_run(args.get("run"))
        with self.lock:
            return {"key": run.key, "agent": run.agent, "startedAt": run.started_at, "status": run.view()["status"],
                    "entries": list(run.entries), "keyframes": run.keyframes, "feedback": run.feedback,
                    "surfaces": [s.view() for s in run.surfaces.values()],
                    "bounds": {"keyframes": MAX_KEYFRAMES, "keyframeBytes": MAX_KEYFRAME_BYTES, "entries": MAX_ENTRIES}}

    def keyframe_path(self, args):
        run = self.get_run(args.get("run"))
        row = next((k for k in run.keyframes if k["id"] == args.get("id")), None)
        if row is None:
            raise ValueError("Keyframe expired")
        return run.directory / row["file"]

    # -- feedback --
    def feedback(self, args):
        run = self.get_run(args.get("run"))
        text = str(args.get("text") or "").strip()
        if not 1 <= len(text) <= MAX_FEEDBACK_TEXT:
            raise ValueError(f"Write between 1 and {MAX_FEEDBACK_TEXT} characters")
        surface = run.surfaces.get(str(args.get("surface") or "")) or next(iter(run.surfaces.values()), None)
        point = args.get("point")
        if point is not None:
            if not isinstance(point, dict) or not all(isinstance(point.get(k), (int, float)) and 0 <= point[k] <= 1 for k in ("x", "y")):
                raise ValueError("point must be {x, y} between 0 and 1")
            point = {"x": round(float(point["x"]), 4), "y": round(float(point["y"]), 4)}
        action_id = args.get("action") or None
        action = None
        if action_id:
            action = next((e for e in run.entries if e.get("id") == action_id), None)
            if action is None:
                raise ValueError("That action is no longer in the log")
        keyframe_id = args.get("keyframe") or None
        frame_v = args.get("v")
        with self.lock:
            # The exact picture Paul commented on: the frame version he held, an existing keyframe, or the latest.
            keyframe = next((k for k in run.keyframes if k["id"] == keyframe_id), None) if keyframe_id else None
            if keyframe is not None:
                keyframe["pinned"] = True
            elif surface is not None:
                frame = surface.frames.find(int(frame_v)) if frame_v else None
                keyframe = self.add_keyframe(run, surface, "feedback", action_id, frame=frame, pinned=True)
        anchor = self.anchor(run, surface, point)
        when = keyframe["at"] if keyframe else now_iso()
        parts = [f'Feedback from Paul on your screen ({surface.label if surface else "your run"}, frame at {when[11:19]} UTC): "{text}"']
        if anchor:
            parts.append(f'He pointed at {anchor["describe"]}.')
        elif point:
            parts.append(f'He pointed at x {round(point["x"] * 100)}%, y {round(point["y"] * 100)}% of the frame.')
        if action:
            parts.append(f'It is about your action: {describe(action)} ({action.get("at", "")[11:19]} UTC).')
        else:
            # Not bound to a step: say which step the picture followed, as context only.
            seen = keyframe["t"] if keyframe else time.time()
            latest = next((e for e in reversed(run.entries) if e.get("kind") == "action" and e.get("t", 0) <= seen
                           and (surface is None or e.get("surface") == surface.id)), None)
            if latest:
                parts.append(f'Your latest step before that picture: {describe(latest)}.')
        message = " ".join(parts)
        row = {"id": "f-" + secrets.token_hex(6), "kind": "feedback", "text": text, "surface": surface.id if surface else None,
               "v": keyframe["v"] if keyframe else frame_v, "keyframe": keyframe["id"] if keyframe else None,
               "action": action_id, "point": point, "anchor": anchor, "message": message, "at": now_iso(), "t": time.time()}
        row["delivery"] = self.deliver(run, row)
        bound = next((k for k in run.keyframes if k["id"] == row["keyframe"]), None) if row["keyframe"] else None
        contract("agentview.feedback", (surface is None or (bound is not None and bound["pinned"]
                                        and (keyframe_id or not frame_v or not surface.frames.find(int(frame_v)) or bound["v"] == int(frame_v))))
                 and row["action"] == action_id and row["delivery"]["channel"] in {"steer", "computer-use", "browser"}
                 and row["text"] in row["message"])
        with self.lock:
            run.feedback.append(row)
            self.add_entry(run, {"kind": "feedback", "id": row["id"], "by": "paul", "text": text, "surface": row["surface"],
                                 "action": action_id, "kf": row["keyframe"], "point": point})
            run.dirty = True
        self.save(run, force=True)
        return row

    def anchor(self, run, surface, point):
        if surface is None or point is None:
            return None
        try:
            if surface.source == "cua" and self.cua is not None:
                sid, wid = surface.ref
                snap = self.cua.snapshots.get((sid, str(wid))) or {}
                meta = (self.cua.frames.get((sid, str(wid))) or {}).get("metadata") or {}
                width, height = meta.get("width") or 0, meta.get("height") or 0
                # Observed controls carry screen bounds; place them on the capture like the driver does.
                origin, scale = (snap.get("window") or {}).get("bounds") or {}, meta.get("scale") or 1
                elements = []
                for e in snap.get("data", {}).get("elements") or []:
                    frame, bounds = e.get("screenshot_frame"), e.get("frame") or {}
                    if not frame and all(k in bounds for k in ("x", "y", "width", "height")) and "x" in origin:
                        frame = {"x": (bounds["x"] - origin["x"]) * scale, "y": (bounds["y"] - origin["y"]) * scale,
                                 "w": bounds["width"] * scale, "h": bounds["height"] * scale}
                    if frame:
                        elements.append({**e, "screenshot_frame": frame})
                element = element_at(elements, point["x"] * width, point["y"] * height)
                if element:
                    return {"label": element.get("label"), "role": element.get("role"),
                            "box": norm_box(element.get("screenshot_frame"), width, height),
                            "describe": " ".join(filter(None, [f'"{element.get("label")}"' if element.get("label") else None, (element.get("role") or "element").lower()]))}
            if surface.source == "browser" and self.browser is not None and surface.capture_size:
                width, height = surface.capture_size
                projection = self.browser.projections.get(surface.ref) or {}
                element = element_at(projection.get("elements"), point["x"] * width, point["y"] * height, "bounds")
                if element and not element.get("secret"):
                    name = str(element.get("name") or "").strip()[:80]
                    return {"label": name, "role": element.get("role"), "box": norm_box(element.get("bounds"), width, height),
                            "describe": " ".join(filter(None, [f'"{name}"' if name else None, element.get("role") or "element"]))}
        except (KeyError, TypeError, ValueError):
            return None
        return None

    def deliver(self, run, row):
        """Steer the running turn if the chat has one; else the computer-use log; else the next browser result."""
        chat = run.agent.get("chatId")
        try:
            from .connected_sessions import broker as connected
            broker = connected._BROKERS.get(os.path.normcase(str(self.root)))
            if broker is not None and chat:
                with broker._lock:
                    live = next((l for l in broker._live.values() if l.data.get("sessionId") == chat
                                 and l.data.get("state") in connected.ACTIVE_STATES and l.data.get("canSteer")), None)
                    run_id = live.data["runId"] if live else None
                if run_id:
                    broker.steer(run_id, row["message"], {})
                    return {"channel": "steer", "state": "delivered", "at": now_iso(), "detail": "Added to the running turn"}
        except Exception as exc:  # noqa: BLE001 - fall back to the agent's next tool call
            row["steerError"] = str(exc)[:200]
        if run.cua_session and self.cua is not None:
            service = self.cua
            s = service.sessions.get(run.cua_session)
            if s is not None and s.get("status") != "ended":
                logged = service.record(s, "paul", "feedback", {"text": row["text"]}, text=row["message"])
                return {"channel": "computer-use", "state": "queued", "seq": logged["seq"], "at": now_iso(),
                        "detail": "The agent reads it with its next computer-use step"}
        with self.lock:
            self.browser_notes.setdefault(run.key, []).append(row["id"])
        return {"channel": "browser", "state": "queued", "at": now_iso(), "detail": "The agent reads it with its next browser step"}

    def mark_delivered(self, run, row, how):
        row["delivery"] = {**row["delivery"], "state": "delivered", "deliveredAt": now_iso(), "detail": how}
        run.dirty = True

    def check_cua_delivery(self, run):
        if not run.cua_session or self.cua is None:
            return
        s = self.cua.sessions.get(run.cua_session)
        if s is None:
            return
        cursors = s.get("_clientCursor") or {}
        chat = run.agent.get("chatId")
        cursor = max([v for k, v in cursors.items() if k == chat] or [0])
        for row in run.feedback:
            delivery = row.get("delivery") or {}
            if delivery.get("channel") == "computer-use" and delivery.get("state") == "queued" and cursor >= delivery.get("seq", 1 << 60):
                self.mark_delivered(run, row, "The agent read it with its next computer-use step")

    def take_browser_notes(self, client):
        """Feedback waiting for this browser agent, as plain messages, marked delivered."""
        key = run_key(client)
        with self.lock:
            ids = self.browser_notes.pop(key, [])
            run = self.runs.get(key)
            if not ids or run is None:
                return []
            rows = [row for row in run.feedback if row["id"] in ids]
            for row in rows:
                self.mark_delivered(run, row, "Attached to the agent's next browser result")
            return [row["message"] for row in rows]

    # -- sources: computer use --
    def attach_cua(self):
        from . import neyvia_cua
        service = neyvia_cua._SERVICES.get(str(self.root))
        if service is None or service is self.cua:
            return
        self.cua, self.cua_cursor = service, 0
        for s in list(service.sessions.values()):
            # Ended sessions were already filed (and kept) by this view; only live ones are mirrored again.
            if s.get("_ephemeral") or s.get("status") == "ended":
                continue
            self.cua_session(s)
            rows = [r for r in list(service.log) if r.get("sessionId") == s["id"]][-200:]
            for row in rows:
                self.cua_log(s, row, backfill=True)
        self.cua_cursor = service.sequence

    def cua_session(self, s):
        if s.get("_ephemeral"):
            return None
        owner = s.get("owner") or {}
        run = self.run_for(owner, owner.get("title"))
        with self.lock:
            run.cua_session = s["id"]
            run.paused_reason = s.get("pausedReason") if s.get("control") == "paul" and s.get("status") != "ended" else None
            if s.get("approvals"):
                run.paused_reason = "approval"
            for w in s.get("windows") or []:
                bounds = w.get("bounds") or {}
                if not w.get("title") or bounds.get("width", 0) < 160 or bounds.get("height", 0) < 100:
                    continue  # helper and tooltip windows are not surfaces anyone watches
                self.cua_surface(run, s, w["window_id"], w.get("app_name"), w.get("title"))
            if s.get("status") == "ended" and all(sr.source == "cua" for sr in run.surfaces.values()):
                run.status = "ended"
        return run

    def cua_surface(self, run, s, window_id, app=None, title=None):
        """The surface of one native window, created the first time the run lists or acts on it."""
        sid = "w" + str(window_id)
        grants = {str(a.get("name") or "").casefold(): a for a in s.get("allow") or []}
        grant = grants.get(str(app or "").casefold()) or {}
        exe = str(grant.get("exe") or grant.get("app") or "")
        # Apps installed with Windows or in Program Files are "apps"; anything else it launched is one it is building.
        system = re.match(r"^[a-z]:[\\/](windows|program files)", exe.casefold()) or not re.search(r"[\\/]", exe)
        kind = "app" if system else "build"
        with self.lock:
            surface = run.surfaces.get(sid)
            if surface is None:
                surface = run.surfaces[sid] = Surface(sid, kind, "cua", (s["id"], int(window_id)), app or "App", app, title)
                run.dirty = True
            surface.ref, surface.kind = (s["id"], int(window_id)), kind
            if title:
                surface.title = title
        return surface

    def cua_log(self, s, row, backfill=False):
        if s.get("_ephemeral"):
            return
        run = self.cua_session(s)
        tool = row.get("tool")
        if tool in {"feedback"}:
            return
        wid = row.get("windowId")
        surface = self.cua_surface(run, s, wid, row.get("app")) if wid is not None else None
        meta = (self.cua.frames.get((s["id"], str(wid))) or {}).get("metadata") or {} if self.cua and wid is not None else {}
        element = row.get("element") or None
        args = row.get("args") or {}
        result = row.get("result") or {}
        readback = next((e.get("detail") for e in result.get("evidence") or [] if e.get("kind") == "value_readback"), None)
        entry = {"id": row.get("id"), "kind": "action" if tool in ACTION_TOOLS else "note" if tool == "note" else "control",
                 "by": "paul" if row.get("by") == "paul" else row.get("by"), "tool": tool, "app": row.get("app"),
                 "surface": surface.id if surface else None, "status": row.get("status"),
                 "effect": result.get("effect"), "summary": str(row.get("text") or "")[:300], "readback": str(readback)[:200] if readback else None,
                 "element": {"label": element.get("label"), "role": element.get("role"),
                             "box": norm_box(element.get("frame"), meta.get("width"), meta.get("height"))} if element else None,
                 "say": {k: (str(args[k])[:200] if isinstance(args[k], str) else args[k]) for k in ("text", "key", "keys", "modifiers", "value", "direction", "amount", "name", "path") if k in args},
                 "point": {"x": round(args["x"] / meta["width"], 4), "y": round(args["y"] / meta["height"], 4)}
                 if isinstance(args.get("x"), (int, float)) and meta.get("width") and meta.get("height") else None,
                 "ms": row.get("ms")}
        if tool == "launch_app":
            entry["say"]["name"] = Path(str(args.get("path") or args.get("name") or "")).stem
        if backfill:
            with self.lock:
                if any(e.get("id") == entry["id"] for e in run.entries):
                    return
                entry = {"n": run.next_n(), "at": row.get("at") or now_iso(), "t": _epoch(row.get("at")), **entry}
                run.entries.append(entry)
                run.last_t = max(run.last_t, entry["t"]) if run.status != "ended" else run.last_t
                run.dirty = True
            return
        self.add_entry(run, entry)
        if entry["kind"] == "action" and surface is not None:
            self.schedule_keyframe(run, surface.id, "after", entry["id"])
        elif entry["kind"] == "action" and tool == "launch_app":
            run.pending_launch = entry["id"]

    def cua_focus(self, s, data):
        if s.get("_ephemeral"):
            return
        run = self.cua_session(s)
        wid = data.get("windowId")
        meta = (self.cua.frames.get((s["id"], str(wid))) or {}).get("metadata") or {}
        element = data.get("element") or None
        point = data.get("point")
        with self.lock:
            run.focus = {"phase": data.get("phase"), "by": data.get("by"), "tool": data.get("tool"), "surface": "w" + str(wid),
                         "say": data.get("say") or {}, "t": time.time(), "at": now_iso(),
                         "element": {"label": element.get("label"), "role": element.get("role"),
                                     "box": norm_box(element.get("frame"), meta.get("width"), meta.get("height"))} if element else None,
                         "point": {"x": round(point["x"] / meta["width"], 4), "y": round(point["y"] / meta["height"], 4)}
                         if point and meta.get("width") and meta.get("height") else None}
            if data.get("phase") == "about":
                run.last_t = time.time()

    def poll_cua(self):
        self.attach_cua()
        service = self.cua
        if service is None:
            return
        events = [e for e in list(service.events) if e["cursor"] > self.cua_cursor]
        for event in events:
            self.cua_cursor = max(self.cua_cursor, event["cursor"])
            s = service.sessions.get(event.get("sessionId"))
            if s is None:
                continue
            try:
                if event["type"] == "session":
                    run = self.cua_session(s)
                    pending = run.pending_launch
                    if pending and run.surfaces:
                        for surface in run.surfaces.values():
                            self.schedule_keyframe(run, surface.id, "after", pending, delay=0.8)
                        run.pending_launch = None
                elif event["type"] == "log":
                    self.cua_log(s, event["data"])
                elif event["type"] == "focus":
                    self.cua_focus(s, event["data"])
            except Exception:  # noqa: BLE001 - one malformed event must not stop the mirror
                continue
        for run in list(self.runs.values()):
            self.check_cua_delivery(run)

    # -- sources: Obscura --
    def browser_event(self, service, tab, phase, op, args=None, element=None, outcome=None, client=None):
        """Called by neyvia_browser around Obscura operations (agent or owner)."""
        if tab.get("engine") != "obscura":
            return
        self.browser = service
        if client is None:
            client = AGENT_CLIENT.get()
        if client is None:
            from .neyvia_cua import NATIVE_CLIENT
            client = NATIVE_CLIENT.get()
        client = client or {"app": "agent", "chatId": "obscura", "title": "Browser agent"}
        run = self.run_for(client, client.get("title"))
        sid = "t" + str(tab["id"])
        host = urlsplit(str(tab.get("url") or "")).hostname or ""
        kind = "build" if host in {"localhost", "127.0.0.1", "::1"} else "browser"
        with self.lock:
            surface = run.surfaces.get(sid)
            if surface is None:
                surface = run.surfaces[sid] = Surface(sid, kind, "browser", tab["id"], tab.get("title") or host or "Page",
                                                      "Obscura", tab.get("title"), tab.get("url"))
                run.dirty = True
            surface.kind, surface.url, surface.title = kind, tab.get("url"), tab.get("title")
            surface.label = tab.get("title") or host or surface.label
        args = args or {}
        size = surface.capture_size
        box = norm_box((element or {}).get("bounds"), *(size or (0, 0))) if element else None
        say = {"value": str(args["value"])[:200]} if args.get("value") is not None and not (element or {}).get("secret") else {}
        if op in {"open", "navigate"}:
            say["url"] = args.get("url") or tab.get("url")
        tool = args.get("action") if op == "action" else op
        named = {"label": str((element or {}).get("name") or "").strip()[:80], "role": (element or {}).get("role"), "box": box,
                 "bounds": (element or {}).get("bounds") if isinstance((element or {}).get("bounds"), dict) else None} if element else None
        if phase == "about":
            with self.lock:
                run.focus = {"phase": "about", "by": "agent", "tool": tool, "surface": sid, "say": say, "t": time.time(),
                             "at": now_iso(), "element": named, "point": None}
                run.last_t = time.time()
            return
        ok = bool((outcome or {}).get("ok", True))
        entry = self.add_entry(run, {"id": "b-" + secrets.token_hex(6), "kind": "action", "by": "agent", "tool": tool, "app": "Obscura",
                                     "surface": sid, "status": "ok" if ok else "failed",
                                     "effect": "confirmed" if ok and op == "action" else None,
                                     "summary": ("Page changed: " + str((outcome or {}).get("title") or "")) if (outcome or {}).get("navigationObserved") else "",
                                     "element": named, "say": say, "point": None, "host": host})
        with self.lock:
            if run.focus and run.focus.get("surface") == sid:
                run.focus = {**run.focus, "phase": "done", "t": time.time()}
        self.schedule_keyframe(run, sid, "after", entry["id"], delay=0.1)

    # -- pump --
    def _pump(self):
        while not self.stopped.wait(0.05):
            try:
                self.step()
            except Exception:  # noqa: BLE001 - keep mirroring
                time.sleep(0.5)

    def step(self, now=None):
        now = now or time.time()
        self.poll_cua()
        if self.browser is None:
            from . import neyvia_browser
            self.browser = neyvia_browser._SERVICES.get(str(self.root))
        due = []
        with self.lock:
            keep = []
            for item in self.pending_keyframes:
                (due if item[0] <= now else keep).append(item)
            self.pending_keyframes = keep
        for _, key, surface_id, reason, action, attempt in due:
            run = self.runs.get(key)
            surface = run and run.surfaces.get(surface_id)
            if surface is None or surface.ref is None:
                continue
            if not self.capture(run, surface, force=True) and attempt < AFTER_RETRIES:
                # The driver is still busy (often the action's own check). An
                # "after" keyframe must show the state after the action, not
                # the last frame from before it, so wait for a fresh capture.
                self.schedule_keyframe(run, surface_id, reason, action, delay=0.5, attempt=attempt + 1)
                continue
            if surface.frames.latest is not None:
                self.add_keyframe(run, surface, reason, action)
        for run in list(self.runs.values()):
            live = run.live(now)
            for surface in list(run.surfaces.values()):
                if surface.ref is not None and run.status != "ended" and surface.capture_due(now, live):
                    self.capture(run, surface)
            self.save(run)

    def close(self):
        self.stopped.set()
        for run in list(self.runs.values()):
            self.save(run, force=True)


def _epoch(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return time.time()


_VIEWS, _LOCK = {}, threading.Lock()


def view_for(root, *, start=True):
    key = str(Path(root).resolve())
    with _LOCK:
        if key not in _VIEWS:
            _VIEWS[key] = AgentView(root, start=start)
        return _VIEWS[key]


def existing(root):
    return _VIEWS.get(str(Path(root).resolve()))


def browser_event(service, tab, phase, op, args=None, element=None, outcome=None):
    """Hook for neyvia_browser; never lets the mirror break a browser operation."""
    try:
        view_for(service.root).browser_event(service, tab, phase, op, args, element, outcome)
    except Exception:  # noqa: BLE001
        pass


def attach_browser_feedback(root, result):
    """Add Paul's waiting feedback to a browser tool result for the acting agent."""
    try:
        view = existing(root)
        if view is None or not isinstance(result, dict):
            return result
        from .neyvia_cua import NATIVE_CLIENT
        client = AGENT_CLIENT.get() or NATIVE_CLIENT.get() or {"app": "agent", "chatId": "obscura"}
        notes = view.take_browser_notes(client)
        if notes:
            return {**result, "ownerFeedback": notes}
    except Exception:  # noqa: BLE001
        pass
    return result


def request(root, op, args):
    view = view_for(root)
    if op == "runs":
        return view.list_runs()
    if op == "timeline":
        return view.timeline(args)
    if op == "frame":
        return view.frame(args)
    if op == "feedback":
        return view.feedback(args)
    raise ValueError("Unknown agent view operation")


def serve_http(backend, handler, parsed, method):
    from .web_backend import _apply_security_headers, _json_response, _read_json_body
    session = backend.authenticated_session(handler)
    if not session or str(session.get("username", "")).casefold() != backend.username.casefold():
        _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required for the agent view"})
        return
    from .neyvia_remote import _loopback, _origin
    if not _loopback(handler.client_address[0]) or not _origin(handler):
        _json_response(handler, 403, {"ok": False, "error": "The agent view is host-local"})
        return
    suffix = parsed.path.removeprefix("/api/ui/agentview").strip("/")
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    try:
        if method == "GET" and suffix == "keyframe":
            raw = view_for(backend.root).keyframe_path(query).read_bytes()
            handler.send_response(200)
            for k, v in {"Content-Type": "image/jpeg", "Content-Length": str(len(raw)), "Cache-Control": "private, max-age=86400"}.items():
                handler.send_header(k, v)
            _apply_security_headers(handler)
            handler.end_headers()
            handler.wfile.write(raw)
            return
        if method == "GET":
            value = request(backend.root, suffix or "runs", query)
        elif method == "POST":
            body = _read_json_body(handler)
            value = request(backend.root, str(body.get("op") or suffix), body.get("args") or {})
        else:
            raise ValueError("Unsupported method")
        _json_response(handler, 200, {"ok": True, "data": value})
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass
    except (ValueError, KeyError, TypeError, OSError) as exc:
        _json_response(handler, 400, {"ok": False, "error": str(exc)[:400]})
