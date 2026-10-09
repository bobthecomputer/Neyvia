"""Author the video editor mods' descriptors and executable CL manuals (plan 28 Build 1-2).

Writes apps/<id>/neyvia.module.json, host-contract.json and manual.cl through the existing
lossless manual compiler (grant_agent.cl.manuals.manual_to_cl). Run with system Python.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import manual_to_cl  # noqa: E402

OBJ = {"type": "object"}


def S(**k):
    return {"type": "string", "maxLength": 4000, **k}


def N(**k):
    return {"type": "number", **k}


STEPS = {"type": "array", "maxItems": 500, "items": {"type": "object", "properties": {"id": S(maxLength=200), "params": OBJ}, "required": ["id"]}}
CREDIT = "Adapted, not forked: every action runs the unmodified upstream program."

MODS = {
    "hyperframes": dict(
        name="HyperFrames", file="hyperframes_mod.py",
        purpose="Agent-usable HyperFrames (HeyGen, Apache-2.0): lint, observe the timeline, render headless to MP4 with outcome contracts, snapshot frames and run the Studio privately.",
        upstream={"repository": "https://github.com/heygen-com/hyperframes", "license": "Apache-2.0", "version": "0.8.138"},
        permissions=["Runs the pinned hyperframes CLI and a local headless Chromium with a throwaway profile (no window)",
                     "Reads and writes the project folder you name",
                     "Telemetry, skill installs and cloud describers are switched off; no network beyond loopback"],
        actions=[
            ("lint", "lint", "Lint a HyperFrames composition folder; returns the upstream findings.", "read", {"project": S()}, ["project"]),
            ("timeline", "timeline", "Observe a composition's tracks and clips as a CL Scene.", "read", {"project": S()}, ["project"]),
            ("render", "render", "Render a composition headless to MP4 and check duration, frame count, black/frozen frames and audio clipping on the file.", "artifact_write",
             {"project": S(), "out": S(), "fps": N(minimum=1, maximum=120), "quality": S(enum=["draft", "standard", "high"]), "expectedS": N(), "workers": N(minimum=1, maximum=8)}, ["project"]),
            ("edit", "edit", "One upstream timeline edit (move, trim, split, delete, set, duplicate) on a clip ref, then re-observe the timeline.", "artifact_write",
             {"project": S(), "op": S(enum=["move", "trim", "split", "delete", "set", "duplicate"]), "ref": S(maxLength=200), "time": N(), "options": OBJ}, ["project", "op", "ref"]),
            ("snapshot", "snapshot", "Capture exact frames as PNG at given times.", "artifact_write",
             {"project": S(), "out": S(), "at": {"type": "array", "items": N()}, "frames": N(minimum=1, maximum=30)}, ["project"]),
            ("studio", "studio", "Start, stop or read the HyperFrames Studio preview server for a project (127.0.0.1:49165, no browser window).", "external_action",
             {"project": S(), "action": S(enum=["start", "stop", "status"])}, ["project", "action"]),
            ("verify", "verify", "Real round trip on a two-clip composition: render headless, then the outcome contracts.", "artifact_write", {}, []),
        ],
        guidance=["Compositions are HTML: clips are elements with data-start, data-duration and data-track-index; one paused GSAP timeline is registered at window.__timelines[composition-id].",
                  "Observe with mod.hyperframes.timeline, change the HTML, lint, then render; read the outcome block before calling a render good.",
                  "Open the visual editor through the HyperFrames Studio app; it embeds the Studio served on loopback."],
        frontier=["HyperFrames 0.8.138 cannot attach to an existing browser over CDP; it launches the local chrome-headless-shell with a throwaway profile. On Windows capture is screenshot mode, about 2-6 frames per second per render on a loaded machine.",
                  CREDIT + " HyperFrames by HeyGen, Apache-2.0, https://github.com/heygen-com/hyperframes."]),
    "filmcraft": dict(
        name="FilmCraft", file="filmcraft_mod.py",
        purpose="Agent-usable FilmCraft (ArtCraft/storytold, MIT or Apache-2.0; a Premiere-style editor in Rust) through its headless CLI: commands, the sequence as a CL Scene, scripted edits, export and frames.",
        upstream={"repository": "https://github.com/storytold/filmcraft", "license": "MIT OR Apache-2.0", "version": "0.2.1"},
        permissions=["Runs the locally built filmcraft-cli headless (no window, no bridge to a desktop app)",
                     "Reads the media you name and writes the .fcproj and exports you name", "No network"],
        actions=[
            ("commands", "commands", "List FilmCraft engine commands (id, label, params) matching a filter.", "read", {"filter": S(maxLength=200)}, []),
            ("inspect", "inspect", "Observe a project's active sequence as a CL Scene: tracks, clips, in/out, effects, transitions, markers.", "read", {"project": S()}, ["project"]),
            ("run", "run", "Run engine commands in order on a project (a new project when omitted) and save it.", "artifact_write", {"project": S(), "steps": STEPS, "saveAs": S()}, ["steps", "saveAs"]),
            ("export", "export", "Export the active sequence and check the outcome contracts on the file.", "artifact_write", {"project": S(), "out": S(), "format": S(maxLength=20)}, ["project", "out"]),
            ("frame", "frame", "Render one Program frame to PNG.", "artifact_write", {"project": S(), "seconds": N(minimum=0), "out": S()}, ["project", "seconds", "out"]),
            ("verify", "verify", "Real round trip: import real Neyvia captures, place clips, export, then the outcome contracts.", "artifact_write", {}, []),
        ],
        guidance=["Every FilmCraft menu item is an engine command with typed params; list them with mod.filmcraft.commands and run them with mod.filmcraft.run.",
                  "Times are integer ticks (254016000000 per second); most commands also accept seconds=.",
                  "Read the sequence back with mod.filmcraft.inspect after every edit; export and read the outcome contracts before claiming a render."],
        frontier=["Built from source with the local Rust toolchain into D:/NeyviaRuns/video/track-video/target; set NEYVIA_FILMCRAFT_CLI to use another build.",
                  CREDIT + " FilmCraft by the ArtCraft team, MIT OR Apache-2.0, https://github.com/storytold/filmcraft."]),
    "effectcraft": dict(
        name="EffectCraft", file="effectcraft_mod.py",
        purpose="Agent-usable EffectCraft (ArtCraft/storytold, an After Effects-style compositor in Rust) through its headless CLI: commands, comps and layers as a CL Scene, scripted edits, frames and renders.",
        upstream={"repository": "https://github.com/storytold/effectcraft", "license": "MIT OR Apache-2.0", "version": "0.3.1"},
        permissions=["Runs the locally built effectcraft-cli headless (no window)", "Reads and writes the .ecproj and renders you name", "No network"],
        actions=[
            ("commands", "commands", "List EffectCraft engine commands matching a filter.", "read", {"filter": S(maxLength=200)}, []),
            ("info", "info", "Observe a project as a CL Scene: every comp, and the active comp's layers with their effects and keyframed properties.", "read", {"project": S()}, []),
            ("run", "run", "Run engine commands in order on a project (the built-in demo when omitted) and save it.", "artifact_write", {"project": S(), "steps": STEPS, "saveAs": S()}, ["steps", "saveAs"]),
            ("frame", "frame", "Render one composition frame to PNG.", "artifact_write", {"project": S(), "comp": S(), "time": N(minimum=0), "out": S()}, ["out"]),
            ("render", "render", "Render a composition to a file and check the outcome contracts.", "artifact_write", {"project": S(), "comp": S(), "out": S(), "format": S(maxLength=20), "start": N(), "end": N()}, ["out"]),
            ("verify", "verify", "Real round trip on a real Neyvia capture: new comp, import, keyframed push-in, a title with Drop Shadow and a fade, observe as a Scene, one frame, a 3 s H.264 render, then the outcome contracts on the decoded file.", "artifact_write", {}, []),
        ],
        guidance=["Comps and layers are addressed by id or name; properties by path (mod.effectcraft.info lists them).",
                  "A run step is an engine command id with JSON params, e.g. comp.new {name,width,height,frameRate,duration}, file.import {paths}, layer.addItem {item,time,duration}, layer.newText {text,name,size,fill,position}, effect.apply {effect,layers}, prop.addKey {layer,path,time,value}; find others with mod.effectcraft.commands.",
                  "Use frames for quick looks and render for the outcome contracts."],
        frontier=["Built from source (effectcraft 0.3.1, needs Rust 1.95 or newer) with a Rust 1.99 toolchain kept on D:/NeyviaRuns/toolchains into D:/NeyviaRuns/video/track-video/target/effectcraft; set NEYVIA_EFFECTCRAFT_CLI to use another build.",
                  CREDIT + " EffectCraft by the ArtCraft team, MIT OR Apache-2.0, https://github.com/storytold/effectcraft."]),
    "photocraft": dict(
        name="PhotoCraft", file="photocraft_mod.py",
        purpose="Agent-usable PhotoCraft (ArtCraft/storytold, a Photoshop-style editor in Rust) for video frames: inspect, run engine commands, convert.",
        upstream={"repository": "https://github.com/storytold/photocraft", "license": "MIT OR Apache-2.0"},
        permissions=["Runs the locally built photocraft-cli headless (no window)", "Reads the images and writes the outputs you name", "No network"],
        actions=[
            ("commands", "commands", "List PhotoCraft engine commands matching a filter.", "read", {"filter": S(maxLength=200)}, []),
            ("info", "info", "Observe an image document (size, mode, layer tree) as a CL Scene.", "read", {"file": S()}, ["file"]),
            ("run", "run", "Open an image, run engine commands in order and save the result.", "artifact_write", {"file": S(), "steps": STEPS, "out": S()}, ["file", "steps", "out"]),
            ("convert", "convert", "Convert an image between formats.", "artifact_write", {"input": S(), "out": S()}, ["input", "out"]),
            ("verify", "verify", "Real round trip on a Neyvia capture: inspect, convert, and compare the decoded pixels.", "artifact_write", {}, []),
        ],
        guidance=["Use PhotoCraft for frame work (grades, crops, exports) before a frame goes into a cut."],
        frontier=["Built from source with the local Rust toolchain into D:/NeyviaRuns/video/track-video/target; set NEYVIA_PHOTOCRAFT_CLI to use another build.",
                  CREDIT + " PhotoCraft by the ArtCraft team, MIT OR Apache-2.0, https://github.com/storytold/photocraft."]),
    "laya-video": dict(
        name="LAYA video", file="laya_video_mod.py", ns="laya_video", dependencies=["hyperframes"],
        extraFiles=["apps/laya-video/briefs/neyvia-launch.cl", "apps/laya-video/briefs/practice.cl"],
        purpose="LAYA edits video by itself: a CL brief becomes a first draft from real captures, the shared Scene core judges the rendered file and keeps only fixes that remove findings; A/B votes become personal taste episodes.",
        upstream=None,
        permissions=["Renders through the HyperFrames mod (headless)", "Reads the captures named in the brief and writes the project folder you name",
                     "Runs local Whisper and Windows OCR; no paid or cloud model calls"],
        actions=[
            ("draft", "draft", "Assemble the first draft EDL from a CL brief and real captures.", "artifact_write", {"brief": S(), "out": S()}, ["brief", "out"]),
            ("inspect", "inspect", "Render and transcribe a project, then judge it with the shared core.", "artifact_write", {"project": S(), "quality": S(enum=["preview", "master"])}, ["project"]),
            ("improve", "improve", "Guarded improve rounds: each named EDL fix is kept only on a strict finding reduction.", "artifact_write",
             {"project": S(), "rounds": N(minimum=1, maximum=24), "maxSeconds": N(minimum=1, maximum=300), "allowedFixes": {"type": "array", "items": S()}}, ["project"]),
            ("vote", "vote", "Record a person's A/B preference between two cuts as personal episodes.", "artifact_write",
             {"a": S(), "b": S(), "winner": S(enum=["a", "b"]), "user": S(minLength=1), "reason": S(), "voteId": S()}, ["a", "b", "winner", "user"]),
            ("verify", "verify", "Replay the recorded launch-cut proof against the laya-video CL contracts.", "read", {}, []),
        ],
        guidance=["Write a brief as CL (S length/aspect/music/captions/must/story lines, C must-hold lines), then draft, improve and inspect at quality master.",
                  "The predicates, their measured facts and named fixes are in manuals/cl/laya-video.cl; every fix edits only edl.json.",
                  "Paul's taste: vote between two cuts; the vote is a personal episode, effective on the next similar edit."],
        frontier=["Renders take minutes on a loaded machine; each improve round is one render plus measurement.", "Votes are only ever cast by a person."]),
}


def chapter(title):
    return {"title": title, **{key: {} for key in ("state", "actions", "checks", "procedures", "judge")},
            **{key: [] for key in ("pitfalls", "frontier", "guidance")}}


def author(mid, m):
    ns = m.get("ns", mid)
    folder = REPO / "apps" / mid
    actions = [{"name": f"neyvia.mod.{ns}.{verb}", "description": desc, "file": f"apps/{mid}/{m['file']}", "function": fn,
                "mutability": mut, "inputSchema": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}
               for verb, fn, desc, mut, props, req in m["actions"]]
    row = {"schema": "neyvia.module.v1", "id": mid, "name": m["name"], "purpose": m["purpose"],
           "files": [f"apps/{mid}/{m['file']}", f"apps/{mid}/manual.cl", f"apps/{mid}/host-contract.json", *m.get("extraFiles", [])],
           "manual": mid, "sourceManual": "manual.cl", "contract": "host-contract.json", "ownerSurface": "Marketplace / Mods",
           "settings": ["enabled"], "events": [], "dependencies": m.get("dependencies", []), "permissions": m["permissions"], "actions": actions}
    if m.get("upstream"):
        row["upstream"] = m["upstream"]
        row["sourceRepository"] = m["upstream"]["repository"]
    (folder / "neyvia.module.json").write_text(json.dumps(row, indent=1) + "\n", encoding="utf-8")
    (folder / "host-contract.json").write_text(json.dumps({"schema": "neyvia.source-contracts.v1", "checks": [f"{mid}.verify-{mid}"]}, indent=1) + "\n", encoding="utf-8")
    content = chapter(m["purpose"])
    schemas = {}
    for a in actions:
        key = a["name"].removeprefix("neyvia.")
        schemas[a["name"]] = a["inputSchema"]
        content["actions"][key] = {"tool": a["name"], "schema": a["name"], "returns": {"type": "object"},
                                   "pre": "Selected workspace; the mod is installed, enabled and its local tool is present",
                                   "effect": a["description"], "reversible": a["mutability"] == "read"}
    verify = f"neyvia.mod.{ns}.verify"
    content["checks"]["verified"] = {"tool": verify, "args": {}, "expect": {"path": "passed", "op": "eq", "value": True}}
    content["procedures"][f"verify-{mid}"] = {"goal": "Run the real round trip and check its outcome contracts",
                                             "inputs": {"type": "object", "properties": {}, "additionalProperties": False},
                                             "steps": [{"action": f"mod.{ns}.verify", "args": {}, "save": "verified", "check": "verified"}]}
    content["pitfalls"] = [{"failure": "The local tool is missing", "recovery": "Build or point the NEYVIA_* path at it; the action refuses rather than downloading anything."},
                           {"failure": "A render exists but is wrong", "recovery": "Read the outcome block (duration, frames, black/frozen runs, clipping); never call a render good from its exit code."}]
    content["guidance"] = m["guidance"] + ["Installs switched off from Marketplace > Apps & mods; read this manual and the declared permissions, then enable it."]
    content["frontier"] = m["frontier"]
    document = {"schema": "neyvia.manual.v1", "id": mid, "kind": "environment", "schemas": schemas, "chapters": {"overview": content}}
    text = manual_to_cl(document)
    (folder / "manual.cl").write_text(text, encoding="utf-8")
    if mid != "laya-video":  # laya-video's repository manual is the CL skill manuals/cl/laya-video.cl
        (REPO / "manuals/cl" / f"{mid}.cl").write_text(text, encoding="utf-8")
    return document


def main():
    for mid, m in MODS.items():
        (REPO / "apps" / mid).mkdir(parents=True, exist_ok=True)
        author(mid, m)
        print("authored", mid)
    # The hosted Studio app gets a manual over its dependency's actions.
    m = MODS["hyperframes"]
    content = chapter("HyperFrames Studio hosted in Neyvia: open a project's timeline, code and live preview privately")
    content["actions"]["mod.hyperframes.studio"] = {"tool": "neyvia.mod.hyperframes.studio", "schema": "neyvia.mod.hyperframes.studio",
                                                    "returns": {"type": "object"}, "pre": "The hyperframes mod is installed and enabled",
                                                    "effect": "Start, stop or read the Studio server for a project; the app embeds it.", "reversible": True}
    content["checks"]["studio-status"] = {"tool": "neyvia.mod.hyperframes.studio", "args": {"project": {"$input": "project"}, "action": "status"},
                                          "expect": {"path": "ok", "op": "eq", "value": True}}
    content["procedures"]["verify-studio"] = {"goal": "Start the Studio for a project, read its status, stop it",
                                              "inputs": {"type": "object", "properties": {"project": S()}, "required": ["project"]},
                                              "steps": [{"action": "mod.hyperframes.studio", "args": {"project": {"$input": "project"}, "action": "start"}, "save": "started", "check": "studio-status"},
                                                        {"action": "mod.hyperframes.studio", "args": {"project": {"$input": "project"}, "action": "stop"}, "save": "stopped"}]}
    content["guidance"] = ["The app page asks for a project folder and embeds the Studio from 127.0.0.1:49165; no browser window opens.",
                           "Agents edit the same project through the hyperframes mod and see the Studio update."]
    content["frontier"] = [CREDIT + " HyperFrames Studio by HeyGen, Apache-2.0, https://github.com/heygen-com/hyperframes."]
    document = {"schema": "neyvia.manual.v1", "id": "hyperframes-studio", "kind": "environment",
                "schemas": {"neyvia.mod.hyperframes.studio": {"type": "object", "properties": next(a for a in m["actions"] if a[0] == "studio")[4], "required": ["project", "action"]}},
                "chapters": {"overview": content}}
    (REPO / "apps/hyperframes-studio/manual.cl").write_text(manual_to_cl(document), encoding="utf-8")
    print("authored hyperframes-studio")


if __name__ == "__main__":
    main()
