"""Run the release batch's real inventory and static impact observers on owned files."""
from pathlib import Path
import json
import os
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.proofs_e_release import (check_runtime_inventory, check_hermes_inventory,
    check_impact_index, check_imported_registries, check_dispatch_membership,
    check_ui_command_evidence, ReleaseProofContractError)
from grant_agent.runtime_capability_inventory import build_runtime_capability_inventory
from grant_agent.mcp_broker import McpOutboundBroker
from grant_agent.neyvia_impact import index, find_gaps, _tree, _imported_sets, _compares, _ui_commands, JS_TOKEN, COMMAND_CALLS


def self_check(root):
    started = time.perf_counter(); root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    workspace, home = root / "runtime-workspace", root / "codex-home"
    plugin = home / "plugins/cache/fixture/plugin/1.0.0"
    (workspace / ".agent_control").mkdir(parents=True, exist_ok=True); plugin.mkdir(parents=True, exist_ok=True)
    marker = "FIXTURE_ENV_METADATA_MUST_STAY_PRIVATE"
    configuration = {"schema": "neyvia.mcp_broker_config.v1", "servers": {"metadata-example": {"transport": "stdio", "command": "fixture-not-started-mcp", "env": {"FIXTURE_MARKER": marker}}}}
    (workspace / ".agent_control/mcp_servers.json").write_text(json.dumps(configuration), encoding="utf-8")
    (plugin / "plugin.json").write_text(json.dumps({"name": "Metadata Plugin", "version": "1.0.0", "skills": []}), encoding="utf-8")
    (home / "config.toml").write_text('[plugins."Metadata Plugin@fixture"]\nenabled = true\n', encoding="utf-8")
    empty_path = root / "empty-executable-path"; empty_path.mkdir(exist_ok=True)
    result = build_runtime_capability_inventory(workspace, home, environment={"PATH": str(empty_path), "HERMES_HOME": str(root / "hermes-home")})
    row = next(row for row in result["mcpServers"] if row["name"] == "metadata-example")
    if row["callable"] is not True or row["hasEnvironment"] is not True or result["plugins"][0]["enabledInCodex"] is not True or result["plugins"][0]["nativeInNeyvia"] is not False or result["hermes"]["available"] is not False or marker in json.dumps(result) or "fixture-not-started-mcp" in json.dumps(result):
        raise RuntimeError("Inventory fixture observer goal failed")
    observers = []
    def reject(id, call):
        refused = False
        try: call()
        except ReleaseProofContractError as error: refused = error.contract == id
        if not refused: raise RuntimeError("Corruption escaped " + id)
        observers.append({"id": id, "status": "passed", "corrupt_result_rejected": True})
    broker_rows = McpOutboundBroker(workspace, include_default_demo=False).list_servers()
    bad = dict(result); bad["mcpServers"] = [{**row, "callable": False, "hasEnvironment": False}]
    reject("runtime.capability-metadata", lambda: check_runtime_inventory(bad, configuration, {"plugins": [{"pluginId": p["pluginId"], "enabled": p["enabledInCodex"]} for p in result["plugins"]]}, broker_rows))
    reject("runtime.hermes-metadata", lambda: check_hermes_inventory({"available": False, "plugins": [{"name": "invented"}], "error": "missing"}))
    repo = root / "impact-repository"
    def put(path, content):
        target = repo / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    command = "fixture_ready_command"
    put("src/grant_agent/neyvia_fixture.py", f'COMMANDS = frozenset({{{command!r}}})\n')
    put("src/grant_agent/neyvia_other.py", 'COMMANDS = {"unrelated_command"}\n')
    backend = 'def dispatch(command):\n    if command.startswith("fixture_"):\n        from .neyvia_fixture import COMMANDS as FIXTURE\n        if command in FIXTURE:\n            return "handled"\n'
    put("src/grant_agent/web_backend.py", backend)
    bridge = 'from .neyvia_fixture import COMMANDS as FIXTURE\nALLOWED_DESKTOP_COMMANDS = frozenset({})\nALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | FIXTURE\n'
    put("src/grant_agent/desktop_bridge.py", bridge)
    frontend = 'callNx("fixture_ready_command"); act("missing_command");\nconst COMMANDS: Record<string, string> = Object.freeze({ future: "future_command" });\nconst error = { code: "unexpected_command", message: "failure_command" };\nconst view = { aliases: ["display_command"] };\n// callNx("comment_command")\nconst example = \'callNx("example_command")\';\nconst panel = <button onClick={() => act("fixture_ready_command")}>Start</button>;\n'
    put("web/src/neyvia/next/view.jsx", frontend)
    graph = index(repo); gaps = find_gaps(graph)
    if set(graph["handled"]) != {command} or graph["bridge"] != {command} or set(graph["ui"]) != {command, "missing_command", "future_command"} or gaps["uiWithoutHandler"]["items"] != ["future_command", "missing_command"]:
        raise RuntimeError("Aliased static graph goal failed")
    damaged = dict(graph); damaged["handled"] = {**graph["handled"], "invented_command": "src/grant_agent/web_backend.py:1"}
    reject("impact.index-provenance", lambda: check_impact_index(damaged))
    trees = {path: _tree(path.read_text(encoding="utf-8"), True) for path in (repo / "src/grant_agent").glob("*.py")}
    tree = trees[repo / "src/grant_agent/web_backend.py"]; imported = _imported_sets(tree, trees, repo)
    reject("impact.import-provenance", lambda: check_imported_registries(tree, trees, repo, {**imported, "UNRELATED": {"unrelated_command"}}))
    branches = _compares(tree, "command", imported)
    reject("impact.dispatch-membership", lambda: check_dispatch_membership(tree, "command", imported, []))
    import re
    normalized = re.sub(r"(\b(?:[A-Z][A-Z0-9_]*_)?COMMANDS)\s*:\s*[^=\n]+(?=\s*=)", r"\1", frontend)
    tokens = [token for token in JS_TOKEN.findall(normalized) if not token.startswith(("//", "/*"))]
    reject("impact.ui-call-evidence", lambda: check_ui_command_evidence(tokens, COMMAND_CALLS, {"display_command"}))
    put("src/grant_agent/web_backend.py", 'def dispatch(command):\n    if command.startswith("fixture_"):\n        from .neyvia_fixture import COMMANDS as FIXTURE\n        return "unsupported"\n')
    changed = find_gaps(index(repo))
    if changed["uiWithoutHandler"]["items"] != ["fixture_ready_command", "future_command", "missing_command"]:
        raise RuntimeError("Removing membership did not expose handler gap")
    return {"ok": True, "status": "passed", "contracts": observers, "procedures": [{"id": "runtime.inventory-metadata", "status": "passed", "pluginFilesObserved": 2, "providerLaunched": False}, {"id": "impact.alias-membership-graph", "status": "passed", "repositoryMutations": 2}], "elapsedMs": round((time.perf_counter()-started)*1000, 2), "boundary": "Actual metadata files and static AST graph, no provider/desktop/native plugin activation"}


if __name__ == "__main__":
    print(json.dumps(self_check(sys.argv[1])))
