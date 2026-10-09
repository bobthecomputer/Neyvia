"""Regenerate only T12's authored executable manual from registered schemas."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import validate

registry = NativeToolRegistry(REPO / ".agent_control/t12/manual")
names = ["status", "sessions", "setup", "action", "receipt", "asset_validate"]
schemas = {"neyvia.gamedev." + name: registry.describe("neyvia.gamedev." + name)["inputSchema"] for name in names}
objects = {"type": "object"}
empty = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
guards = {
    "status": ("Selected backend root and scoped workspace; no editor starts", "Observe installation separately from heartbeat connection"),
    "sessions": ("Selected backend root", "Observe exact engine/project/context/session/capabilities; never select by engine alone"),
    "setup": ("Existing project inside selected workspace; installed native editor; no conflicting bridge files", "Copy local bridge package and create a project-scoped token; no editor/system install"),
    "action": ("Exact connected session advertises action; matching context/Studio; scoped file paths; load_asset passes validator", "Queue an affinity-bound native operation once; success is determined by native completion, not queue admission"),
    "receipt": ("Existing requestId on the same persistent backend", "Observe queue/running/terminal result, error and elapsed time; pending is not completed"),
    "asset_validate": ("Existing scoped .glb/.gltf with bounded local resources and Node available", "Run official Khronos Validator; invalid exports cannot be loaded by action"),
}
actions = {name: {"tool": "neyvia.gamedev." + name, "schema": "neyvia.gamedev." + name, "returns": objects,
                  "pre": guards[name][0], "effect": guards[name][1], "reversible": True} for name in names}
actions["action"]["reversible"] = False
data = {"schema": "neyvia.manual.v1", "id": "game-dev", "kind": "environment", "schemas": schemas, "chapters": {
    "bridges": {"title": "Operate native game editors and Babylon through exact sessions and checked receipts",
      "state": {"live": {"tool": "neyvia.gamedev.status", "args": {}, "inputs": empty,
                         "shape": {"type": "object", "properties": {"engines": {"type": "array"}, "sessions": {"type": "array"}}, "required": ["engines", "sessions"]}}},
      "actions": actions,
      "checks": {
          "complete": {"tool": "neyvia.gamedev.receipt", "args": {"requestId": {"$input": "requestId"}}, "expect": {"path": "status", "op": "eq", "value": "succeeded"}},
          "valid-asset": {"tool": "neyvia.gamedev.asset_validate", "args": {"path": {"$input": "path"}}, "expect": {"path": "valid", "op": "eq", "value": True}},
      },
      "procedures": {
          "discover-live-editors": {"goal": "Find installed editors and exact connected native contexts before operating", "inputs": empty,
                                    "steps": [{"action": "status", "args": {}, "save": "availability"}, {"action": "sessions", "args": {}, "save": "native"}]},
          "review-completed-action": {"goal": "Check a terminal native receipt after polling until it stops being queued/running",
                "inputs": {"type": "object", "properties": {"requestId": {"type": "string"}}, "required": ["requestId"], "additionalProperties": False},
                "steps": [{"action": "receipt", "args": {"requestId": {"$input": "requestId"}}, "save": "receipt", "check": "complete"}]},
          "validate-export-before-engine-load": {"goal": "Reject broken glTF resources before any engine import",
                "inputs": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
                "steps": [{"action": "asset_validate", "args": {"path": {"$input": "path"}}, "save": "validation", "check": "valid-asset"}]},
      },
      "judge": {},
      "pitfalls": [
          {"failure": "Editor is detected but no native session is connected", "recovery": "Use setup then enable the project-local plugin in its actual editor; inspect heartbeat before actions"},
          {"failure": "Action is queued/running", "recovery": "Poll the same requestId until terminal; do not call it complete or queue a fresh retry"},
          {"failure": "Backend restart, timeout or ambiguous completion", "recovery": "Inspect native state first; interrupted actions are failed and never automatically replayed"},
          {"failure": "Changed request payload reuses an ID", "recovery": "Inspect previous receipt, then choose a new ID only for a new explicit intent"},
          {"failure": "Roblox simulation stop preserves edits", "recovery": "Require preserveChanges:true for simulation; player EndTest uses exact Server session, then observe Edit playResult"},
      ],
      "frontier": ["Native Unity/Godot/Blender/Roblox compilation and journeys need installed editors; no host was present in this task",
                   "Rendered Babylon proof needs working Chrome control; native proof uses explicitly identified NullEngine",
                   "Unity glTF loading requires an existing project importer",
                   "Roblox StudioTestService play/end APIs and actual Client/Server plugin contexts remain unverified without Studio"],
      "guidance": [
          "Observer/action/check tools share HTTP /api/backend, bot state and desktop forwarding; existing generic Tauri IPC carries gamedev_*_command.",
          "Unity: select/inspect path is scene hierarchy or Assets/...; guarded script edit uses source+expectedSha256; component edit path/component/property/value or vector; run/stop/reload; test mode EditMode/PlayMode only with existing Test Framework.",
          "Godot Edit: inspect; select/edit node relative to scene, property and value; script edit path res://...gd, source, expectedSha256; validate path res://...gd; run -> observe separate Play session; Play interact node,input invokes game's explicit neyvia_interact method.",
          "Roblox: exact studio_id and Edit/Client/Server affinity; Instance path, script source+expectedSource; run mode play uses StudioTestService (if available); stop mode play requires Server and final Edit playResult observation; simulation stop requires preserveChanges:true; read actual console.",
          "Blender: inspect/select/edit object and location/rotation/scale; render path PNG and camera; export path GLB/glTF and selectedOnly; validate then load_asset path.",
          "Babylon: edit op create/transform/material, name, position/rotation/scaling/color finite triples, expectedRevision; run/stop; interact name,rotateY radians; test name,position/minVertices; export path GLB with expectedSha256 for overwrite; validate then load_asset path GLB.",
          "Export/import proof is boundary-specific. NullEngine runs real scene geometry and loader but cannot prove rendered pixels, clicks or Blender rendering.",
          "Engine APIs remain native; do not unify Unity Components, Roblox Instances and Godot Nodes.",
          "Private .neyvia/gamedev-bridge.json must remain out of source control. Never expose its token in UI or receipts.",
      ]}
}}
result = validate(data, registry)
(REPO / "manuals/game-dev.manual.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))
