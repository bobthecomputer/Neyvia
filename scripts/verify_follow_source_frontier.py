"""Replay source-only historical assertions without changing UI requirements."""
from __future__ import annotations

import importlib.util
import ast
import json
from pathlib import Path
import sys
import subprocess

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]
active = False
node_allowed = False


def guard(event, args):
    if not active:
        return
    if event == "subprocess.Popen" and node_allowed and str(args[0]) == "node":
        return
    if event in {"socket.connect", "subprocess.Popen", "os.system"}:
        raise PermissionError("Source-only proof forbids network/process execution")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0]).resolve()
        if not path.is_relative_to(REPO):
            raise PermissionError("Source-only proof forbids external file access")


sys.addaudithook(guard)
assertions_preserved = {}
for filename in ("test_workspace_selection_behavior.py", "test_live_review_panel_frontend.py", "test_desktop_ui_contract.py"):
    path = "tests/" + filename
    original = subprocess.run(["git", "show", "69c59214:" + path], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    def assertions(source):
        return sorted(ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(source))
                      if isinstance(node, ast.Assert) or isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert"))
    before, after = assertions(original), assertions((REPO / path).read_text(encoding="utf-8"))
    assert before == after
    assertions_preserved[path] = len(before)
ledger = json.loads((REPO / "scripts/evidence/FOLLOW-failures.json").read_text(encoding="utf-8"))
checks = []
modules = {}
for case in ledger["cases"]:
    if case["rootCauseGroup"] not in {"source-contract-ownership-or-ui-frontier", "removed-fixture-artifact-path"}:
        continue
    if "test_workspace_selection_behavior.py" in case["id"]:
        continue
    parts = case["id"].split("::")
    path = REPO / parts[0]
    if path not in modules:
        spec = importlib.util.spec_from_file_location("follow_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[path] = module
    module = modules[path]
    target = getattr(module, parts[1])() if len(parts) == 3 else module
    try:
        node_allowed = parts[-1] in {
            "test_desktop_fixtures_keep_hermes_available_for_missions",
            "test_fluxio_shell_confirm_current_runtime_default_and_live_image_route",
        }
        active = True
        getattr(target, parts[-1])()
    except Exception as exc:
        checks.append({"id": case["id"], "passed": False, "exception": type(exc).__name__,
                       "diagnostic": str(exc)[:200] if not isinstance(exc, AssertionError) else "Original source assertion failed",
                       "boundary": "Current source assertion remains unmet; no UI changes or assertions removed"})
    else:
        checks.append({"id": case["id"], "passed": True,
                       "boundary": "Source assertion only; no rendered behavior claim"})
    finally:
        active = False
        node_allowed = False

# This maintained pure helper runs through actual Node with all original assertions.
spec = importlib.util.spec_from_file_location("follow_workspace_selection", REPO / "tests/test_workspace_selection_behavior.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.WorkspaceSelectionBehaviorTests.setUpClass()
for name in sorted(name for name in vars(module.WorkspaceSelectionBehaviorTests) if name.startswith("test_")):
    getattr(module.WorkspaceSelectionBehaviorTests(), name)()
    checks.append({"id": "tests/test_workspace_selection_behavior.py::WorkspaceSelectionBehaviorTests::" + name,
                   "passed": True, "boundary": "Real Node executes maintained selection helper with original assertions"})
receipt = {"boundary": "Source-only historic UI/path assertions replayed under no-network/no-external-file guard; only two inspected pure Node fixture/source scripts may spawn. Selection helper separately executes actual Node. No UI assertion pruned or product UI edited.",
           "checks": checks, "renderedProof": False,
           "originalAssertionsPreserved": assertions_preserved,
           "passed": sum(row["passed"] for row in checks), "unmet": sum(not row["passed"] for row in checks)}
(REPO / "scripts/evidence/FOLLOW-source-frontier.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({key: receipt[key] for key in ("passed", "unmet", "renderedProof")}))
