"""Author MOD's CL chapters using the existing lossless manual compiler."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import manual_to_cl
from grant_agent.neyvia_modules import DEFINITIONS
from grant_agent.source_marketplace import DEFINITIONS as MARKETPLACE_DEFINITIONS
from grant_agent.module_plugins import manifests


def chapter(title):
    return {"title": title, **{key: {} for key in ("state", "actions", "checks", "procedures", "judge")},
            **{key: [] for key in ("pitfalls", "frontier", "guidance")}}


def document(identity, content, definitions):
    schemas = {}
    for name, description, props, required in definitions:
        tool = "neyvia." + name
        schemas[tool] = {"type": "object", "properties": props, "required": required}
        content["actions"][name] = {"tool": tool, "schema": tool, "returns": {"type": "object"},
            "pre": "Selected workspace; module is mapped and any optional dependencies are enabled",
            "effect": description, "reversible": True}
    return {"schema": "neyvia.manual.v1", "id": identity, "kind": "environment", "schemas": schemas, "chapters": {"overview": content}}


def author():
    overview = chapter("Reusable repository modules, public APIs and optional mods")
    overview["state"]["catalog"] = {"tool": "neyvia.modules.list", "args": {},
        "inputs": {"type": "object", "properties": {}, "additionalProperties": False}, "shape": {"type": "object"}}
    overview["state"]["module"] = {"tool": "neyvia.modules.get", "args": {"id": {"$input": "id"}},
        "inputs": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, "shape": {"type": "object"}}
    overview["checks"]["map-current"] = {"tool": "neyvia.modules.validate", "args": {},
        "expect": {"path": "ok", "op": "eq", "value": True}}
    overview["checks"]["enabled-state"] = {"tool": "neyvia.modules.get", "args": {"id": {"$input": "id"}},
        "expect": {"path": "module.enabled", "op": "eq", "value": {"$input": "enabled"}}}
    overview["procedures"]["verify-map"] = {"goal": "Every scoped source file has an owner, every action exists and generated data is current",
        "inputs": {"type": "object", "properties": {}, "additionalProperties": False},
        "steps": [{"action": "modules.validate", "args": {}, "save": "map", "check": "map-current"}]}
    overview["procedures"]["set-optional"] = {"goal": "Change optional module availability and observe the persisted result",
        "inputs": {"type": "object", "properties": {"id": {"type": "string"}, "enabled": {"type": "boolean"}},
                   "required": ["id", "enabled"], "additionalProperties": False},
        "steps": [{"action": "marketplace.set", "args": {"id": {"$input": "id"}, "enabled": {"$input": "enabled"}},
                   "save": "changed", "check": "enabled-state"}]}
    for verb, enabled, state in (("enable-source", True, "active"), ("disable-source", False, "disabled")):
        overview["checks"][verb] = {"tool": "neyvia.marketplace.get", "args": {"id": {"$input": "id"}},
            "expect": {"path": "item.state", "op": "eq", "value": state}}
        overview["procedures"][verb] = {"goal": "Persist and observe source item state " + state,
            "inputs": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            "steps": [{"action": "marketplace.set", "args": {"id": {"$input": "id"}, "enabled": enabled}, "save": "changed", "check": verb}]}
    overview["guidance"] = [
        "MODULES.md indexes source-derived modules. modules/<id>/README.md lists each purpose, public API, files, CL manual, contracts and dependencies.",
        "Core modules stay enabled. Source apps and mods use one workspace-local marketplace lifecycle; every mod action and hosted app SDK call uses its saved gate.",
        "Run modules.verify-map() after source changes. Rebuild config/neyvia.modules.json with system Python scripts/generate_module_map.py; review before commit.",
        "The registry maps existing implementation units; a generated purpose or import dependency is a static description, not a claim of independently replaceable ABI.",
        "Read neyvia chapter modding-neyvia and docs/BUILDING_APPS_AND_MODS.md. Reuse neyvia-sdk for sign-in/providers, memory, LAYA verification, CL and app hosting rather than copying architecture."]
    overview["pitfalls"] = [{"failure": "Module map drifted or manual names a missing action", "recovery": "Fix ownership/action registration; compile CL, regenerate the module map and rerun modules.verify-map()."},
        {"failure": "Optional module is disabled or required by an enabled dependant", "recovery": "Enable required dependencies first; disable dependants before their dependency. Core switches are refused."}]
    overview["frontier"] = ["Trusted repository-local mods only; no downloading or executing untrusted packages. Changing a mod action schema requires restarting the owned backend to rebuild its tool catalog.",
        "Source inspection is read-only; edit the named file in your editor. External connector runtime readiness is described by game-dev.cl, not inferred from registry presence."]
    modules_doc = document("modules", overview, [*DEFINITIONS, *MARKETPLACE_DEFINITIONS])
    plugin = manifests()[0]
    action = plugin["actions"][0]
    hello = chapter("A real optional personal greeting mod")
    hello["checks"]["greeting"] = {"tool": action["name"], "args": {"name": "Paul"},
        "expect": {"path": "greeting", "op": "eq", "value": "Hello, Paul!"}}
    hello["procedures"]["verify-greeting"] = {"goal": "Call the installed optional mod and verify the exact personal greeting",
        "inputs": {"type": "object", "properties": {}, "additionalProperties": False},
        "steps": [{"action": "mod.hello.greet", "args": {"name": "Paul"}, "save": "greeting", "check": "greeting"}]}
    hello["guidance"] = ["The example lives in apps/hello-module. Its action is registered automatically at backend startup; the existing marketplace manages apps and mods.",
        "Run hello-module.verify-greeting(); call mod.hello.greet(name='your name') to build a personal greeting.",
        "Install apps/hello-module through marketplace.install, then enable it with modules.set-optional(id='hello-module', enabled=true). Disable it to prove subsequent greeting calls fail."]
    hello["frontier"] = ["This example is a deterministic local action, not an AI model call."]
    hello_doc = document("hello-module", hello, [("mod.hello.greet", action["description"], action["inputSchema"]["properties"], ["name"])])
    metadata = {"neyvia." + name: {"mutability_class": "artifact_write" if name == "marketplace.set" else
        "external_action" if name in {"marketplace.install", "marketplace.update"} else "read"}
                for name, _, _, _ in [*DEFINITIONS, *MARKETPLACE_DEFINITIONS]}
    metadata[action["name"]] = {"mutability_class": "read"}
    index_path = REPO / "config/neyvia_manuals.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for doc in (modules_doc, hello_doc):
        identity = doc["id"]
        (REPO / "manuals/cl" / (identity + ".cl")).write_text(manual_to_cl(doc, metadata), encoding="utf-8")
        # The full compiler requires an indexed artifact to exist before its first compile.
        (REPO / "manuals" / (identity + ".manual.json")).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        if not any(row["id"] == identity for row in index["manuals"]):
            index["manuals"].append({"id": identity, "path": "manuals/" + identity + ".manual.json",
                "description": doc["chapters"]["overview"]["title"], "clSource": "manuals/cl/" + identity + ".cl"})
        if identity == "hello-module":
            (REPO / "apps/hello-module/manual.cl").write_text(manual_to_cl(doc, metadata), encoding="utf-8")
            (REPO / "apps/hello-module/host-contract.json").write_text(json.dumps({"schema": "neyvia.source-contracts.v1", "checks": ["hello-module.verify-greeting", "modules.verify-map"]}, indent=2) + "\n", encoding="utf-8")
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    neyvia_path = REPO / "manuals/cl/neyvia.cl"
    source = neyvia_path.read_text(encoding="utf-8")
    # Add records without reformatting or renumbering the large existing manual.
    header_line = next(line for line in source.splitlines() if line.startswith("-- @manual "))
    header = json.loads(header_line[len("-- @manual "):])
    for identity, title, guidance in [
        ("modding-neyvia", "Building apps and mods", [
            "Start from templates/neyvia-module. Copy the template to apps/<module-id>, choose a unique id and the neyvia.mod.<namespace>.<action> namespace, and list every owned file.",
            "Implement the declared function(args, root=...) in the owned Python file. Declare the exact input schema and actual read/artifact_write/external_action mutability; no core action overrides.",
            "Write manuals/cl/<module-id>.cl with typed actions, executable checks and procedures, using hello-module.cl as the small example. Add its CL source/artifact to config/neyvia_manuals.json.",
            "Run system Python scripts/cl_compile_manuals.py, then scripts/generate_module_map.py. The compiler's --check includes map ownership, missing-action and entry-point navigation checks.",
            "Read docs/BUILDING_APPS_AND_MODS.md and use neyvia-sdk for provider sign-in, model calls, memory, LAYA verification, CL/manual calls and app hosting. Never implement parallel provider credentials or memory stores for shared services.",
            "Restart only your owned local backend to discover new action schemas. Install the app or mod through the existing marketplace from its local folder or git URL; inspect its manual and contracts. Run the manual contract; switch off/on and prove refusal/persistence.",
            "Commit source, authored CL, compiled artifacts and the generated registry together. Never push, merge, publish or install an untrusted mod through this path.",
            "Executable entry points: modules.verify-map(), modules.set-optional(id='hello-module',enabled=false), hello-module.verify-greeting()."]),
        ("module-manuals", "Every module manual", ["Module registry: config/neyvia.modules.json. Read modules.list(query='...'), then modules.get(id='...') for ownership and exact manual links."] +
         ["Read neyvia.manual.load(id='" + row["id"] + "') -- " + row["clSource"] for row in index["manuals"]])]:
        if identity in header["chapters"]:
            # Deterministic refresh of only our appended chapter.
            start = source.index("L neyvia." + identity + " v1 --")
            following = source.find("\nL neyvia.", start + 1)
            source = source[:start] + (source[following + 1:] if following >= 0 else "")
        header["chapters"][identity] = {"title": title}
        source = source.rstrip() + "\nL neyvia." + identity + " v1 -- " + title + "\n"
        for number, line in enumerate(guidance):
            record = {"chapter": identity, "section": "guidance", "key": str(number), "data": line}
            source += "-- @record " + json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            source += "M neyvia " + json.dumps(line) + ' src:"authored manual" state:verified\n'
    current_header = next(line for line in source.splitlines() if line.startswith("-- @manual "))
    source = source.replace(current_header, "-- @manual " + json.dumps(header, sort_keys=True, separators=(",", ":")), 1)
    neyvia_path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    author()
